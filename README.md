# AgentWorkspace 后端骨架

AI 协作工作台的本机开发骨架。当前只有 Django 服务、首页和健康检查，尚无业务功能。

已从真实Windows启动脚本完成HTTP与浏览器验证；4项契约测试、Django系统检查和Python代码检查通过。验证服务已停止。

## 投递简历后继续

1. 双击 `Run-Backend.cmd`，打开首页确认服务正常。
2. 在Codex选择本目录，新聊天使用 `START_HERE.md` 的入口；现有聊天可说“继续 AgentWorkspace，从当前任务开始”。
3. 当前状态与下一项范围在 `tasks/current.md`。按既定路线准备工作区授权读写的首个小规格，确认后实现，不重建项目或重复安装依赖。


## 启动

双击根目录的 `Run-Backend.cmd`。它会：

1. 使用 `.venv\Scripts\python.exe`（`PYTHONUTF8=1`）；
2. 对本地开发库执行 `manage.py migrate --noinput`；
3. 启动 `runserver 127.0.0.1:8000`。

缺少虚拟环境或 Django 时会明确报错并保留窗口。按 `Ctrl+C` 停止，不注册常驻服务。脚本不联网、不安装依赖、不读取 MySQL 凭据。

启动后：

- 首页：http://127.0.0.1:8000/
- 健康检查：http://127.0.0.1:8000/api/health/ （仅表示进程存活，不表示数据库或 AI 可用）

## 常用命令

在项目根目录执行：

```text
.venv\Scripts\python.exe backend\manage.py check
.venv\Scripts\python.exe backend\manage.py migrate --noinput
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check backend
```

## 当前开发库

本机开发与测试使用 SQLite：`.tools/dev.sqlite3`，已由本次迁移创建。`.tools/` 已被 Git 忽略，其中还存放首次运行生成的 `django-secret-key`；两者都不提交。

## 未实现 / 待接

- MySQL：尚未接入，保留为后续明确选型；当前不自动探测或猜测凭据。
- AI：用户在应用运行时自行配置 AI API key，开发阶段不需要提供密钥。
- 首个业务任务：未实现。当前 `core` 只有首页和只读健康检查。
- 管理员账号、业务模型、前端框架均未创建。
