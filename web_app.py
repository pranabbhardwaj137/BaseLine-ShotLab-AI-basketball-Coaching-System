"""
Baseline Shot Lab - Web App Entry Point.
Delegates to `basketball.app.web_app`.
"""
import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from basketball.app.web_app import main

if __name__ == "__main__":
    main()
