# 当前任务

## 最新快照（T009：本机工作区技术验收通过，待用户体验）
- 版本PLAN-r2 / RULES-r5。状态ACCEPTED_BY_CODEX_WAITING_USER_REVIEW；用户授权“开始第一步”的固定工作区闭环已完成，不自动推进下一业务阶段。
- 访问http://127.0.0.1:8000/workspace/；服务当前运行于Codex exec session 75882，通过Run-Backend.cmd启动，仅127.0.0.1。再次启动前先确认8000端口，不重复启动。
- 功能：授权固定.tools/workspaces/demo→列出/读取UTF8文本→新建不覆盖→撤销；浏览器会话隔离，保留CSRF/no-store/自动转义。最大64KiB，只支持根内普通.txt/.md，不支持任意目录/命令执行。
- 验证：pytest 69 passed/1 skipped；跳过真实文件symlink因WinError1314。真实junction（含父目录）、硬链接、模拟symlink拒绝、越界/覆盖/编码/大小测试通过；ruff backend/tools与Django check通过。
- 浏览器：真实授权→读取→创建→读取→重名拒绝→越界/CSRF拒绝→跨浏览器拒绝→撤销拒绝均通过；桌面和390px移动页面无横向溢出。示例文件留在demo，测试会话已撤销。
- WorkBuddy完成T009A/B；B在最终回报阶段触发300秒通道超时，报告与源码已落盘，原node进程39980已结束后由Codex复核。未重复派活。
- Codex补正：文件名保留原输入并拒绝尾部空格；创建成功提示只显示一次。先补2项失败回归再修复，测试全通过（除明确权限跳过项）。
- 边界：不是OS沙箱，未防本机恶意进程并发替换；未完成成员账号、任意文件夹选择或AI执行器。
- 证据：tasks/acceptance/T009.md，tasks/reports/T009-browser.json和T009-{desktop,mobile}.png；服务代码backend/workspaces/。
- 下一步：用户体验此页并反馈，确认本步后再收敛后续规格；不自动进入注册/项目/团队/Agent阶段。
## 上一快照（T009B派发：会话授权与页面）
- 版本PLAN-r2 / RULES-r5，用户授权T009闭环。T009A已完成文件服务：54 passed/1 skipped；跳过的是本机无权限创建文件符号链接，真实硬链接与目录junction已实测，不能称该跳过用例已通过。
- 当前任务T009B：APPROVED。WorkBuddy接入Django会话与表单页面，补父目录junction拒绝及符号链接属性的独立分支验证；Codex后续浏览器验收。
- 测试目录仅.tools/workspaces/demo；授权前不初始化，GET不写文件，POST保留CSRF；其它浏览器无授权、撤销后拒绝文件访问。
- 范围、状态仍以tasks/specs/T009-workspace.md为准；T009完成交用户体验，不自动进入账号/项目/Agent等阶段。
## 上一快照（T009派发：本地工作区最小闭环）
- 版本：PLAN-r2 / RULES-r5；基线53220eb。用户“开始第一步”明确授权本项，不等于批准所有业务阶段。
- 当前任务T009A：APPROVED。WorkBuddy实现可信根目录文件服务与单测；随后T009B接Django会话授权、页面和验收。
- 规格tasks/specs/T009-workspace.md。固定项目.tools/workspaces/demo演示目录；不读取其它用户文件，不接AI/命令执行，不新增依赖。
- 基线工作区干净，派活前确认无其它任务执行；只有WorkBuddy写实现，Codex复核。
- 骨架已验收，T008证据沿用。完成本阶段后给用户体验，不自动跨到账号/项目/团队阶段。
## 上一快照（T008A：后端骨架已完成，待Codex验收）
- 版本：PLAN-r2 / RULES-r4；授权来源为用户直接要求开Django项目（T008A APPROVED）。
- 状态：DONE_PENDING_CODEX_REVIEW；仅 WorkBuddy 单执行者，未派 agent、未联网、未装依赖。
- 产物：`backend/`（config + core，Django 5.2.18）、`pytest.ini`、`backend/core/tests.py`（3 契约测试）、首页模板、`.gitignore` 增 `*.sqlite3`。
- 接口：GET `/api/health/` → `{"status":"ok","service":"agentworkspace"}`，POST 405；`/` 显示“AI协作工作台 / Django服务已启动”及健康链接。
- 密钥：优先 `DJANGO_SECRET_KEY`，否则首次生成 `.tools/django-secret-key`（已忽略）；源码无密钥。SQLite 指向 `.tools/dev.sqlite3`，尚未创建。
- 验证：pytest RED 3 failed(404, EXIT=1) → GREEN 3 passed(EXIT=0)；`manage.py check` 0 issues(EXIT=0)；`ruff check backend` 修 3 个真实问题后 All checks passed(EXIT=0)。证据：`tasks/logs/T008A.log`、`tasks/reports/T008A.json`。
- 未做：迁移、runserver/HTTP 实机、Run-Backend.cmd、MySQL、管理员账号、业务模型与 AI 调用。
- 下一步：Codex 验收后派 T008B（启动入口+迁移+实机 HTTP 验证）。

## 上一快照（T008 派发时：Django骨架）
- 版本：PLAN-r2 / RULES-r4。用户直接授权本项，不代表批准全部业务阶段。
- 当前任务：T008A，APPROVED。WorkBuddy创建 backend Django骨架、首页/健康接口和必要测试；Codex验收后补启动入口与迁移验证。
- 规格：tasks/specs/T008-bootstrap.md。允许新增backend/、pytest.ini及必要忽略规则；不覆盖既有协作产物，不联网下载、不做业务功能、不读取密钥。
- 默认本机开发SQLite在.tools/，MySQL登录未验证；产品运行时用户自行连接AI。
- 开工前确认无其它执行任务；同一时刻一个写入者。完成本项后不自动进入业务阶段。

## 上轮准备验收快照
### 原快照（T007：Codex准备验收与上下文交接）
- 版本：`PLAN-r2`（DRAFT_WAITING_USER_REVIEW）/ `RULES-r3`。
- 产品：AI协作工作台，统一任务、上下文、成员进度与验收；外部工具按权限领取/回报。接入设计见 `docs/AI_INTEGRATION.md`，产品接入尚未实现。
- 用户已有AI API key，将在应用运行时自行连接；开发阶段无需索取密钥。
- 开工工具：隔离Python/Django/测试工具、Node/pnpm/Git、两端技能、原生单专家已准备并复核。入口 `START_HERE.md`，结果 `tasks/READINESS.md` / `tasks/reports/preflight.json`。
- MySQL：服务与3306通过，登录未验证、未创建业务库；本机检查入口 Configure-MySQL.cmd（隐藏输入、不存密码）。
- GUI：专家包已注册且validator通过；GUI显示及A2A自动同步原生界面未实测。
- 业务阶段完成0个，P0待用户审阅；不自动启动业务或跨阶段。
- 当前活跃执行任务：无。T006调用超时后对应进程树25796已停止，产物由Codex复核；不重复派发。
- 下一步：在此目录新聊天先读AGENTS与本快照；运行Check-Ready，审阅P0，锁定首个小规格后再派WorkBuddy。
## 上一快照（T005，2026-10-22）
- 专家包 `agentworkspace-fullstack-executor` validate/register 均 0；`experts/ROLES.md` 与来源副本已建。
- 未验证：GUI 是否可见（需重启客户端）；未添加云端项目、未改 `experts.json`。

## T000 协作资料初始化
- 状态：ACCEPTED_BY_CODEX
- 范围：仅 3 个文档（`AGENTS.md`、`PROJECT.md`、`tasks/current.md`）。
- 未启动：业务代码、环境安装、数据库、打包、联网操作。

### 实际产物
- `D:\Users\28369\Desktop\AgentWorkspace\AGENTS.md`
- `D:\Users\28369\Desktop\AgentWorkspace\PROJECT.md`
- `D:\Users\28369\Desktop\AgentWorkspace\tasks\current.md`

### 实际执行的检查
- 创建前确认 `AgentWorkspace` 不存在，无同名文件可覆盖；目录内仅有本 3 个文件。
- WorkBuddy 创建时的行数：`AGENTS.md` 40、`PROJECT.md` 32、`tasks/current.md` 30，合计 102 行；之后 Codex 回填了验收记录。
- 3 文件均通过 `iconv -f UTF-8 -t UTF-8` 校验。
- 未运行：业务测试、依赖安装、数据库、打包、联网，均未启动；未初始化 git。

### Codex 验收（2026-10-22）
- 已独立读取实际 3 文件，并用严格 UTF-8 解码检查；目录文件清单与范围一致。
- 已核对分工、短任务回报、单写入者、验收规则；已区分用户要求与未锁定建议。
- 本轮 A2A 未提供可核验 token 用量，不把返回字符数当作 token 数，也不宣称节省比例。
- T000 验收通过；下一任务尚未派发。

### 下次派活模板（留空占位）
- 任务 ID：
- 目标：
- 根目录与基线：
- 必读文件与按需读取文件：
- 允许修改范围：
- 接口与不可变约束：
- 验收与验证命令：
- 停止或回报条件：

### 下一步
当时计划收敛首个技术验证范围与未定选型后下达 T001；现已完成本轮 T001 文档任务，见下。

## T001 阶段计划与协作规则升级
- 状态：`ACCEPTED_BY_CODEX`
- A2A 任务 ID：`task-3615a2377f904cdebae9f214faaa0364`
- 基线：`PLAN-r1`、`RULES-r1`；业务代码、服务、依赖均未变动。

### 范围与实际产物
- 修改：`AGENTS.md`（新增阶段/修订号、停止通道、原生会话追加要求、进度可见性）、`PROJECT.md`（追加分阶段与可见执行要求）、本文件。
- 新建：`CONSTRAINTS.md`（`RULES-r1`）、`tasks/plan.md`（`PLAN-r1`）、`tasks/visibility.md`。
- 完成：P0–P10 阶段表与能力依赖图；约束条目 C1–C12；可见性事实与限制。
- 未做：无业务代码、无新服务、无依赖安装、无对外消息、未改 A2A-Hub、未启动 P0/P1。

### 进度
- 业务阶段完成：0 个。
- P0：`WAITING_USER_REVIEW`。
- 执行中业务任务：无。
- 下一步：等用户审阅路线；之后才准备 P0 验证任务。

### Codex 验收
- 已读取阶段计划、约束、可见性说明及修改段，并独立严格 UTF-8 解码全部 6 个文件。
- 已修正阶段依赖和可见性表述，保留未验证事项；阶段草案未获得用户批准，不能据此启动业务实现。
- 本轮只更新协作与规划文档；未安装依赖、启动服务或修改 A2A-Hub。

## T003 依赖安装（可观测后台）
- 状态：`TIMEOUT_PARTIAL`（A2A 300s 超时，不是安装失败）
- 实际：uv 0.12.10 经 `tools/install-core.ps1` 在隐藏独立进程中安装核心依赖；wrapper 首轮因日志句柄冲突 FAILED 后重启。
- 产物：`tasks/logs/T003-core.log`、`T003-core.err.log`、`T003-core.ps1.log`、`tasks/reports/install-core.json`、`requirements-dev.lock`。
- 已知瑕疵：`install-core.json` 记 `status=FAILED`、`exit_code=null`，属 PowerShell `Start-Process -PassThru` 重定向输出的误判（uv 实际退出 0）；历史报告保留不改，以 `env-verify.json` 为更正状态。

## T004 环境复核 + 官方安装器尝试
- 状态：`TIMEOUT_PARTIAL`
- 环境复核：`tasks/reports/env-verify.json` 的 `status=SUCCESS`、`reinstall_performed=false`；django 5.2.18 / pytest 9.1.1 / pytest-django 4.14.0 / ruff 0.17.1 / mysqlclient 2.3.0 / playwright 1.64.0 均可 import；lock 18 行。
- 官方安装器：GitHub 整库下载未设超时，工具侧超时；Codex 已确认并终止该唯一 CLI 进程树 21352 及其下载子进程，桌面 App 未受影响。
- 未做：无新库、无 DB、无 Chromium 下载、无业务代码。

## T004R2 本地恢复安装（本轮）
- 状态：`DONE_LOCAL_ONLY`
- 前置：确认四个目标路径均不存在后才复制，未覆盖已有文件；本轮零网络请求，未重跑官方安装器。
- 复制：`.tools/source-cache` → `C:\Users\28369\.codex\skills`、`C:\Users\28369\.workbuddy\skills`，各含 `webapp-testing`（6 文件）与 `python-testing-patterns`（3 文件 + MIT `LICENSE`）。
- 校验：4 份 `SKILL.md` 严格 UTF-8、YAML 头正常无 BOM；源与两份副本 SHA256 全一致；引用文件齐全；`with_server.py --help` 退出 0，未启动服务器。
- 记录：`tasks/tooling-sources.json`（固定 ref、URL、SHA256、安装路径、许可证）。
- 未做：无外网下载、无服务启动、无 DB、无业务代码。



## T006 开发入口与环境预检
- 状态：TIMEOUT_PARTIAL，实际文件已由Codex接管复核。
- WorkBuddy生成开发终端、预检、浏览器smoke、MySQL本机登录检查、配置示例和Windows入口，归档重复状态文件。
- A2A工具约300秒超时；仅对应CLI进程树25796停止，未停止桌面App或MySQL。
- 无业务代码、无数据库创建、无模型调用。最终实际结果见T007。

## T007 Codex复核与本轮准备收口
- 状态：ACCEPTED_PREPARATION；授权来源为用户要求查GitHub安装技能/专家并完成开工准备，以及本轮上下文/工具接入/API/产品定位补充。
- 修正入口指向唯一current、精简专家授权规则以尊重已有授权；补齐运行时自接API与进度证据要求。
- 精确还原上游源文件，9项Git blob SHA1核对通过，刷新现有SHA256记录；保留历史日志中的旧值。
- 修正预检真实调用本机validator、按实际修订号读取、Git配置忽略判定；收窄异常捕获，lint无抑制。
- 已验证：开发入口版本、Check-Ready、浏览器操作、Django临时配置、技能/专家、lint/编译、MySQL拒绝非本机目标。MySQL真实登录未运行，产品模型/业务/安装包测试未运行。
- 所有后续业务阶段仍需按用户要求验收；准备完成不等于产品完成。


## T008 Codex最终验收
- 接受WorkBuddy的T008A/T008B产物，独立检查源码与接口契约；修正启动器runserver失败后返回非零。
- 从真实Run-Backend.cmd在上层工作目录启动，复核首页/health 200、POST405、Host限制400；Chrome完成页面/健康链接导航与截图，无页面脚本异常。
- 独立pytest4项、ruff backend/tools、Django check均通过；测试服务器进程树已停止且8000关闭。
- T008B曾把.cmd误传给Python lint产生语法诊断；.cmd以实际Windows启动验证，Python源以ruff检查，未降低规则。
- 未验证手动Ctrl+C交互；没有MySQL、API模型、业务流程或安装包验收。


## T009 Codex验收收口
- 审阅服务、路径边界、会话校验、CSRF与模板转义；补正2个HTTP/反馈缺口并验证。
- 浏览器第一轮因测试选择器同时匹配region和textbox而中断；更正为textbox角色后全流程通过，未降低断言。失败记录保留T009-browser-attempt1.json。
- 当前服务保留运行供用户体验；服务器属于exec session75882，后续停止通过该会话或核对任务进程树，不杀其它服务。
