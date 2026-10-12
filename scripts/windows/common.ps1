# Dependency-free Windows PowerShell 5.1 bootstrap/launch utilities.
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

function ConvertTo-NativeArgument([string]$Value) {
    # Windows CommandLineToArgvW quoting, including quotes and trailing backslashes.
    return '"' + [regex]::Replace([regex]::Replace($Value, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
}

function Invoke-BootstrapTool([string]$Executable, [string[]]$ToolArguments, [switch]$Capture, [switch]$Retry) {
    for ($Attempt=1; $Attempt -le 3; $Attempt++) {
        $Info = [Diagnostics.ProcessStartInfo]::new()
        $Info.FileName = $Executable
        $Info.Arguments = ($ToolArguments | ForEach-Object { ConvertTo-NativeArgument $_ }) -join ' '
        $Info.UseShellExecute = $false; $Info.CreateNoWindow = $true
        $Info.RedirectStandardOutput = $true; $Info.RedirectStandardError = $true
        $Info.StandardOutputEncoding = [Text.UTF8Encoding]::new($false)
        $Info.StandardErrorEncoding = [Text.UTF8Encoding]::new($false)
        $Process = [Diagnostics.Process]::Start($Info)
        try {
            $OutLines = [Collections.Generic.List[string]]::new()
            $ErrorLines = [Collections.Generic.List[string]]::new()
            $OutTask = $Process.StandardOutput.ReadLineAsync()
            $ErrorTask = $Process.StandardError.ReadLineAsync()
            $OutDone = $false; $ErrorDone = $false
            while (-not $OutDone -or -not $ErrorDone) {
                $Progressed = $false
                if (-not $OutDone -and $OutTask.IsCompleted) {
                    $Line = $OutTask.Result; $Progressed = $true
                    if ($null -eq $Line) { $OutDone = $true }
                    else { $OutLines.Add($Line); if (-not $Capture) { Write-Host $Line }; $OutTask = $Process.StandardOutput.ReadLineAsync() }
                }
                if (-not $ErrorDone -and $ErrorTask.IsCompleted) {
                    $Line = $ErrorTask.Result; $Progressed = $true
                    if ($null -eq $Line) { $ErrorDone = $true }
                    else { $ErrorLines.Add($Line); if (-not $Capture) { Write-Host $Line }; $ErrorTask = $Process.StandardError.ReadLineAsync() }
                }
                if (-not $Progressed) { Start-Sleep -Milliseconds 30 }
            }
            $Process.WaitForExit()
            $StandardOut = ($OutLines -join "`n").Trim(); $StandardError = ($ErrorLines -join "`n").Trim()
            if ($Process.ExitCode -eq 0) {
                if ($Capture) { return $StandardOut }


                return
            }
            $Detail = $StandardOut + "`n" + $StandardError
            if ($Retry -and $Attempt -lt 3 -and $Detail -match 'timed? ?out|connection (reset|refused|aborted)|temporar|\b(429|502|503|504)\b|name resolution') {
                Write-Host "Temporary network error; retry $Attempt/2..."
                Start-Sleep -Seconds ($Attempt * 2)
                continue
            }
            throw "Command failed ($($Process.ExitCode)): $Executable`n$Detail"
        } finally { $Process.Dispose() }
    }
}

function Get-VerifiedArchive($Spec, [string]$Directory) {
    $Name = [IO.Path]::GetFileName(([Uri]$Spec.url).AbsolutePath)
    $Target = Join-Path $Directory $Name
    if (Test-Path -LiteralPath $Target) {
        if ((Get-Sha256File $Target) -eq $Spec.sha256) { return $Target }
    }
    $Partial = $Target + '.part'
    for ($Attempt=1; $Attempt -le 3; $Attempt++) {
        try {
            Invoke-WebRequest -Uri $Spec.url -OutFile $Partial -UseBasicParsing -TimeoutSec 60
            if ((Get-Sha256File $Partial) -ne $Spec.sha256) {
                throw "Downloaded archive failed SHA256 verification: $Name"
            }
            Move-Item -LiteralPath $Partial -Destination $Target -Force
            return $Target
        } catch {
            if ($Attempt -eq 3 -or $_.Exception.Message -notmatch 'timed? ?out|connection|temporar|\b(429|502|503|504)\b|name resolution') { throw }
            Start-Sleep -Seconds ($Attempt * 2)
        } finally { Remove-Item -LiteralPath $Partial -Force -ErrorAction SilentlyContinue }
    }
}

function Get-Sha256File([string]$Path) {
    # Avoid optional module auto-loading in a Python-launched Windows PowerShell session.
    $Stream = [IO.File]::OpenRead($Path)
    $Hash = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($Hash.ComputeHash($Stream))).Replace('-','').ToLowerInvariant() }
    finally { $Stream.Dispose(); $Hash.Dispose() }
}

function Start-VaultRagSetup([string]$Repository) {
    $Arguments = '-NoProfile -ExecutionPolicy Bypass -File ' + (ConvertTo-NativeArgument (Join-Path $Repository 'scripts\setup.ps1'))
    # This is the user-visible installer progress window requested by the double-click flow.
    $Process = Start-Process -FilePath powershell.exe -ArgumentList $Arguments -WorkingDirectory $Repository -WindowStyle Normal -PassThru
    try { $Process.WaitForExit(); return $Process.ExitCode } finally { $Process.Dispose() }
}
