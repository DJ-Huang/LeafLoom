# Windows 10/11 x64 bootstrap. No global PATH, registry or execution-policy changes.
param([switch]$NoOpen)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)
Set-StrictMode -Version Latest
$VaultRagRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "windows\common.ps1")
$VaultRagState = Get-VaultRagState
$env:VAULT_RAG_HOME = $VaultRagState
$RuntimeRoot = Join-Path $VaultRagState "runtimes"
$LogsRoot = Join-Path $VaultRagState "logs"
$InstallMarker = Join-Path $VaultRagState "windows-install.json"
$InstallMutex = $null
$OwnsMutex = $false
$TranscriptStarted = $false
try {
    if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') {
        throw "This release supports Windows 10/11 x64 only."
    }
    New-Item -ItemType Directory -Force -Path $VaultRagState | Out-Null
    $Sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    & icacls.exe $VaultRagState /inheritance:r /grant:r "*${Sid}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Cannot protect the private state directory." }
    New-Item -ItemType Directory -Force -Path $LogsRoot,$RuntimeRoot | Out-Null
    $InstallMutex = [Threading.Mutex]::new($false, ('Local\VaultRagInstall-' + (Get-TextHash $VaultRagState.ToLowerInvariant())))
    try { $OwnsMutex = $InstallMutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $OwnsMutex = $true }
    if (-not $OwnsMutex) { throw "Another installation is already running. Please wait for it to finish." }
    Start-Transcript -Path (Join-Path $LogsRoot "setup.log") -Append | Out-Null
    $TranscriptStarted = $true
    Remove-Item -LiteralPath $InstallMarker -Force -ErrorAction SilentlyContinue
    Set-Location -LiteralPath $VaultRagRoot
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $env:PYTHONUTF8 = '1'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $RuntimeRoot "python"
    $env:UV_PYTHON_BIN_DIR = Join-Path $RuntimeRoot "python-bin"
    $env:UV_CACHE_DIR = Join-Path $RuntimeRoot "uv-cache"
    $Manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot "windows\runtimes.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    Write-Host "Preparing dependency installer..."
    $UvDir = Join-Path $RuntimeRoot ('uv-' + $Manifest.uv.version)
    $Uv = Join-Path $UvDir "uv.exe"
    if (-not (Test-Path -LiteralPath $Uv)) {
        $Archive = Get-VerifiedArchive $Manifest.uv $RuntimeRoot
        New-Item -ItemType Directory -Force -Path $UvDir | Out-Null
        Expand-Archive -LiteralPath $Archive -DestinationPath $UvDir -Force
    }
    if (-not (Test-Path -LiteralPath $Uv)) { throw "The downloaded uv archive has no uv.exe." }
    $PythonChoice = Find-Python312
    if (-not $PythonChoice) {
        Write-Host "Downloading private Python runtime..."
        Invoke-Tool $Uv @('python','install','--no-bin','--no-registry',$Manifest.python)
        $PythonChoice = $Manifest.python
    }
    $VenvPython = Join-Path $VaultRagRoot ".venv\Scripts\python.exe"
    if ((Test-Path -LiteralPath (Join-Path $VaultRagRoot '.venv')) -and -not (Test-Path -LiteralPath $VenvPython)) {
        throw "The existing .venv is not a Windows environment. Rename it before installing; it was not deleted."
    }
    if (Test-Path -LiteralPath $VenvPython) {
        $Version = & $VenvPython -c "import sys; print('%s.%s' % sys.version_info[:2] if sys.maxsize > 2**32 else 'unsupported')"
        if ($LASTEXITCODE -ne 0 -or $Version -ne '3.12') { throw "The existing .venv must use Python 3.12. Rename it before installing." }
    }
    Write-Host "Installing locked Python dependencies (Windows CPU PyTorch)..."
    Invoke-Tool $Uv @('sync','--locked','--no-dev','--python',$PythonChoice)
    Write-Host 'Checking Windows native runtime DLLs...'
    Invoke-Tool $VenvPython @('-X','utf8',(Join-Path $PSScriptRoot 'windows\check_runtime.py'))
    $Node = Find-CompatibleNode
    if (-not $Node) {
        Write-Host "Downloading private Node runtime (build only)..."
        $Archive = Get-VerifiedArchive $Manifest.node $RuntimeRoot
        Expand-Archive -LiteralPath $Archive -DestinationPath $RuntimeRoot -Force
        $Node = Join-Path $RuntimeRoot ('node-' + $Manifest.node.version + '-win-x64\node.exe')
    }
    if (-not (Test-Path -LiteralPath $Node)) { throw "Node runtime is missing." }
    $Npm = Join-Path (Split-Path $Node -Parent) 'npm.cmd'
    if (-not (Test-Path -LiteralPath $Npm)) { throw "The selected Node installation has no npm.cmd." }
    # Child build processes need Node; this modifies this process only.
    $env:PATH = (Split-Path $Node -Parent) + ';' + $env:PATH
    Write-Host "Building the local webpage..."
    Invoke-Tool $Npm @('ci','--prefix','web')
    Invoke-Tool $Npm @('run','build','--prefix','web')
    Write-Host "Preparing BGE-M3. The first download can take several minutes..."
    Invoke-Tool $VenvPython @('-X','utf8','-m','vault_rag.cli','model-prepare')
    Invoke-Tool $VenvPython @('-X','utf8',(Join-Path $PSScriptRoot 'write_mcp_fragment.py'))
    Write-Host "Registering current-user service and tray login tasks..."
    Invoke-Tool $VenvPython @('-X','utf8','-m','vault_rag.cli','service','install')
    $Marker = @{repository=$VaultRagRoot; python=$VenvPython; node=$Node; lock_hash=(Get-FileHash -LiteralPath (Join-Path $VaultRagRoot 'uv.lock') -Algorithm SHA256).Hash; installed_at=[DateTime]::UtcNow.ToString('o')}
    $TemporaryMarker = $InstallMarker + '.tmp'
    [IO.File]::WriteAllText($TemporaryMarker, ($Marker | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $TemporaryMarker -Destination $InstallMarker -Force
    Write-Host "Installation complete. Logs: $LogsRoot"
    if (-not $NoOpen) { Invoke-Tool $VenvPython @('-X','utf8','-m','vault_rag.windows_entry','open') }
} catch {
    Write-Host ("Installation failed: " + $_.Exception.Message) -ForegroundColor Red
    Show-VaultRagError ($_.Exception.Message + "`nLogs: " + $LogsRoot + "`nRun the installer again to retry.")
    exit 1
} finally {
    if ($TranscriptStarted) { Stop-Transcript | Out-Null }
    if ($OwnsMutex) { $InstallMutex.ReleaseMutex() }
    if ($null -ne $InstallMutex) { $InstallMutex.Dispose() }
}
