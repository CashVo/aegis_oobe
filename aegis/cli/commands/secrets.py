#!/usr/bin/env python3
# aegis/cli/commands/secrets.py
# Implements: Part X, §10.1 — `aegis secrets` subcommands

"""
Secret/Key Management CLI Commands

Provides secure handling of API keys and secrets:
- add-key: Add a new secret (with hidden input)
- remove-key: Remove a secret
- change-key: Change a secret's value
- copy-key: Copy a secret between .env and .bashrc
- move-key: Move a secret between sources
- list-keys: List all secrets (redacted by default)
- show-key: Show a specific secret (redacted)
- export-keys: Export secrets to JSON backup
- import-keys: Import secrets from JSON backup
- rotate-key: Rotate a key (alias for change-key)
- audit-log: Show audit trail
- validate: Validate all key formats
- doctor: Run health checks
- sync: Sync keys to .env
"""

import typer
from pathlib import Path
from typing import Annotated, Optional, List
from rich.table import Table
from rich.console import Console

from aegis.utils.secrets import (
    SecretsManager, 
    SecretSource, 
    SecretEntry,
    get_manager,
    redact_value
)

app = typer.Typer(
    name="secrets",
    help="Secret/Key management for API keys and credentials",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()


def get_secrets_manager() -> SecretsManager:
    """Get SecretsManager instance for current project."""
    project_root = Path.cwd()
    return get_manager(project_root)


def print_key_table(entries: List[SecretEntry], show_values: bool = False, title: str = "Secrets") -> None:
    """Print secrets in a formatted table."""
    table = Table(title=title, show_header=True, header_style="bold cyan")
    table.add_column("Key", style="bold")
    table.add_column("Source", style="dim")
    table.add_column("Status", justify="center")
    if show_values:
        table.add_column("Value (redacted)", style="yellow")
    table.add_column("Description")
    
    for entry in entries:
        status = "✓ Valid" if entry.is_valid else f"✗ Invalid: {entry.validation_error}"
        row = [
            entry.key,
            entry.source.value,
            status,
        ]
        if show_values:
            row.append(redact_value(entry.value))
        row.append(entry.description or "")
        table.add_row(*row)
    
    console.print(table)


@app.command("list")
def list_keys(
    show_values: Annotated[bool, typer.Option("--show-values", "-v", help="Show redacted values")] = False,
    source: Annotated[Optional[str], typer.Option("--source", "-s", help="Filter by source: env, bashrc, environment")] = None,
    invalid_only: Annotated[bool, typer.Option("--invalid", help="Show only invalid keys")] = False,
) -> None:
    """List all managed secrets (values redacted by default)."""
    mgr = get_secrets_manager()
    entries = mgr.list_keys(show_values=show_values, redacted=True)
    
    # Filter by source
    if source:
        try:
            src = SecretSource(source)
            entries = [e for e in entries if e.source == src]
        except ValueError:
            typer.echo(f"[✗] Invalid source: {source}. Use: env, bashrc, environment", err=True)
            raise typer.Exit(1)
    
    # Filter invalid only
    if invalid_only:
        entries = [e for e in entries if not e.is_valid]
    
    if not entries:
        typer.echo("[!] No secrets found")
        return
    
    print_key_table(entries, show_values=show_values)


@app.command("show")
def show_key(
    key: Annotated[str, typer.Argument(help="Key name to show")],
    show_value: Annotated[bool, typer.Option("--value", "-v", help="Show redacted value")] = True,
) -> None:
    """Show details for a specific secret."""
    mgr = get_secrets_manager()
    entry = mgr.get_key(key, redacted=not show_value)
    
    if not entry:
        typer.echo(f"[✗] Key not found: {key}", err=True)
        raise typer.Exit(1)
    
    typer.echo("═══════════════════════════════════════")
    typer.echo(f"  Key: {entry.key}")
    typer.echo(f"  Source: {entry.source.value}")
    typer.echo(f"  Status: {'✓ Valid' if entry.is_valid else f'✗ Invalid: {entry.validation_error}'}")
    if show_value:
        typer.echo(f"  Value: {redact_value(entry.value)}")
    if entry.description:
        typer.echo(f"  Description: {entry.description}")
    if entry.created_at:
        typer.echo(f"  Created: {entry.created_at}")
    if entry.updated_at:
        typer.echo(f"  Updated: {entry.updated_at}")
    typer.echo("═══════════════════════════════════════")


@app.command("add")
def add_key(
    key: Annotated[str, typer.Argument(help="Key name (UPPER_SNAKE_CASE)")],
    value: Annotated[Optional[str], typer.Option("--value", help="Value (if omitted, prompts securely)")] = None,
    source: Annotated[Optional[str], typer.Option("--source", "-s", help="Target source: env or bashrc")] = None,
    description: Annotated[Optional[str], typer.Option("--desc", "-d", help="Description for the key")] = None,
    non_interactive: Annotated[bool, typer.Option("--non-interactive", help="Fail if value not provided")] = False,
) -> None:
    """Add a new secret key (prompts securely for value if not provided)."""
    mgr = get_secrets_manager()
    
    src = None
    if source:
        try:
            src = SecretSource(source)
        except ValueError:
            typer.echo(f"[✗] Invalid source: {source}. Use: env or bashrc", err=True)
            raise typer.Exit(1)
    
    success, msg = mgr.add_key(
        key=key,
        value=value,
        source=src,
        description=description or "",
        interactive=not non_interactive
    )
    
    if success:
        typer.echo(f"[✓] {msg}")
    else:
        typer.echo(f"[✗] {msg}", err=True)
        raise typer.Exit(1)


@app.command("remove")
def remove_key(
    key: Annotated[str, typer.Argument(help="Key name to remove")],
    source: Annotated[Optional[str], typer.Option("--source", "-s", help="Source to remove from: env or bashrc")] = None,
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation")] = False,
) -> None:
    """Remove a secret key."""
    mgr = get_secrets_manager()
    
    if not force:
        if not typer.confirm(f"Remove key '{key}'?"):
            typer.echo("Aborted.")
            raise typer.Exit(0)
    
    src = None
    if source:
        try:
            src = SecretSource(source)
        except ValueError:
            typer.echo(f"[✗] Invalid source: {source}. Use: env or bashrc", err=True)
            raise typer.Exit(1)
    
    success, msg = mgr.remove_key(key, src)
    
    if success:
        typer.echo(f"[✓] {msg}")
    else:
        typer.echo(f"[✗] {msg}", err=True)
        raise typer.Exit(1)


@app.command("change")
def change_key(
    key: Annotated[str, typer.Argument(help="Key name to change")],
    value: Annotated[Optional[str], typer.Option("--value", help="New value (if omitted, prompts securely)")] = None,
    non_interactive: Annotated[bool, typer.Option("--non-interactive", help="Fail if value not provided")] = False,
) -> None:
    """Change an existing secret's value (shows current redacted value)."""
    mgr = get_secrets_manager()
    
    success, msg = mgr.change_key(key, value, interactive=not non_interactive)
    
    if success:
        typer.echo(f"[✓] {msg}")
    else:
        typer.echo(f"[✗] {msg}", err=True)
        raise typer.Exit(1)


@app.command("copy")
def copy_key(
    key: Annotated[str, typer.Argument(help="Key name to copy")],
    target: Annotated[str, typer.Argument(help="Target source: env or bashrc")],
) -> None:
    """Copy a key from its current source to another."""
    mgr = get_secrets_manager()
    
    try:
        target_src = SecretSource(target)
    except ValueError:
        typer.echo(f"[✗] Invalid target: {target}. Use: env or bashrc", err=True)
        raise typer.Exit(1)
    
    success, msg = mgr.copy_key(key, target_src)
    
    if success:
        typer.echo(f"[✓] {msg}")
    else:
        typer.echo(f"[✗] {msg}", err=True)
        raise typer.Exit(1)


@app.command("move")
def move_key(
    key: Annotated[str, typer.Argument(help="Key name to move")],
    target: Annotated[str, typer.Argument(help="Target source: env or bashrc")],
) -> None:
    """Move a key from its current source to another (copy + remove from source)."""
    mgr = get_secrets_manager()
    
    try:
        target_src = SecretSource(target)
    except ValueError:
        typer.echo(f"[✗] Invalid target: {target}. Use: env or bashrc", err=True)
        raise typer.Exit(1)
    
    if not typer.confirm(f"Move key '{key}' to {target_src.value}?"):
        typer.echo("Aborted.")
        raise typer.Exit(0)
    
    success, msg = mgr.move_key(key, target_src)
    
    if success:
        typer.echo(f"[✓] {msg}")
    else:
        typer.echo(f"[✗] {msg}", err=True)
        raise typer.Exit(1)


@app.command("export")
def export_keys(
    output: Annotated[Path, typer.Argument(help="Output JSON file path")],
    include_values: Annotated[bool, typer.Option("--include-values/--no-values", help="Include actual values (not redacted)")] = True,
) -> None:
    """Export all secrets to a JSON file for backup/migration."""
    mgr = get_secrets_manager()
    
    if output.exists():
        if not typer.confirm(f"Overwrite {output}?"):
            typer.echo("Aborted.")
            raise typer.Exit(0)
    
    success, msg = mgr.export_keys(output, include_values=include_values)
    
    if success:
        typer.echo(f"[✓] {msg}")
        if include_values:
            typer.echo("[!] WARNING: Export contains actual secret values - store securely!")
    else:
        typer.echo(f"[✗] {msg}", err=True)
        raise typer.Exit(1)


@app.command("import")
def import_keys(
    input_file: Annotated[Path, typer.Argument(help="Input JSON file path")],
    target: Annotated[str, typer.Option("--target", "-t", help="Target source: env or bashrc")] = "env",
) -> None:
    """Import secrets from a JSON export file."""
    mgr = get_secrets_manager()
    
    if not input_file.exists():
        typer.echo(f"[✗] File not found: {input_file}", err=True)
        raise typer.Exit(1)
    
    try:
        target_src = SecretSource(target)
    except ValueError:
        typer.echo(f"[✗] Invalid target: {target}. Use: env or bashrc", err=True)
        raise typer.Exit(1)
    
    success, msg = mgr.import_keys(input_file, target_src)
    
    if success:
        typer.echo(f"[✓] {msg}")
    else:
        typer.echo(f"[✗] {msg}", err=True)
        raise typer.Exit(1)


@app.command("rotate")
def rotate_key(
    key: Annotated[str, typer.Argument(help="Key name to rotate")],
    value: Annotated[Optional[str], typer.Option("--value", help="New value (if omitted, prompts securely)")] = None,
    non_interactive: Annotated[bool, typer.Option("--non-interactive", help="Fail if value not provided")] = False,
) -> None:
    """Rotate a key (alias for change-key with audit logging)."""
    mgr = get_secrets_manager()
    
    success, msg = mgr.rotate_key(key, value)
    
    if success:
        typer.echo(f"[✓] {msg}")
    else:
        typer.echo(f"[✗] {msg}", err=True)
        raise typer.Exit(1)


@app.command("audit")
def audit_log(
    limit: Annotated[int, typer.Option("--limit", "-n", help="Number of entries to show")] = 50,
) -> None:
    """Show audit trail of secret changes."""
    mgr = get_secrets_manager()
    entries = mgr.audit_log_entries(limit)
    
    if not entries:
        typer.echo("[!] No audit entries found")
        return
    
    table = Table(title="Secret Audit Log", show_header=True, header_style="bold cyan")
    table.add_column("Timestamp", style="dim")
    table.add_column("Action", style="bold")
    table.add_column("Key")
    table.add_column("Source")
    table.add_column("Details")
    
    for entry in reversed(entries):  # Most recent first
        table.add_row(
            entry["timestamp"][:19].replace("T", " "),
            entry["action"],
            entry["key"],
            entry["source"],
            entry["details"]
        )
    
    console.print(table)


@app.command("validate")
def validate_keys() -> None:
    """Validate all loaded keys against known formats."""
    mgr = get_secrets_manager()
    results = mgr.validate_all()
    
    if not results:
        typer.echo("[!] No keys to validate")
        return
    
    table = Table(title="Key Validation Results", show_header=True, header_style="bold cyan")
    table.add_column("Key", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Details")
    
    valid_count = 0
    for key, (is_valid, error) in sorted(results.items()):
        if is_valid:
            table.add_row(key, "✓ Valid", "")
            valid_count += 1
        else:
            table.add_row(key, "✗ Invalid", error)
    
    console.print(table)
    typer.echo(f"\nValid: {valid_count}/{len(results)}")
    
    if valid_count < len(results):
        raise typer.Exit(1)


@app.command("doctor")
def doctor() -> None:
    """Run health checks on secret configuration."""
    mgr = get_secrets_manager()
    issues = mgr.doctor()
    
    has_issues = False
    
    for category, items in issues.items():
        if items:
            has_issues = True
            typer.echo(f"\n[!] {category.replace('_', ' ').title()}:")
            for item in items:
                typer.echo(f"  • {item}")
    
    if not has_issues:
        typer.echo("[✓] All health checks passed!")
    else:
        typer.echo("\n[!] Issues found - review above")
        raise typer.Exit(1)


@app.command("sync")
def sync_keys(
    keys: Annotated[Optional[List[str]], typer.Argument(help="Specific keys to sync (default: all)")] = None,
) -> None:
    """Sync keys to .env file (useful for moving from bashrc to project-local)."""
    mgr = get_secrets_manager()
    
    success, msg = mgr.sync_to_env(keys)
    
    if success:
        typer.echo(f"[✓] {msg}")
    else:
        typer.echo(f"[✗] {msg}", err=True)
        raise typer.Exit(1)


@app.command("generate")
def generate_key(
    key_type: Annotated[str, typer.Argument(help="Type of key to generate: openrouter, github, random")],
    key_name: Annotated[Optional[str], typer.Argument(help="Custom key name (optional)")] = None,
) -> None:
    """Generate a new API key placeholder or random secret."""
    import secrets
    import string
    
    if key_type == "random":
        # Generate a secure random string
        alphabet = string.ascii_letters + string.digits + "-_"
        value = "".join(secrets.choice(alphabet) for _ in range(64))
        name = key_name or "GENERATED_SECRET"
    elif key_type == "openrouter":
        typer.echo("[!] OpenRouter keys must be created at https://openrouter.ai/keys")
        typer.echo("    This command only creates a placeholder.")
        value = "sk-or-v1-PLACEHOLDER_REPLACE_WITH_REAL_KEY"
        name = key_name or "OPENROUTER_API_KEY"
    elif key_type == "github":
        typer.echo("[!] GitHub tokens must be created at https://github.com/settings/tokens")
        typer.echo("    This command only creates a placeholder.")
        value = "ghp_PLACEHOLDER_REPLACE_WITH_REAL_TOKEN"
        name = key_name or "GITHUB_TOKEN"
    else:
        typer.echo(f"[✗] Unknown key type: {key_type}", err=True)
        typer.echo("Available types: random, openrouter, github")
        raise typer.Exit(1)
    
    # Show the generated value (only time it's shown in plain text!)
    typer.echo(f"\n[!] Generated {name}:")
    typer.echo(f"    {value}")
    typer.echo("\n[!] This is the ONLY time the full value will be displayed.")
    typer.echo("    Save it now - it will be redacted in all future outputs.")
    
    if typer.confirm("Add to .env now?"):
        mgr = get_secrets_manager()
        success, msg = mgr.add_key(name, value, SecretSource.ENV_FILE, f"Generated {key_type} key", interactive=False)
        if success:
            typer.echo(f"[✓] {msg}")
        else:
            typer.echo(f"[✗] {msg}", err=True)
            raise typer.Exit(1)