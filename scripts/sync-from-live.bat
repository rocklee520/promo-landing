@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
echo 正在从线上拉取内容，避免本地覆盖后台修改...
python -c "import json,urllib.request; u='https://promo-landing.onrender.com/api/content'; c=json.load(urllib.request.urlopen(u,timeout=60)); c.setdefault('site',{})['adminPassword']=''; open('data/content.json','w',encoding='utf-8').write(json.dumps(c,ensure_ascii=False,indent=2)+chr(10)); print('OK posts',len(c.get('posts') or []))"
if errorlevel 1 (
  echo 拉取失败，请检查网站是否可访问
  exit /b 1
)
echo 已写入 data\content.json
