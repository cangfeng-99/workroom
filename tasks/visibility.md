# tasks/visibility.md（执行可见性现状）

2026-10-22 由 Codex 诊断：只读查看源码 + HTTP 探测。以下为实测结论，未实现的部分不写成已实现。

## 已验证事实

- A2A 的 `workbuddy` 命令具备 `-p` 与 `--output-format stream-json`，属于无头 CLI 执行，不是原生 WorkBuddy 桌面任务页。
- MCP 的 `mcp_server.py` 使用进程内 Hub 实例；HTTP 8080 控制台与 `/health` 当前连接被拒绝。另启 HTTP 实例不保证能查看 MCP 原任务；需验证同一执行后端，或共享存储及实时事件通道，不能只凭地址相同推断联通。
- 原生 WorkBuddy 任务页官方支持展示步骤、文件等；当前 CLI 任务自动同步到 GUI **未验证**。
- 只能展示实际输出的步骤、工具调用与结果，以及简短决策说明；平台未提供的内部思考无法补出。

## 可采用的路径：原生 GUI 执行（本机联动示范待验证）

1. Codex 准备并写好 `tasks/current.md`（当轮唯一批准的小任务）。
2. 用户在 WorkBuddy 中选择本目录，发一句入口指令：只执行 current 中已批准的小任务，并回填结果。
3. 用户直接看 WorkBuddy 的执行过程。
4. Codex 回读产物完成验收。

- 同一任务严禁再由 A2A 重复启动。
- 入口模板只能读取已批准任务；若状态不是已批准，只做只读说明，不执行。

## 待验证的全自动可视路径

- 候选：官方 CodeBuddy `--serve` WebUI / HTTP / SSE；需先确认本机版本，并验证同一会话/任务 ID。
- 通过后才能接 A2A 统一执行后端。目前**不是**已完成的接入。
- 未核验前不改网关、不改全局设置、不启动免鉴权服务。

## 来源

- https://www.codebuddy.cn/docs/workbuddy/Conversation
- https://www.codebuddy.cn/docs/cli/web-ui
- https://www.codebuddy.cn/docs/cli/http-api
