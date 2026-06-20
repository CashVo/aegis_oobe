#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENV_DIR = PROJECT_ROOT / ".venv"

def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)

def ensure_venv() -> None:
    if not VENV_DIR.exists():
        print("Creating .venv...")
        run(["uv", "venv", str(VENV_DIR)])

def sync_deps() -> None:
    print("Syncing dependencies...")
    run(["uv", "sync", "--extra", "dev", "--extra", "web"])

def main() -> None:
    ensure_venv()
    sync_deps()
    print()
    print("Next step:")
    print(f"  source {VENV_DIR}/bin/activate")

if __name__ == "__main__":
    main()