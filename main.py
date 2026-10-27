"""
Baseline Shot Lab - CLI Entry Point.
Delegates to `basketball.app.main`.
"""
import sys
from pathlib import Path

# Ensure 'src' is on sys.path for direct script execution
_SRC_DIR = Path(__file__).resolve().parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from basketball.app.main import main

if __name__ == "__main__":
    main()
