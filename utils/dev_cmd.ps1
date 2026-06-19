#!/usr/bin/env pwsh or powershell
# dev_cmd.ps1 - Aegis development command runner (uv-powered) - For use during dev phase (pre-Aegis CLI)
# dev.cmd - A command alias/wrapper that lives at root, points to where the dev_cmd.ps1 actual lives within the project
# Place at repo root (or utils/ with a dev.cmd wrapper)
#
# Example: The `help` command shows all of usage examples — `.\dev help` and gets the full menu.

[CmdletBinding(PositionalBinding = $true)]
param(
  [Parameter(Position = 0)]
  [string]$Task = "help",

  [string[]]$Extra = @(),
  [switch]$Dev,
  [switch]$Web,
  [switch]$Mcp,
  [switch]$All,
  [switch]$Frozen,
  [switch]$Upgrade,
  [switch]$Force,
  [string]$Python = "3.12",

  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$Passthru
)

$ErrorActionPreference = "Continue"
$DefaultPort = 8420
$BootstrapMarker = ".aegis_bootstrapped"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptRoot

Set-Location $RepoRoot

# ==================================================================
# SHARED HELPERS
# ==================================================================

function Get-ExtrasArgs {
  $set = New-Object 'System.Collections.Generic.HashSet[string]'
  foreach ($x in $Extra) { if ($x) { $null = $set.Add($x) } }
  if ($Dev) { $null = $set.Add("dev") }
  if ($Web) { $null = $set.Add("web") }
  if ($Mcp) { $null = $set.Add("mcp") }
  if ($All) { foreach ($x in @("dev","web","mcp")) { $null = $set.Add($x) } }
  $out = @()
  foreach ($x in $set) { $out += @("--extra", $x) }
  return $out
}

function Write-Header($msg) { Write-Host "`n--- $msg ---" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err($msg) { Write-Host "[ERR] $msg" -ForegroundColor Red }

function Assert-UvInstalled {
  if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Err "'uv' is not installed or not on PATH."
    Write-Host "  Install: irm https://astral.sh/uv/install.ps1 | iex" -ForegroundColor Yellow
    exit 1
  }
}

function Test-Bootstrapped { return (Test-Path $BootstrapMarker) -and (-not $Force) }
function Test-VenvExists { return Test-Path .venv }
function Test-VenvActive { return $null -ne $env:VIRTUAL_ENV }

# ==================================================================
# ENV FUNCTIONS (each flag = one function)
# ==================================================================

function Invoke-EnvStatus {
  Write-Header "Environment Status"

  $pyVer = if (Test-VenvActive) { & python --version 2>$null } else { & uv run python --version 2>$null }
  $uvVer = & uv --version 2>$null
  $pyExe = if (Test-VenvActive) { & python -c "import sys; print(sys.executable)" 2>$null } else { "N/A" }

  Write-Host "Python:     $pyVer"
  Write-Host "Executable: $pyExe"
  Write-Host "uv:         $uvVer"
  Write-Host "Installer:  uv (pip is not used in this project)" -ForegroundColor DarkGray
  Write-Host ""

  if (Test-VenvActive) {
    Write-Host "Venv:       ACTIVE ($env:VIRTUAL_ENV)" -ForegroundColor Green
  } elseif (Test-VenvExists) {
    Write-Host "Venv:       EXISTS (not activated)" -ForegroundColor Yellow
  } else {
    Write-Host "Venv:       NOT FOUND" -ForegroundColor Red
  }

  Write-Host "Platform:   $([System.Runtime.InteropServices.RuntimeInformation]::OSDescription)"
  Write-Host "CWD:        $(Get-Location)"
}

function Invoke-VenvCreate {
  Assert-UvInstalled
  Write-Header "Creating Virtual Environment"

  if (Test-VenvExists) {
    Write-Warn ".venv already exists. Destroy first with: .\dev env --venv_destroy"
    return $false
  }

  & uv python install $Python | Out-Host
  & uv venv --python $Python | Out-Host

  if (-not (Test-VenvExists)) {
    Write-Err "Venv creation failed."
    return $false
  }

  Write-Ok "Venv created (Python $Python)."
  return $true
}

function Invoke-VenvSync {
  Assert-UvInstalled

  if (Test-Path uv.lock) {
    Write-Host "Syncing dependencies from uv.lock..." -ForegroundColor Cyan
    & uv sync --extra dev --extra web --extra mcp | Out-Host
    Write-Ok "All dependencies installed."
    return $true
  } else {
    Write-Warn "No uv.lock found. Locking first..."
    & uv lock | Out-Host
    & uv sync --extra dev --extra web --extra mcp | Out-Host
    Write-Ok "Dependencies locked and installed."
    return $true
  }
}

function Invoke-VenvActivate {
  Write-Header "Activating Virtual Environment"

  if (-not (Test-VenvExists)) {
    Write-Err "No .venv found. Create one first: .\dev env --venv_create"
    return
  }

  if (Test-VenvActive) {
    Write-Warn "Already active: $env:VIRTUAL_ENV"
    return
  }

  Write-Host "[ADVISE] Run this command directly in your shell:" -ForegroundColor Cyan
  Write-Host ""
  Write-Host "  . .\.venv\Scripts\Activate.ps1" -ForegroundColor White
  Write-Host ""
  Write-Host "(Activation must be dot-sourced - cannot be executed from a child script)" -ForegroundColor DarkGray
}

function Invoke-VenvDeactivate {
  Write-Header "Deactivating Virtual Environment"

  if (-not (Test-VenvActive)) {
    Write-Warn "No venv is currently active."
    return
  }

  Write-Host "[ADVISE] Run this command directly in your shell:" -ForegroundColor Cyan
  Write-Host ""
  Write-Host "  deactivate" -ForegroundColor White
  Write-Host ""
  Write-Host "(Deactivation must run in the calling shell scope)" -ForegroundColor DarkGray
}

function Invoke-VenvDestroy {
  Write-Header "Destroying Virtual Environment"

  if (-not (Test-VenvExists)) {
    Write-Warn "No .venv to destroy."
    return $true
  }

  if (Test-VenvActive) {
    Write-Err "Venv is currently ACTIVE. Deactivate first."
    Write-Host "  Run: deactivate" -ForegroundColor White
    Write-Host "  Then: .\dev env --venv_destroy" -ForegroundColor White
    return $false
  }

  Write-Host "Removing .venv..." -ForegroundColor Yellow
  Remove-Item -Recurse -Force .venv -ErrorAction Stop
  Write-Ok ".venv destroyed."
  return $true
}

function Invoke-ClearBytecache {
  Write-Host "Clearing Python bytecache..." -ForegroundColor Yellow
  Get-ChildItem -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
  Write-Ok "Bytecache cleared."
}

function Invoke-InstallPkg([string]$PackageName) {
  Assert-UvInstalled
  Write-Header "Installing Package"

  if (-not $PackageName) {
    Write-Err "Missing package name."
    Write-Host "Usage: .\dev env --install_pkg <package_name>" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Examples:" -ForegroundColor Cyan
    Write-Host "  .\dev env --install_pkg redis"
    Write-Host "  .\dev env --install_pkg 'redis[hiredis]'"
    Write-Host "  .\dev env --install_pkg 'pydantic>=2.0'"
    return
  }

  if (-not (Test-VenvExists)) {
    Write-Err "No .venv found. Create one first: .\dev env --venv_create"
    return
  }

  Write-Host "Adding '$PackageName' via uv..." -ForegroundColor Cyan
  Write-Host ""
  & uv add $PackageName | Out-Host
  $exitCode = $LASTEXITCODE

  Write-Host ""
  if ($exitCode -eq 0) {
    Write-Ok "Package '$PackageName' installed successfully."
    Write-Host "  - pyproject.toml updated" -ForegroundColor DarkGray
    Write-Host "  - uv.lock regenerated" -ForegroundColor DarkGray
  } else {
    Write-Err "Failed to install '$PackageName'. Check the package name and try again."
  }
}

function Invoke-EnvVerify {
  Write-Host "Verifying key imports..." -ForegroundColor Cyan
  $checks = @(
    @{ Name = "redis"; Cmd = "import redis; print('OK')" },
    @{ Name = "rich"; Cmd = "import rich; print('OK')" },
    @{ Name = "fastapi"; Cmd = "import fastapi; print('OK')" },
    @{ Name = "pydantic"; Cmd = "import pydantic; print('OK')" }
  )
  foreach ($check in $checks) {
    $result = & uv run python -c $check.Cmd 2>$null
    $status = if ($result -eq "OK") { "OK" } else { "MISSING" }
    $color = if ($result -eq "OK") { "Green" } else { "Red" }
    Write-Host "  $($check.Name): $status" -ForegroundColor $color
  }
}

function Invoke-CleanBoot {
  Assert-UvInstalled
  Write-Header "Clean Boot - Full Environment Rebuild"

  if (Test-VenvActive) {
    Write-Err "Venv is active. Cannot destroy while active."
    Write-Host ""
    Write-Host "  Run these commands manually:" -ForegroundColor Cyan
    Write-Host "    deactivate" -ForegroundColor White
    Write-Host "    .\dev env --clean_boot" -ForegroundColor White
    return
  }

  # Step 1: Destroy
  Write-Host "[1/5] " -NoNewline
  Invoke-VenvDestroy | Out-Null

  # Step 2: Clear cache
  Write-Host "[2/5] " -NoNewline
  Invoke-ClearBytecache

  # Step 3: Create
  Write-Host "[3/5] " -NoNewline
  $created = Invoke-VenvCreate
  if (-not $created) { return }

  # Step 4: Sync
  Write-Host "[4/5] " -NoNewline
  Invoke-VenvSync

  # Step 5: Verify
  Write-Host "[5/5] " -NoNewline
  Invoke-EnvVerify

  Write-Host ""
  Write-Ok "=== CLEAN BOOT COMPLETE ==="
  Write-Host ""
  Write-Host "  Next steps:" -ForegroundColor White
  Write-Host "    .venv\Scripts\Activate" -ForegroundColor White
  Write-Host "    .\dev run boot --skip-redis --force" -ForegroundColor White
}

# ─────────────────────────────────────────────────────────────
# SEARCH — Search command set for Aegis dev tooling
# ─────────────────────────────────────────────────────────────

$script:DEFAULT_EXCLUDES = @('.venv', '__pycache__', '.git', 'node_modules', '.mypy_cache', '*.egg-info')

function _build_exclude_filter {
    param([string[]]$ExtraDirs = @())
    $all = $script:DEFAULT_EXCLUDES + $ExtraDirs
    return { 
        $path = $_.FullName
        foreach ($ex in $all) {
            if ($path -like "*\$ex\*" -or $path -like "*\$ex") { return $false }
        }
        return $true
    }
}

function _get_files {
    param(
        [string]$Path = ".",
        [string]$Include = "*.py",
        [string[]]$ExcludeDirs = @()
    )
    $filter = _build_exclude_filter -ExtraDirs $ExcludeDirs
    Get-ChildItem -Path $Path -Recurse -Include $Include -File | Where-Object $filter
}

function Dev-Search {
    $SubCommand = $args[0]

    # Strip the subcommand from the original args, pass the rest raw
    $passArgs = $args[1..($args.Count - 1)]  # everything after $SubCommand

    switch ($SubCommand) {
        "text"    { Dev-Search-Text @passArgs }
        "files"   { Dev-Search-Files @passArgs }
        "def"     { Dev-Search-Def @passArgs }
        "imports" { Dev-Search-Imports @passArgs }
        "todo"    { Dev-Search-Todo @passArgs }
        "replace" { Dev-Search-Replace @passArgs }
        "recent"  { Dev-Search-Recent @passArgs }
        default   {
            Write-Host "`n  dev search <command>" -ForegroundColor White
            Write-Host "    text     Grep files for a regex pattern"
            Write-Host "    files    Find files by name/glob"
            Write-Host "    def      Find function/class definitions"
            Write-Host "    imports  Find where a symbol is imported"
            Write-Host "    todo     Surface TODO/FIXME/HACK markers"
            Write-Host "    replace  Find-and-replace with preview"
            Write-Host "    recent   Recently modified files"
            Write-Host ""
        }
    }
}


# ─────────────────────────────────────────────────────────────
# dev search text
# ─────────────────────────────────────────────────────────────
function Dev-Search-Text {
    <#
    .SYNOPSIS
        Grep files for a regex pattern.
    .EXAMPLE
        dev search text --pattern "correlation_id=original\." 
        dev search text --pattern "async def" --include "*.py" --context 2
        dev search text --pattern "TODO" --path .\agents\ --no-ignore-case
    #>
    param(
        [Parameter(Mandatory)][string]$Pattern,
        [string]$Path = ".",
        [string]$Include = "*.py",
        [switch]$NoIgnoreCase,
        [int]$Context = 0,
        [string[]]$ExcludeDirs = @()
    )

    $files = _get_files -Path $Path -Include $Include -ExcludeDirs $ExcludeDirs
    $params = @{
        Pattern = $Pattern
        CaseSensitive = $NoIgnoreCase.IsPresent
    }
    if ($Context -gt 0) { $params.Context = $Context }

    $results = $files | Select-String @params

    if (-not $results) {
        Write-Host "  No matches." -ForegroundColor DarkGray
        return
    }

    $grouped = $results | Group-Object Path
    foreach ($group in $grouped) {
        $relPath = [System.IO.Path]::GetRelativePath((Get-Location), $group.Name)
        Write-Host "`n  $relPath" -ForegroundColor Cyan
        foreach ($match in $group.Group) {
            $lineNum = "$($match.LineNumber)".PadLeft(4)
            Write-Host "    ${lineNum}: " -NoNewline -ForegroundColor DarkGray
            Write-Host $match.Line.Trim() -ForegroundColor White
        }
    }
    Write-Host "`n  $($results.Count) matches in $($grouped.Count) files." -ForegroundColor Green
}

# ─────────────────────────────────────────────────────────────
# dev search files
# ─────────────────────────────────────────────────────────────
function Dev-Search-Files {
    <#
    .SYNOPSIS
        Find files by name pattern.
    .EXAMPLE
        dev search files --pattern "*router*"
        dev search files --pattern "*.toml" --path .\config\
    #>
    param(
        [Parameter(Mandatory)][string]$Pattern,
        [string]$Path = ".",
        [string[]]$ExcludeDirs = @()
    )

    $filter = _build_exclude_filter -ExtraDirs $ExcludeDirs
    $results = Get-ChildItem -Path $Path -Recurse -Filter $Pattern -File | Where-Object $filter

    if (-not $results) {
        Write-Host "  No files found." -ForegroundColor DarkGray
        return
    }

    foreach ($f in $results) {
        $rel = [System.IO.Path]::GetRelativePath((Get-Location), $f.FullName)
        $size = "{0:N0} B" -f $f.Length
        Write-Host "  $rel" -NoNewline -ForegroundColor Cyan
        Write-Host "  ($size)" -ForegroundColor DarkGray
    }
    Write-Host "`n  $($results.Count) files found." -ForegroundColor Green
}

# ─────────────────────────────────────────────────────────────
# dev search def
# ─────────────────────────────────────────────────────────────
function Dev-Search-Def {
    <#
    .SYNOPSIS
        Find function or class definitions by name.
    .EXAMPLE
        dev search def --name "publish"
        dev search def --name "Router" --type class
    #>
    param(
        [Parameter(Mandatory)][string]$Name,
        [ValidateSet("all", "function", "class")][string]$Type = "all",
        [string]$Path = ".",
        [string]$Include = "*.py"
    )

    $pattern = switch ($Type) {
        "function" { "^\s*(async\s+)?def\s+.*$Name" }
        "class"    { "^\s*class\s+.*$Name" }
        "all"      { "^\s*(async\s+)?(def|class)\s+.*$Name" }
    }

    Dev-Search-Text -Pattern $pattern -Path $Path -Include $Include -Context 0
}

# ─────────────────────────────────────────────────────────────
# dev search imports
# ─────────────────────────────────────────────────────────────
function Dev-Search-Imports {
    <#
    .SYNOPSIS
        Find where a module or symbol is imported.
    .EXAMPLE
        dev search imports --name "AegisMessage"
        dev search imports --name "redis"
    #>
    param(
        [Parameter(Mandatory)][string]$Name,
        [string]$Path = ".",
        [string]$Include = "*.py"
    )

    $pattern = "(from\s+\S+\s+import\s+.*$Name|import\s+.*$Name)"
    Dev-Search-Text -Pattern $pattern -Path $Path -Include $Include -Context 0
}

# ─────────────────────────────────────────────────────────────
# dev search todo
# ─────────────────────────────────────────────────────────────
function Dev-Search-Todo {
    <#
    .SYNOPSIS
        Surface TODO, FIXME, HACK, NOTE comments.
    .EXAMPLE
        dev search todo
        dev search todo --path .\agents\ --severity fixme
    #>
    param(
        [string]$Path = ".",
        [string]$Include = "*.py",
        [ValidateSet("all", "todo", "fixme", "hack", "note")][string]$Severity = "all"
    )

    $pattern = switch ($Severity) {
        "all"   { "#\s*(TODO|FIXME|HACK|NOTE)" }
        default { "#\s*$($Severity.ToUpper())" }
    }

    Dev-Search-Text -Pattern $pattern -Path $Path -Include $Include -Context 0
}

# ─────────────────────────────────────────────────────────────
# dev search replace (preview + confirm)
# ─────────────────────────────────────────────────────────────
function Dev-Search-Replace {
    <#
    .SYNOPSIS
        Find and replace across files. Shows preview, asks to confirm.
    .EXAMPLE
        dev search replace --find "original.message_id" --replace "original.correlation_id"
        dev search replace --find "redis_conn" --replace "redis_client" --include "*.py"
    #>
    param(
        [Parameter(Mandatory)][string]$Find,
        [Parameter(Mandatory)][string]$Replace,
        [string]$Path = ".",
        [string]$Include = "*.py",
        [switch]$NoIgnoreCase,
        [switch]$Force
    )

    $files = _get_files -Path $Path -Include $Include
    $affected = @()

    foreach ($f in $files) {
        $content = Get-Content $f.FullName -Raw
        if ($content -match [regex]::Escape($Find)) {
            $affected += $f
        }
    }

    if (-not $affected) {
        Write-Host "  No matches for '$Find'." -ForegroundColor DarkGray
        return
    }

    Write-Host "`n  Found in $($affected.Count) files:" -ForegroundColor Yellow
    foreach ($f in $affected) {
        $rel = [System.IO.Path]::GetRelativePath((Get-Location), $f.FullName)
        Write-Host "    $rel" -ForegroundColor Cyan
    }
    Write-Host "`n  Replace: " -NoNewline; Write-Host "'$Find'" -ForegroundColor Red
    Write-Host "  With:    " -NoNewline; Write-Host "'$Replace'" -ForegroundColor Green

    if (-not $Force) {
        $confirm = Read-Host "`n  Proceed? (y/N)"
        if ($confirm -ne 'y') { Write-Host "  Aborted." -ForegroundColor DarkGray; return }
    }

    foreach ($f in $affected) {
        $content = Get-Content $f.FullName -Raw
        if ($NoIgnoreCase) {
            $content = $content -creplace [regex]::Escape($Find), $Replace
        } else {
            $content = $content -replace [regex]::Escape($Find), $Replace
        }
        [System.IO.File]::WriteAllText($f.FullName, $content)
    }
    Write-Host "  ✅ Replaced in $($affected.Count) files." -ForegroundColor Green
}

# ─────────────────────────────────────────────────────────────
# dev search recent
# ─────────────────────────────────────────────────────────────
function Dev-Search-Recent {
    <#
    .SYNOPSIS
        Files modified within the last N minutes.
    .EXAMPLE
        dev search recent --minutes 30
        dev search recent --minutes 60 --include "*.py"
    #>
    param(
        [int]$Minutes = 30,
        [string]$Path = ".",
        [string]$Include = "*.*",
        [string[]]$ExcludeDirs = @()
    )

    $cutoff = (Get-Date).AddMinutes(-$Minutes)
    $filter = _build_exclude_filter -ExtraDirs $ExcludeDirs
    $results = Get-ChildItem -Path $Path -Recurse -Include $Include -File |
        Where-Object $filter |
        Where-Object { $_.LastWriteTime -gt $cutoff } |
        Sort-Object LastWriteTime -Descending

    if (-not $results) {
        Write-Host "  No files modified in the last $Minutes minutes." -ForegroundColor DarkGray
        return
    }

    foreach ($f in $results) {
        $rel = [System.IO.Path]::GetRelativePath((Get-Location), $f.FullName)
        $age = [math]::Round(((Get-Date) - $f.LastWriteTime).TotalMinutes)
        Write-Host "  ${age}m ago  " -NoNewline -ForegroundColor DarkGray
        Write-Host $rel -ForegroundColor Cyan
    }
    Write-Host "`n  $($results.Count) files." -ForegroundColor Green
}

# ==================================================================
# HELP
# ==================================================================

function Show-Help {
  @"

  Aegis Dev Runner (.\dev <task> [options])
  =========================================
  [Using this script file: Place this file in the project's root directory and name it `dev.cmd`]

  SETUP & DEPENDENCIES
  --------------------
    bootstrap [-Force]     Full first-run: install uv, create venv, lock, sync, run aegis_boot.py
    lock [-Upgrade]        Resolve deps -> uv.lock
    sync [-All|-Dev|-Web|-Mcp] [-Frozen]
                           Install deps from lock

    Examples:
      .\dev bootstrap                     # first-time setup (does everything) - (deactivate venv first!)
      .\dev bootstrap -Force              # re-run full setup even if already done - (deactivate venv first!)
      .\dev lock                          # resolve deps, write uv.lock
      .\dev lock -Upgrade                 # upgrade all deps to latest compatible
      .\dev sync                          # install base deps only
      .\dev sync -Dev                     # install base + dev extras (pytest, ruff, mypy)
      .\dev sync -Web                     # install base + web extras (uvicorn, fastapi)
      .\dev sync -Mcp                     # install base + mcp extras
      .\dev sync -All                     # install everything (dev + web + mcp)
      .\dev sync -All -Frozen             # install exact locked versions (CI mode)

  CODE QUALITY
  ------------
    test [args]            Run pytest
    lint [args]            Run ruff check
    format [args]          Run ruff format (auto-fix)
    typecheck [args]       Run mypy
    check                  lint + typecheck + test (full local CI)

    Examples:
      .\dev test                          # run all tests
      .\dev test -k "test_redis"          # run tests matching pattern
      .\dev test -x                       # stop on first failure
      .\dev test --tb=short               # shorter tracebacks
      .\dev lint                          # check all files for lint errors
      .\dev lint --fix                    # auto-fix lint errors
      .\dev format                        # format all files in place
      .\dev format --check                # check formatting without changing files
      .\dev typecheck                     # run mypy on entire project
      .\dev check                         # run lint + typecheck + tests (full pass)

  RUNNING AEGIS
  -------------
    run [boot|restart|status] [args]
                           Manage the Aegis system lifecycle
    runmcp [args]          Start MCP server
    web [start|stop|status] [args]
                           Manage Mission Control web server

    Examples:
      .\dev run boot                      # start Aegis (first boot or cold start)
      .\dev run boot --skip-redis         # boot without managing Redis (external Redis)
      .\dev run boot --headless           # boot without web server (CLI only)
      .\dev run boot --verbose            # boot with detailed output
      .\dev run restart                   # graceful restart (keeps Redis)
      .\dev run restart --force           # force kill then restart
      .\dev run restart --full            # full restart including Redis
      .\dev run status                    # show current system status
      .\dev runmcp                        # start the MCP server
      .\dev web start                     # launch Mission Control (foreground)
      .\dev web start --reload            # launch with hot-reload (dev mode)
      .\dev web stop                      # stop the web server
      .\dev web status                    # check if running + hit /health

  ENVIRONMENT (.\dev env <flag>)
  -----------------------------
    --status               Show current env info (default)
    --venv_create          Create .venv via uv
    --venv_activate        Print activation command - must run manually
    --venv_deactivate      Print deactivation command - must run manually
    --venv_destroy         Remove .venv - (deactivate venv first!)
    --venv_sync            Sync deps from uv.lock into .venv
    --install_pkg <name>   Add a package via uv (updates pyproject.toml + uv.lock)
    --verify               Check that key imports work
    --clean_boot           Destroy + rebuild + sync + verify (one shot) - (deactivate venv first!)

    Examples:
      .\dev env                           # show environment status (default)
      .\dev env --status                  # same as above (explicit)
      .\dev env --venv_create             # create a new .venv with Python $Python
      .\dev env --venv_activate           # prints the activation command to run
      .\dev env --venv_deactivate         # prints the deactivation command to run
      .\dev env --venv_destroy            # delete .venv entirely) - (deactivate venv first!)
      .\dev env --venv_sync               # install all deps from uv.lock into .venv
      .\dev env --install_pkg redis       # add redis to project
      .\dev env --install_pkg 'redis[hiredis]'   # add with extras
      .\dev env --install_pkg 'pydantic>=2.0'    # add with version constraint
      .\dev env --verify                  # check redis, rich, fastapi, pydantic imports
      .\dev env --clean_boot              # full rebuild (deactivate venv first!)

  UTILITIES
  ---------
    killport [port]        Kill process on port (default: $DefaultPort)
    ports                  Show all listening ports with process names
    redis [start|stop|status]
                           Manage Redis in WSL
    logs [lines]           Tail Aegis system log (default: 50 lines)
    clean                  Remove .venv, caches, __pycache__, bootstrap marker

    Examples:
      .\dev killport          # kill whatever is on port $DefaultPort
      .\dev killport 8080     # kill whatever is on port 8080
      .\dev ports             # list all listening ports + process names
      .\dev redis start       # start Redis daemon in WSL
      .\dev redis stop        # stop Redis in WSL
      .\dev redis status      # check if Redis is running (PONG test)
      .\dev logs              # tail last 50 lines (default)
      .\dev logs 200          # tail last 200 lines
      .\dev logs clear        # safely clear the log file (UTF-8, no NULs)
      .\dev clean             # nuke .venv, caches, bootstrap marker

  OPTIONS (global flags)
  ----------------------
    -Dev                   Include dev extras when syncing
    -Web                   Include web extras when syncing
    -Mcp                   Include mcp extras when syncing
    -All                   Include all extras (dev + web + mcp)
    -Frozen                Use exact locked versions (no resolution)
    -Upgrade               Upgrade all deps when locking
    -Force                 Force re-run (bypass bootstrap marker, force kill, etc.)
    -Python "3.xx"         Python version for venv creation (default: 3.12)

  COMMON WORKFLOWS
  ----------------
    # First time on a new machine:
      .\dev bootstrap

    # Daily startup:
      . .\.venv\Scripts\Activate.ps1
      .\dev redis start
      .\dev run boot --skip-redis

    # After pulling new code:
      .\dev sync -All
      .\dev check

    # Environment is broken (nuclear option):
      deactivate
      .\dev env --clean_boot
      . .\.venv\Scripts\Activate.ps1
      .\dev run boot --skip-redis

    # Add a new dependency:
      .\dev env --install_pkg some-package
      # (automatically updates pyproject.toml + uv.lock)

    # Debug a port conflict:
      .\dev ports
      .\dev killport 8420
      .\dev web start

  GREP SEARCH
  ----------------
    dev search <command>
    text     Grep files for a regex pattern
    files    Find files by name/glob
    def      Find function/class definitions
    imports  Find where a symbol is imported
    todo     Surface TODO/FIXME/HACK markers
    replace  Find-and-replace with preview
    recent   Recently modified files

    EXAMPLES:
	# Find text pattern in all files from cwd:
		.\dev search text --pattern "correlation_id=original\.message_id"

	# Find where Router class is defined:
		.\dev search def --name "Router" --type class

	# What imports AegisMessage?
		.\dev search imports --name "AegisMessage"

	# What did I touch in the last hour?
		.\dev search recent --minutes 60

	# Bulk rename a variable across the project:
		.\dev search replace --find "redis_conn" --replace "redis_client"

	# Find all the debt I've left behind:
		.\dev search todo --severity fixme

	# Where's the warden config file?
		.\dev search files --pattern "*warden*"
		
"@ | Write-Host
}

# ==================================================================
# MAIN TASK ROUTER
# ==================================================================

switch ($Task.ToLower()) {
  "help" { Show-Help; break }
  
  "search" { Dev-Search @Passthru; break }

  "bootstrap" {
    if (Test-Bootstrapped) {
      Write-Ok "Already bootstrapped. Use -Force to re-run."
      break
    }
    Write-Header "Aegis Bootstrap"
    Assert-UvInstalled
    Invoke-VenvCreate
    Invoke-VenvSync
    Write-Header "Running Aegis first-run setup"
    & uv run python .\scripts\aegis_boot.py @Passthru
    if ($LASTEXITCODE -eq 0) {
      Get-Date -Format "yyyy-MM-dd HH:mm:ss" | Out-File $BootstrapMarker -Encoding utf8
      Write-Ok "=== AEGIS BOOTSTRAP COMPLETE ==="
    } else {
      Write-Warn "aegis_boot.py exited with code $LASTEXITCODE. Check logs."
    }
    break
  }

  "lock" {
    Assert-UvInstalled
    $lockFlags = @(); if ($Upgrade) { $lockFlags += "--upgrade" }
    & uv lock @lockFlags | Out-Host
    break
  }

  "sync" {
    Assert-UvInstalled
    $extrasArgs = Get-ExtrasArgs
    $syncFlags = @(); if ($Frozen) { $syncFlags += "--frozen" }
    & uv sync @syncFlags @extrasArgs | Out-Host
    break
  }

  "test"      { Assert-UvInstalled; & uv run pytest @Passthru; break }
  "lint"      { Assert-UvInstalled; & uv run ruff check . @Passthru; break }
  "format"    { Assert-UvInstalled; & uv run ruff format . @Passthru; break }
  "typecheck" { Assert-UvInstalled; & uv run mypy . @Passthru; break }

  "check" {
    Assert-UvInstalled
    Write-Header "Lint";      & uv run ruff check .
    Write-Header "Typecheck"; & uv run mypy .
    Write-Header "Tests";     & uv run pytest @Passthru
    Write-Ok "All checks passed."
    break
  }

  "run" {
    Assert-UvInstalled
    $action = if ($Passthru) { $Passthru[0] } else { "status" }
    $RunArgs = @()
    if ($Passthru.Count -gt 1) { $RunArgs = $Passthru[1..($Passthru.Count - 1)] }
    switch ($action.ToLower()) {
      "boot"    { & uv run python .\scripts\aegis_boot.py @RunArgs }
      "restart" { & uv run python .\scripts\aegis_restart.py @RunArgs }
      "status"  { & uv run python .\scripts\aegis_status.py @RunArgs }
      default   { Write-Err "Unknown: '$action'. Use: .\dev run [boot|restart|status]" }
    }
    break
  }

  "runmcp" { Assert-UvInstalled; & uv run aegis-mcp @Passthru; break }

  "web" {
    Assert-UvInstalled
    $action = if ($Passthru) { $Passthru[0] } else { "status" }
    $WebArgs = @()
    if ($Passthru.Count -gt 1) { $WebArgs = $Passthru[1..($Passthru.Count - 1)] }

    switch ($action.ToLower()) {
      "start" {
        # Check if already running
        try {
          $conn = Get-NetTCPConnection -LocalPort $DefaultPort -ErrorAction Stop
          $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
          Write-Warn "Web server already running: $($proc.ProcessName) (PID $($proc.Id)) on port $DefaultPort"
          return
        } catch {
          # Port is free — good to go
        }

        Write-Header "Starting Mission Control (port $DefaultPort)"
        & uv run uvicorn aegis.web.app:app --host 127.0.0.1 --port $DefaultPort @WebArgs
      }
      "stop" {
        Write-Header "Stopping Mission Control"
        try {
          $conn = Get-NetTCPConnection -LocalPort $DefaultPort -ErrorAction Stop
          $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
          Write-Host "Killing $($proc.ProcessName) (PID $($proc.Id)) on port $DefaultPort" -ForegroundColor Yellow
          Stop-Process -Id $proc.Id -Force
          Start-Sleep -Milliseconds 500
          Write-Ok "Web server stopped."
        } catch {
          Write-Ok "Web server is not running (port $DefaultPort is free)."
        }
      }
      "status" {
        try {
          $conn = Get-NetTCPConnection -LocalPort $DefaultPort -ErrorAction Stop
          $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
          Write-Ok "Web server: RUNNING - $($proc.ProcessName) (PID $($proc.Id)) on port $DefaultPort"

          # Try to hit the health endpoint
          try {
            $response = Invoke-RestMethod -Uri "http://127.0.0.1:$DefaultPort/health" -TimeoutSec 2 -ErrorAction Stop
            Write-Host "  Health: $($response.status) | Ready: $($response.ready)" -ForegroundColor DarkGray
          } catch {
            Write-Host "  Health: endpoint not responding" -ForegroundColor Yellow
          }
        } catch {
          Write-Err "Web server: NOT RUNNING (port $DefaultPort is free)"
        }
      }
      default {
        Write-Err "Unknown web action: '$action'"
        Write-Host "Usage: .\dev web [start|stop|status] [args]"
      }
    }
    break
  }

  "killport" {
    $port = if ($Passthru) { $Passthru[0] } else { $DefaultPort }
    try {
      $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction Stop
      $proc = Get-Process -Id $conn.OwningProcess
      Write-Host "Killing $($proc.ProcessName) (PID $($proc.Id)) on port $port" -ForegroundColor Yellow
      Stop-Process -Id $proc.Id -Force
      Write-Ok "Port $port freed."
    } catch { Write-Ok "Port $port is already free." }
    break
  }

  "ports" {
    Write-Header "Listening Ports"
    Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
      Sort-Object LocalPort |
      ForEach-Object {
        $proc = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
        [PSCustomObject]@{ Port = $_.LocalPort; PID = $_.OwningProcess; Process = $proc.ProcessName }
      } | Format-Table -AutoSize
    break
  }

  "redis" {
    $action = if ($Passthru) { $Passthru[0] } else { "status" }
    switch ($action.ToLower()) {
      "start"  { wsl bash -lc "redis-server --daemonize yes"; Write-Ok "Redis started (WSL)" }
      "stop"   { wsl bash -lc "redis-cli shutdown"; Write-Warn "Redis stopped" }
      "status" {
        $result = wsl bash -lc "redis-cli ping 2>/dev/null"
        if ($result -eq "PONG") { Write-Ok "Redis: RUNNING (PONG)" } else { Write-Err "Redis: NOT RUNNING" }
      }
      default { Write-Host "Usage: .\dev redis [start|stop|status]" }
    }
    break
  }

  "logs" {
    $action = if ($Passthru) { $Passthru[0] } else { "tail" }
    $logFile = "logs\aegis_system.log"

    # Find the log file
    if (-not (Test-Path $logFile)) {
      $alt = Get-ChildItem -Recurse -Filter "aegis_system.log" -ErrorAction SilentlyContinue | Select-Object -First 1
      if ($alt) { $logFile = $alt.FullName }
    }

    switch ($action.ToLower()) {
      "clear" {
        if (Test-Path $logFile) {
          [System.IO.File]::WriteAllText((Resolve-Path $logFile).Path, "")
          Write-Ok "Log file cleared (UTF-8): $logFile"
        } else {
          Write-Warn "Log file not found."
        }
      }
      "tail" {
        $lines = if ($Passthru.Count -gt 0 -and $Passthru[0] -match '^\d+$') { $Passthru[0] } else { "50" }
        if (Test-Path $logFile) {
          Get-Content $logFile -Tail ([int]$lines)
        } else {
          Write-Warn "Log file not found."
        }
      }
      default {
        # Treat as line count (backwards compat: .\dev logs 100)
        $lines = $action
        if (Test-Path $logFile) {
          Get-Content $logFile -Tail ([int]$lines)
        } else {
          Write-Warn "Log file not found."
        }
      }
    }
    break
  }

  # == ENV (sub-command router) ========================================
  "env" {
    $envAction = "status"
    $pkgName = $null
    for ($i = 0; $i -lt $Passthru.Count; $i++) {
      switch ($Passthru[$i]) {
        "--status"           { $envAction = "status" }
        "--venv_create"      { $envAction = "venv_create" }
        "--venv_activate"    { $envAction = "venv_activate" }
        "--venv_deactivate"  { $envAction = "venv_deactivate" }
        "--venv_destroy"     { $envAction = "venv_destroy" }
        "--venv_sync"        { $envAction = "venv_sync" }
        "--install_pkg"      { $envAction = "install_pkg"; $i++; $pkgName = $Passthru[$i] }
        "--verify"           { $envAction = "verify" }
        "--clean_boot"       { $envAction = "clean_boot" }
        default {
          Write-Err "Unknown env arg: $($Passthru[$i])"
          Write-Host "Run '.\dev help' for usage." -ForegroundColor Yellow
          return
        }
      }
    }

    # Route to function
    switch ($envAction) {
      "status"           { Invoke-EnvStatus }
      "venv_create"      { Invoke-VenvCreate }
      "venv_activate"    { Invoke-VenvActivate }
      "venv_deactivate"  { Invoke-VenvDeactivate }
      "venv_destroy"     { Invoke-VenvDestroy }
      "venv_sync"        { Invoke-VenvSync }
      "install_pkg"      { Invoke-InstallPkg $pkgName }
      "verify"           { Invoke-EnvVerify }
      "clean_boot"       { Invoke-CleanBoot }
    }
    break
  }

  "clean" {
    Write-Header "Cleaning"
    Remove-Item -Force -Recurse -ErrorAction SilentlyContinue .venv, .pytest_cache, .mypy_cache, .ruff_cache
    Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -Force -ErrorAction SilentlyContinue $BootstrapMarker
    Write-Ok "Cleaned."
    break
  }

  default {
    Write-Err "Unknown task: '$Task'"
    Write-Host "Run '.\dev help' for available commands."
    exit 1
  }
}