# AgentWorkspace AI 协作工作台

本机 Django 开发版本：注册登录、项目空间、真人/AI角色团队、邀请、计划任务树，以及显式授权的本机文件工作区。

当前实现与验收以 `tasks/current.md` 最新快照为准；规格、边界和证据分别在 `tasks/specs/`、`CONSTRAINTS.md` 和 `tasks/acceptance/`。AI角色目前用于分工，尚未连接模型或外部工具。

## 投递简历后继续

1. 双击 `Run-Backend.cmd`，打开首页确认服务正常。
2. 在Codex选择本目录，新聊天使用 `START_HERE.md` 的入口；现有聊天可说“继续 AgentWorkspace，从当前任务开始”。
3. 打开 `/projects/` 体验项目空间与新建配置；下一项范围看 `tasks/current.md`，不重建项目或重复安装依赖。


## 启动

双击根目录的 `Run-Backend.cmd`。它会：

1. 使用 `.venv\Scripts\python.exe`（`PYTHONUTF8=1`）；
2. 对本地开发库执行 `manage.py migrate --noinput`；
3. 启动 `runserver 127.0.0.1:8000`。

缺少虚拟环境或 Django 时会明确报错并保留窗口。按 `Ctrl+C` 停止，不注册常驻服务。脚本不联网、不安装依赖、不读取 MySQL 凭据。

启动后：

- 首页：http://127.0.0.1:8000/
- 项目：http://127.0.0.1:8000/projects/
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

## 使用项目与本机文件

注册登录后打开 http://127.0.0.1:8000/projects/ ：

1. 新建项目：名称、说明、项目指令、可选工作空间和初始成员。选择目录只填路径，勾选授权并提交后才绑定当前项目；owner自动加入。
2. 动态发布成员留言；计划切换表格/看板或打开任务树；任务可拆分、指定负责人/日期/状态，真人成员可更新自己被分配任务的状态。
3. 资产页只展示owner已授权本机目录的元数据，不上传。进入原文件工作区可编辑常见UTF-8代码/文本（64KiB以内）并保存回原处或新建；冲突和重名不覆盖。
4. 所有者可添加真人/AI角色、调整分工或生成一次性邀请。真人必须是已有活跃账号或通过邀请注册；邀请不分享本机文件权限。
5. 授权绑定当前账号/项目/浏览器会话。撤销或退出后需重新授权；其它成员不能读取owner的目录，资产也不会变成共享云文件。

工作区使用用户选定的既有实际文件夹，每目录最多显示100项；路径越界、隐藏、链接/reparse及多硬链文件受保护。未授予命令执行能力，也不是OS级沙箱。真实文件symlink测试受Windows权限限制而跳过，其余安全验证以最新验收记录为准。

## 未实现 / 待接

- MySQL：尚未接入，保留为后续明确选型；当前不自动探测或猜测凭据。
- AI API设置与连接测试、外部AI编程工具连接、自动拆分/执行、技能与定时执行仍待后续规格；用户届时自行填写key。
- 当前仅127.0.0.1开发服务，邀请链接尚不能直接提供跨电脑远程协作。最终部署、桌面安装包与执行隔离方案未锁定。
