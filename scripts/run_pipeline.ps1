# Run hidden by Task Scheduler. The path comes from this script, not the current directory.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$scriptPath = Join-Path $PSScriptRoot 'pipeline.py'
# Same rule as Python: ENERGY_DATA_DIR if set, otherwise <project>\data.
$dataDir = if ($env:ENERGY_DATA_DIR) { $env:ENERGY_DATA_DIR } else { Join-Path $projectRoot 'data' }
$logDir = Join-Path $dataDir 'runs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
Set-Location -LiteralPath $projectRoot
# UTC and UTF-8 keep the logs consistent even on a Portuguese-locale Windows.
$env:PYTHONUTF8 = '1'
$schedulerLog = Join-Path $logDir 'scheduler.log'
try {
    # In PowerShell 5.1, redirecting a native executable's stderr with
    # ErrorActionPreference=Stop turns the first log line into an exception
    # and kills Python mid-run. cmd.exe does the redirection instead.
    & cmd.exe /d /c "`"$pythonPath`" `"$scriptPath`" >> `"$schedulerLog`" 2>&1"
    exit $LASTEXITCODE
} catch {
    $_ | Out-File -LiteralPath $schedulerLog -Append -Encoding utf8
    exit 1
}
