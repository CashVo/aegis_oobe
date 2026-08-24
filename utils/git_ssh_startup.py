#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

KEY_PATH = Path.home() / ".ssh" / "cash-hub.key"
GIT_HOST = "git@github.com"

def run(cmd: list[str], capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=True,
        text=True,
        capture_output=capture,
    )

def agent_running() -> bool:
    return bool(os.environ.get("SSH_AUTH_SOCK"))

def start_agent() -> None:
    result = run(["ssh-agent", "-s"], capture=True)
    for line in result.stdout.splitlines():
        if line.startswith("SSH_AUTH_SOCK=") or line.startswith("SSH_AGENT_PID="):
            key, rest = line.split(";", 1)[0].split("=", 1)
            os.environ[key] = rest
    print("SSH agent started.")

def add_key() -> None:
    run(["ssh-add", str(KEY_PATH)])
    print(f"Loaded key: {KEY_PATH}")

def test_github() -> None:
    result = subprocess.run(
        ["ssh", "-T", GIT_HOST],
        text=True,
        capture_output=True,
    )

    output = (result.stdout or "") + (result.stderr or "")
    if "successfully authenticated" in output:
        print(output.strip())
        print("GitHub SSH test complete.")
        return

    print(output.strip(), file=sys.stderr)
    raise subprocess.CalledProcessError(result.returncode, result.args)

def main() -> None:
    if not KEY_PATH.exists():
        print(f"Missing key: {KEY_PATH}", file=sys.stderr)
        sys.exit(1)

    if not agent_running():
        start_agent()

    add_key()

    try:
        test_github()
    except subprocess.CalledProcessError as e:
        print("SSH test failed.", file=sys.stderr)
        sys.exit(e.returncode)

if __name__ == "__main__":
    main()