@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .sender-venv\Scripts\python.exe goto missing
.sender-venv\Scripts\python.exe -X utf8 sender.py --groups
goto end
:missing
echo 请先运行 start-test-sender.bat 完成安装和连接配置。
:end
pause
