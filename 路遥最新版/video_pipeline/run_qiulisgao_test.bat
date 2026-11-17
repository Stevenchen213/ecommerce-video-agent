@echo off
chcp 65001 >nul
cd /d "%~dp0.."
python -m video_pipeline.cli run video_pipeline\examples\qiulisgao_test.yaml --jianying
pause
