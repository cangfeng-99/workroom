# 把自己的AI工具接入WorkRoom

项目提供者无需安装所有用户的AI软件。每位用户在自己的设备安装并登录相应工具，在WorkRoom中绑定自己的项目权限。

## 最短连接流程

1. 登录项目，打开「工具连接」，选择只读或领取/交付权限。编辑者/负责人可接入自己的工具，只读成员只能查看。
2. 本机预览检测到Codex、WorkBuddy、Cursor或Claude Code配置目录时，点击「一键连接」。系统自动登记本人设备实例、生成项目凭据、备份并合并客户端配置，不用填写设备/实例名或复制Token。
3. 重新加载客户端的MCP连接或开启新会话，调用`whoami`核对身份，再`get_project`。网页会在短时状态检查中显示「凭据已验证」，表示该凭据有成功调用记录；客户端当前状态需在AI应用中核对。仅配置写入显示「待工具加载」。

## 服务器与其他设备

- 正式服务器不检查或写入云主机的个人AI配置。Cursor使用官方安装链接，需在Cursor中确认；安装链接通过本机`cursor://`传递项目配置，不把凭据放入WorkRoom的HTTP查询参数。
- Codex、WorkBuddy、Claude Code可下载单文件连接助手，在实际运行工具的电脑上打开。Windows为`.cmd`，Mac为`.command`，Linux为`.sh`。助手需要Python3.11及以上，不下载或启动模型、不替用户登录账号。Mac若未保留执行权限，用`sh Connect-WorkRoom-工具.command`运行。
- 没检测到本机工具时会提供下载助手；应先安装并打开一次对应AI工具。配置目录存在只是可配置的线索，不代表软件已运行或账号已登录。
- 助手按固定的用户配置路径写入：Codex `~/.codex/config.toml`、WorkBuddy `~/.workbuddy/mcp.json`、Cursor `~/.cursor/mcp.json`、Claude Code `~/.claude.json`。配置用`workroom-p项目-实例`独立名称，保留原`workroom`及其它服务；先备份，再原子替换，损坏/链接/冲突时停止。重连不创建同设备的重复实例。
- 下载文件包含当前项目的30天凭据，保存在本人设备，勿分享或提交Git。撤销连接会令凭据失效；原客户端条目可在对应工具中移除。

## 高级接入

其他设备的自定义名称、能力、手动配置以及Harness接入收在「高级接入」中。能力为用户声明，不因勾选就获得本机文件权限。每人管理自己的凭据；项目凭据有效30天，可撤销。

DeepSeek Harness本轮仍使用官方`dsh-mcp-client`配置条目，未冒充已有通用自动安装。合并到实际Cordis插件列表并保留其他条目；自定义客户端按其文档导入。手动模板默认折叠。

Claude配置使用`type: http`，WorkBuddy与Cursor使用`url/headers`，Harness使用`transport: streamable-http`和`serverName`；都指向`/mcp/`，不需要本机Python桥。WorkBuddy格式已对齐本机5.9.2自身UserMcpFile.toEntry写出的HTTP配置，不额外写streamableHttp类型。Codex使用`http_headers`。URL来自当前服务地址，本机预览的127.0.0.1仅同机可达，不能复制到另一台设备当作服务器。

本机已有配置的按钮为“更新本机配置”，只保存配置，不会反向重启AI应用。重复更新时复用同项目/用户/实例/权限的有效凭据；过期或明确撤销的凭据不复用，改变权限仍使旧权限失效。撤销授权仍可在“管理连接”执行。不要把网页更新配置当作客户端重连。

本机预览如将用户目录迁移到其他盘，可由所有者在`workroom/data/local-preview/client-config-homes.json`中显式声明各工具实际用户根目录，例如`{"workbuddy":"E:/Users/28369"}`，重启预览后生效。目录必须经本人核实；安装器仍拒绝其下的链接/多硬链接，不会自动跟随任意重定向。正式server不使用本机预览的这份文件。

项目授权使用限期Bearer令牌，不是Claude账号；本版没有MCP OAuth动态注册或外部账号托管。配置含私有凭据，不要提交到Git或公开聊天。网站不能直接修改用户电脑的客户端配置。

## 执行顺序

`whoami` → `get_inbox/next_task` → `get_task_context` → `claim_task` → 心跳/规则确认 → 执行 → `submit_result` → 独立复核 → 负责人验收。

严格任务的认领响应包含本次快照，交付按快照核对。外部工具只提交自己认领的任务，不能把任务直接改成done。`review_delivery`只记录独立意见，不代替人工验收。

## 支持范围

- HTTP MCP：无状态JSON响应，支持2025-03-26/2025-06-18/2025-11-25协商；GET无SSE时405，通知202；所有请求校验项目令牌、Origin和当前成员权限。
- 旧stdio桥保留，`mcp_server.py`、`remote_bridge.py`、`tool_schema.py`仍可用于需要桥接的环境；工具schema与HTTP共用同一份定义。
- MCP接入表示客户端能调用WorkRoom，不表示WorkRoom能反向唤醒任意GUI。无公开CLI/API的工具先走交互式领取，不冒充自动执行。
- 已用官方MCP Python SDK 1.30.0验证HTTP/HTTPS初始化、工具列表和身份调用。没有在本机安装、登录或调用真实Claude Code账号，也未消耗模型API。
- T062额外实测：浏览器点击Codex/WorkBuddy，在隔离用户目录写入真实配置，再通过HTTPS调用MCP并自动更新状态；Windows下载助手在第二个隔离用户目录实跑。未改开发者当前真实客户端配置，也未声称Mac或实际厂商账号已验收。

官方依据：[Claude Code MCP](https://code.claude.com/docs/en/mcp)、[Codex MCP](https://developers.openai.com/codex/mcp)、[Cursor MCP](https://cursor.com/docs/mcp)、[WorkBuddy连接器](https://open.workbuddy.cn/docs/connector)、[Harness官方MCP客户端](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md)、[MCP HTTP传输](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)、[官方Python SDK客户端](https://github.com/modelcontextprotocol/python-sdk/blob/v1.30.0/docs/client.md)。
