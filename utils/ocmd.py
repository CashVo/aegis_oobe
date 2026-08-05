#!/usr/bin/env python3
"""
ocmd — Ollama Commands.

Default behavior targets the remote workstation Ollama instance.

Usage:
    ocmd setup
    ocmd models [use-local=true]
    ocmd status [use-local=true]
    ocmd load <model> [duration] [use-local=true]
    ocmd unload <model> [use-local=true]
    ocmd keepalive <model> <duration> [use-local=true]

Examples:
    ocmd setup

    ocmd models
    ocmd models use-local=true

    ocmd status
    ocmd status use-local=true

    ocmd load qwen2.5-coder:32b
    ocmd load qwen2.5-coder:32b 60m
    ocmd load qwen2.5-coder:32b 60m use-local=true

    ocmd keepalive qwen2.5-coder:32b -1
    ocmd keepalive qwen2.5-coder:32b 60m use-local=true

    ocmd unload qwen2.5-coder:32b
    ocmd unload qwen2.5-coder:32b use-local=true

Supported durations:
    30s       30 seconds
    60m       60 minutes
    2h        2 hours
    0         unload immediately
    -1        keep loaded indefinitely
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

# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

DEFAULT_OLLAMA_HOST = os.environ.get(
    "OLLAMA_HOST",
    "http://ai-brain.hare-catla.ts.net:11434",
).rstrip("/")

LOCAL_OLLAMA_HOST = "http://207.211.172:11434"

INSTALL_DIR = Path.home() / "bin"
INSTALL_PATH = INSTALL_DIR / "ocmd"

# ---------------------------------------------------------------------
# Host selection
# ---------------------------------------------------------------------

def extract_host_flag(args: list[str]) -> tuple[list[str], str]:
    """
    Remove the host-selection flag from args and return:

        cleaned_args, selected_host

    Supported forms:

        use-local=true
        use-local=false
        --use-local
        --use-local=true
        --use-local=false
        --use-remote

    The default is the remote Ollama host.
    """

    cleaned_args: list[str] = []
    use_local = False

    for arg in args:
        normalized = arg.strip().lower()

        if normalized in {
            "use-local=true",
            "--use-local",
            "--use-local=true",
        }:
            use_local = True

        elif normalized in {
            "use-local=false",
            "--use-local=false",
            "--use-remote",
        }:
            use_local = False

        else:
            cleaned_args.append(arg)

    host = LOCAL_OLLAMA_HOST if use_local else DEFAULT_OLLAMA_HOST
    return cleaned_args, host

# ---------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------

def post_json(host: str, path: str, payload: dict) -> dict:
    """Send a JSON POST request to Ollama."""

    url = f"{host}{path}"
    data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()

    if not raw:
        return {}

    # Ollama may return newline-delimited JSON when streaming.
    lines = raw.decode("utf-8").splitlines()
    parsed =[
        json.loads(line)
        for line in lines
        if line.strip()
    ]

    return parsed[-1] if parsed else {}

def get_json(host: str, path: str) -> dict:
    """Send a JSON GET request to Ollama."""

    url = f"{host}{path}"

    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read())

# ---------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------

def parse_duration(value: str):
    """
    Convert numeric Ollama values to integers while preserving
    duration strings such as 30s, 60m, and 2h.
    """

    try:
        return int(value)
    except ValueError:
        return value

def print_host(host: str) -> None:
    print(f"Host: {host}")

# ---------------------------------------------------------------------
# Ollama commands
# ---------------------------------------------------------------------

def load_model(host: str, model: str, duration: str = "-1") -> None:
    """Load a model or refresh its keep-alive value."""

    keep_alive = parse_duration(duration)

    post_json(
        host,
        "/api/generate",
        {
            "model": model,
            "keep_alive": keep_alive,
        },
    )

    print(f"Loaded '{model}' with keep_alive={duration}")
    print_host(host)

def unload_model(host: str, model: str) -> None:
    """Unload a model immediately."""

    post_json(
        host,
        "/api/generate",
        {
            "model": model,
            "keep_alive": 0,
        },
    )

    print(f"Unloaded '{model}'")
    print_host(host)

def set_keepalive(host: str, model: str, duration: str) -> None:
    """Set or refresh the keep-alive value for a model."""

    keep_alive = parse_duration(duration)

    post_json(
        host,
        "/api/generate",
        {
            "model": model,
            "keep_alive": keep_alive,
        },
    )

    print(f"Set '{model}' keep_alive={duration}")
    print_host(host)

def show_status(host: str) -> None:
    """Show models currently loaded in memory."""

    data = get_json(host, "/api/ps")
    models = data.get("models", [])

    print_host(host)

    if not models:
        print("No models currently loaded.")
        return

    print(f"{'NAME':<35} {'SIZE':<12} {'EXPIRES'}")
    print("-" * 85)

    for model in models:
        name = model.get("name", "?")
        size_gb = model.get("size", 0) / (1024 ** 3)
        expires_at = model.get("expires_at", "?")

        print(
            f"{name:<35} "
            f"{size_gb:>6.1f} GB   "
            f"{expires_at}"
        )

def list_models(host: str) -> None:
    """List models installed on the selected Ollama instance."""

    data = get_json(host, "/api/tags")
    models = data.get("models", [])

    print_host(host)

    if not models:
        print("No models installed.")
        return

    print(f"{'NAME':<35} {'SIZE':<12} {'MODIFIED'}")
    print("-" * 95)

    for model in models:
        name = model.get("name", "?")
        size_gb = model.get("size", 0) / (1024 ** 3)
        modified_at = model.get("modified_at", "?")

        print(
            f"{name:<35} "
            f"{size_gb:>6.1f} GB   "
            f"{modified_at}"
        )

# ---------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------

def setup() -> None:
    """
    Install the currently running/source script as ~/bin/ocmd.

    Run this from the project copy after making changes:

        python3 utils/ocmd.py setup
    """

    source_path = Path(__file__).resolve()
    destination = INSTALL_PATH.resolve()

    INSTALL_DIR.mkdir(parents=True, exist_ok=True)

    # Avoid copying the file onto itself if running ~/bin/ocmd setup.
    if source_path != destination:
        shutil.copy2(source_path, destination)

    current_mode = destination.stat().st_mode
    destination.chmod(
        current_mode
        | stat.S_IXUSR
        | stat.S_IXGRP
        | stat.S_IXOTH
    )

    print(f"Installed: {destination}")
    print()
    print("Try:")
    print("  ocmd models")
    print("  ocmd status")

# ---------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------

def print_usage() -> None:
    print(__doc__)

# ---------------------------------------------------------------------
# Main command dispatcher
# ---------------------------------------------------------------------

def main() -> int:
    if len(sys.argv) < 2:
        print_usage()
        return 1

    command = sys.argv[1]
    raw_args = sys.argv[2:]

    # Remove use-local=true or --use-local before command validation.
    args, host = extract_host_flag(raw_args)

    try:
        if command == "setup":
            setup()

        elif command == "models":
            if args:
                print("Usage: ocmd models [use-local=true]")
                return 1

            list_models(host)

        elif command == "status":
            if args:
                print("Usage: ocmd status [use-local=true]")
                return 1

            show_status(host)

        elif command == "load":
            if not args or len(args) > 2:
                print(
                    "Usage: ocmd load "
                    "<model> [duration] [use-local=true]"
                )
                return 1

            model = args[0]
            duration = args[1] if len(args) == 2 else "-1"

            load_model(host, model, duration)

        elif command == "unload":
            if len(args) != 1:
                print(
                    "Usage: ocmd unload "
                    "<model> [use-local=true]"
                )
                return 1

            unload_model(host, args[0])

        elif command == "keepalive":
            if len(args) != 2:
                print(
                    "Usage: ocmd keepalive "
                    "<model> <duration> [use-local=true]"
                )
                return 1

            set_keepalive(host, args[0], args[1])

        else:
            print(f"Unknown command: {command}")
            print_usage()
            return 1

    except urllib.error.HTTPError as error:
        print(f"Ollama returned HTTP {error.code}: {error.reason}")
        print(f"Host: {host}")
        return 1

    except urllib.error.URLError as error:
        print(f"Could not connect to Ollama at {host}")
        print(f"Details: {error.reason}")
        return 1

    except json.JSONDecodeError as error:
        print(f"Ollama returned invalid JSON: {error}")
        return 1

    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
