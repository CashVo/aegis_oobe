# Aegis Secrets Management Guide

## Overview

The `aegis secrets` command group provides secure management of API keys, tokens, and other credentials across two storage locations:

- **`.env`** — Project-local secrets (committed to `.gitignore`, travels with the project)
- **`~/.bashrc`** — User-global secrets (persists across projects, loaded in every shell)

## Security Best Practices Implemented

| Feature | Description |
|---------|-------------|
| **Hidden Input** | Values entered via `getpass` — never echoed to terminal |
| **Redacted Display** | Values shown as `sk-ab***xy` (first/last 4 chars only) |
| **Format Validation** | Known key patterns validated on add/change |
| **Audit Logging** | All changes logged to `.secrets_audit.log` |
| **Automatic Backups** | `.env.bak.TIMESTAMP` and `.bashrc.bak.TIMESTAMP` created before writes |
| **Source Separation** | Global vs project keys stored in recommended locations |

---

## Command Reference

### `aegis secrets list` — List All Secrets

```bash
# List all secrets (redacted values)
aegis secrets list

# Show redacted values explicitly
aegis secrets list --show-values

# Filter by source
aegis secrets list --source env
aegis secrets list --source bashrc

# Show only invalid keys
aegis secrets list --invalid
```

**Output Example:**
```
═══════════════════════════════════════════
  Secrets                                       
═══════════════════════════════════════════
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┓
┃ Key                ┃ Source    ┃ Status     ┃ Value (redacted)      ┃ Description     ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━┩
│ OPENAI_API_KEY     │ .env      │ ✓ Valid    │ sk-ab***xy            │ OpenAI API      │
│ OPENROUTER_API_KEY │ .env      │ ✓ Valid    │ sk-or***12            │ OpenRouter API  │
│ GITHUB_TOKEN       │ .bashrc   │ ✓ Valid    │ ghp_ab***yz           │ GitHub PAT      │
└────────────────────┴───────────┴────────────┴───────────────────────┴─────────────────┘
```

---

### `aegis secrets show` — Show Single Secret

```bash
# Show key details (redacted value)
aegis secrets show OPENROUTER_API_KEY

# Show full value (DANGEROUS - only for copy-paste)
aegis secrets show OPENROUTER_API_KEY --value
```

**Output Example:**
```
═══════════════════════════════════════
  Key: OPENROUTER_API_KEY
  Source: .env
  Status: ✓ Valid
  Value: sk-or-v1-a***bC3D
  Description: OpenRouter API key for LLM gateway
═══════════════════════════════════════
```

---

### `aegis secrets add` — Add New Secret

```bash
# Interactive (prompts securely for value)
aegis secrets add OPENROUTER_API_KEY

# With description
aegis secrets add OPENROUTER_API_KEY --desc "OpenRouter API key for LLM gateway"

# Specify storage location
aegis secrets add GITHUB_TOKEN --source bashrc --desc "GitHub Personal Access Token"

# Non-interactive (for scripts)
aegis secrets add API_KEY --value "sk-xxx" --non-interactive
```

**Interactive Flow:**
```
Enter value for OPENROUTER_API_KEY: ****************************************
Confirm value for OPENROUTER_API_KEY: ****************************************
[✓] Key OPENROUTER_API_KEY added to .env
```

**Security Notes:**
- Value never displayed in plain text during entry
- Format validated against known patterns (OpenRouter, OpenAI, GitHub, etc.)
- Recommended source auto-selected (`.env` for project keys, `.bashrc` for global)

---

### `aegis secrets remove` — Remove Secret

```bash
# Interactive confirmation
aegis secrets remove OLD_API_KEY

# Force (skip confirmation)
aegis secrets remove OLD_API_KEY --force

# Remove from specific source
aegis secrets remove GITHUB_TOKEN --source bashrc
```

---

### `aegis secrets change` — Change Secret Value

```bash
# Interactive (shows current redacted value)
aegis secrets change OPENROUTER_API_KEY

# Non-interactive
aegis secrets change OPENROUTER_API_KEY --value "sk-new-key" --non-interactive
```

**Interactive Flow:**
```
Current value: sk-or***12
Enter new value for OPENROUTER_API_KEY: ****************************
Confirm new value for OPENROUTER_API_KEY: ****************************
[✓] Key OPENROUTER_API_KEY updated in .env
```

---

### `aegis secrets copy` — Copy Between Sources

```bash
# Copy from .env to .bashrc (make project key global)
aegis secrets copy OPENROUTER_API_KEY bashrc

# Copy from .bashrc to .env (make global key project-local)
aegis secrets copy GITHUB_TOKEN env
```

---

### `aegis secrets move` — Move Between Sources

```bash
# Move key (copy + remove from source)
aegis secrets move GITHUB_TOKEN env
```

---

### `aegis secrets export` — Backup Secrets

```bash
# Export with values (for migration/backup)
aegis secrets export secrets_backup.json

# Export without values (audit-safe)
aegis secrets export secrets_audit.json --no-values
```

**Output Example (`secrets_backup.json`):**
```json
{
  "exported_at": "2026-08-21T15:30:00.000000",
  "project_root": "/home/user/aegis_oobe",
  "keys": {
    "OPENROUTER_API_KEY": {
      "value": "sk-or-v1-actual-key-value",
      "source": ".env",
      "description": "OpenRouter API key",
      "is_valid": true,
      "validation_error": ""
    }
  }
}
```

⚠️ **WARNING**: Exports with `--include-values` contain actual secrets. Store securely and delete after use.

---

### `aegis secrets import` — Restore Secrets

```bash
# Import to .env (default)
aegis secrets import secrets_backup.json

# Import to .bashrc
aegis secrets import secrets_backup.json --target bashrc
```

---

### `aegis secrets rotate` — Rotate Key

```bash
# Interactive rotation
aegis secrets rotate OPENROUTER_API_KEY

# Non-interactive
aegis secrets rotate OPENROUTER_API_KEY --value "sk-new-key" --non-interactive
```

Alias for `change` with explicit audit logging for key rotation tracking.

---

### `aegis secrets audit` — View Audit Trail

```bash
# Last 50 entries (default)
aegis secrets audit

# Last 100 entries
aegis secrets audit --limit 100
```

**Output Example:**
```
═══════════════════════════════════════════
  Secret Audit Log                            
═══════════════════════════════════════════
┏━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┓
┃ Timestamp            ┃ Action   ┃ Key              ┃ Source    ┃ Details                ┃
┡━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━┩
│ 2026-08-21 15:30:00  │ add      │ OPENROUTER_API_K │ .env      │ Added to .env          │
│ 2026-08-21 15:35:00  │ change   │ OPENROUTER_API_K │ .env      │ Value updated          │
│ 2026-08-21 15:40:00  │ rotate   │ OPENROUTER_API_K │ .env      │ Value updated          │
└──────────────────────┴──────────┴──────────────────┴───────────┴────────────────────────┘
```

---

### `aegis secrets validate` — Validate All Keys

```bash
aegis secrets validate
```

Checks all loaded keys against known format patterns (OpenAI, Anthropic, OpenRouter, GitHub, etc.).

**Output Example:**
```
═══════════════════════════════════════════
  Key Validation Results                    
═══════════════════════════════════════════
┏━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Key                  ┃ Status    ┃ Details                           ┃
┡━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ OPENAI_API_KEY       │ ✓ Valid   │                                   │
│ OPENROUTER_API_KEY   │ ✓ Valid   │                                   │
│ INVALID_KEY          │ ✗ Invalid │ Value doesn't match expected ...  │
└──────────────────────┴───────────┴───────────────────────────────────┘

Valid: 2/3
```

---

### `aegis secrets doctor` — Health Check

```bash
aegis secrets doctor
```

Comprehensive health checks:

| Check | Description |
|-------|-------------|
| **missing** | Keys referenced but not found |
| **invalid_format** | Keys failing format validation |
| **duplicate_sources** | Same key in both `.env` and `.bashrc` |
| **env_not_loaded** | Keys not present in current shell environment |
| **recommendations** | Keys in non-recommended storage location |

---

### `aegis secrets sync` — Sync to .env

```bash
# Sync all keys to .env
aegis secrets sync

# Sync specific keys
aegis secrets sync OPENROUTER_API_KEY GITHUB_TOKEN
```

Useful for consolidating keys from `.bashrc` into project-local `.env`.

---

### `aegis secrets generate` — Generate Placeholder/Random Keys

```bash
# Generate random 64-char secret
aegis secrets generate random

# Generate with custom name
aegis secrets generate random MY_CUSTOM_SECRET

# OpenRouter placeholder
aegis secrets generate openrouter

# GitHub token placeholder
aegis secrets generate github
```

**Output Example:**
```
[!] Generated OPENROUTER_API_KEY:
    sk-or-v1-PLACEHOLDER_REPLACE_WITH_REAL_KEY

[!] This is the ONLY time the full value will be displayed.
    Save it now - it will be redacted in all future outputs.

Add to .env now? [y/N]: y
[✓] Key OPENROUTER_API_KEY added to .env
```

---

## Key Storage Recommendations

| Key Type | Recommended Source | Reason |
|----------|-------------------|--------|
| `OPENAI_API_KEY` | `.env` | Project-specific |
| `ANTHROPIC_API_KEY` | `.env` | Project-specific |
| `OPENROUTER_API_KEY` | `.env` | Project-specific |
| `GITHUB_TOKEN` | `.bashrc` | Used across projects |
| `HUGGINGFACE_TOKEN` | `.bashrc` | Used across projects |
| `AWS_ACCESS_KEY_ID` | `.bashrc` | Global credentials |
| `AWS_SECRET_ACCESS_KEY` | `.bashrc` | Global credentials |
| `DATABASE_URL` | `.env` | Project-specific |
| `REDIS_URL` | `.env` | Project-specific |

---

## Workflow Examples

### Initial Project Setup

```bash
# 1. Clone project
git clone https://github.com/your/aegis_oobe.git
cd aegis_oobe

# 2. Add required API keys
aegis secrets add OPENROUTER_API_KEY --desc "OpenRouter for LLM gateway"
aegis secrets add OPENAI_API_KEY --desc "OpenAI for embeddings"

# 3. Add global keys (if not already in ~/.bashrc)
aegis secrets add GITHUB_TOKEN --source bashrc --desc "GitHub PAT for repo access"

# 4. Validate
aegis secrets validate
aegis secrets doctor
```

### Key Rotation (Monthly Security Practice)

```bash
# 1. Check current keys
aegis secrets list --show-values

# 2. Rotate OpenRouter key
aegis secrets rotate OPENROUTER_API_KEY
# Enter new key from OpenRouter dashboard

# 3. Verify
aegis secrets validate
aegis secrets audit --limit 10
```

### Team Member Onboarding

```bash
# 1. Export template (no values)
aegis secrets export team_template.json --no-values

# 2. Share template with team member
# They fill in their own keys

# 3. Team member imports
aegis secrets import team_template.json
# Prompts for each key value securely
```

### Migration to New Machine

```bash
# On old machine
aegis secrets export ~/secrets_migration.json

# Transfer file securely (encrypted USB, password-protected archive, etc.)

# On new machine
aegis secrets import ~/secrets_migration.json
```

### CI/CD Integration

```bash
# In CI pipeline, inject secrets as environment variables
# Export from local for reference
aegis secrets export ci_secrets.json --no-values

# In GitHub Actions:
# - Store secrets in GitHub Secrets UI
# - Reference in workflow: ${{ secrets.OPENROUTER_API_KEY }}
```

---

## Audit Log Format

Each entry in `.secrets_audit.log` is a JSON line:

```json
{
  "timestamp": "2026-08-21T15:30:00.123456",
  "action": "add|remove|change|copy|move|rotate|export|import|sync",
  "key": "OPENROUTER_API_KEY",
  "source": ".env|.bashrc|environment",
  "details": "Human-readable description"
}
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Key not loading in shell | Run `source ~/.bashrc` or restart terminal |
| "Invalid format" error | Check key pattern at https://platform.openrouter.ai/docs |
| Duplicate in both sources | Run `aegis secrets doctor`, then `move` to recommended |
| Audit log growing large | Archive old entries: `mv .secrets_audit.log .secrets_audit.log.2026-08` |
| Forgot key value | Cannot recover — rotate and generate new key |

---

## Quick Reference Card

```bash
# Daily use
aegis secrets list                 # See all keys
aegis secrets add KEY_NAME         # Add new key (secure prompt)
aegis secrets change KEY_NAME      # Update key (shows current)

# Maintenance
aegis secrets validate             # Check all formats
aegis secrets doctor               # Full health check
aegis secrets audit                # Review changes

# Backup/Restore
aegis secrets export backup.json   # With values (secure!)
aegis secrets import backup.json   # Restore

# Advanced
aegis secrets move KEY env         # Move global → project
aegis secrets copy KEY bashrc      # Copy project → global
aegis secrets generate random      # Generate secure random
```

---

## Integration with Aegis Agents

Once Aegis is running, it can use these commands as skills:

| Chat Command | Aegis Action |
|--------------|--------------|
| "Add my OpenRouter key" | `secrets add OPENROUTER_API_KEY` (prompts securely) |
| "Rotate the GitHub token" | `secrets rotate GITHUB_TOKEN` |
| "Show me all API keys" | `secrets list --show-values` |
| "Audit who changed keys" | `secrets audit --limit 100` |
| "Validate all keys" | `secrets validate` |
| "Backup secrets for migration" | `secrets export migration.json` |

The agent will prompt for confirmation on destructive operations and never display full secret values in chat.