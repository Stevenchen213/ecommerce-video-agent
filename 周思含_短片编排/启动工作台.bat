@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Starting 短片编排成片台 on http://127.0.0.1:8790/
python -m uvicorn app.api:app --host 127.0.0.1 --port 8790
pause
