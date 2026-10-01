@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

echo ========================================
echo   双平台视频组装台
echo ========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 未找到 python，请先安装并加入 PATH。
  pause
  exit /b 1
)

echo [1/2] 检查依赖...
python -m pip install -r "video_pipeline\requirements.txt" -q
if errorlevel 1 (
  echo [警告] 依赖安装可能失败，仍尝试启动...
)

echo [2/2] 启动服务 http://127.0.0.1:8787/
echo       浏览器打开上述地址即可使用对接台
echo       按 Ctrl+C 可停止
echo.

start "" "http://127.0.0.1:8787/"
python -m video_pipeline.cli serve --host 127.0.0.1 --port 8787

echo.
echo 服务已退出。
pause
