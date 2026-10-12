param([ValidateSet('open','stop','install')][string]$Action='open')
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$OutputEncoding=[Text.UTF8Encoding]::new($false)
Set-StrictMode -Version Latest
$VaultRagRoot=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
. (Join-Path $PSScriptRoot 'common.ps1')
$VaultRagState=Get-VaultRagState
$env:VAULT_RAG_HOME=$VaultRagState
$MarkerFile=Join-Path $VaultRagState 'windows-install.json'
try {
    if ($Action -eq 'install') {
        exit (Start-VaultRagSetup $VaultRagRoot)
    }
    $Ready=$false
    if (Test-Path -LiteralPath $MarkerFile) {
        try {
            $Marker=Get-Content -LiteralPath $MarkerFile -Raw -Encoding UTF8 | ConvertFrom-Json
            $Ready=$Marker.repository -eq $VaultRagRoot -and (Test-Path -LiteralPath $Marker.python)
            if ($Ready) { $Ready=$Marker.lock_hash -eq (Get-FileHash -LiteralPath (Join-Path $VaultRagRoot 'uv.lock') -Algorithm SHA256).Hash }
        } catch { $Ready=$false }
    }
    if (-not $Ready) {
        if ($Action -eq 'stop') {
            # A failed upgrade can leave a working service without a success marker.
            $Python=Join-Path $VaultRagRoot '.venv\Scripts\python.exe'
            if (-not (Test-Path -LiteralPath $Python)) { throw 'No installed Windows service environment was found.' }
        } else {
            exit (Start-VaultRagSetup $VaultRagRoot)
        }
    } else { $Python=$Marker.python }
    # Hide both the launcher and its server/tray children; preserve command arguments.
    $Pythonw=Join-Path (Split-Path $Python -Parent) 'pythonw.exe'
    $Info=[Diagnostics.ProcessStartInfo]::new()
    $Info.FileName=$Python
    if (Test-Path -LiteralPath $Pythonw) { $Info.FileName=$Pythonw }
    $Info.Arguments='-X utf8 -m vault_rag.windows_entry ' + $Action
    $Info.WorkingDirectory=$VaultRagRoot
    $Info.UseShellExecute=$false; $Info.CreateNoWindow=$true
    $Process=[Diagnostics.Process]::Start($Info)
    $Process.WaitForExit()
    if ($Process.ExitCode -ne 0 -and $Process.ExitCode -ne 2) {
        Show-VaultRagError ('The launcher could not run. Run the installer again to repair the environment.' + "`nLogs: " + (Join-Path $VaultRagState 'logs'))
    }
    exit $Process.ExitCode
} catch {
    Show-VaultRagError ($_.Exception.Message + "`nLogs: " + (Join-Path $VaultRagState 'logs'))
    exit 1
}
