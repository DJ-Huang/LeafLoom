# Shared bootstrap utilities. Works with built-in Windows PowerShell 5.1.
function Get-VaultRagState {
    if ($env:VAULT_RAG_HOME) { return [IO.Path]::GetFullPath($env:VAULT_RAG_HOME) }
    return Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'VaultRag'
}

function Get-TextHash([string]$Text) {
    $Hash = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($Hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)))).Replace('-','').Substring(0,24) }
    finally { $Hash.Dispose() }
}

function Show-VaultRagError([string]$Message) {
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.MessageBox]::Show($Message, 'VaultRag', [Windows.Forms.MessageBoxButtons]::OK, [Windows.Forms.MessageBoxIcon]::Error) | Out-Null
}

function Invoke-Tool([string]$Executable, [string[]]$ToolArguments) {
    & $Executable @ToolArguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Executable $($ToolArguments -join ' ')" }
}

function Get-VerifiedArchive($Spec, [string]$Directory) {
    $Name = [IO.Path]::GetFileName(([Uri]$Spec.url).AbsolutePath)
    $Target = Join-Path $Directory $Name
    if (Test-Path -LiteralPath $Target) {
        if ((Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash.ToLowerInvariant() -eq $Spec.sha256) { return $Target }
        Remove-Item -LiteralPath $Target -Force
    }
    $Partial = $Target + '.part'
    try {
        Invoke-WebRequest -Uri $Spec.url -OutFile $Partial -UseBasicParsing
        if ((Get-FileHash -LiteralPath $Partial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Spec.sha256) {
            throw "Downloaded archive failed SHA256 verification: $Name"
        }
        Move-Item -LiteralPath $Partial -Destination $Target -Force
        return $Target
    } finally { Remove-Item -LiteralPath $Partial -Force -ErrorAction SilentlyContinue }
}

function Find-Python312 {
    # Single quotes inside Python survive PowerShell 5.1's legacy native quoting.
    $Probe = "import sys; print(sys.executable if sys.version_info[:2] == (3,12) and sys.maxsize > 2**32 else '')"
    foreach ($Name in @('py.exe','python.exe','python3.exe')) {
        $Command = Get-Command $Name -ErrorAction SilentlyContinue
        if (-not $Command -or $Command.Source -like '*\WindowsApps\*') { continue }
        $ProbeArgs = @('-c',$Probe)
        if ($Name -eq 'py.exe') { $ProbeArgs = @('-3.12') + $ProbeArgs }
        try {
            $Value = & $Command.Source @ProbeArgs 2>$null
            if ($LASTEXITCODE -eq 0 -and $Value -and (Test-Path -LiteralPath $Value)) { return [string]$Value }
        } catch { }
    }
    return $null
}

function Start-VaultRagSetup([string]$Repository) {
    $Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $Repository 'scripts\setup.ps1') + '"'
    $Process = Start-Process -FilePath powershell.exe -ArgumentList $Arguments -WorkingDirectory $Repository -WindowStyle Normal -PassThru
    # Wait for the installer itself, not its browser or scheduled service descendants.
    $Process.WaitForExit()
    return $Process.ExitCode
}

function Find-CompatibleNode {
    $Command = Get-Command node.exe -ErrorAction SilentlyContinue
    if (-not $Command) { return $null }
    try {
        $Version = & $Command.Source --version
        if ($LASTEXITCODE -eq 0 -and $Version -match '^v(\d+)\.(\d+)\.') {
            $Major=[int]$Matches[1]; $Minor=[int]$Matches[2]
            if (($Major -eq 22 -and $Minor -ge 12) -or $Major -gt 22) { return $Command.Source }
        }
    } catch { }
    return $null
}
