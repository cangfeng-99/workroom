# 新会话与开工入口

项目目录：`D:\Users\28369\Desktop\AgentWorkspace`。在 Codex 与 WorkBuddy 中都选择这个目录。只选择上层 Desktop 时，不假定子目录的 AGENTS.md 会自动加载。

## Codex 新聊天开场

```text
继续 D:\Users\28369\Desktop\AgentWorkspace 项目。
先读 AGENTS.md 和 tasks/current.md 最新快照/本轮任务，按需读约束、计划、专家路由与源码。
先报告当前 PLAN/RULES 修订号、阶段、已验证结果、未决事项与下一项小任务。
Codex 负责规划、派活和验收；WorkBuddy 实现与验证，只使用这两个开发角色。
先检查原任务/进程是否仍在执行，禁止重复派活；授权内准备继续，业务阶段按计划等我认可。
用户已有 AI API key，会在应用运行时自行连接，不需要我在聊天里提供。
```

## WorkBuddy 原生会话入口

```text
工作目录 D:\Users\28369\Desktop\AgentWorkspace。
按 CODEBUDDY.md 读取 AGENTS.md 与 tasks/current.md。
只领取本轮明确批准、且没有其它执行者占用的任务；无已批准任务时仅说明当前状态。
执行时写步骤、命令结果、阻塞与产物；结束回填同一份 current，交回 Codex 验收。
不要重复启动 A2A 已在执行的任务。
```

## 每轮最小上下文

| 文件 | 用途 | 何时读 |
|---|---|---|
| AGENTS.md | 分工、授权、读写与验收约定 | 开工 |
| tasks/current.md | 当前版本、任务、结果、阻塞与下一步 | 先读最新快照与相关任务 |
| CONSTRAINTS.md | 用户已确认约束及变更 | 修订号变化、冲突、需求变更 |
| tasks/plan.md | 阶段路线与验收门槛 | 规划和阶段切换 |
| PROJECT.md | 产品范围与未定选型 | 需求和架构相关 |
| experts/ROLES.md | 专家参考路由 | 需要对应工程知识 |
| tasks/tooling-sources.json | 安装来源、版本与校验 | 安装/升级/故障 |

技能先按名称与说明发现，需要时读取完整 SKILL.md；不全量加载全部技能、专家原文与历史日志。项目规则和实际用户授权优先于来源中的通用默认。

每轮结束回写实际完成项、验证及退出码、未验证项、阻塞、下一步和任务/run ID。重要口头变更同步约束并增加修订号。此流程依靠遵守与核验，不是自动监听或强制同步。新会话可恢复已写入的事实，无法恢复未记录的全部聊天细节或内部思考。

## 本机入口

- `Run-Backend.cmd`：双击启动本机 Django 开发服务（先迁移本地 SQLite，再 `runserver 127.0.0.1:8000`）；Ctrl+C 停止，不常驻。
- `Start-Dev.cmd`：打开本目录开发终端，设置当前进程的 Python/Node/pnpm 路径；不是产品启动器。
- `Check-Ready.cmd`：检查环境并更新 `tasks/reports/preflight.json`。
- `Configure-MySQL.cmd`：在本机终端隐藏输入密码，只验证登录；不存密码、不建库、不永久配置。需持久配置时再依据业务规格实施。

项目使用本地 Git 检查点保存源码与交接资料，尚未推送或创建远程仓库。切换目录、工作树或电脑前，先确认带上最新项目文件；全局技能安装不会自动随项目同步到其它电脑。
