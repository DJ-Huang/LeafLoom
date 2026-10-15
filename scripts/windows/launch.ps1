param([ValidateSet('open','stop','install')][string]$Action='open')
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
Set-StrictMode -Version Latest
$VaultRagRoot=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
. (Join-Path $PSScriptRoot 'common.ps1')
$VaultRagState=Get-VaultRagState
$env:VAULT_RAG_HOME=$VaultRagState
$LaunchMutex=$null
$OwnsLaunch=$false
try {
    $DesktopMarker=Join-Path $VaultRagState 'desktop-install.json'
    if (Test-Path -LiteralPath $DesktopMarker) {
        try { $Desktop=Get-Content -LiteralPath $DesktopMarker -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $Desktop=$null }
        if ($null -ne $Desktop -and $Desktop.schema -eq 1 -and (Test-Path -LiteralPath $Desktop.executable -PathType Leaf)) {
            if ($Action -eq 'stop') {
                $ControlDir=Join-Path $VaultRagState 'desktop-control'
                [IO.Directory]::CreateDirectory($ControlDir) | Out-Null
                [IO.File]::WriteAllText((Join-Path $ControlDir 'quit'), '1')
            } else {
                Start-Process -FilePath $Desktop.executable -WindowStyle Hidden
            }
            exit 0
        }
    }
    if ($Action -ne 'stop') {
        $LaunchMutex=[Threading.Mutex]::new($false, ('Local\VaultRagLaunch-' + (Get-TextHash $VaultRagState.ToLowerInvariant())))
        # Repeated clicks queue invisibly; only one controller can open setup.
        try { $OwnsLaunch=$LaunchMutex.WaitOne() } catch [Threading.AbandonedMutexException] { $OwnsLaunch=$true }
    }
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
    # One check inside the locked operation; exit 3 requests a visible installer.
    $null=Invoke-BootstrapTool $Python ($Base + @('--action',$Action,'--no-install')) -Capture -AllowSetup
    if ($LASTEXITCODE -eq 3) { exit (Start-VaultRagSetup $VaultRagRoot) }
    exit 0
} catch {
    Show-VaultRagError ($_.Exception.Message + "`nLogs: " + (Join-Path $VaultRagState 'logs'))
    exit 1
} finally {
    if ($OwnsLaunch) { $LaunchMutex.ReleaseMutex() }
    if ($null -ne $LaunchMutex) { $LaunchMutex.Dispose() }
}
