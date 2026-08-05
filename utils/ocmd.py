#!/usr/bin/env python3
"""
ocmd — Ollama Commands.

Ollama management:

    ocmd setup
    ocmd models [use-local=true]
    ocmd status [use-local=true]
    ocmd load <model> [duration] [use-local=true]
    ocmd unload <model> [use-local=true]
    ocmd keepalive <model> <duration> [use-local=true]

Aider profiles:

    ocmd start-aider --list
    ocmd start-aider ws-qwen-fast
    ocmd start-aider ws-qwen-coder
    ocmd start-aider oracle-qwen-fast
    ocmd start-aider oracle-quen-coder

Pass additional Aider arguments after the profile:

    ocmd start-aider oracle-qwen-fast --read AGENTS.md
    ocmd start-aider ws-qwen-fast --message "Review the current diff"

Supported durations:

    30s       30 seconds
    60m       60 minutes
    2h        2 hours
    0         unload immediately
    -1        keep loaded indefinitely

HINT:
- Run this command to install/update ocmd on local env:
    python3 utils/ocmd.py setup
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

LOCAL_OLLAMA_HOST = os.environ.get(
    "OLLAMA_LOCAL_HOST",
    "http://localhost:11434",
).rstrip("/")

INSTALL_DIR = Path.home() / "bin"
INSTALL_PATH = INSTALL_DIR / "ocmd"

# ---------------------------------------------------------------------
# Aider profiles
# ---------------------------------------------------------------------

AIDER_PROFILES: dict[str, dict[str, str]] = {
    "ws-qwen-fast": {
        "model": "ollama_chat/qwen3.5:0.8b",
        "host": DEFAULT_OLLAMA_HOST,
        "description": "Workstation Ollama — Qwen3.5:0.8B - FAST",
    },
    "ws-qwen-coder": {
        "model": "ollama_chat/qwen2.5-coder",
        "host": DEFAULT_OLLAMA_HOST,
        "description": "Workstation Ollama — Qwen2.5-coder - CODING",
    },
    "oracle-qwen-fast": {
        "model": "ollama/qwen3.5:0.8b",
        "host": LOCAL_OLLAMA_HOST,
        "description": "Oracle-local Ollama — Qwen3.5:0.8b - FAST",
    },
    "oracle-qwen-coder": {
        "model": "ollama_chat/qwen2.5-coder:latest",
        "host": LOCAL_OLLAMA_HOST,
        "description": "Oracle-local Ollama — Qwen Coder - CODING",
    },
    "oracle-qwen-thinking": {
        "model": "ollama/qwen3.5:9b",
        "host": LOCAL_OLLAMA_HOST,
        "description": "Oracle-local Ollama — Qwen Thinking - THINKING",
    },
}

# ---------------------------------------------------------------------
# Host selection
# ---------------------------------------------------------------------

def extract_host_flag(args: list[str]) -> tuple[list[str], str]:
    """
    Remove the host-selection flag from arguments.

    Supported forms:

        use-local=true
        use-local=false
        --use-local
        --use-local=true
        --use-local=false
        --use-remote

    The default is the remote/workstation Ollama host.
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

    parsed = [
        json.loads(line)
        for line in lines
        if [line.strip()]
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

def parse_duration(value: str) -> int | str:
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
            f"{name:<35}"
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
            f"{name:<35}"
            f"{size_gb:>6.1f} GB   "
            f"{modified_at}"
        )

# ---------------------------------------------------------------------
# Aider commands
# ---------------------------------------------------------------------

def list_aider_profiles() -> None:
    """Display all configured Aider profiles."""

    print("Available Aider profiles:")
    print()

    for name, profile in AIDER_PROFILES.items():
        print(f"  {name:<18} {profile['description']}")
        print(f"  {'':<18} Model: {profile['model']}")
        print(f"  {'':<18} Host:  {profile['host']}")
        print()

def start_aider(profile_name: str, aider_args: list[str]) -> int:
    """
    Launch Aider using a configured host/model profile.

    os.execvp() replaces the current ocmd process with Aider. This gives
    Aider normal interactive terminal behavior, proper signal handling,
    and clean operation inside tmux.
    """

    profile = AIDER_PROFILES.get(profile_name)

    if profile is None:
        print(
            f"Unknown Aider profile: {profile_name}",
            file=sys.stderr,
        )
        print("", file=sys.stderr)
        list_aider_profiles()
        return 2

    aider_command = [
        "aider",
        "--model",
        profile["model"],
        *aider_args,
    ]

    # Copy the current environment and override the Ollama endpoint
    # for this Aider process only.
    aider_environment = os.environ.copy()
    aider_environment["OLLAMA_API_BASE"] = profile["host"]

    print(
        f"Starting Aider profile '{profile_name}'"
    )
    print(f"  Model: {profile['model']}")
    print(f"  Host:  {profile['host']}")
    print()

    try:
        os.execvpe(
            aider_command[0],
            aider_command,
            aider_environment
        )

    except FileNotFoundError:
        print(
            "Aider was not found on PATH.",
            file=sys.stderr,
        )
        print(
            "Activate the environment where Aider is installed, "
            "then try again.",
            file=sys.stderr,
        )
        return 127

    except PermissionError:
        print(
            "Aider exists but is not executable.",
            file=sys.stderr,
        )
        return 127

    # os.execvp() does not return on success.
    return 0

# ---------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------

def setup() -> None:
    """
    Install the current script as ~/bin/ocmd.

    Run this command to install/update:

        python3 utils/ocmd.py setup
    """

    source_path = Path(__file__).resolve()
    destination = INSTALL_PATH.resolve()

    INSTALL_DIR.mkdir(parents=True, exist_ok=True)

    # Avoid copying the file onto itself.
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
    print("  ocmd start-aider --list")

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

    # Handle start-aider before global host-flag processing.
    #
    # This is intentional: every Aider profile already specifies its
    # host, and Aider's own arguments should pass through untouched.
    if command == "start-aider":
        if not raw_args:
            print(
                "Usage: ocmd start-aider "
                "<profile-name> [Aider arguments]",
                file=sys.stderr,
            )
            print()
            list_aider_profiles()
            return 2

        if raw_args == ["--list"]:
            list_aider_profiles()
            return 0

        profile_name = raw_args[0]
        aider_args = raw_args[1:]

        return start_aider(profile_name, aider_args)

    # All non-Aider commands use the normal host-selection behavior.
    args, host = extract_host_flag(raw_args)

    try:
        if command == "setup":
            if args:
                print("Usage: ocmd setup")
                return 1

            setup()

        elif command == "list":
            if args:
                print("Usage: ocmd list [use-local=true]")
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
            print(f"Unknown command: {command}", file=sys.stderr)
            print()
            print_usage()
            return 1

    except urllib.error.HTTPError as error:
        print(
            f"Ollama returned HTTP {error.code}: {error.reason}",
            file=sys.stderr,
        )
        print(f"Host: {host}", file=sys.stderr)
        return 1

    except urllib.error.URLError as error:
        print(
            f"Could not connect to Ollama at {host}",
            file=sys.stderr,
        )
        print(f"Details: {error.reason}", file=sys.stderr)
        return 1

    except json.JSONDecodeError as error:
        print(
            f"Ollama returned invalid JSON: {error}",
            file=sys.stderr,
        )
        return 1

    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
