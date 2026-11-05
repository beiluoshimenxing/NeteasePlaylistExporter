@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo 正在准备 Python 环境...
  py -3.11 -m venv .venv
  if errorlevel 1 (
    echo 请安装 Python 3.11 或以上版本，再运行本文件。
    pause
    exit /b 1
  )
)
".venv\Scripts\python.exe" -c "import PySide6,httpx,qrcode,PIL" >nul 2>&1
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo 依赖安装失败，请检查网络后重新双击。
    pause
    exit /b 1
  )
)
start "" ".venv\Scripts\pythonw.exe" main.py
