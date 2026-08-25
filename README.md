# File: README.md
# Purpose: Project overview, setup, and architecture summary.

# Project Aegis

Aegis is a local-first, multi-agent AI system designed for robust, secure, and extensible operation. It is built on an event-driven architecture and is designed to be multi-tenant from the ground up.

## Core Architecture
- **Local-First:** No mandatory cloud dependencies. Runs on your own hardware.
- **Python-Based:** Uses standard Python 3.12 with a `venv`.
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
    For web UI and MCP server support:
    ```bash
    pip install -e ".[dev,web,mcp]"
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

## CLI Command Reference

The `aegis` CLI provides the following top-level commands:

| Command | Description |
|---------|-------------|
| `install` | Complete first-run installation (deps, Redis, system, bootstrap) |
| `start` | Start the Aegis system (System Manager + all agents + web UI) |
| `stop` | Graceful shutdown of the running Aegis system |
| `status` | Show system health (agents, Redis, scheduler) |
| `chat` | Interactive chat with TOrchestrator |
| `user` | User management commands |
| `tenant` | Tenant management commands |
| `memory` | Lexicon memory commands |
| `schedule` | Scheduler management commands |
| `config` | Configuration commands |
| `secrets` | Secret/Key management commands |

### `aegis install` — First-Run Installation
```bash
aegis install [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--username, -u` | Root username (default: `root`) |
| `--name, -n` | Root display name (default: `System Root`) |
| `--passphrase, -p` | Root passphrase (optional) |
| `--tenant-name` | Initial tenant name (default: `Default`) |
| `--config, -c` | Config file path (default: `aegis_config.yaml`) |
| `--skip-deps` | Skip optional dependency installation |
| `--skip-redis` | Skip Redis installation and startup |

### `aegis start` — Start System
```bash
aegis start [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--config, -c` | Config file path (default: `aegis_config.yaml`) |
| `--web / --no-web` | Enable/disable Mission Control Web UI (default: enabled) |
| `--port, -p` | Port for Mission Control Web UI (default: 8420) |

### `aegis stop` — Stop System
```bash
aegis stop [OPTIONS]
```
| Option | Description |
|--------|-------------|
| `--config, -c` | Config file path (default: `aegis_config.yaml`) |

### `aegis status` — System Health
```bash
aegis status [OPTIONS]
```
| Option | Description |
|--------|-------------|
| `--config, -c` | Config file path (default: `aegis_config.yaml`) |
| `--json` | Output as JSON |

### `aegis chat` — Interactive Chat
```bash
aegis chat [OPTIONS]
```
| Option | Description |
|--------|-------------|
| `--config, -c` | Config file path (default: `aegis_config.yaml`) |
| `--tenant` | Tenant ID (default: `default`) |
| `--user` | User ID (default: `root`) |
| `--session` | Resume existing session ID |

### `aegis user` — User Management
```bash
aegis user [OPTIONS] COMMAND
```

| Subcommand | Description |
|------------|-------------|
| `create` | Create a new user |
| `list` | List users in the current tenant |
| `update` | Update user details |
| `delete` | Delete a user |
| `bootstrap` | Bootstrap identity system (first-run init) |

**Examples:**
```bash
aegis user create --username alice --name "Alice Smith" --role member
aegis user list --tenant default
aegis user update --username alice --name "Alice Jones"
aegis user bootstrap --username admin --tenant-name MyOrg
```

### `aegis tenant` — Tenant Management
```bash
aegis tenant [OPTIONS] COMMAND
```

| Subcommand | Description |
|------------|-------------|
| `create` | Create a new tenant |
| `list` | List all tenants |

**Examples:**
```bash
aegis tenant create --name "Engineering" --display-name "Engineering Team"
aegis tenant list
```

### `aegis memory` — Lexicon Memory
```bash
aegis memory [OPTIONS] COMMAND
```

| Subcommand | Description |
|------------|-------------|
| `search` | Search Lexicon memory tiers |
| `export` | Export memory to portable JSON file |
| `import` | Import memory from JSON file |

**Examples:**
```bash
aegis memory search --query "API design" --tiers L1,L2
aegis memory export --file memory_backup.json
aegis memory import --file memory_backup.json
```

### `aegis schedule` — Scheduler
```bash
aegis schedule [OPTIONS] COMMAND
```

| Subcommand | Description |
|------------|-------------|
| `list` | List all scheduled jobs |
| `add` | Add a new scheduled job |
| `remove` | Remove a scheduled job |

**Examples:**
```bash
aegis schedule list
aegis schedule add --name "daily-report" --cron "0 9 * * *" --action "generate_report"
aegis schedule remove --name "daily-report"
```

### `aegis config` — Configuration
```bash
aegis config [OPTIONS] COMMAND
```

| Subcommand | Description |
|------------|-------------|
| `show` | Show current configuration |
| `set` | Set a configuration value (dot-notation key) |

**Examples:**
```bash
aegis config show
aegis config set oracle.default_model nemotron-3-ultra
aegis config set web.port 8420
```

### `aegis secrets` — Secret/Key Management
```bash
aegis secrets [OPTIONS] COMMAND
```

| Subcommand | Description |
|------------|-------------|
| `list` | List all managed secrets (values redacted) |
| `show` | Show details for a specific secret |
| `add` | Add a new secret key (secure prompt for value) |
| `remove` | Remove a secret key |
| `change` | Change an existing secret's value |
| `copy` | Copy a key from source to destination |
| `move` | Move a key (copy + remove from source) |
| `export` | Export all secrets to JSON for backup/migration |
| `import` | Import secrets from JSON export file |
| `rotate` | Rotate a key (alias for change with audit) |
| `audit` | Show audit trail of secret changes |
| `validate` | Validate all keys against known formats |
| `doctor` | Run health checks on secret configuration |
| `sync` | Sync keys to .env file |
| `generate` | Generate new API key placeholder or random secret |

**Examples:**
```bash
aegis secrets list
aegis secrets add --key OPENROUTER_API_KEY
aegis secrets show --key OPENROUTER_API_KEY
aegis secrets export --file secrets_backup.json
aegis secrets doctor
```

## Web UI (Mission Control)
When the system is running with web UI enabled (default), access the dashboard at:
- **Mission Control**: http://localhost:8420
- **Redis Bus Observability**: http://localhost:8420/redis-bus
- **Chat**: http://localhost:8420/chat
- **Memory Explorer**: http://localhost:8420/memory
- **Users**: http://localhost:8420/users
- **Scheduler**: http://localhost:8420/schedule
- **Logs**: http://localhost:8420/logs

Observer health endpoint (separate port):
- **Health**: http://127.0.0.1:8421/health

## Project Structure
- `aegis/`: The main Python package.
  - `agents/`: Agent implementations, starting with `base.py`.
  - `schemas/`: Pydantic models for core data structures like `AegisMessage`.
  - `config/`: Configuration loading and validation.
  - `bus/`: Redis message bus implementation.
  - `web/`: FastAPI web UI (Mission Control)
  - `observer/`: System monitoring and health
  - `manager/`: System Manager and agent registry
  - `cli/`: CLI command implementations
  - `forge/`: Tool execution agent
- `tests/`: Unit and integration tests.
- `pyproject.toml`: Project metadata and dependencies.
- `aegis_config.yaml`: Default configuration file.
- `docs/`: Additional documentation.

## Configuration
The system is configured via `aegis_config.yaml` with the following precedence:
1. CLI arguments (highest)
2. Environment variables (`AEGIS_*`)
3. YAML config file
4. Pydantic defaults (lowest)

Key sections:
- `redis`: Redis connection settings
- `oracle`: LLM gateway configuration (providers, models, cache)
- `system_manager`: Health checks, restart policies
- `scheduler`: Job store, enable/disable
- `web`: Mission Control host/port/CORS
- `observer`: Health endpoint port (default: 8421)
- `janus`: API Gateway settings
- `warden`: Authorization policies
- `identity`: User/tenant store
- `forge`: Execution workspace

## Common Issues & Solutions

### Port Conflicts
If you see "address already in use" errors:
- **Port 8420** (Mission Control): Change with `--port` or `web.port` in config
- **Port 8421** (Observer Health): Change `observer.health_port` in config
- The observer health server now auto-selects a free port if 8421 is taken

### Missing Dependencies
If `aegis start` fails with import errors:
```bash
pip install -e ".[web,mcp]"
```

### Redis Not Running
```bash
# Quick start with Docker
docker run -d -p 6379:6379 redis:alpine
```

### First-Run Bootstrap Fails
Ensure Redis is running, then:
```bash
aegis user bootstrap --username root --tenant-name Default
```

## Testing
```bash
# Run all tests
pytest

# Run specific test module
pytest tests/test_identity/

# Run with coverage
pytest --cov=aegis
```