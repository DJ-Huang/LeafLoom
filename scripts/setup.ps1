# vault-rag Windows setup: venv, install, .env, Ollama model, MCP fragment JSON.
# Run from repo:  powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1

$ErrorActionPreference = "Stop"
$VaultRagRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $VaultRagRoot

Write-Host "vault-rag root: $VaultRagRoot"

$VenvPython = Join-Path $VaultRagRoot ".venv\Scripts\python.exe"
$VenvPip = Join-Path $VaultRagRoot ".venv\Scripts\pip.exe"

if (-not (Test-Path $VenvPython)) {
  Write-Host "Creating virtual environment..."
  $created = $false
  if (Get-Command py -ErrorAction SilentlyContinue) {
    try {
      & py -3.12 -m venv .venv 2>$null
      if (Test-Path $VenvPython) { $created = $true }
    } catch { }
  }
  if (-not $created) {
    & python -m venv .venv
  }
}

if (-not (Test-Path $VenvPython)) {
  throw "Failed to create .venv; ensure Python 3.11+ is on PATH."
}

Write-Host "Upgrading pip and installing vault-rag (editable)..."
& $VenvPython -m pip install -U pip
& $VenvPython -m pip install -e .

$EnvExample = Join-Path $VaultRagRoot ".env.example"
$EnvFile = Join-Path $VaultRagRoot ".env"
if (-not (Test-Path $EnvFile)) {
  if (Test-Path $EnvExample) {
    Copy-Item $EnvExample $EnvFile
    Write-Host "Created .env from .env.example"
  }
}

Write-Host "Pulling embedding model (ignore errors if Ollama is offline)..."
try {
  & ollama pull bge-m3 2>&1 | Write-Host
} catch {
  Write-Warning "ollama pull bge-m3 failed: $_"
}

Write-Host "Writing Cursor MCP fragment..."
& $VenvPython (Join-Path $VaultRagRoot "scripts\write_mcp_fragment.py")

Write-Host ""
Write-Host "Done. Next:"
Write-Host "  1) Start Ollama, then:  .\.venv\Scripts\Activate.ps1  ;  vault-rag reindex"
Write-Host "  2) Merge vault-rag\_generated\cursor-mcp-vault-rag.fragment.json into %USERPROFILE%\.cursor\mcp.json"
Write-Host "  3) Restart Cursor fully."
