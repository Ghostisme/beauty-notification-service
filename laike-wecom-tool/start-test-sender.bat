@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .sender-venv\Scripts\python.exe python -m venv .sender-venv
.sender-venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements-sender.lock
if errorlevel 1 goto fail
if not exist sender-config.json .sender-venv\Scripts\python.exe -X utf8 sender.py --configure --test-only
if errorlevel 1 goto fail
if not exist sender-data\desktop-profile.json .sender-venv\Scripts\python.exe -X utf8 sender.py --calibrate
if errorlevel 1 goto fail
.sender-venv\Scripts\python.exe -X utf8 sender.py --test-only
goto end
:fail
echo 测试群发送端尚未就绪，请检查上方提示。
:end
pause
