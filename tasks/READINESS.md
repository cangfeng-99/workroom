# 开工准备验收

## 最新补充：T008 Django骨架已验收

- 用户直接授权创建Django项目，当前RULES-r4。backend/与Windows启动入口已完成；默认本机开发SQLite已迁移。
- 实际Run-Backend.cmd从上层目录启动，首页/health均200、POST405、非法Host400；浏览器页面与链接验证通过。4项pytest、ruff backend/tools、Django check通过。
- 详细报告tasks/reports/T008-live.json；验证进程树已停止。双击Run-Backend.cmd重启。
- 本页后文为T007时点的准备记录，其中“业务代码尚未实现”仍有效；骨架创建状态以上述补充和current为准。

2026-10-22，Codex 复核 WorkBuddy 产物。当前规则以 CONSTRAINTS.md 为准，状态只认 current.md。

## 已完成

- 独立项目目录、本地 Git 仓库与秘密/依赖忽略规则；未提交、未推送。
- 隔离 Python 3.12.14：Django5.2.18、pytest、pytest-django、Ruff、mysqlclient、Playwright，锁定文件 requirements-dev.lock。
- 复用本机 Node24.19.0、pnpm11.25.0、Git；开发终端仅更改当前进程 PATH，无全局路径修改。
- Codex/WorkBuddy 各安装 webapp-testing 和 python-testing-patterns。固定来源 ref，保留许可证；Codex 对连接器源内容精确还原并核对9个 Git blob SHA1，安装副本逐文件校验。
- WorkBuddy 单 Agent 全栈执行专家已注册；原8个市场条目保留。按需路由后端、前端、Agent、安全、测试参考；不自动派生其他 Agent，不固定模型。
- 新聊天入口 START_HERE.md；WorkBuddy 入口 CODEBUDDY.md；旧 AGENTS/current.md 已归档，指针统一至 tasks/current.md。
- Start-Dev.cmd、Check-Ready.cmd、Configure-MySQL.cmd。最后一个仅隐藏输入并检查本机登录，不保存密码、不创建库、不永久配置。

## 实际核验

- Check-Ready.cmd --no-pause：开发工具 PASS；报告 tasks/reports/preflight.json。包括依赖、Node/pnpm/Git、MySQL服务与端口、技能、原生专家validator、版本、Git忽略、临时文件读写、临时Django system check、Chrome点击/状态变化/截图。
- tools/Enter-Dev.ps1：新PowerShell进程中 Python/Node/pnpm 版本正确。
- ruff check tools 与 compileall：通过；未增加忽略或跳过检查。
- check_mysql.py --help：正常；--host example.com：在输入凭据和连接前拒绝，预期退出15。
- 下载的 with_server.py --help：退出0。该helper不是产品命令沙箱，不接收不可信命令。

以上是工具准备验证。临时SQLite内存配置不代表产品数据库选型；临时文件读写不代表产品目录权限隔离已验收；浏览器smoke不是产品端到端测试。

## 尚需的运行信息与产品决定

- 用户已有 API key，在产品运行时自行连接，开发准备无需接收。
- MySQL80服务/3306可达；账号密码尚未提供，登录与业务库未验证。可由用户在本机运行登录检查。
- 前端与桌面框架、首个外部平台动作仍未锁定。已有参考不视为批准。
- 原生专家GUI卡片显示未实测；未向云端项目添加专家。注册/validator通过不等于GUI已加载。
- 现有 A2A 无头执行已实跑，但自动同步到WorkBuddy原生任务页未证实。需要原生可见过程时，使用START_HERE中的GUI入口，同一任务只启动一次。
- 产品的AI工具连接器、MCP、心跳与进度流、权限隔离、自动取消、业务功能、安装包都尚未实现；业务阶段通过0个。

## 明天第一步

先用START_HERE恢复当前上下文，运行Check-Ready，审阅P0的范围与验收结果，再锁定第一个小规格。求职投递继续，项目开发不等待所有平台和功能齐全。

## 执行通道记录

T003/T004/T006触及A2A约300秒调用时限，超时不等于子进程结束。已检查实际进程和产物，T004/T006对应仍活跃的单轮进程树由Codex停止后复核，没有重复派发安装。依赖下载完成；历史错误报告与日志保留，最终状态以新预检为准。后续任务应更小；长外部命令脱离模型调用并带超时/日志/状态，模型不阻塞等待下载。

历史 install-core.ps1/launch-install.ps1/launch_detached.py 仅保留排障记录，不是开工入口。若重建环境，先核对 requirements-dev.lock，使用 tools/install-core.py 或依赖管理器的明确命令；不要重复运行旧安装器。
