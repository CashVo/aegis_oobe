#!/usr/bin/env python3
"""
ollama-ctl.py — Load/unload/status control for a remote Ollama instance.
Lives on aegis. Laptop/phone SSH into aegis and run this directly.

Usage:
    ollama-ctl.py load      <model> [duration]   # default duration = -1 (forever)
    ollama-ctl.py unload    <model>
    ollama-ctl.py keepalive <model> <duration>
    ollama-ctl.py status
    ollama-ctl.py models

Examples:
    ollama-ctl.py load qwen2.5-coder:32b
    ollama-ctl.py load qwen2.5-coder:32b 60m
    ollama-ctl.py unload qwen2.5-coder:32b
    ollama-ctl.py status
    ollama-ctl.py models
"""

import sys
import json
import urllib.request
import urllib.error

# ---- Configure once ----
OLLAMA_HOST = "http://ai-brain.hare-catla.ts.net:11434"
# -------------------------

def _post(path, payload):
    url = f"{OLLAMA_HOST}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read()

def _get(path):
    url = f"{OLLAMA_HOST}{path}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read())

def load(model, duration="-1"):
    keep_alive = int(duration) if duration.lstrip("-").isdigit() else duration
    _post("/api/generate", {"model": model, "keep_alive": keep_alive})
    print(f"Loaded '{model}' — keep_alive={duration}")

def unload(model):
    _post("/api/generate", {"model": model, "keep_alive": 0})
    print(f"Unloaded '{model}'")

def keepalive(model, duration):
    keep_alive = int(duration) if duration.lstrip("-").isdigit() else duration
    _post("/api/generate", {"model": model, "keep_alive": keep_alive})
    print(f"Set '{model}' keep_alive={duration}")

def status():
    data = _get("/api/ps")
    models = data.get("models", [])
    if not models:
        print("No models currently loaded.")
        return
    for m in models:
        print(f"{m.get('name')}  |  expires_at: {m.get('expires_at')}  |  size: {m.get('size')}")

def list_models():
    data = _get("/api/tags")
    models = data.get("models", [])
    if not models:
        print("No models installed on workstation.")
        return
    print(f"{'NAME':<30} {'SIZE':<12} MODIFIED")
    for m in models:
        name = m.get("name", "?")
        size_gb = round(m.get("size", 0) / (1024**3), 1)
        modified = m.get("modified_at", "?")
        print(f"{name:<30} {str(size_gb)+'GB':<12} {modified}")

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    try:
        if cmd == "load":
            load(*args)
        elif cmd == "unload":
            unload(*args)
        elif cmd == "keepalive":
            keepalive(*args)
        elif cmd == "status":
            status()
        elif cmd == "models":
            list_models()
        else:
            print(__doc__)
            sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Connection failed — is Ollama reachable at {OLLAMA_HOST}? ({e})")
        sys.exit(1)
    except TypeError:
        print(__doc__)
        sys.exit(1)

if __name__ == "__main__":
    main()