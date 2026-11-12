# Windows PowerShell 5.1 and PowerShell 7 entry point. Keep this file ASCII.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidatePattern('^[a-z][a-z0-9-]*$')]
    [string] $Operation,

    [Parameter(Position = 1)]
    [System.Collections.IDictionary] $Arguments = @{}
)

$ErrorActionPreference = 'Stop'
# Preserve the Python client's JSON errors even if the caller enables this PS 7 option.
$PSNativeCommandUseErrorActionPreference = $false
$pythonCommand = $null
$pythonPrefix = @()

# Probe interpreters only, never retry a service operation with another runtime.
foreach ($name in @('python', 'py', 'python3')) {
    foreach ($candidate in @(Get-Command $name -CommandType Application -All -ErrorAction SilentlyContinue)) {
        if ($candidate.Source -match '[/\\]Microsoft[/\\]WindowsApps[/\\]') {
            continue # Microsoft Store aliases may open the Store instead of Python.
        }
        $prefix = @()
        if ($name -eq 'py') { $prefix = @('-3') }
        try {
            & $candidate.Source @prefix -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>$null
            if ($LASTEXITCODE -eq 0) {
                $pythonCommand = $candidate.Source
                $pythonPrefix = $prefix
                break
            }
        } catch {
            # A missing/broken launcher is not a usable interpreter.
        }
    }
    if ($pythonCommand) { break }
}

if (-not $pythonCommand) {
    Write-Output '{"ok":false,"error":"Python 3.11+ was not found. Install Python or add its executable to PATH; Microsoft Store aliases are skipped."}'
    exit 1
}

$previousOutputEncoding = $OutputEncoding
$previousConsoleEncoding = [Console]::OutputEncoding
try {
    # PS 5.1 defaults native stdin to ASCII. Native stdout also needs UTF-8 decoding.
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    [Console]::OutputEncoding = $OutputEncoding
    $requestJson = ConvertTo-Json -InputObject $Arguments -Depth 100 -Compress
    $requestJson | & $pythonCommand @pythonPrefix -X utf8 (Join-Path $PSScriptRoot 'leafloom.py') $Operation -
    $requestExitCode = $LASTEXITCODE
} finally {
    $OutputEncoding = $previousOutputEncoding
    [Console]::OutputEncoding = $previousConsoleEncoding
}
exit $requestExitCode
