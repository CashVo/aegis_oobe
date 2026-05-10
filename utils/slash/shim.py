# utils/slash/shim.py
# Repo-local shim that dispatches to the canonical slash pack at SLASH_HOME.

import os
import sys
import subprocess
from pathlib import Path

def main(argv: list[str]) -> int:
    home = os.environ.get("SLASH_HOME", "").strip()
    if not home:
        print("ERROR: SLASH_HOME is not set.")
        return 1

    # Run as module from SLASH_HOME so package imports work
    return subprocess.call(
        [sys.executable, "-m", "slash_runtime", *argv],
        cwd=home,
    )

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
