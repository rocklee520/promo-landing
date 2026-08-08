@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo  快速恢复：拉取备份 + 本地拉起 + 打开 Render 控制台
echo  若还要临时公网链接，请运行： 快速恢复-带隧道.bat
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\recover.ps1" %*
pause
