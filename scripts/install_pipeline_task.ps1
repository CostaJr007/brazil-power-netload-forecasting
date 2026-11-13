# Installs only this project's task. Does not require or store a password.
param([string]$TaskName = 'Energy-Data-Pipeline', [switch]$Uninstall)
$ErrorActionPreference = 'Stop'
if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    return
}
$runner = Join-Path $PSScriptRoot 'run_pipeline.ps1'
if (-not (Test-Path -LiteralPath $runner)) { throw "Runner ausente: $runner" }
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing -and -not ($existing.Actions.Arguments -like ('*' + $runner + '*'))) {
    throw "A task with this name and a different action already exists. It will not be overwritten."
}
$account = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $runner + '"'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments
# Indefinite repetition in minutes; per-source frequencies are decided in Python.
$timer = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 15)
$login = New-ScheduledTaskTrigger -AtLogOn -User $account
$principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($timer,$login) `
    -Principal $principal -Settings $settings -Description 'ONS/MERGE/GFS/INMET collection and Silver processing for the Energy project.' -Force | Out-Null
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName,State
Get-ScheduledTaskInfo -TaskName $TaskName | Select-Object NextRunTime,LastRunTime,LastTaskResult
