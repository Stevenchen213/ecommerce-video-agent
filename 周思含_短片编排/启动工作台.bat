@echo off
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo 未找到 python，请先安装 Python 并加入 PATH
  pause
  exit /b 1
)

echo Checking dependencies...
python -c "import uvicorn,fastapi,yaml,dotenv" 2>nul
if errorlevel 1 (
  echo Installing requirements...
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo 依赖安装失败
    pause
    exit /b 1
  )
)

echo Starting 短片编排成片台 on http://127.0.0.1:8790/
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://127.0.0.1:8790/"
python -m uvicorn app.api:app --host 127.0.0.1 --port 8790
pause
