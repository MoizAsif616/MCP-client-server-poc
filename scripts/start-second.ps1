$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:PORT = '8001'
$env:PUBLIC_URL = 'http://127.0.0.1:8001'
$env:SERVER_NAME = 'Second Learning MCP'
$env:LOG_DIR = Join-Path $projectRoot 'logs\second-backend'
& .\.venv\Scripts\python.exe -m backend
