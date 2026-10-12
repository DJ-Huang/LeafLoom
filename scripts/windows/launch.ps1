param([ValidateSet('open','stop','install')][string]$Action='open')
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
Set-StrictMode -Version Latest
$VaultRagRoot=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
. (Join-Path $PSScriptRoot 'common.ps1')
$VaultRagState=Get-VaultRagState
$env:VAULT_RAG_HOME=$VaultRagState
try {
    if ($Action -eq 'install') { exit (Start-VaultRagSetup $VaultRagRoot) }
    $Bootstrap=Join-Path $VaultRagState 'bootstrap-python.json'
    $Python=$null
    if (Test-Path -LiteralPath $Bootstrap) {
        try { $Python=(Get-Content -LiteralPath $Bootstrap -Raw -Encoding UTF8 | ConvertFrom-Json).python } catch { }
    }
    # A legacy install supplies an interpreter while the bootstrap marker is upgraded.
    if (-not $Python -or -not (Test-Path -LiteralPath $Python)) { $Python=Join-Path $VaultRagRoot '.venv\Scripts\python.exe' }
    if (-not (Test-Path -LiteralPath $Python)) {
        if ($Action -eq 'stop') { exit 0 }
        exit (Start-VaultRagSetup $VaultRagRoot)
    }
    $Base=@('-X','utf8',(Join-Path $VaultRagRoot 'scripts\installer.py'),'--repository',$VaultRagRoot,'--state',$VaultRagState)
    if ($Action -eq 'open') {
        try { $null=Invoke-BootstrapTool $Python ($Base + @('--action','check')) -Capture }
        catch { exit (Start-VaultRagSetup $VaultRagRoot) }
    }
    $null=Invoke-BootstrapTool $Python ($Base + @('--action',$Action)) -Capture
    exit 0
} catch {
    Show-VaultRagError ($_.Exception.Message + "`nLogs: " + (Join-Path $VaultRagState 'logs'))
    exit 1
}