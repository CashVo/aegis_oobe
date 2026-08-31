#!/usr/bin/env python3
# aegis/utils/secrets.py
# Secret/Key management utilities for Aegis
#
# Implements: Secure API key and secret management via .env and .bashrc
# Features: add-key, remove-key, change-key, copy-key, list-keys, show-key, export-keys, import-keys

"""
Secret/Key Management for Aegis

Provides secure handling of API keys and secrets via:
- .env files (project-local, gitignored)
- ~/.bashrc (user-global, persistent across projects)

Security Best Practices:
- Never display secrets in plain text (redacted/obfuscated only)
- Use secure input (hidden prompts) for key entry
- Support key rotation and auditing
- Validate key formats where possible
- Audit trail for key changes
"""

import os
import re
import shutil
import getpass
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from enum import Enum
import json
from datetime import datetime


class SecretSource(Enum):
    """Where a secret is stored."""
    ENV_FILE = ".env"
    BASHRC = "~/.bashrc"
    ENVIRONMENT = "environment"


@dataclass
class SecretEntry:
    """Represents a single secret/key entry."""
    key: str
    value: str
    source: SecretSource
    description: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    is_valid: bool = True
    validation_error: str = ""


class SecretsManager:
    """
    Manages API keys and secrets across .env and .bashrc.
    
    Security Features:
    - Redacted display (shows only first/last 4 chars)
    - Hidden input prompts
    - Key format validation
    - Audit logging of changes
    - Backup before modifications
    """
    
    # Known key patterns for validation
    KEY_PATTERNS = {
        "OPENAI_API_KEY": r"^sk-[a-zA-Z0-9]{48,}$",
        "ANTHROPIC_API_KEY": r"^sk-ant-[a-zA-Z0-9_-]{95,}$",
        "OPENROUTER_API_KEY": r"^sk-or-v1-[a-zA-Z0-9_-]{100,}$",
        "GITHUB_TOKEN": r"^gh[pousr]_[a-zA-Z0-9]{36,}$",
        "HUGGINGFACE_TOKEN": r"^hf_[a-zA-Z0-9]{34,}$",
        "REDDIT_CLIENT_ID": r"^[a-zA-Z0-9_-]{14}$",
        "REDDIT_CLIENT_SECRET": r"^[a-zA-Z0-9_-]{27}$",
        "TWITTER_API_KEY": r"^[a-zA-Z0-9]{25}$",
        "TWITTER_API_SECRET": r"^[a-zA-Z0-9]{50}$",
        "DISCORD_TOKEN": r"^[a-zA-Z0-9_-]{59}\.[a-zA-Z0-9_-]{6}\.[a-zA-Z0-9_-]{27}$",
        "SLACK_BOT_TOKEN": r"^xoxb-[0-9]{11,}-[0-9]{11,}-[a-zA-Z0-9]{24}$",
        "SLACK_APP_TOKEN": r"^xapp-[0-9]{11,}-[0-9]{11,}-[a-zA-Z0-9]{24}$",
        "AWS_ACCESS_KEY_ID": r"^AKIA[0-9A-Z]{16}$",
        "AWS_SECRET_ACCESS_KEY": r"^[a-zA-Z0-9/+=]{40}$",
        "GOOGLE_API_KEY": r"^AIza[0-9A-Za-z_-]{35}$",
        "AZURE_API_KEY": r"^[a-f0-9]{32}$",
        "PINECONE_API_KEY": r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
        "WEAVIATE_API_KEY": r"^[a-zA-Z0-9_-]{64,}$",
        "QDRANT_API_KEY": r"^[a-zA-Z0-9_-]{64,}$",
        "REDIS_URL": r"^redis://",
        "DATABASE_URL": r"^(postgresql|mysql|sqlite)://",
    }
    
    # Keys that should be in .bashrc (global) vs .env (project-local)
    GLOBAL_KEYS = {
        "GITHUB_TOKEN", "HUGGINGFACE_TOKEN", "AWS_ACCESS_KEY_ID", 
        "AWS_SECRET_ACCESS_KEY", "AZURE_API_KEY", "GOOGLE_API_KEY"
    }
    
    PROJECT_KEYS = {
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY",
        "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "TWITTER_API_KEY",
        "TWITTER_API_SECRET", "DISCORD_TOKEN", "SLACK_BOT_TOKEN",
        "SLACK_APP_TOKEN", "PINECONE_API_KEY", "WEAVIATE_API_KEY",
        "QDRANT_API_KEY", "REDIS_URL", "DATABASE_URL"
    }
    
    def __init__(self, project_root: Optional[Path] = None):
        self.project_root = project_root or Path.cwd()
        self.env_file = self.project_root / ".env"
        self.bashrc_file = Path.home() / ".bashrc"
        self.audit_log_path = self.project_root / ".secrets_audit.log"
        
    def _redact_value(self, value: str, show_chars: int = 4) -> str:
        """Redact a secret value for safe display."""
        if not value:
            return "(empty)"
        if len(value) <= show_chars * 2:
            return "*" * len(value)
        return value[:show_chars] + "*" * (len(value) - show_chars * 2) + value[-show_chars:]
    
    def _validate_key_format(self, key: str, value: str) -> Tuple[bool, str]:
        """Validate a key's format against known patterns."""
        if key in self.KEY_PATTERNS:
            pattern = self.KEY_PATTERNS[key]
            if not re.match(pattern, value):
                return False, f"Value doesn't match expected format for {key}"
        return True, ""
    
    def _get_recommended_source(self, key: str) -> SecretSource:
        """Determine recommended storage location for a key."""
        if key in self.GLOBAL_KEYS:
            return SecretSource.BASHRC
        return SecretSource.ENV_FILE
    
    def _read_env_file(self) -> Dict[str, str]:
        """Read .env file and return key-value pairs."""
        if not self.env_file.exists():
            return {}
        
        secrets = {}
        content = self.env_file.read_text()
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                secrets[k.strip()] = v.strip().strip('"\'')
        return secrets
    
    def _read_bashrc(self) -> Dict[str, str]:
        """Read .bashrc and extract export statements."""
        if not self.bashrc_file.exists():
            return {}
        
        secrets = {}
        content = self.bashrc_file.read_text()
        # Match export KEY="value" or export KEY=value
        pattern = r'^export\s+([A-Z_][A-Z0-9_]*)\s*=\s*["\']?([^"\'\n]+)["\']?'
        for match in re.finditer(pattern, content, re.MULTILINE):
            secrets[match.group(1)] = match.group(2)
        return secrets
    
    def _write_env_file(self, secrets: Dict[str, str], descriptions: Optional[Dict[str, str]] = None) -> None:
        """Write secrets to .env file with optional descriptions."""
        descriptions = descriptions or {}
        lines = ["# Aegis Project Secrets", f"# Generated: {datetime.now().isoformat()}", ""]
        
        for key in sorted(secrets.keys()):
            if key in descriptions:
                lines.append(f"# {descriptions[key]}")
            lines.append(f'{key}="{secrets[key]}"')
            lines.append("")
        
        self.env_file.write_text("\n".join(lines))
    
    def _write_bashrc(self, secrets: Dict[str, str], descriptions: Optional[Dict[str, str]] = None) -> None:
        """Write secrets to .bashrc as export statements."""
        descriptions = descriptions or {}
        
        # Read existing content
        content = self.bashrc_file.read_text() if self.bashrc_file.exists() else ""
        
        # Remove existing Aegis-managed exports (between markers)
        start_marker = "# >>> AEGIS SECRETS START >>>"
        end_marker = "# <<< AEGIS SECRETS END <<<"
        
        if start_marker in content and end_marker in content:
            before = content.split(start_marker)[0]
            after = content.split(end_marker)[1]
        else:
            before = content.rstrip() + "\n\n" if content else ""
            after = ""
        
        # Build new secrets section
        lines = [start_marker, "# Aegis-managed secrets - DO NOT EDIT MANUALLY", ""]
        for key in sorted(secrets.keys()):
            if key in descriptions:
                lines.append(f"# {descriptions[key]}")
            lines.append(f'export {key}="{secrets[key]}"')
        lines.append("")
        lines.append(end_marker)
        
        new_content = before + "\n".join(lines) + after
        self.bashrc_file.write_text(new_content)
    
    def _backup_file(self, file_path: Path) -> Optional[Path]:
        """Create a backup of a file before modification."""
        if not file_path.exists():
            return None
        backup = file_path.with_suffix(f"{file_path.suffix}.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        shutil.copy2(file_path, backup)
        return backup
    
    def _log_audit(self, action: str, key: str, source: SecretSource, details: str = "") -> None:
        """Log an audit entry for secret changes."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "key": key,
            "source": source.value,
            "details": details
        }
        with open(self.audit_log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    
    def load_all(self) -> Dict[str, SecretEntry]:
        """Load all secrets from all sources."""
        entries = {}
        
        # Load from .env
        env_secrets = self._read_env_file()
        for key, value in env_secrets.items():
            is_valid, error = self._validate_key_format(key, value)
            entries[key] = SecretEntry(
                key=key,
                value=value,
                source=SecretSource.ENV_FILE,
                is_valid=is_valid,
                validation_error=error
            )
        
        # Load from .bashrc
        bashrc_secrets = self._read_bashrc()
        for key, value in bashrc_secrets.items():
            is_valid, error = self._validate_key_format(key, value)
            # If already in .env, .env takes precedence
            if key not in entries:
                entries[key] = SecretEntry(
                    key=key,
                    value=value,
                    source=SecretSource.BASHRC,
                    is_valid=is_valid,
                    validation_error=error
                )
            else:
                # Mark as also in bashrc
                entries[key].source = SecretSource.ENV_FILE
        
        # Load from environment (highest precedence)
        for key in set(env_secrets.keys()) | set(bashrc_secrets.keys()):
            if key in os.environ:
                env_value = os.environ[key]
                is_valid, error = self._validate_key_format(key, env_value)
                if key in entries:
                    entries[key].value = env_value
                    entries[key].source = SecretSource.ENVIRONMENT
                    entries[key].is_valid = is_valid
                    entries[key].validation_error = error
                else:
                    entries[key] = SecretEntry(
                        key=key,
                        value=env_value,
                        source=SecretSource.ENVIRONMENT,
                        is_valid=is_valid,
                        validation_error=error
                    )
        
        return entries
    
    def list_keys(self, show_values: bool = False, redacted: bool = True) -> List[SecretEntry]:
        """List all known keys with optional value display."""
        entries = self.load_all()
        result = []
        for entry in entries.values():
            # Create a copy to avoid modifying the original
            entry_copy = SecretEntry(
                key=entry.key,
                value=entry.value,
                source=entry.source,
                description=entry.description,
                created_at=entry.created_at,
                updated_at=entry.updated_at,
                is_valid=entry.is_valid,
                validation_error=entry.validation_error
            )
            if show_values:
                if redacted:
                    entry_copy.value = self._redact_value(entry_copy.value)
            else:
                entry_copy.value = self._redact_value(entry_copy.value) if redacted else "(hidden)"
            result.append(entry_copy)
        return sorted(result, key=lambda e: e.key)
    
    def get_key(self, key: str, redacted: bool = True) -> Optional[SecretEntry]:
        """Get a specific key's value."""
        entries = self.load_all()
        if key in entries:
            entry = entries[key]
            # Create a copy to avoid modifying the original
            entry_copy = SecretEntry(
                key=entry.key,
                value=entry.value,
                source=entry.source,
                description=entry.description,
                created_at=entry.created_at,
                updated_at=entry.updated_at,
                is_valid=entry.is_valid,
                validation_error=entry.validation_error
            )
            if redacted:
                entry_copy.value = self._redact_value(entry_copy.value)
            return entry_copy
        return None
    
    def add_key(
        self, 
        key: str, 
        value: Optional[str] = None, 
        source: Optional[SecretSource] = None,
        description: str = "",
        interactive: bool = True
    ) -> Tuple[bool, str]:
        """
        Add a new key or update existing one.
        
        Returns: (success, message)
        """
        # Validate key name
        if not re.match(r'^[A-Z_][A-Z0-9_]*$', key):
            return False, f"Invalid key name: {key}. Must be uppercase with underscores."
        
        # Check if key already exists in FILES (not environment)
        env_secrets = self._read_env_file()
        bashrc_secrets = self._read_bashrc()
        if key in env_secrets or key in bashrc_secrets:
            return False, f"Key {key} already exists. Use change-key to modify."
        
        # Get value interactively if not provided
        if value is None and interactive:
            value = getpass.getpass(f"Enter value for {key}: ").strip()
            if not value:
                return False, "No value provided"
            # Confirm
            confirm = getpass.getpass(f"Confirm value for {key}: ").strip()
            if value != confirm:
                return False, "Values don't match"
        
        if not value:
            return False, "No value provided"
        
        # Validate format
        is_valid, error = self._validate_key_format(key, value)
        if not is_valid:
            return False, f"Validation failed: {error}"
        
        # Determine source
        if source is None:
            source = self._get_recommended_source(key)
        
        # Backup and write
        try:
            if source == SecretSource.ENV_FILE:
                backup = self._backup_file(self.env_file)
                secrets = self._read_env_file()
                secrets[key] = value
                descriptions = {key: description} if description else {}
                self._write_env_file(secrets, descriptions)
            else:
                backup = self._backup_file(self.bashrc_file)
                secrets = self._read_bashrc()
                secrets[key] = value
                descriptions = {key: description} if description else {}
                self._write_bashrc(secrets, descriptions)
            
            self._log_audit("add", key, source, f"Added to {source.value}")
            return True, f"Key {key} added to {source.value}"
        except Exception as e:
            return False, f"Failed to write: {e}"
    
    def remove_key(self, key: str, source: Optional[SecretSource] = None) -> Tuple[bool, str]:
        """Remove a key from storage."""
        entries = self.load_all()
        if key not in entries:
            return False, f"Key {key} not found"
        
        entry = entries[key]
        target_source = source or entry.source
        
        try:
            if target_source == SecretSource.ENV_FILE:
                backup = self._backup_file(self.env_file)
                secrets = self._read_env_file()
                if key in secrets:
                    del secrets[key]
                    self._write_env_file(secrets)
                else:
                    return False, f"Key {key} not found in .env"
            elif target_source == SecretSource.BASHRC:
                backup = self._backup_file(self.bashrc_file)
                secrets = self._read_bashrc()
                if key in secrets:
                    del secrets[key]
                    self._write_bashrc(secrets)
                else:
                    return False, f"Key {key} not found in .bashrc"
            else:
                return False, f"Cannot remove from {target_source.value} directly"
            
            self._log_audit("remove", key, target_source, f"Removed from {target_source.value}")
            return True, f"Key {key} removed from {target_source.value}"
        except Exception as e:
            return False, f"Failed to remove: {e}"
    
    def change_key(
        self, 
        key: str, 
        new_value: Optional[str] = None,
        interactive: bool = True
    ) -> Tuple[bool, str]:
        """Change an existing key's value."""
        entries = self.load_all()
        if key not in entries:
            return False, f"Key {key} not found"
        
        entry = entries[key]
        
        # Get new value
        if new_value is None and interactive:
            print(f"Current value: {self._redact_value(entry.value)}")
            new_value = getpass.getpass(f"Enter new value for {key}: ").strip()
            if not new_value:
                return False, "No value provided"
            confirm = getpass.getpass(f"Confirm new value for {key}: ").strip()
            if new_value != confirm:
                return False, "Values don't match"
        
        if not new_value:
            return False, "No value provided"
        
        # Validate
        is_valid, error = self._validate_key_format(key, new_value)
        if not is_valid:
            return False, f"Validation failed: {error}"
        
        # Update in source
        try:
            if entry.source == SecretSource.ENV_FILE:
                backup = self._backup_file(self.env_file)
                secrets = self._read_env_file()
                secrets[key] = new_value
                self._write_env_file(secrets)
            elif entry.source == SecretSource.BASHRC:
                backup = self._backup_file(self.bashrc_file)
                secrets = self._read_bashrc()
                secrets[key] = new_value
                self._write_bashrc(secrets)
            else:
                return False, f"Cannot modify {entry.source.value} directly - set in environment"
            
            self._log_audit("change", key, entry.source, "Value updated")
            return True, f"Key {key} updated in {entry.source.value}"
        except Exception as e:
            return False, f"Failed to update: {e}"
    
    def copy_key(self, key: str, target_source: SecretSource) -> Tuple[bool, str]:
        """Copy a key from one source to another."""
        entries = self.load_all()
        if key not in entries:
            return False, f"Key {key} not found"
        
        entry = entries[key]
        if entry.source == target_source:
            return False, f"Key already in {target_source.value}"
        
        try:
            if target_source == SecretSource.ENV_FILE:
                backup = self._backup_file(self.env_file)
                secrets = self._read_env_file()
                secrets[key] = entry.value
                self._write_env_file(secrets)
            elif target_source == SecretSource.BASHRC:
                backup = self._backup_file(self.bashrc_file)
                secrets = self._read_bashrc()
                secrets[key] = entry.value
                self._write_bashrc(secrets)
            
            self._log_audit("copy", key, target_source, f"Copied from {entry.source.value} to {target_source.value}")
            return True, f"Key {key} copied to {target_source.value}"
        except Exception as e:
            return False, f"Failed to copy: {e}"
    
    def move_key(self, key: str, target_source: SecretSource) -> Tuple[bool, str]:
        """Move a key from one source to another (copy + remove from source)."""
        # First get the original source
        entries = self.load_all()
        if key not in entries:
            return False, f"Key {key} not found"
        original_source = entries[key].source
        
        success, msg = self.copy_key(key, target_source)
        if not success:
            return False, msg
        
        return self.remove_key(key, original_source)
    
    def export_keys(self, output_file: Path, include_values: bool = True) -> Tuple[bool, str]:
        """Export all keys to a JSON file (for backup/migration)."""
        entries = self.load_all()
        data = {
            "exported_at": datetime.now().isoformat(),
            "project_root": str(self.project_root),
            "keys": {}
        }
        
        for key, entry in entries.items():
            if include_values:
                value = entry.value
            else:
                value = self._redact_value(entry.value)
            data["keys"][key] = {
                "value": value,
                "source": entry.source.value,
                "description": entry.description,
                "is_valid": entry.is_valid,
                "validation_error": entry.validation_error
            }
        
        try:
            output_file.write_text(json.dumps(data, indent=2))
            self._log_audit("export", "ALL", SecretSource.ENV_FILE, f"Exported to {output_file}")
            return True, f"Exported {len(entries)} keys to {output_file}"
        except Exception as e:
            return False, f"Export failed: {e}"
    
    def import_keys(self, input_file: Path, target_source: SecretSource = SecretSource.ENV_FILE) -> Tuple[bool, str]:
        """Import keys from a JSON export file."""
        try:
            data = json.loads(input_file.read_text())
            keys = data.get("keys", {})
            
            imported = 0
            for key, info in keys.items():
                value = info.get("value")
                # Skip redacted values (contain ... or start with *)
                if value and not (value.startswith("*") or "..." in value):
                    success, msg = self.add_key(key, value, target_source, interactive=False)
                    if success:
                        imported += 1
            
            self._log_audit("import", "ALL", target_source, f"Imported {imported} keys from {input_file}")
            return True, f"Imported {imported} keys from {input_file}"
        except Exception as e:
            return False, f"Import failed: {e}"
    
    def rotate_key(self, key: str, new_value: Optional[str] = None) -> Tuple[bool, str]:
        """Rotate a key (change value and log rotation)."""
        return self.change_key(key, new_value)
    
    def audit_log_entries(self, limit: int = 50) -> List[Dict]:
        """Get recent audit log entries."""
        if not self.audit_log_path.exists():
            return []
        
        entries = []
        with open(self.audit_log_path) as f:
            for line in f:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries[-limit:]
    
    def validate_all(self) -> Dict[str, Tuple[bool, str]]:
        """Validate all loaded keys."""
        entries = self.load_all()
        results = {}
        for key, entry in entries.items():
            results[key] = (entry.is_valid, entry.validation_error)
        return results
    
    def sync_to_env(self, keys: Optional[List[str]] = None) -> Tuple[bool, str]:
        """Sync specified keys (or all) to .env file."""
        entries = self.load_all()
        target_keys = keys or list(entries.keys())
        
        env_secrets = self._read_env_file()
        updated = 0
        
        for key in target_keys:
            if key in entries:
                env_secrets[key] = entries[key].value
                updated += 1
        
        try:
            backup = self._backup_file(self.env_file)
            self._write_env_file(env_secrets)
            self._log_audit("sync", "MULTIPLE", SecretSource.ENV_FILE, f"Synced {updated} keys to .env")
            return True, f"Synced {updated} keys to .env"
        except Exception as e:
            return False, f"Sync failed: {e}"
    
    def doctor(self) -> Dict[str, List[str]]:
        """Run health checks on secret configuration."""
        issues = {
            "missing": [],
            "invalid_format": [],
            "duplicate_sources": [],
            "env_not_loaded": [],
            "recommendations": []
        }
        
        entries = self.load_all()
        
        for key, entry in entries.items():
            # Check format
            if not entry.is_valid:
                issues["invalid_format"].append(f"{key}: {entry.validation_error}")
            
            # Check if in environment
            if key not in os.environ:
                issues["env_not_loaded"].append(key)
            
            # Check for duplicates across sources
            env_has = key in self._read_env_file()
            bashrc_has = key in self._read_bashrc()
            if env_has and bashrc_has:
                issues["duplicate_sources"].append(key)
        
        # Recommendations
        for key in entries:
            recommended = self._get_recommended_source(key)
            actual = entries[key].source
            if recommended != actual and actual != SecretSource.ENVIRONMENT:
                issues["recommendations"].append(
                    f"{key}: recommended {recommended.value}, currently in {actual.value}"
                )
        
        return issues


# Convenience functions for CLI usage
def get_manager(project_root: Optional[Path] = None) -> SecretsManager:
    """Get a SecretsManager instance."""
    return SecretsManager(project_root)


def redact_value(value: str) -> str:
    """Redact a value for display."""
    mgr = SecretsManager()
    return mgr._redact_value(value)