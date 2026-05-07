# env_setup.ps1 — Aegis OOBE
# Rebuilds .venv with Python 3.12 and installs editable + dev deps + sanity checks.

$ErrorActionPreference = "Stop"

$PyVer   = "3.12"
$VenvDir = ".venv"

Write-Host ""
Write-Host "[1/8] Move to repo root (script directory)..."
Set-Location -Path $PSScriptRoot

Write-Host ""
Write-Host "[2/8] Ensure Python $PyVer is available via py launcher..."
py -$PyVer -V | Out-Null

Write-Host ""
Write-Host "[3/8] Remove old venv if it exists: $VenvDir"
if (Test-Path $VenvDir) {
    Remove-Item -Recurse -Force $VenvDir
}

Write-Host ""
Write-Host "[4/8] Create new venv: $VenvDir (Python $PyVer)"
py -$PyVer -m venv $VenvDir

$Py  = Join-Path $VenvDir "Scripts\python.exe"
$Act = Join-Path $VenvDir "Scripts\Activate.ps1"

Write-Host ""
Write-Host "[5/8] Upgrade pip/setuptools/wheel..."
& $Py -m pip install -U pip setuptools wheel

Write-Host ""
Write-Host "[6/8] Install project editable + dev extras..."
& $Py -m pip install -e ".[dev]"

Write-Host ""
Write-Host "[7/8] Sanity checks..."
& $Py -V
& $Py -m pip -V
& $Py -c "import pydantic; import pytest; import pytest_asyncio; print('pydantic', pydantic.__version__); print('pytest', pytest.__version__); print('pytest_asyncio', pytest_asyncio.__version__)"
& $Py -c "import aegis, aegis.config; print('aegis:', aegis.__file__); print('aegis.config:', aegis.config.__file__)"

Write-Host ""
Write-Host "[8/8] Done."
Write-Host "Activate: $Act"
Write-Host "Run tests: & $Py -m pytest"
Write-Host ""

# Optional: auto-activate in the CURRENT PowerShell session.
. $Act