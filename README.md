# 更新速递 · 推广页

公网地址：https://promo-landing.onrender.com

## 本地

双击 `启动.bat`，打开 http://127.0.0.1:8787/  
后台：http://127.0.0.1:8787/admin.html

## Render 部署注意

若提示无法访问 GitHub 仓库：把仓库设为 Public，或给 Render GitHub App 勾选该仓库后重连。

生产环境请在 Render → Environment 设置：

- `ADMIN_PASSWORD` = 你的后台密码（例如 `liy123456780`）

## 备份（已启用）

1. **后台每次保存**：自动下载一份 `content-backup-*.json` 到你的电脑  
2. **云端每 15 分钟**：GitHub Action 把线上内容写入私有仓库  
   - `data/content.json`（下次部署用的种子）  
   - `backups/content-latest.json` + 历史快照  
3. 也可手动点后台「导出 JSON 备份」

手动立刻备份：GitHub → Actions → Backup content → Run workflow

## 网站打不开时：快速恢复

### 方式 A（推荐，恢复固定域名）

1. 打开 https://dashboard.render.com/  
2. 进入服务 `promo-landing`  
3. **Manual Deploy → Deploy latest commit**  
4. 等 Live 后继续用：https://promo-landing.onrender.com

若整个服务被删：用同一仓库重新 Blueprint 部署即可（内容在私有仓库里）。

### 方式 B（本机一键应急）

1. 双击 `快速恢复.bat`  
   - 拉取最新备份  
   - 启动本地站  
   - 打开 Render 控制台  
2. 需要临时外网链接：双击 `快速恢复-带隧道.bat`

### 方式 C（从某份备份还原）

把 `backups/content-xxxx.json` 或本地下载的备份，在后台用「导入 JSON」→「保存全部到服务器」。
