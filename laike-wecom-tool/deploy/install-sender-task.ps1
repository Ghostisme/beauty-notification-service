param([string]$TaskName = 'Laike-WeCom-Sender')
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectPath '.sender-venv\Scripts\pythonw.exe'
$senderPath = Join-Path $projectPath 'sender.py'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '请先运行 start-sender.bat 安装并完成发送端配置。' }
if (-not (Test-Path -LiteralPath (Join-Path $projectPath 'sender-config.json'))) { throw '发送端连接尚未配置。' }
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$arguments = '-X utf8 "' + $senderPath + '"'
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument $arguments -WorkingDirectory $projectPath
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description '登录后运行企微门店通知发送端；需要保持桌面可交互。' -Force | Out-Null
Write-Host '已配置登录后自动启动。请关闭手动运行的旧发送端，再从任务计划程序启动此任务。'
