param([switch]$ServiceSmoke)
$ErrorActionPreference='Stop'
$Repository=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$Python=Join-Path $Repository '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) { throw 'Run the installer first.' }
Get-ChildItem -LiteralPath (Join-Path $Repository 'scripts') -Filter '*.ps1' -Recurse | ForEach-Object {
    $Tokens=$null; $Errors=$null
    [Management.Automation.Language.Parser]::ParseFile($_.FullName,[ref]$Tokens,[ref]$Errors) | Out-Null
    if ($Errors.Count) { throw ($Errors | Out-String) }
}
& $Python -X utf8 (Join-Path $PSScriptRoot 'run_checks.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($ServiceSmoke) {
    & $Python -X utf8 (Join-Path $PSScriptRoot 'service_smoke.py')
    exit $LASTEXITCODE
}
