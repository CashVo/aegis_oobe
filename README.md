# File: README.md
# Purpose: Project overview, setup, and architecture summary.

# Project Aegis

Aegis is a local-first, multi-agent AI system designed for robust, secure, and extensible operation. It is built on an event-driven architecture and is designed to be multi-tenant from the ground up.

## Core Architecture
- **Local-First:** No mandatory cloud dependencies. Runs on your own hardware.
- **Python-Based:** Uses standard Python 3.11+ with a `venv`.
- **Event-Driven:** Agents communicate asynchronously via a Redis message bus.
- **Multi-Agent:** A council of specialized agents handles distinct tasks (Orchestration, Code Generation, Memory, Security, etc.).
- **Multi-Tenant:** All data is strictly partitioned by `tenant_id` and `user_id`.

## Quick Setup

### One-Command Installation (Recommended)
For the simplest first-run experience, run the automated installer:
```bash
aegis install
```
This command handles everything automatically:
1. Installs optional dependencies (web UI, MCP server)
2. Starts Redis if not running
3. Starts the Aegis system
4. Bootstraps the identity store with root user and tenant

You can customize the installation:
```bash
aegis install --username myadmin --name "System Admin" --passphrase "secure123" --tenant-name "MyOrg"
```

### Manual Installation
If you prefer step-by-step control:

1.  **Clone the repository:**
    ```bash
    git clone <repository_url>
    cd project-aegis
    ```

2.  **Create and activate a virtual environment:**
    ```bash
    python -m venv .venv
    source .venv/bin/activate
    # On Windows: .venv\Scripts\activate
    ```

3.  **Install in editable mode with development dependencies:**
    ```bash
    pip install -e ".[dev]"
    ```

4.  **Start Redis (required):**
    ```bash
    # Ubuntu/Debian
    sudo apt-get install redis-server
    sudo systemctl start redis
    
    # macOS
    brew install redis
    brew services start redis
    
    # Docker
    docker run -d -p 6379:6379 redis:alpine
    ```

5.  **Start the Aegis system:**
    ```bash
    aegis start
    ```
    This launches the System Manager which starts all agents (Observer, Warden, Identity, Lexicon, Janus, Oracle, Forge, TOrchestrator) and the Mission Control web UI at http://localhost:8420.

6.  **First-Run Bootstrap** (if not using `aegis install`):
    On first run, the identity store is empty. You must bootstrap the system to create the initial tenant and root user:
    ```bash
    aegis user bootstrap --username root --tenant-name Default
    ```
    This creates:
    - The "Default" tenant with all system roles (root, admin, member, observer)
    - A root user with full (*) permissions
    
    You can customize the root username, display name, passphrase, and tenant name:
    ```bash
    aegis user bootstrap --username myadmin --name "System Admin" --passphrase "secure123" --tenant-name "MyOrg"
    ```

7.  **Run tests:**
    ```bash
    pytest
    ```

## Project Structure
- `aegis/`: The main Python package.
  - `agents/`: Agent implementations, starting with `base.py`.
  - `schemas/`: Pydantic models for core data structures like `AegisMessage`.
  - `config/`: Configuration loading and validation.
  - `bus/`: Redis message bus implementation.
- `tests/`: Unit and integration tests.
- `pyproject.toml`: Project metadata and dependencies.
- `aegis_config.yaml`: Default configuration file.
