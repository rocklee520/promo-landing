# 更新速递 · 推广页

## 本地

双击 `启动.bat`，打开 http://127.0.0.1:8787/  
后台：http://127.0.0.1:8787/admin.html（默认密码 `admin123`）

## 固定上线（Render 免费）

1. 代码推到 GitHub
2. 打开 https://dashboard.render.com/select-repo?type=web
3. 选择本仓库，会读取 `render.yaml` 自动创建服务
4. 部署完成后得到固定地址：`https://promo-landing-xxxx.onrender.com`

可选（让后台修改在免费套餐重启后也不丢）：在 Render 环境变量里加

- `GITHUB_TOKEN`：有 `repo` 权限的 GitHub Token
- `GITHUB_REPO`：`你的用户名/仓库名`
- `GITHUB_BRANCH`：`main`
- `GITHUB_CONTENT_PATH`：`data/content.json`

免费套餐闲置约 15 分钟后会休眠，首次打开可能要等几十秒唤醒。
