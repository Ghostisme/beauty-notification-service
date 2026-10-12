@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe python -m venv .venv
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.lock
if errorlevel 1 goto fail
.venv\Scripts\python.exe -X utf8 run.py
goto end
:fail
echo 安装未完成，请检查上方错误。
:end
pause
