# Windows bootstrap: no preinstalled Python/Node and no global machine changes.
param([switch]$NoOpen)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)
Set-StrictMode -Version Latest
$VaultRagRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'windows\common.ps1')
$VaultRagState = Get-VaultRagState
$env:VAULT_RAG_HOME = $VaultRagState
$BootstrapMutex = $null
$OwnsMutex = $false
$TranscriptStarted = $false
try {
    if (-not [Environment]::Is64BitOperatingSystem -or [Environment]::OSVersion.Version.Major -lt 10 -or
        $env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') {
        throw 'Supported systems: Windows 10/11 x64.'
    }
    New-Item -ItemType Directory -Force -Path $VaultRagState | Out-Null
    $Sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    & icacls.exe $VaultRagState /inheritance:r /grant:r "*${Sid}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot protect the private state directory.' }
    $Logs = Join-Path $VaultRagState 'logs'
    $RuntimeRoot = Join-Path $VaultRagState 'runtimes'
    New-Item -ItemType Directory -Force -Path $Logs,$RuntimeRoot | Out-Null
    $BootstrapMutex = [Threading.Mutex]::new($false, ('Local\VaultRagBootstrap-' + (Get-TextHash $VaultRagState.ToLowerInvariant())))
    try { $OwnsMutex = $BootstrapMutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $OwnsMutex = $true }
    if (-not $OwnsMutex) { throw 'Another installation is running. Wait for it to finish.' }
    Start-Transcript -Path (Join-Path $Logs 'bootstrap.log') -Append | Out-Null
    $TranscriptStarted = $true
    Set-Location -LiteralPath $VaultRagRoot
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $env:PYTHONUTF8 = '1'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $RuntimeRoot 'python'
    $env:UV_PYTHON_BIN_DIR = Join-Path $RuntimeRoot 'python-bin'
    $env:UV_CACHE_DIR = Join-Path $RuntimeRoot 'uv-cache'
    $env:UV_PYTHON_CACHE_DIR = Join-Path $RuntimeRoot 'python-archives'
    $Manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'runtimes.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $Spec = $Manifest.platforms.'windows-x64'.uv
    Write-Host '[1/2] Preparing verified dependency installer...'
    $UvDir = Join-Path $RuntimeRoot ('uv-' + $Manifest.uv_version)
    $Uv = Join-Path $UvDir 'uv.exe'
    $ValidUv = $false
    if (Test-Path -LiteralPath (Join-Path $UvDir '.verified')) {
        try {
            $ValidUv = (Get-Content -LiteralPath (Join-Path $UvDir '.verified') -Raw).Trim() -eq $Spec.sha256 -and
                (Invoke-BootstrapTool $Uv @('--version') -Capture).StartsWith('uv ' + $Manifest.uv_version + ' ')
        } catch { }
    }
    if (-not $ValidUv) {
        $Archive = Get-VerifiedArchive $Spec $RuntimeRoot
        # Preserve a damaged/unverified runtime; extract only into a fresh directory.
        if (Test-Path -LiteralPath $UvDir) {
            Rename-Item -LiteralPath $UvDir -NewName ((Split-Path $UvDir -Leaf) + '-old-' + [Guid]::NewGuid().ToString('N'))
        }
        New-Item -ItemType Directory -Path $UvDir | Out-Null
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [IO.Compression.ZipFile]::ExtractToDirectory($Archive, $UvDir)
        if (-not (Invoke-BootstrapTool $Uv @('--version') -Capture).StartsWith('uv ' + $Manifest.uv_version + ' ')) { throw 'Unexpected uv version.' }
        [IO.File]::WriteAllText((Join-Path $UvDir '.verified'), $Spec.sha256)
    }
    Write-Host '[2/2] Preparing private Python (existing downloads are reused)...'
    $PythonSpec = $Manifest.platforms.'windows-x64'.python
    $PythonDownloads = Join-Path $RuntimeRoot 'python-downloads.json'
    $DownloadMetadata = @{}; $DownloadMetadata[$PythonSpec.key] = $PythonSpec
    [IO.File]::WriteAllText($PythonDownloads, ($DownloadMetadata | ConvertTo-Json -Depth 6), [Text.UTF8Encoding]::new($false))
    Invoke-BootstrapTool $Uv @('python','install','--no-bin','--no-registry','--python-downloads-json-url',$PythonDownloads,$Manifest.python) -Retry
    $Python = (Invoke-BootstrapTool $Uv @('python','find','--managed-python','--no-project','--no-python-downloads',$Manifest.python) -Capture).Trim()
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Private Python was not found after preparation.' }
    $BootstrapMarker = Join-Path $VaultRagState 'bootstrap-python.json'
    $TemporaryMarker = $BootstrapMarker + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
    [IO.File]::WriteAllText($TemporaryMarker, (@{python=$Python; version=$Manifest.python} | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $TemporaryMarker -Destination $BootstrapMarker -Force
    $Arguments = @('-X','utf8',(Join-Path $PSScriptRoot 'installer.py'),'--repository',$VaultRagRoot,'--state',$VaultRagState,'--action','install')
    if ($NoOpen) { $Arguments += '--no-open' }
    # The shared installer streams and records both stdout/stderr itself.
    $ErrorActionPreference = 'Continue'
    & $Python @Arguments
    $Result = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    exit $Result
} catch {
    $Message = "Bootstrap failed: $($_.Exception.Message)`nLogs: $(Join-Path $VaultRagState 'logs')`nRun the same installer again to retry."
    Write-Host $Message -ForegroundColor Red
    if (-not $NoOpen) { Show-VaultRagError $Message }
    exit 1
} finally {
    if ($TranscriptStarted) { Stop-Transcript | Out-Null }
    if ($OwnsMutex) { $BootstrapMutex.ReleaseMutex() }
    if ($null -ne $BootstrapMutex) { $BootstrapMutex.Dispose() }
}
