# /doc/ENVIRONMENT_MANAGEMENT.md
# Aegis Multi-Environment Management Guide

## Overview

This document describes the dev/test/prod environment workflow for Aegis using Git worktrees, with operational commands in `utils/dev.py`.

## Environment Strategy

```
┌─────────────────────────────────────────────────────────────────┐
│                      MAIN REPOSITORY                            │
│  (bare or standard clone with worktrees)                        │
├──────────────────┬──────────────────┬──────────────────────────┤
│   DEV WORKTREE   │   TEST WORKTREE  │      PROD WORKTREE       │
│  (main branch)   │  (test branch)   │    (prod branch/tag)     │
│                  │                  │                          │
│  - Live reload   │  - Sample data   │  - Optimized build       │
│  - Debug logs    │  - Integration   │  - Minimal logging       │
│  - Hot reload    │    tests         │  - Release config        │
└──────────────────┴──────────────────┴──────────────────────────┘
```

## Quick Start

```bash
# 1. Clone the repository (if not already)
git clone https://github.com/cashvo/aegis_oobe.git
cd aegis_oobe

# 2. Set up all three environments
python -m utils.dev setup-envs

# 3. Start development
cd ../aegis-dev
python -m utils.dev start-dev

# 4. Run tests in test env
cd ../aegis-test
python -m utils.dev populate-test-data
python -m pytest -v

# 5. Deploy to prod
cd ../aegis-prod
python -m utils.dev deploy-prod
```

## Git Worktree Setup

### Automatic Setup (Recommended)

```bash
# From the main repo root
python -m utils.dev setup-envs
```

This creates:
- `../aegis-dev` → main branch (development)
- `../aegis-test` → test branch (testing with sample data)
- `../aegis-prod` → prod branch (production)

### Manual Setup

```bash
# Create worktrees manually
git worktree add ../aegis-dev main
git worktree add ../aegis-test test
git worktree add ../aegis-prod prod

# Or if branches don't exist yet
git worktree add -b test ../aegis-test main
git worktree add -b prod ../aegis-prod main
```

### Worktree Commands

```bash
# List all worktrees
python -m utils.dev worktree list

# Create a new worktree for a feature
python -m utils.dev worktree create feature/my-feature

# Remove a worktree
python -m utils.dev worktree remove feature/my-feature

# Sync all worktrees with remote
python -m utils.dev worktree sync
```

## Environment-Specific Commands

### Development Environment (`aegis-dev`)

```bash
cd ../aegis-dev

# Start dev server with hot reload
python -m utils.dev start-dev

# Or manually
uv run aegis-web --reload

# Run with debug logging
AEGIS_LOG_LEVEL=DEBUG uv run aegis-web

# Run tests
python -m utils.dev test -v

# Clean and reinstall
python -m utils.dev clean-install
```

### Test Environment (`aegis-test`)

```bash
cd ../aegis-test

# Populate sample data for observability testing
python -m utils.dev populate-test-data

# Run integration tests
python -m utils.dev test --integration

# Run specific test modules
python -m utils.dev test -k "redis_bus"

# Reset test data
python -m utils.dev reset-test-data
```

### Production Environment (`aegis-prod`)

```bash
cd ../aegis-prod

# Build optimized production
python -m utils.dev build-prod

# Deploy (uses production config)
python -m utils.dev deploy-prod

# Health check
python -m utils.dev health-check

# Rollback
python -m utils.dev rollback-prod
```

## Sample Data for Observability Testing

The `populate-test-data` command creates realistic test data:

```bash
cd ../aegis-test
python -m utils.dev populate-test-data
```

This creates:
- **5 agent streams** (warden, torchestrator, lexicon, janus, observer)
- **Broadcast stream** with system events
- **1000+ messages** with varied types, priorities, token usage
- **Consumer groups** with pending/acknowledged messages
- **Correlation chains** (request→response pairs)
- **Stuck/abandoned messages** for pipeline visualization
- **Token usage data** for charts (prompt/completion tokens)
- **Historical data** spanning 7 days for cumulative charts

### Data Characteristics

| Stream | Messages | Pending | Token Range | Purpose |
|--------|----------|---------|-------------|---------|
| warden | 200 | 15 | 50-500 | Security decisions |
| torchestrator | 300 | 25 | 100-2000 | Task orchestration |
| lexicon | 150 | 10 | 200-4000 | Context retrieval |
| janus | 100 | 5 | 50-300 | Policy evaluation |
| observer | 50 | 2 | 10-100 | Health/events |
| broadcast | 200 | 0 | 5-50 | System events |

## Configuration per Environment

Each environment uses its own config:

```
aegis-dev/
├── aegis_config.yaml      # Dev config (debug, local Redis)
├── .env                   # Dev secrets
└── aegis_data/            # Dev databases

aegis-test/
├── aegis_config.yaml      # Test config (test DB, sample data)
├── .env                   # Test secrets
└── aegis_data/            # Test databases + observability.db

aegis-prod/
├── aegis_config.yaml      # Prod config (optimized, external Redis)
├── .env                   # Prod secrets (gitignored)
└── aegis_data/            # Prod databases
```

### Config Differences

| Setting | Dev | Test | Prod |
|---------|-----|------|------|
| Log Level | DEBUG | INFO | WARNING |
| Redis DB | 0 | 1 | 2 |
| Hot Reload | Yes | No | No |
| Sample Data | No | Yes | No |
| Metrics | Basic | Full | Full |
| Rate Limits | None | Test | Strict |

## Dev.py Command Reference

### Environment Management
```bash
python -m utils.dev setup-envs          # Create all 3 worktrees
python -m utils.dev worktree list       # List worktrees
python -m utils.dev worktree create <name> [branch]  # New feature worktree
python -m utils.dev worktree remove <name>           # Remove worktree
python -m utils.dev worktree sync       # Pull latest in all worktrees
```

### Development
```bash
python -m utils.dev start-dev           # Start dev server (hot reload)
python -m utils.dev start-dev --port 8421  # Custom port
python -m utils.dev clean-install       # Clean + reinstall deps
python -m utils.dev test                # Run tests
python -m utils.dev test -v -k "redis"  # Verbose, filtered
```

### Testing
```bash
python -m utils.dev populate-test-data  # Create sample data
python -m utils.dev populate-test-data --days 30  # More history
python -m utils.dev reset-test-data     # Clear test data only
python -m utils.dev test --integration  # Integration tests
python -m utils.dev test --e2e          # End-to-end tests
```

### Production
```bash
python -m utils.dev build-prod          # Build optimized
python -m utils.dev deploy-prod         # Deploy to prod
python -m utils.dev health-check        # Verify deployment
python -m utils.dev rollback-prod       # Rollback last deploy
```

### Maintenance
```bash
python -m utils.dev delete-aegis        # Full cleanup (all envs)
python -m utils.dev reset-db            # Reset databases only
python -m utils.dev clean-logs          # Clean logs only
python -m utils.dev start-redis         # Start Redis
python -m utils.dev stop-redis          # Stop Redis
python -m utils.dev install-dev         # Install in dev mode
```

## Workflow: Feature Development

```bash
# 1. Create feature worktree from main
cd ~/aegis_oobe
python -m utils.dev worktree create feature/redis-bus-dashboard

# 2. Work in the feature directory
cd ../aegis-feature-redis-bus-dashboard
# ... make changes ...

# 3. Test locally
python -m utils.dev test -v

# 4. Commit and push
git add -A
git commit -m "feat: add redis bus dashboard"
git push origin feature/redis-bus-dashboard

# 5. Create PR, merge to main
# 6. Sync dev worktree
cd ../aegis-dev
git pull origin main

# 7. Deploy to test for integration testing
cd ../aegis-test
git pull origin test  # or merge main into test
python -m utils.dev populate-test-data
python -m utils.dev test --integration

# 8. Promote to prod
git tag v0.13.0
cd ../aegis-prod
git pull origin prod  # or checkout tag
python -m utils.dev deploy-prod
```

## CI/CD Integration

### GitHub Actions Example

```yaml
# .github/workflows/ci.yml
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Setup Python
        uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - name: Install
        run: pip install -e ".[dev]"
      - name: Test
        run: python -m utils.dev test --coverage

  integration:
    runs-on: ubuntu-latest
    needs: test
    steps:
      - uses: actions/checkout@v4
      - name: Setup test env
        run: |
          git worktree add -b test ../aegis-test main
          cd ../aegis-test
          python -m utils.dev populate-test-data
      - name: Integration tests
        run: python -m utils.dev test --integration
```

## Aegis Self-Management (Future)

Once Aegis is operational, it **can** manage this workflow with you steering from chat:

### How It Would Work

```
You (Chat) → Aegis Orchestrator → Dev Tools → Git/Worktree/Dev.py
```

### Commands Aegis Could Execute

| Chat Command | Aegis Action |
|--------------|--------------|
| "Create a feature branch for the new dashboard" | `worktree create feature/dashboard` |
| "Run the test suite" | `test --coverage` |
| "Deploy to test environment" | `populate-test-data && test --integration` |
| "Show me the pipeline health" | Query Redis Bus observability API |
| "Rollback production" | `rollback-prod` |
| "Create sample data for testing" | `populate-test-data --days 30` |

### Required Capabilities

1. **Dev Tool Access** - Aegis needs `utils.dev` as a tool/plugin
2. **Git Access** - Read/write to worktrees
3. **Process Management** - Start/stop services
4. **Observability Access** - Query its own dashboards
5. **Confirmation Gates** - Human approval for destructive ops

### Example Chat Flow

```
You: "Aegis, I need to test the new token chart with 30 days of data"

Aegis: "I'll set up the test environment with 30 days of sample data."
       → Runs: `worktree sync` → `populate-test-data --days 30` → `test -k token`
       
Aegis: "Done! Test environment ready at http://localhost:8421/redis-bus
        The token chart now has 30 days of cumulative data across 5 agents.
        Pipeline shows 12 stuck messages, 3 abandoned - ready for testing."

You: "Great. Deploy to test for the team to review."

Aegis: "Deploying to test environment..."
       → Merges feature branch to test, restarts test server
       
Aegis: "Test deployed at http://test.aegis.local/redis-bus
        Team can access via VPN. Archiver running, 7-day retention active."
```

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| Worktree already exists | `python -m utils.dev worktree remove <name>` then recreate |
| Redis connection failed | `python -m utils.dev start-redis` |
| Port already in use | `python -m utils.dev start-dev --port 8421` |
| Test data not loading | `python -m utils.dev reset-test-data && python -m utils.dev populate-test-data` |
| Config not found | Copy `aegis_config.yaml.example` to `aegis_config.yaml` |

### Reset Everything

```bash
# Nuclear option - reset all environments
python -m utils.dev delete-aegis --force
python -m utils.dev setup-envs
python -m utils.dev populate-test-data
```

## Security Notes

- **Never commit** `.env` files or `aegis_config.yaml` with secrets
- **Prod secrets** should come from vault/env vars, not files
- **Worktrees** share `.git` but have separate working directories
- **Redis** uses different DB numbers per environment (0/1/2)

---

## Quick Reference Card

```bash
# Daily workflow
cd ~/aegis-dev          # Development
python -m utils.dev start-dev

cd ~/aegis-test         # Testing  
python -m utils.dev populate-test-data

cd ~/aegis-prod         # Production
python -m utils.dev health-check

# From anywhere
python -m utils.dev worktree list
python -m utils.dev worktree sync
```