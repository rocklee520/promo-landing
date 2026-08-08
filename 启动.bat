@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在启动推广站...
python server.py
pause
