@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 请先保持「启动.bat」在运行，再开本窗口生成公网链接。
echo.
set PATH=%PATH%;%ProgramFiles%\nodejs;%LOCALAPPDATA%\Programs\nodejs
npx --yes localtunnel --port 8787
pause
