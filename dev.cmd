@echo off
REM Alias for ".\dev" that points to the actual file where all the commands live (e.g.: .\utils\dev_cmd.ps1)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0utils\dev_cmd.ps1" %*