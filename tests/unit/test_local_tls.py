"""Tests for the built-in local HTTPS certificates (``web_app.py --https``)."""

import datetime as dt
import ipaddress
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

try:
    import cryptography  # noqa: F401
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
except ImportError:  # pragma: no cover - optional dependency
    x509 = None

import basketball.app.local_tls as local_tls


@unittest.skipIf(x509 is None, "cryptography is not installed")
class LocalTlsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="shotlab_tls_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def load(self, name):
        data = (self.tmp / name).read_bytes()
        return x509.load_pem_x509_certificates(data) if name == local_tls.SERVER_CERT_NAME else x509.load_pem_x509_certificate(data)

    def test_certificates_cover_only_private_addresses(self):
        info = local_tls.ensure_local_certificates(self.tmp, ["192.168.1.20", "10.0.0.7", "8.8.8.8", "192.0.2.5", "not-an-ip"])
        self.assertTrue(info["created_ca"] and info["created_server"])
        leaf = self.load(local_tls.SERVER_CERT_NAME)[0]
        san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        ips = {str(ip) for ip in san.get_values_for_type(x509.IPAddress)}
        self.assertEqual(ips, {"127.0.0.1", "::1", "192.168.1.20", "10.0.0.7"})
        self.assertIn("localhost", san.get_values_for_type(x509.DNSName))
        eku = leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        self.assertIn(ExtendedKeyUsageOID.SERVER_AUTH, list(eku))
        start = getattr(leaf, "not_valid_before_utc", None) or leaf.not_valid_before.replace(tzinfo=dt.timezone.utc)
        life = local_tls._not_after(leaf) - start
        self.assertLessEqual(life.days, 398, "Apple platforms reject longer-lived TLS certificates")

    def test_ca_is_name_constrained_and_keys_are_private(self):
        local_tls.ensure_local_certificates(self.tmp, ["192.168.1.20"])
        ca = self.load(local_tls.CA_CERT_NAME)
        constraints = ca.extensions.get_extension_for_class(x509.NameConstraints)
        self.assertTrue(constraints.critical)
        permitted = constraints.value.permitted_subtrees
        nets = {str(name.value) for name in permitted if isinstance(name, x509.IPAddress)}
        self.assertIn("192.168.0.0/16", nets)
        self.assertNotIn("0.0.0.0/0", nets)
        self.assertTrue(ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)
        if os.name == "posix":
            for name in (local_tls.CA_KEY_NAME, local_tls.SERVER_KEY_NAME):
                mode = stat.S_IMODE((self.tmp / name).stat().st_mode)
                self.assertEqual(mode & 0o077, 0, f"{name} must be readable by the owner only")
        # The DER copy for phones is the same certificate, and it contains no private key.
        der = (self.tmp / local_tls.CA_DER_NAME).read_bytes()
        self.assertEqual(x509.load_der_x509_certificate(der), ca)
        self.assertNotIn(b"PRIVATE KEY", der)

    def test_reuse_and_renewal(self):
        first = local_tls.ensure_local_certificates(self.tmp, ["192.168.1.20"])
        ca_bytes = (self.tmp / local_tls.CA_CERT_NAME).read_bytes()
        leaf_bytes = (self.tmp / local_tls.SERVER_CERT_NAME).read_bytes()
        again = local_tls.ensure_local_certificates(self.tmp, ["192.168.1.20"])
        self.assertFalse(again["created_ca"] or again["created_server"])
        self.assertEqual((self.tmp / local_tls.SERVER_CERT_NAME).read_bytes(), leaf_bytes)
        moved = local_tls.ensure_local_certificates(self.tmp, ["192.168.1.44"])   # new Wi-Fi address
        self.assertFalse(moved["created_ca"], "phones keep trusting the same CA")
        self.assertTrue(moved["created_server"])
        self.assertEqual((self.tmp / local_tls.CA_CERT_NAME).read_bytes(), ca_bytes)
        self.assertIn("192.168.1.44", moved["names"]["ips"])
        self.assertTrue(first["created_ca"])
        self.assertRegex(local_tls.ca_fingerprint(self.tmp / local_tls.CA_CERT_NAME), r"^([0-9A-F]{2}:){31}[0-9A-F]{2}$")

    @unittest.skipIf(shutil.which("openssl") is None, "openssl CLI not available")
    def test_chain_verifies_and_public_names_are_refused(self):
        local_tls.ensure_local_certificates(self.tmp, ["192.168.1.20"])
        leaf_pem = self.load(local_tls.SERVER_CERT_NAME)[0].public_bytes(serialization.Encoding.PEM)
        (self.tmp / "leaf.pem").write_bytes(leaf_pem)
        ok = subprocess.run(["openssl", "verify", "-purpose", "sslserver", "-CAfile", str(self.tmp / local_tls.CA_CERT_NAME),
                             str(self.tmp / "leaf.pem")], capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        # Even with the CA key, a certificate for a public website fails name-constraint checks.
        ca_key = serialization.load_pem_private_key((self.tmp / local_tls.CA_KEY_NAME).read_bytes(), password=None)
        ca = self.load(local_tls.CA_CERT_NAME)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = dt.datetime.now(dt.timezone.utc)
        forged = (x509.CertificateBuilder()
                  .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "bank.example.com")]))
                  .issuer_name(ca.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
                  .not_valid_before(now).not_valid_after(now + dt.timedelta(days=30))
                  .add_extension(x509.SubjectAlternativeName([x509.DNSName("bank.example.com"),
                                                              x509.IPAddress(ipaddress.ip_address("93.184.216.34"))]), False)
                  .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False)
                  .sign(ca_key, hashes.SHA256()))
        (self.tmp / "forged.pem").write_bytes(forged.public_bytes(serialization.Encoding.PEM))
        bad = subprocess.run(["openssl", "verify", "-purpose", "sslserver", "-CAfile", str(self.tmp / local_tls.CA_CERT_NAME),
                              str(self.tmp / "forged.pem")], capture_output=True, text=True)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("subtree", (bad.stdout + bad.stderr).lower())


if __name__ == "__main__":
    unittest.main()
