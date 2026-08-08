@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo  快速恢复（含临时公网隧道）
echo  本窗口需保持开启；关闭后临时链接失效。
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\recover.ps1" -Tunnel
pause
