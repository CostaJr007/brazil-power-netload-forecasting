# Executado de modo oculto pelo Agendador. O caminho vem deste script, não do diretório atual.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$scriptPath = Join-Path $PSScriptRoot 'pipeline.py'
$logDir = Join-Path $projectRoot 'data\runs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
Set-Location -LiteralPath $projectRoot
# UTC e UTF-8 deixam os registros consistentes mesmo no Windows em português.
$env:PYTHONUTF8 = '1'
$schedulerLog = Join-Path $logDir 'scheduler.log'
try {
    # No PowerShell 5.1, redirecionar stderr de executável nativo com
    # ErrorActionPreference=Stop transforma a primeira linha de log em exceção
    # e encerra o Python no meio da execução. O cmd.exe faz o redirecionamento.
    & cmd.exe /d /c "`"$pythonPath`" `"$scriptPath`" >> `"$schedulerLog`" 2>&1"
    exit $LASTEXITCODE
} catch {
    $_ | Out-File -LiteralPath $schedulerLog -Append -Encoding utf8
    exit 1
}
