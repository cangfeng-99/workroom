# T013：工作区授权与项目关联状态说明

2026-10-23，PLAN-r5 / RULES-r8，基线7de132a。P2验收修复，不推进P3。用户截图：独立`/workspace/`已授权`D:\`，项目“开发”仍显示“尚未关联文件夹”。这是不同上下文的状态，当前入口与文案未讲清，也缺少列表中的关联操作。

## 目标与边界

- 独立工作区明确标注当前授权用于独立工作区；到项目使用需明确关联。不要再让用户把“目录已授权”和“项目已关联”当成同一个状态。
- 项目列表展示本次有效文件夹授权的位置与归属，项目行同时展示关联位置与该项目的文件访问状态；有当前有效授权时为尚未关联的项目提供POST“关联到此项目”，复用既有owner/CSRF保护的关联接口，不在GET或仅查看列表时自动关联。
- 项目详情明确展示本项目“已授权，可读写”或“尚未授权”等状态。只有user、project_id、目录位置均匹配既有工作区逻辑才显示已授权；独立授权、另一个项目授权、已改变目录的旧授权不能误标已授权。
- 已关联项目继续保留既有明确关联/打开流程，不自动换目录。没有可用授权时显示选择授权入口。独立页若持有项目授权，解释此页上下文不同并引导从项目进入，不能把项目权限扩大到独立页。
- 权限判断应复用同一个现有语义：可将workspaces.views的_context_grant与_same_path最小迁移到grants模块供两边使用，不写第二套近似判断、不新增权限。目录关联仍显式POST并轮换grant_id，旧页面保存仍拒绝；模型、迁移、运行库、真实用户数据、原文件边界均不改。
- 展示路径/项目名继续自动转义；移动端无横向溢出；不新增依赖、前端框架或后台任务。

## 分工与允许范围

Codex写规格与复核；WorkBuddy唯一实现者，不派其它agent。工作根D:\Users\28369\Desktop\AgentWorkspace。允许改backend/projects/views.py、templates/projects/{list,detail,base}.html、tests.py，以及backend/workspaces/grants.py、views.py、templates/workspaces/workspace.html和必要回归；仅为本修复，禁止顺手重构其它功能。任务记录tasks/current.md与tasks/logs/T013.log、tasks/reports/T013.md。

先读AGENTS.md、current最新快照、本规格与相关源码；技能按debugging-and-error-recovery、incremental-implementation、frontend-ui-engineering、test-driven-development、security-and-hardening应用。专家只按需读取ROLES对应相关片段，不照抄其中框架/模型选型。

## 验证与停止条件

1. 先写能失败的针对性回归：先创建未关联项目，再授权独立目录，项目列表有目录/明确关联按钮但项目仍未获权限；显式关联后项目详情/列表与项目工作区都显示一致的已授权状态。
2. GET列表/详情不改project.workspace_path或grant；同目录不同项目、换路径旧grant、跨账号、撤销/重新登录等不能误显示已授权；原旧页写入拒绝断言保留。
3. 先focused RED→修复→GREEN；全量.venv\Scripts\python.exe -m pytest -q、ruff check backend tools、manage.py check、git diff --check。不得削弱/删除断言或改skip/安全限制以过检查。
4. 记录真实命令/退出码与结果。WorkBuddy不重启或新起8000、不执行实际迁移、不读取真实用户数据库/凭据、不建真实账号、不commit；完成后停止写入并回报。Codex独立审阅并用隔离临时账号/目录在Chrome实测，保留用户admin及“开发”项目原样。
5. 最终目标是用户刷新项目列表能看到当前已授权目录，明确点关联后进入本项目工作区读写。P2仍待用户整体体验确认。
