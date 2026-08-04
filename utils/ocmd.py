#!/usr/bin/env python3
"""
ollama-ctl.py — Control a remote Ollama server from Aegis.

Commands:
    setup
    models
    status
    load <model> [duration]
    unload <model>
    keepalive <model> <duration>

Examples:
    ocmd setup
    ocmd models
    ocmd status
    ocmd load qwen2.5-coder:32b
    ocmd load qwen2.5-coder:32b 60m
    ocmd keepalive qwen2.5-coder:32b -1
    ocmd unload qwen2.5-coder:32b
 
NOTE:
- To use an alias, make sure to add the alias definition in `~/.bashrc` and then reload it for the current shell.
    Exp:
        echo "alias oc='ocmd.py'" >> ~/.bashrc
        source ~/.bashrc
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import urllib.error
import urllib.request
from pathlib import Path

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

OLLAMA_HOST = os.environ.get(
    "OLLAMA_HOST",
    "http://ai-brain.hare-catla.ts.net:11434",
).rstrip("/")

INSTALL_DIR = Path.home() / "bin"
INSTALL_PATH = INSTALL_DIR / "ocmd" # ocmd = Ollama command python filename

# -------------------------------------------------------------------
# HTTP helpers
# -------------------------------------------------------------------

def _post(path: str, payload: dict) -> dict:
    url = f"{OLLAMA_HOST}{path}"
    data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()

    # Ollama may return an empty response for some keep-alive requests.
    if not raw:
        return {}

    # Streaming responses may contain multiple JSON lines.
    lines = raw.decode("utf-8").splitlines()
    parsed = json.loads(line) for line in lines if [line.strip()]
    return parsed[-1] if parsed else {}

def _get(path: str) -> dict:
    url = f"{OLLAMA_HOST}{path}"

    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read())

# -------------------------------------------------------------------
# Commands
# -------------------------------------------------------------------

def parse_duration(value: str):
    """
    Preserve Ollama's accepted values:
        -1, 0, 60
        60s, 30m, 2h
    """
    try:
        return int(value)
    except ValueError:
        return value

def load_model(model: str, duration: str = "-1") -> None:
    keep_alive = parse_duration(duration)

    _post(
        "/api/generate",
        {
            "model": model,
            "keep_alive": keep_alive,
        },
    )

    print(f"Loaded '{model}' with keep_alive={duration}")

def unload_model(model: str) -> None:
    _post(
        "/api/generate",
        {
            "model": model,
            "keep_alive": 0,
        },
    )

    print(f"Unloaded '{model}'")

def set_keepalive(model: str, duration: str) -> None:
    keep_alive = parse_duration(duration)

    _post(
        "/api/generate",
        {
            "model": model,
            "keep_alive": keep_alive,
        },
    )

    print(f"Set '{model}' keep_alive={duration}")

def show_status() -> None:
    data = _get("/api/ps")
    models = data.get("models", [])

    if not models:
        print("No models currently loaded.")
        return

    print(f"{'NAME':<35} {'SIZE':<12} {'EXPIRES'}")
    print("-" * 80)

    for model in models:
        name = model.get("name", "?")
        size_gb = model.get("size", 0) / (1024 ** 3)
        expires_at = model.get("expires_at", "?")

        print(f"{name:<35} {size_gb:>6.1f} GB   {expires_at}")

def list_models() -> None:
    data = _get("/api/tags")
    models = data.get("models", [])

    if not models:
        print("No models installed on the workstation.")
        return

    print(f"{'NAME':<35} {'SIZE':<12} {'MODIFIED'}")
    print("-" * 85)

    for model in models:
        name = model.get("name", "?")
        size_gb = model.get("size", 0) / (1024 ** 3)
        modified = model.get("modified_at", "?")

        print(f"{name:<35} {size_gb:>6.1f} GB   {modified}")

def setup() -> None:
    """
    Install the currently running/source script into ~/bin.

    This is intentionally idempotent: running setup repeatedly simply
    refreshes ~/bin/ollama-ctl.py.
    """
    source_path = Path(__file__).resolve()
    destination = INSTALL_PATH.resolve()

    INSTALL_DIR.mkdir(parents=True, exist_ok=True)

    # Avoid copying onto itself when setup is run from ~/bin.
    if source_path != destination:
        shutil.copy2(source_path, destination)

    current_mode = destination.stat().st_mode
    destination.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    print(f"Installed: {destination}")
    print()
    print("Make sure ~/bin is on PATH:")
    print('  export PATH="$HOME/bin:$PATH"')
    print()
    print("Then use:")
    print("  ocmd models")
    print("  ocmd status")
    print("  ocmd // Prints doc/help content")

def print_usage() -> None:
    print(__doc__)

# -------------------------------------------------------------------
# Entry point
# -------------------------------------------------------------------

def main() -> int:
    if len(sys.argv) < 2:
        print_usage()
        return 1

    command = sys.argv[1]
    args = sys.argv[2:]

    try:
        if command == "setup":
            setup()

        elif command == "models":
            list_models()

        elif command == "status":
            show_status()

        elif command == "load":
            if not args or len(args) > 2:
                print("Usage: ollama-ctl.py load <model> [duration]")
                return 1

            model = args[0]
            duration = args[1] if len(args) == 2 else "-1"
            load_model(model, duration)

        elif command == "unload":
            if len(args) != 1:
                print("Usage: ollama-ctl.py unload <model>")
                return 1

            unload_model(args[0])

        elif command == "keepalive":
            if len(args) != 2:
                print("Usage: ollama-ctl.py keepalive <model> <duration>")
                return 1

            set_keepalive(args[0], args[1])

        else:
            print(f"Unknown command: {command}")
            print_usage()
            return 1

    except urllib.error.URLError as error:
        print(f"Connection failed: {OLLAMA_HOST}")
        print(f"Details: {error}")
        return 1

    except json.JSONDecodeError as error:
        print(f"Ollama returned invalid JSON: {error}")
        return 1

    return 0

if __name__ == "__main__":
    raise SystemExit(main())