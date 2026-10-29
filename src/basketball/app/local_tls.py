"""Local HTTPS for phone camera access on the same Wi-Fi (``web_app.py --lan --https``).

Browsers only allow camera access (``navigator.mediaDevices.getUserMedia``) in a *secure context*:
``https://`` pages or ``http://localhost``. A phone opening ``http://192.168.x.x:8765`` is not a
secure context, so the camera API is simply absent. This module creates a small private
certificate authority on this computer and a server certificate for its local addresses, so the
app can be served over HTTPS without any third-party tool.

Safety measures:

* The CA certificate carries **critical name constraints**: it can only vouch for private-network
  IP addresses, ``localhost`` and ``.local`` names. Even if its key leaked, it could not be used to
  impersonate public websites on a device that trusts it.
* The CA private key stays in ``cert_dir`` with owner-only permissions and is never served.
* The server certificate follows Apple's TLS rules (SAN, serverAuth EKU, RSA-2048, SHA-256,
  validity under 398 days) and is re-issued automatically when it nears expiry or when this
  computer's local IP addresses change.

Requires the ``cryptography`` package (``pip install cryptography``). ``--tls-cert``/``--tls-key``
(for example from mkcert) remain available as an alternative.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import json
import os
import socket
from pathlib import Path
from typing import Iterable

CA_CERT_NAME = "shotlab-local-ca.pem"
CA_KEY_NAME = "shotlab-local-ca-key.pem"
CA_DER_NAME = "shotlab-local-ca.crt"
SERVER_CERT_NAME = "shotlab-server.pem"
SERVER_KEY_NAME = "shotlab-server-key.pem"
SERVER_META_NAME = "shotlab-server.json"

CA_VALID_DAYS = 3650
SERVER_VALID_DAYS = 397          # Apple platforms reject TLS server certificates valid for more than 398 days
RENEW_BEFORE_DAYS = 30

PERMITTED_NETWORKS = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "169.254.0.0/16",
                      "100.64.0.0/10"]
PERMITTED_IPV6 = ["::1/128", "fc00::/7", "fe80::/10"]
PERMITTED_DNS = ["localhost", "local"]


class LocalTLSUnavailable(RuntimeError):
    """Raised when the cryptography package is not installed."""


def _crypto():
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise LocalTLSUnavailable(
            "--https needs the 'cryptography' package. Install it with:  python -m pip install cryptography\n"
            "Or create certificates with mkcert and pass --tls-cert/--tls-key instead (see README).") from exc
    return x509, hashes, serialization, rsa, ExtendedKeyUsageOID, NameOID


def _write_private(path: Path, data: bytes) -> None:
    """Write a private key readable by the owner only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - e.g. some Windows filesystems
        pass


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _not_after(cert) -> dt.datetime:
    """Expiry as an aware datetime (cryptography < 42 only has the naive ``not_valid_after``)."""
    value = getattr(cert, "not_valid_after_utc", None)
    return value if value is not None else cert.not_valid_after.replace(tzinfo=dt.timezone.utc)


def is_permitted_ip(ip) -> bool:
    """True for addresses the local CA may certify (private LAN ranges, loopback, link-local)."""
    ip = ipaddress.ip_address(ip)
    nets = PERMITTED_NETWORKS if ip.version == 4 else PERMITTED_IPV6
    return any(ip in ipaddress.ip_network(net) for net in nets)


def server_names(addresses: Iterable[str]) -> dict[str, list[str]]:
    """Names the server certificate should cover: localhost, loopback, this computer's LAN IPs and <host>.local."""
    ips = ["127.0.0.1", "::1"]
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if is_permitted_ip(ip) and str(ip) not in ips:
            ips.append(str(ip))
    dns = ["localhost"]
    host = socket.gethostname().split(".")[0].strip().lower()
    if host and all(ch.isalnum() or ch == "-" for ch in host):
        dns.append(f"{host}.local")
    return {"ips": ips, "dns": dns}


def _ca_valid(cert_dir: Path) -> bool:
    x509, *_ = _crypto()
    cert_path, key_path = cert_dir / CA_CERT_NAME, cert_dir / CA_KEY_NAME
    if not cert_path.is_file() or not key_path.is_file():
        return False
    try:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    except ValueError:
        return False
    return _not_after(cert) - _now() > dt.timedelta(days=RENEW_BEFORE_DAYS)


def _create_ca(cert_dir: Path):
    x509, hashes, serialization, rsa, _eku, NameOID = _crypto()
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    host = socket.gethostname().split(".")[0][:40] or "computer"
    name = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Basketball Shot Lab (local only)"),
        x509.NameAttribute(NameOID.COMMON_NAME, f"Shot Lab Local CA ({host})"),
    ])
    permitted = ([x509.IPAddress(ipaddress.ip_network(net)) for net in PERMITTED_NETWORKS + PERMITTED_IPV6]
                 + [x509.DNSName(name_) for name_ in PERMITTED_DNS])
    now = _now()
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=CA_VALID_DAYS))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=True,
                                         crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.NameConstraints(permitted_subtrees=permitted, excluded_subtrees=None), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    _write_private(cert_dir / CA_KEY_NAME, key.private_bytes(serialization.Encoding.PEM,
                                                             serialization.PrivateFormat.PKCS8,
                                                             serialization.NoEncryption()))
    (cert_dir / CA_CERT_NAME).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (cert_dir / CA_DER_NAME).write_bytes(cert.public_bytes(serialization.Encoding.DER))
    # A new CA invalidates any server certificate signed by an old one.
    for stale in (SERVER_CERT_NAME, SERVER_KEY_NAME, SERVER_META_NAME):
        (cert_dir / stale).unlink(missing_ok=True)


def _server_valid(cert_dir: Path, names: dict[str, list[str]]) -> bool:
    x509, *_ = _crypto()
    cert_path, key_path, meta_path = (cert_dir / SERVER_CERT_NAME, cert_dir / SERVER_KEY_NAME,
                                      cert_dir / SERVER_META_NAME)
    if not (cert_path.is_file() and key_path.is_file() and meta_path.is_file()):
        return False
    try:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return False
    if _not_after(cert) - _now() < dt.timedelta(days=RENEW_BEFORE_DAYS):
        return False
    return set(names["ips"]) <= set(meta.get("ips", [])) and set(names["dns"]) <= set(meta.get("dns", []))


def _create_server(cert_dir: Path, names: dict[str, list[str]]):
    x509, hashes, serialization, rsa, ExtendedKeyUsageOID, NameOID = _crypto()
    ca_key = serialization.load_pem_private_key((cert_dir / CA_KEY_NAME).read_bytes(), password=None)
    ca_cert = x509.load_pem_x509_certificate((cert_dir / CA_CERT_NAME).read_bytes())
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = _now()
    san = [x509.DNSName(name) for name in names["dns"]] + [x509.IPAddress(ipaddress.ip_address(ip)) for ip in names["ips"]]
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Basketball Shot Lab (local only)"),
                                     x509.NameAttribute(NameOID.COMMON_NAME, "Shot Lab on this computer")]))
            .issuer_name(ca_cert.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=SERVER_VALID_DAYS))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=True,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                         crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    _write_private(cert_dir / SERVER_KEY_NAME, key.private_bytes(serialization.Encoding.PEM,
                                                                 serialization.PrivateFormat.PKCS8,
                                                                 serialization.NoEncryption()))
    # Full chain (leaf + CA) so clients that trust the CA can build the path.
    (cert_dir / SERVER_CERT_NAME).write_bytes(cert.public_bytes(serialization.Encoding.PEM)
                                              + ca_cert.public_bytes(serialization.Encoding.PEM))
    (cert_dir / SERVER_META_NAME).write_text(json.dumps({"ips": names["ips"], "dns": names["dns"],
                                                         "not_after": _not_after(cert).isoformat()}),
                                             encoding="utf-8")


def ensure_local_certificates(cert_dir: Path, addresses: Iterable[str]) -> dict:
    """Create or reuse the local CA and a server certificate covering ``addresses``.

    Returns paths and what was created, for the start-up message.
    """
    cert_dir = Path(cert_dir)
    cert_dir.mkdir(parents=True, exist_ok=True)
    created_ca = created_server = False
    if not _ca_valid(cert_dir):
        _create_ca(cert_dir)
        created_ca = True
    names = server_names(addresses)
    if created_ca or not _server_valid(cert_dir, names):
        _create_server(cert_dir, names)
        created_server = True
    return {
        "cert": cert_dir / SERVER_CERT_NAME, "key": cert_dir / SERVER_KEY_NAME,
        "ca_pem": cert_dir / CA_CERT_NAME, "ca_der": cert_dir / CA_DER_NAME,
        "created_ca": created_ca, "created_server": created_server, "names": names,
    }


def ca_fingerprint(ca_pem: Path) -> str:
    """SHA-256 fingerprint of the CA certificate, to compare on the phone before trusting it."""
    x509, hashes, *_ = _crypto()
    cert = x509.load_pem_x509_certificate(Path(ca_pem).read_bytes())
    digest = cert.fingerprint(hashes.SHA256()).hex().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))
