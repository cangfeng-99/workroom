# AI 协作工作台：接入设计记录

2026-10-22。范围已由用户提出；以下技术接法为候选，尚未实现产品连接器，也未批准业务阶段。

## 产品职责

项目保存目标、约束版本、阶段、任务、依赖、成员、执行记录、产物和验收结论，成为共同上下文来源。用户可查看成员当前任务、最近心跳、阻塞、待验收项与阶段进度。已验收任务与总任务可形成可解释的完成度，任务范围变更需更新基线；AI 自报百分比不作为客观完成度。

一次协作：用户提出目标→Codex 拆分→批准小任务→WorkBuddy 领取→上报步骤与产物→Codex 验收或退回→用户确认阶段→下一阶段。开发本项目只使用 Codex/WorkBuddy；产品未来可容纳更多人类和 AI 成员。

## 两个接入方向

1. **本项目调用外部工具**：应用→执行器适配层→成员电脑上的本地 runner→Codex/WorkBuddy 官方执行入口。云端 Django 不能直接读取成员电脑目录；必须经过该设备的 runner 与明确的工作区授权。
2. **外部工具操作本项目**：Codex/WorkBuddy→MCP 服务或受支持 HTTP 接口→项目的上下文/任务/进度服务。MCP 是工具和信息的接口，不会自动建立成员身份、自动同步历史或获得文件/命令权限。

候选 MCP 工具：get_project_context、list_tasks、claim_task、report_progress、submit_result。它们是设计示例，当前不存在可连接地址。写操作必须绑定成员、项目和任务权限；领取任务使用租约/版本避免重复执行。

## 各工具适配

| 对象 | 接法候选 | 本机证据与限制 |
|---|---|---|
| Codex | App Server；小型批任务可选官方 SDK/exec | 本机 codex-cli 0.163.0-alpha.11.1 有 app-server；当前仅验证版本与 help，未编写产品客户端。App Server 可管理会话、流式事件和审批；以本机协议生成结果为准 |
| WorkBuddy 执行工具 | 已实跑的 CLI + stream-json；HTTP/ACP 候选需按安装版本验证 | 已通过 A2A 多次实际操作文件。桌面5.9.0所带cbc2.117.1，与在线文档较新版本不等同。现有 A2A 不保证与原生GUI同一会话 |
| 应用自身的模型 AI | 运行时连接设置，用户自行输入 API 配置 | 用户已有 key；开发者无需接收。供应商、地址、模型和能力按用户配置验证，不把“兼容 OpenAI”视为所有供应商完全相同 |

官方 Codex SDK 文档已说明旧 codex mcp-server 入口移除；不要照旧教程把 Codex 本身用该命令包装。应用作为 MCP 服务供 Codex 调用，与应用通过 App Server 调用 Codex，是不同方向。

## 数据与可见性边界

- 每次执行持久化 task ID、run ID、工具侧会话 ID、所用上下文版本、状态事件、心跳、产物和验收记录。恢复新会话优先构造当前任务所需上下文，不反复转发全部聊天。
- 至少区分待领取、执行中、等待输入、阻塞、工具报完成、待验收、验收通过/退回、失败、取消、断连或状态陈旧。断连不当完成，重试不重复产生外部副作用。
- 展示可获得的步骤、命令、差异、测试和决策说明；不宣称获取内部完整思考。界面百分比与阶段状态要有计算依据。
- 程序适配层要验证事件是否属于同一 run。A2A 调用后另开 WebUI/HTTP 实例，不能据此证明看到原任务。
- 本机 runner 分别处理目录授权、命令权限与外部平台动作授权。项目成员身份不等于对其电脑所有文件有权限。多执行器并发写入前需隔离工作树或任务文件范围和锁。
- 用户 API key 不进入 Git、普通日志、项目上下文或外部编码任务提示。运行时连接成功/失败可见，失败不回显密钥；持久存储方式待对应安全规格确定。

## 首个接入验收候选

一个外部 AI 领取已批准的小任务，读取对应规则版本，在授权测试目录修改一个文件，上报心跳/步骤/结果并附真实测试证据；面板展示状态变化，由另一角色验收。验证重复领取、断连、超时、退回和越权拒绝。通过后再扩展多工具与自动调度。此项还未开工。

## 官方来源（本轮已读取）

- [Codex 技能](https://learn.chatgpt.com/docs/build-skills)
- [AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Codex SDK](https://learn.chatgpt.com/docs/codex-sdk)
- [Codex App Server](https://learn.chatgpt.com/docs/app-server)
- [Codex MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
- [CodeBuddy Web UI](https://www.codebuddy.cn/docs/cli/web-ui)
- [CodeBuddy HTTP API Beta](https://www.codebuddy.cn/docs/cli/http-api)
