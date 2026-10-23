# AgentWorkspace 后端骨架

AI协作工作台的本机开发版本：Django服务、首页、健康检查，以及已完成技术验收的本机演示工作区。

已从真实Windows启动脚本完成HTTP与浏览器验证；T008骨架已验收；T009完整测试69项通过、1项因Windows文件符号链接权限跳过，Django系统检查及Python代码检查通过。最新运行状态见tasks/current.md。

## 投递简历后继续

1. 双击 `Run-Backend.cmd`，打开首页确认服务正常。
2. 在Codex选择本目录，新聊天使用 `START_HERE.md` 的入口；现有聊天可说“继续 AgentWorkspace，从当前任务开始”。
3. 当前状态与下一项范围在 `tasks/current.md`。先体验 /workspace/ 的授权、读取、新建与撤销流程，反馈后再确定下一项；不重建项目或重复安装依赖。


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

## 第一步：本机演示工作区

启动后打开 http://127.0.0.1:8000/workspace/ ：

1. 点击“授权使用演示工作区”，首次准备 `.tools/workspaces/demo` 与 `welcome.md`。
2. 点击文件读取；输入文件名和内容后创建 .txt/.md，再从列表读取真实磁盘内容。
3. 重名不会覆盖，文件上限64KiB；文本中的HTML按文本显示。
4. 点击“撤销授权”后，本浏览器不能再读写；已有文件保留，其它浏览器需独立授权。

当前只开放固定演示目录，不能输入任意本机根目录；不执行文件或命令。它不是OS级沙箱，未对抗本机恶意进程并发替换路径。Windows真实文件symlink测试因WinError1314未运行；真实junction、硬链接及拒绝symlink属性的调用级测试通过。验收记录见tasks/acceptance/T009.md。

## 未实现 / 待接

- MySQL：尚未接入，保留为后续明确选型；当前不自动探测或猜测凭据。
- AI：用户在应用运行时自行配置 AI API key，开发阶段不需要提供密钥。
- 账号、项目、成员、任务分配、AI连接器和执行进度流尚待后续阶段。
- 管理员账号、业务模型、前端框架均未创建。
