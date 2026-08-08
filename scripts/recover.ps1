param(
  [switch]$Tunnel,
  [string]$BackupFile = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Root "server.py"))) {
  $Root = Get-Location
}

Set-Location $Root
Write-Host "== 快速恢复 ==" -ForegroundColor Cyan
Write-Host "目录: $Root"

# 1) pull latest backups from GitHub
try {
  git pull --ff-only origin main
  Write-Host "[OK] 已拉取最新仓库/备份" -ForegroundColor Green
} catch {
  Write-Host "[!] git pull 失败，继续用本地文件: $($_.Exception.Message)" -ForegroundColor Yellow
}

# 2) restore content.json from backup if requested / if missing
$dataFile = Join-Path $Root "data\content.json"
$latest = Join-Path $Root "backups\content-latest.json"
if ($BackupFile -and (Test-Path $BackupFile)) {
  Copy-Item $BackupFile $dataFile -Force
  Write-Host "[OK] 已从指定备份恢复: $BackupFile" -ForegroundColor Green
} elseif (Test-Path $latest) {
  Copy-Item $latest $dataFile -Force
  Write-Host "[OK] 已从 backups/content-latest.json 恢复到 data/content.json" -ForegroundColor Green
} else {
  Write-Host "[i] 使用现有 data/content.json" -ForegroundColor Yellow
}

# 3) open Render redeploy page (cloud recovery)
$renderUrl = "https://dashboard.render.com/"
Write-Host "[i] 云端恢复：打开 Render Dashboard → promo-landing → Manual Deploy → Deploy latest commit"
Start-Process $renderUrl

# 4) start local emergency server
Write-Host "[i] 启动本地应急站 http://127.0.0.1:8787/"
$server = Start-Process -FilePath "python" -ArgumentList "server.py" -PassThru -WindowStyle Normal

Start-Sleep -Seconds 2
try {
  $h = Invoke-WebRequest "http://127.0.0.1:8787/api/health" -UseBasicParsing -TimeoutSec 5
  Write-Host "[OK] 本地服务正常: $($h.Content)" -ForegroundColor Green
} catch {
  Write-Host "[!] 本地服务未就绪，请检查 Python 窗口报错" -ForegroundColor Red
}

Start-Process "http://127.0.0.1:8787/"
Start-Process "http://127.0.0.1:8787/admin.html"

if ($Tunnel) {
  Write-Host "[i] 正在生成临时公网链接（需保持本窗口运行）..."
  $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
  npx --yes localtunnel --port 8787
} else {
  Write-Host ""
  Write-Host "恢复手段:" -ForegroundColor Cyan
  Write-Host "  A. Render 控制台 Manual Deploy（固定域名恢复）"
  Write-Host "  B. 本地已启动，可把 http://127.0.0.1:8787 给自己测"
  Write-Host "  C. 需要临时外网链接时再运行:  .\快速恢复.bat -Tunnel"
  Write-Host ""
  Write-Host "按 Enter 结束本脚本（不会关闭已启动的 python 服务）"
  [void][System.Console]::ReadLine()
}
