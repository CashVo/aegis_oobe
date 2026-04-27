# File: aegis/__main__.py
# Purpose: Enables `python -m aegis` execution by forwarding to the main CLI app.

from aegis.main import cli_app

if __name__ == "__main__":
    cli_app()
