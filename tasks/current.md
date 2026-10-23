# 当前任务

## 最新快照（T016：项目协作画布手动闭环已技术验收，待用户体验）
- PLAN-r7 / RULES-r10。T016A后端提交7951410；T016B真实界面完成并通过Codex验收。用户本轮明确纠正T015界面方向，未将旧界面记为用户认可；本轮等用户体验，不自动推进邀请/AI执行。
- 新建项目直达board；左侧真实项目导航与工作空间，中间日期标尺/多级任务树/父子SVG连线，右侧任务详情/团队。真实保存成员、分工角色、任务内容/父级/日期/负责人/状态，支持继续拆分子任务、搜索、折叠/展开、缩放、重置与列表视图。节点最小260px/88px并增大字号；横向位置表示开始日期，卡片内显示时间段。
- 真人通过现有活跃账号添加；角色可修改；AI是明确“未连接”的角色条目，添加不调用任何工具/API。owner管理结构与成员，真人成员只读协作数据并更新本人被分配任务状态；不获得owner本机路径或文件访问。邀请链接、模型自动拆分、Codex/WorkBuddy连接/执行仍待后续规格。
- 增量迁移已在备份后应用，原账号/项目记录逐项一致，原项目补owner成员；未重置库或覆盖用户文件。原文件授权/保存继续可用，新画布选择文件夹后仍需明确POST授权并设为工作空间。
- WorkBuddy完成主要A/B源码但两次通道300秒超时均无最终简报。Codex分别核对并停止唯一node23876(A)/26236(B)任务树后接管，未并发写入或重复派发。B复核后修复顶部团队按钮、错误表单自动打开、picker加载时输入保护、当前项目文件入口，并补显著新建任务入口和节点可读性；以Codex实测为证据。
- 最终pytest199 passed/1 skipped/3 subtests passed（33.45秒）；原skip为Windows symlink权限。ruff/check/Node语法、迁移一致性通过。权限过滤在测试进程内去掉的变异被陌生账号用例捕获，源码未改。Chrome10组真实操作通过，包括三级五任务四连线、成员/角色、错误保留输入、状态刷新持久化、成员边界、原文件保存、无JS/减弱动效；脚本异常0，390/768/1440无页面横向溢出，桌面和窄屏截图检查。
- 失败证据保留：首次新静态目录被开发服务finder旧缓存遗漏404，重载后CSS/JS200；第二次发现顶部团队按钮未绑定并修复；第三次是QA空状态文案不匹配已更正；第四次发现任务新建入口只在隐藏详情页，补画布工具栏入口。最终含日期倒置400自动打开表单/保留输入的完整复验通过，无降低产品断言。Kaspersky注入外网在隔离会话阻断并单列，未知来源仍触发失败。
- 临时QA账号/项目/任务已按唯一名称精确清理，未改admin/开发项目内容。证据tasks/acceptance/T016.md、tasks/reports/T016-browser.json与T016-{empty,canvas}-{1440,768,390}.png。8000继续运行，exec session75829，最后复核worker24724（自动重载会变化），仅127.0.0.1。
- 用户入口http://127.0.0.1:8000/projects/，点击项目名称进入画布；已有项目保留，空画布不种入示例任务。下一步是体验当前手动闭环；认可后准备邀请链接与AI连接的下一项规格。

## 上一快照（T016：项目协作画布方向修正与手动闭环）
- PLAN-r7 / RULES-r10，基线83d1a0b，开工git干净。用户明确表示T015界面不符合预期，要求项目→工作空间→真人/AI角色团队→多级任务与时间线节点；不记为T015视觉认可。
- 规格tasks/specs/T016-project-canvas.md。T016A WorkBuddy实现成员/任务数据、表单、权限与画布上下文契约；T016B再实现真实画布布局与交互。Codex单独更新规格、复核与浏览器验收，单写入者，不派额外agent。
- 当前运行8000继续使用，增量迁移由Codex检查并备份后应用，不重置开发库、不改用户已有项目名称/路径/文件；旧文件权限与owner边界保持。
- 本轮真人使用现有账号添加，邀请链接仍为后续；AI为可分配任务的角色条目，明确尚未连接/执行。项目成员可读协作数据并更新本人被分配任务的状态，只有项目所有者管理团队和任务结构，不自动获得本机文件访问。
- T016A已技术验收，详情tasks/acceptance/T016A.md。WorkBuddy32项专项完成落盘但300秒通道超时无最终简报，Codex核对停止唯一node23876任务树后接管，补画布GET方法限制与长用户名兼容（RED→GREEN）。最终199 passed/1 skipped/3 subtests passed，ruff/check/makemigrations检查通过；未并发写入或重复派发。
- 0002已实际增量迁移通过，前后原账号/项目记录逐项一致，原项目owner成员已补齐。当前8000自动重载，复核worker2500；现有文件服务继续沿用。
- T016A保存本地提交7951410，34项专项通过；T016B现在APPROVED。WorkBuddy仅改画布模板/静态资源、core/base的sidebar/extra_head块和项目入口，不改A后端接口或已有文件协议；Codex期间只读，B结束后独立浏览器验收。不把临时基本表单页当作最终效果。

## 上一快照（T015：真实页面统一界面已技术验收，待用户体验）
- PLAN-r6 / RULES-r9，状态ACCEPTED_BY_CODEX_WAITING_USER_REVIEW。用户“继续”授权的现有页面迁移完成，P2整体仍待用户确认，P3未开始。
- 首页、登录/注册、项目列表/创建/详情、真实文件工作区统一core/base与本地app.css/js；深色导航、统一卡片/表单/提示，Tabler1.7.0+Motion14.6.0固定本地文件及许可证/哈希。新增本人项目名称/说明搜索、授权状态筛选、重置及减弱动效。数据来自现有Django后端，未使用样稿演示数据。
- 后端Python、模型/迁移/依赖和目录协议无改动；文件夹picker脚本与基线逐字一致。保留POST关联/登出、owner/CSRF、独立与项目授权隔离、冲突保留编辑、原位置保存和新建规则，未修改用户admin/开发项目。
- WorkBuddy T015通道300秒超时，模板/样式已落盘但未取得最终报告。Codex核对唯一node7624任务树（parent7332，16:04:12创建，命令含唯一任务T015）并停止，确认后接手，未重复派发或并发写入。Codex补齐说明搜索、计数播报和授权文案，以下检查均由Codex实跑。
- 最终pytest165 passed/1 skipped/3 subtests passed（26.91秒）；原skip为Windows文件symlink权限限制。ruff backend/tools、Django check、Node语法通过。Chrome真实业务9组、描述/状态/重置/转义专项通过，反转筛选条件的浏览器内存变异被断言捕获，源码未改；390/768/1440无横向溢出，截图视觉检查通过，脚本异常/资源失败均0。
- 浏览器前两轮失败记录保留：第一轮选择器错误地匹配两个不同状态徽标；第二轮重开picker后未等初始目录加载便填路径。限定徽标语义并等待列表就绪后全流程通过，未降低产品断言。外部网络全阻断，已知Kaspersky注入域单列，未知域仍使检查失败；不改安全软件。
- 临时QA账号与其项目已精确清理；证据tasks/acceptance/T015.md、tasks/reports/T015-browser.json、T015-filter.json与截图。服务exec session75829、复核PID24500，仅127.0.0.1:8000；本轮启动时原8000未监听，无重置/迁移。真实入口http://127.0.0.1:8000/projects/，8030仍是独立旧样稿地址。
- 下一步：用户在真实项目页体验新界面、关联与项目内读写；确认当前阶段后再准备P3团队邀请规格，不自动跨阶段。

## 上一快照（T015：将样稿风格接入真实业务页面）
- PLAN-r6 / RULES-r9，状态APPROVED，基线fabe03f，开工git干净，无活跃WB任务。用户连续“继续”授权本轮已有页面统一UI，不进入P3。
- 规格tasks/specs/T015-real-ui.md：共享core/base+本地app.css/js与Tabler/Motion；迁移账号/项目/首页，再迁移实际workspace，保留所有真实表单/CSRF/owner/授权和文件边界，不注入样稿数据。
- WorkBuddy唯一写业务模板/静态资源与必要检查；Codex规划/独立复核和临时账号浏览器验收。当前8000未监听，待资源/模板完成后由Codex启动；不重置DB、不覆盖用户项目。
- 下一步：实现后核验真实创建/关联/读写、失败恢复、身份隔离及390/768/1440布局，再交用户体验。

## 上一快照（T014：开源调研与交互样稿已完成，待视觉反馈）
- PLAN-r5 / RULES-r8，状态RESEARCH_AND_PREVIEW_DONE_WAITING_USER_REVIEW。已响应GitHub同类学习与开源界面/动效要求；P2仍待整体验收，不自动进入P3，正式前端/桌面选型未锁定。
- 交付docs/OPEN_SOURCE_RESEARCH.md、25份来源记录docs/OPEN_SOURCE_SOURCES.json；已查看Plane模型、OpenHands Agent Canvas架构/ACP适配、Vibe Kanban执行器。记录Vibe Kanban原公司关闭转社区维护、各许可差异；未安装或运行这些参考应用。
- docs/previews/workbench.html为隔离样稿：Tabler1.7.0 CSS+Motion14.6.0 JS本地固定文件/许可证/SHA256；可搜索筛选、详情dialog、内存新建、减弱动效、规划入口反馈。显著说明示例数据，不接真实账号/文件/AI，不改backend或用户数据。
- WorkBuddy T014A只读审计完成；T014B三文件已落盘但通道300秒超时未取得最终简报。Codex核对并停止唯一node18152任务树后接手，没有并发写入或重复派发。补正一次一个授权及已关联但未授权的样稿状态。
- Chrome11组通过：交互/输入安全、焦点ESC、1440/768/390无横向溢出、系统减弱动效、动画库失败与JS禁用降级、资源哈希。脚本错误0，截图视觉检查通过。首轮受本机Kaspersky浏览器注入影响的网络断言失败保留；复测阻断外部网络并单列已知环境注入域，未改安全软件设置，应用没有外部资源依赖。
- Node JS语法、diff check通过；backend无diff，沿用T013业务测试基线，本轮没有重跑。详情tasks/acceptance/T014.md与tasks/reports/T014-browser.json。
- 样稿http://127.0.0.1:8030/workbench.html，专用静态服务exec session89876、PID36572，仅127.0.0.1、目录docs/previews；8000原Django继续运行。侧栏打开返回queued，不视为用户已看到。
- 下一候选：根据视觉反馈把这套组件接入当前项目列表/详情，然后迁移工作区；新业务功能继续按原阶段逐个规格和验收。未把样稿当作已接真实功能。

## 上一快照（T014：GitHub参考调研与界面样稿）
- PLAN-r5 / RULES-r8，基线916035d。用户授权学习同类GitHub项目与开源界面/动效；本轮交付可追溯参考、开发方案与隔离的可交互样稿，不视为P2整体认可或P3开工。
- Codex已查README/架构/许可证：Plane项目管理、OpenHands当前Agent Canvas外部Agent/本地后端边界、Vibe Kanban任务执行审查；后者宣布转社区维护。UI候选Tabler+Motion（MIT）；React Bits有附加条款、Animate.css当前Hippocratic，不能统称MIT。
- T014A WorkBuddy只读审计已完成且未写文件；现有四套独立shell，建议共享core模板/静态目录，保留表单与授权边界。
- T014B仅在docs/previews/实现界面样稿及交互，示例数据明确标注；Tabler1.7.0 CSS与Motion14.6.0 JS本地固定副本，不改真实业务/用户数据/最终框架选型。规格tasks/specs/T014-open-source-ui.md。
- 下一步：WorkBuddy实现样稿；Codex整理调研与组件/功能开发顺序，并浏览器验收。用户仍可继续在8000体验现有P2。

## 上一快照（T013：授权与项目关联状态修复已技术验收，待用户体验）
- PLAN-r5 / RULES-r8，状态ACCEPTED_BY_CODEX_WAITING_USER_REVIEW；仍为P2验收修复，不推进P3。注册登录此前已获用户确认。
- 用户截图：独立工作区D:\已授权，但“开发”项目尚未关联。已补当前授权目录/归属、项目关联位置与访问状态、列表显式POST“关联到此项目”；关联后从项目进入工作区。独立入口解释项目授权范围，不自动借用权限。
- projects/workspaces共用grants.context_grant（用户、project_id、目录均匹配）；GET不自动关联，关联继续owner/CSRF与grant_id轮换；未改模型/迁移/依赖/文件边界，未改用户账号或“开发”项目数据。
- WorkBuddy原任务自然结束，node32784已退出，报告落盘。通道300秒超时后未重复派发，确认结束后Codex接管；原报告初步163 passed/1 skipped。
- Codex补正列表归属模板变量、失效项目授权提示、旧会话异常项目ID保护，并补回归。RED复现→focused31 passed/3 subtests passed；最终pytest165 passed/1 skipped/3 subtests passed，ruff/check/diff check通过。唯一skip仍为既有Windows文件symlink权限不足。
- Chrome临时账号/目录8组实测通过：关联前后状态、POST关联、实际保存、同路径第二项目不共享、独立页范围说明、撤销/重授权、重登录需授权；脚本错误0，1280/390px截图检查且无横向溢出。临时测试账号与项目已精确清理。
- 服务沿用Run-Backend.cmd exec session6238与自动重载；复核时worker13544，127.0.0.1:8000，无重复启动。验收详情tasks/acceptance/T013.md，报告tasks/reports/T013-browser.json与截图。
- 下一步：用户刷新/projects/，在“开发”行点“关联到此项目”，确认“已授权，可读写”，再从该项目打开工作区编辑保存；P2整体仍等用户体验确认。

## 上一快照（T013完成：授权与项目关联状态/入口已修复，待Codex复核）
- PLAN-r5 / RULES-r8，基线7de132a，状态DONE_PENDING_CODEX_REVIEW；仅WorkBuddy写业务文件，未派agent/广播/联网/装依赖/起服务/迁移/commit，Codex两处文档改动保留。
- 按tasks/specs/T013-workspace-status.md实现：`workspaces.grants`新增`same_path`与`context_grant`（用户+project_id+目录位置三重匹配，独立上下文只认空project_id），projects/workspaces两边复用，未新增权限。
- 项目列表显示本次登录授权目录及归属（独立工作区/某项目）；项目行显示关联位置与文件访问状态（已授权，可读写/尚未授权）；未关联或同路径项目给显式POST“关联到此项目”，复用既有owner+CSRF接口并轮换grant_id；GET不写库不改grant。
- 项目详情明确“已授权，可读写/尚未授权”，区分关联位置与访问权限；独立授权、其它项目授权、换路径旧授权均不误标；无可用授权时给项目工作区授权入口。
- 独立工作区标注授权仅限独立工作区、不会自动关联；持有项目授权时说明属于该项目并引导从项目进入，仍拒绝写入（403）。
- 验证：新增7项回归，RED 7 failed/22 passed EXIT=1 → focused GREEN 29 passed；全量pytest 163 passed/1 skipped；ruff、manage.py check、git diff --check均通过。业务约+212/-49行（测试另+106）。
- 未做：未重启8000、未迁移、未读真实用户数据/凭据、未建真实账号；未做真实Chrome与390px实测，留Codex隔离账号/目录验收，保留用户admin与“开发”项目。
- 下一步：Codex只读复核并按规格浏览器验收；用户刷新项目列表即可看到当前授权目录，点“关联到此项目”后进入项目工作区读写。P2仍待用户整体确认，不自动进入P3。

## 上一快照（T013派发：修复授权与项目关联状态不清楚）
- PLAN-r5 / RULES-r8，状态APPROVED，基线7de132a，开工git干净，无活跃WorkBuddy CLI任务。仍为P2修复，不推进P3。
- 用户实测注册登录成功；本次截图中独立工作区D:\已授权，“开发”项目尚未关联。原因是权限与项目关联分开，但列表缺少当前授权提示与关联入口。
- 按tasks/specs/T013-workspace-status.md：统一状态判断，项目列表显示当前目录和明确POST关联入口，详情标明本项目是否已获权限，独立工作区解释授权范围；不自动关联/放宽权限，不改用户数据。
- 由WorkBuddy唯一写业务文件，Codex只读复核与浏览器隔离验收；现8000进程35736继续运行，不重复启动，不派其它agent。
- 完成后交用户刷新体验，整体P2仍待用户确认。

## 上一快照（T012：P2账号与项目技术验收通过，待用户体验）
- PLAN-r5 / RULES-r8，状态ACCEPTED_BY_CODEX_WAITING_USER_REVIEW；用户授权的A+B完成，P1原流程保留并纳入登录门禁；不自动进入P3团队/任务/AI。
- 用户体验进展：2026-10-23用户确认“注册登录成功”，注册/登录已通过用户验证；项目创建、文件夹关联及项目内读写仍待用户确认，整体P2状态不变。
- 入口http://127.0.0.1:8000/projects/，首次到/accounts/signup/注册，注册/登录成功进本人项目列表；POST退出。无预置用户/管理员，真实账号由用户自行注册。
- 功能：本人项目创建/列表/详情、关联当前明确授权的本机目录、打开项目上下文工作区、子目录读写/新建/撤销。模型保存路径，重新登录项目与路径保留，但必须再次授权文件访问。
- 安全：owner过滤+user_id/project_id grant；登录/退出清旧授权，项目/目录改变拒绝旧grant，保存/新建/撤销与导航保留项目。匿名文件页跳登录，目录API401，CSRF/no-store/自动转义与P1文件边界保留；health公开只读。
- WorkBuddy T012A完成回报且已提交c598188；B通道300秒超时，Codex核对并停止唯一node11920任务树后接管，没有并发写入/重复派发；B未取得的最终回报不作为验证证据。
- Codex补正：异常项目query返回404且无文件访问；补跨项目旧页POST/改关联路径旧grant回归与普通注册权限断言；旧测试统一改从grants模块引用常量，未删断言；纯force_login权限fixture去除无关密码哈希，真实注册登录哈希测试保留。生成迁移加ClassVar注解，无lint抑制。
- 数据：原SQLite库已备份到.tools/backups，projects.0001_initial仅创建Project表，实际增量迁移OK，无重置；最终makemigrations检查无差异。
- 最终验证：pytest156 passed/1 skipped（既有file symlink权限跳过），ruff backend/tools、Django check、diff check通过。移除owner过滤的内存变异被回归捕获，实际源码未改。
- Chrome实测注册登录、项目创建/关联/原位置保存、跨账号404、项目切换拒绝、POST退出、服务重启后账号/两个项目仍在、重登录需再授权、拒绝外站next及撤销退出均通过；页面脚本错误0，390px无横向溢出。测试账号和其项目已精确清理，未留演示凭据。
- 当前服务：Run-Backend.cmd exec session6238，仅127.0.0.1:8000，原19518已Ctrl+C结束；不要重复启动。验收证据tasks/acceptance/T012.md与tasks/reports/T012-browser.json/截图；两个QA助手失败已更正后全流程通过。
- 下一步：用户继续创建项目、关联已授权文件夹，并在项目工作区编辑保存文件；用户认可本阶段后再准备团队与邀请的下一规格。当前仍本机开发版，数据库/桌面最终选型、远程文件访问、AI执行器尚未实现。

## 上一快照（T012A已复核，T012B项目闭环派发）
- PLAN-r5 / RULES-r8。T012A ACCEPTED_BY_CODEX：注册/登录/POST退出与账号归属授权代码已独立审阅，134 passed/1 skipped，ruff/check通过。浏览器完整验收留到B集成后一次完成。
- T012B APPROVED：WorkBuddy新增本人Project与增量迁移、创建/列表/详情、关联当前授权文件夹、project上下文工作区。规格T012-accounts-projects.md的B段；只一个写入者，不派额外agent。
- 仅B范围及必要accounts测试默认登录重定向联动；当前服务继续运行，B不应用真实迁移/不重启。完成后Codex审阅迁移、应用本机开发库并做真实Chrome完整闭环。
- 此阶段用户授权完整A+B，不需在小任务之间重问；完成后等待用户验收，不进入P3。

## 上一快照（T012A：账号与文件权限归属完成，待Codex复核）
- 状态DONE_PENDING_CODEX_REVIEW；PLAN-r5 / RULES-r8，基线3be613c+Codex文档改动。仅WorkBuddy写入，未派agent、未联网/装依赖/未起服务/未commit、未迁移/重置DB、未建真实账号。
- 新增accounts app：/accounts/signup/（UserCreationForm，注册即登录）、/accounts/login/（LoginView子类）、POST /accounts/logout/（LogoutView，GET405）；登录/注册清除旧文件夹授权，退出flush session；外站next被拒。LOGIN_REDIRECT_URL暂为首页，projects留T012B。
- 新增workspaces/grants.py：grant含user_id，get_grant仅接受已登录且user_id匹配；旧匿名/缺失user_id授权失效，project_id预留空串。workspace页面login_required；匿名/folders返回401 JSON；health保持公开。
- 旧HTTP测试加真实User+force_login，保留原CSRF/越界/链接/跨会话/撤销/冲突/文件名断言；“另一浏览器”改为同账号另一Client无grant仍403。
- 验证：RED accounts ImportError EXIT=2 → GREEN accounts 12 passed；workspaces/test_views 35 passed；完整pytest 134 passed/1 skipped（既有symlink权限跳过）EXIT=0；ruff backend tools All checks passed；manage.py check 0 issues。日志tasks/logs/T012A.log。
- 未验证：真实浏览器注册/登录/退出与8000实机（autoreload已加载，不重复启动）；T012B项目功能未开始。

## 上一快照（T012派发：P2账号与项目开始）
- PLAN-r5 / RULES-r8；基线3be613c、开工git干净，无其它活跃WB任务。用户“开始下一步”明确授权P2，P1已验收。
- T012A APPROVED：WorkBuddy实现Django注册/登录/POST退出，文件接口登录门禁与用户绑定授权；T012B随后实现本人项目与工作区关联。只一个写入者，不派额外agent。
- 规格tasks/specs/T012-accounts-projects.md。当前开发SQLite继续使用，已有auth/session表保留；项目增量迁移前已备份到.tools/backups。无模型API/MySQL/外部服务。
- 运行服务127.0.0.1:8000，exec session19518，沿用autoreload，禁止重复起服务。新app加载/迁移完成后Codex必要时重启并做真实浏览器验收。
- 本阶段完成后交用户体验，不进入团队/任务/Agent阶段。

## 上一快照（P1：本地文件夹工作区已获用户验收）
- 版本PLAN-r4 / RULES-r7。状态ACCEPTED_BY_USER；用户于2026-10-23确认文件夹授权和读写已可用，完成当前规格的第一步验收。
- 已接受：实际文件夹作为工作区；页面内选择目录→显式授权→浏览/读取→编辑保存回原位置与新建→撤销。技术证据沿用T010/T011，用户验收见tasks/acceptance/T011.md。
- 此次仅更新验收/路线/约束事实，无业务源码改动、无新派发或后台任务，不重跑未变化的业务测试。
- 原文件类型/64KiB/列表上限、路径/会话权限及不执行命令的边界保留；前端/桌面最终选型与后续路线仍为草案。
- 下一候选：P2账号与项目（注册、登录退出、项目列表/创建、项目详情与当前工作区关联）。尚未派发实现任务；准备下一步时先锁定最小规格，不把本次验收视为全部路线批准。

## 上一快照（T011：技术验收完成时）
- PLAN-r3 / RULES-r6。状态ACCEPTED_BY_CODEX_WAITING_USER_REVIEW；本次仅修复当前工作区步骤，不跨阶段。
- 用户报告原按钮一直转圈无弹窗；旧action=pick同步等后台PowerShell ShowDialog，相关进程无可见窗口。旧native mock验收不能证明实机可用，已替换为页面内目录dialog。
- 当前流程：选择文件夹→立即打开网页dialog→驱动器/子目录/上级/绝对路径导航→使用此文件夹回填→单独点击授权。关闭/ESC不改输入或授权；请求8秒超时可重试，关闭中止、过期响应忽略；浏览仅目录元数据，不开文件内容。
- 已移除subprocess/PowerShell选择器；旧pick POST快速提示。新POST/workspace/folders/保留CSRF/no-store，只列普通非隐藏目录，拒绝UNC/设备/相对/..与链接等，原root+grant_id/文件读写保护不变。
- WorkBuddy主要实现已落盘，通道300秒超时后仍执行且未回填；Codex核对并停止唯一node33156任务树后接管，没有并发写入或重复派发。未取得WB最终报告；检查与验收以Codex实际结果为准。
- 开发时新增static目录曾使运行服务脚本404；当前脚本已内联，并完整重启项目服务。现Run-Backend.cmd exec session19518，127.0.0.1:8000；旧75882已Ctrl+C结束。不要重复起8000。
- 验证：pytest122 passed/1 skipped（既有真实file symlink权限跳过）；ruff backend/tools、Django check、git diff --check通过。补浏览不打开文件内容测试；..验证内存变异被回归捕获，实际源码未改。
- Chrome真实点击选择器、目录进入/返回/空目录、错误恢复、选择填路径、关闭/ESC、8秒超时重试、关闭后重开通过；随后授权→原位置编辑/新建→冲突→换根旧授权拒绝→撤销全流程通过，页面脚本错误0，390px无横向溢出。
- 证据tasks/acceptance/T011.md、tasks/reports/T011-browser.json、T011-picker-{desktop,mobile}.png。首轮拦截器清理CancelledError已修正QA脚本并重跑，无产品页面异常。
- 下一步：用户刷新http://127.0.0.1:8000/workspace/，体验页面内选择器及授权。原文本64KiB/100项/不执行命令等边界继续适用；未接AI，不自动推进下一阶段。

## 上一快照（T011派发：修复选择文件夹后页面等待）
- PLAN-r3 / RULES-r6；基线e53b058，开工git干净。用户实测选择按钮一直转圈、没有弹窗，授权修复当前步骤。
- 已定位：action=pick同步调用PowerShell原生ShowDialog，HTTP等120秒；实机存在server32484的picker子进程，无可见主窗口。此前仅mock并未验证真实弹窗，不能沿用为可用证据。
- T011 APPROVED：由WorkBuddy改为页面内文件夹选择器，只浏览文件夹名称/路径、选择填入路径，再显式授权。移除PowerShell阻塞入口；保持现有授权、保存、撤销规则，无新依赖/桌面框架。
- Codex规格tasks/specs/T011-folder-picker-fix.md；WorkBuddy唯一写入者，结束后Codex真实浏览器点击验收。不得重复启动8000服务，不自动跨阶段。

## 上一快照（T010：实际文件夹工作区技术验收通过，待用户体验）
- 版本PLAN-r3 / RULES-r6。状态ACCEPTED_BY_CODEX_WAITING_USER_REVIEW；用户选定的文件夹就是工作区，T009固定demo语义已由本次用户要求替代，不自动跨阶段。
- 地址http://127.0.0.1:8000/workspace/，沿用本机服务exec session75882。选择文件夹或输入绝对路径→显式授权→浏览子目录→编辑保存回原文件→新建→撤销；授权不创建欢迎文件/目录，不导入demo。
- WorkBuddy完成T010A/B；B通道300秒超时，原任务实际完成并回写记录，node20208自然退出后Codex才接手，没有重复派活或并发写入。
- 授权按浏览器session，root+grant_id；create/save校验授权版本，换根后旧页不能误写；CSRF/no-store/转义及逐级路径/链接/硬链拒绝保留。保存核对revision，外部修改或写入失败不覆盖原文件且保留输入。
- Codex补正：路径字段strip=False避免开头空格导致写错相邻文件/目录；两个表单ID与标签区分；取消选择保留文件列表；加5个回归并加强1个取消断言。版本比较内存变异被测试捕获，未修改实际源码。
- 最终验证：pytest113 passed/1 skipped（真实文件symlink因Windows权限跳过；junction/硬链/模拟symlink已测）；ruff backend/tools通过，Django check0 issues，git diff --check通过。
- 真实Chrome全流程通过：实际目录不写盘授权、子目录/特殊字符路径读写、磁盘核对、新建/重名拒绝、越界/CSRF/跨会话、冲突保留输入、换根旧grant拒绝、撤销；桌面/390px无横向溢出，无页面脚本错误。最终测试会话已撤销。
- 边界：常见UTF8代码文本<=64KiB、每目录显示最多100项；隐藏/链接/多硬链不开放；不含AI/命令/删除重命名。原生Windows弹窗仅mock与Forms环境探测，尚未人工实点；手动路径已实测。不是OS沙箱，未防恶意本地并发替换。
- 证据tasks/acceptance/T010.md、tasks/reports/T010-browser.json和T010-{desktop,mobile}.png；失败的两个浏览器选择器报告保留，已修正测试后全流程通过。
- 下一步：用户在页面授权自己的目录并体验读写；按反馈修正本步，用户认可后再准备下一阶段。

## 上一快照（T010B：实际文件夹授权与编辑已实现，待 Codex 复核）
- 版本PLAN-r3 / RULES-r6；基于未提交T010A文件继续。状态DONE_PENDING_CODEX_REVIEW；仅WorkBuddy单执行者，未派agent、未联网/装依赖、未启动服务、未commit。复用运行中的127.0.0.1:8000（autoreload已加载新页面，GET 200）。
- 改动：新增workspaces/picker.py；重写forms.py、views.py、workspace.html、test_views.py（31项）、test_picker.py（6项）；services.py仅补NUL二进制拒绝（binary_content）与回归；home入口文字、settings注释各一处。
- 授权：session键workspace_grant_v2 = {root, grant_id}；旧workspace_grant_root仅用于撤销清理、从不读取；授权只validate_root()，不建目录/welcome，不复制demo；成功时cycle_key。
- 页面：显示根完整路径、当前目录/根目录/返回上级；列目录+可编辑文件（100项上限提示）；读取进可编辑表单（含revision）；保存写回原处，冲突/失败保留输入并提示重新读取；新建不覆盖；撤销。390px靠单列布局、min-width:0、anywhere换行处理，未实测。
- 安全：GET不写盘、不开对话框；所有POST保留CSRF、no-store、自动转义；create/save必须匹配本次grant_id，切换根后旧页403且不写入；跨会话/撤销/越界/链接/隐藏/硬链拒绝沿用服务层。
- picker：固定PowerShell脚本常量+固定参数（-STA -NonInteractive -NoProfile -File），CREATE_NO_WINDOW，120s超时，取消/超时/失败分别提示；命令不含任何用户输入；mock测试6项；真实Windows对话框未实测。
- 验证：pytest 108 passed/1 skipped（唯一跳过仍为无权限建symlink）；ruff backend tools All checks passed；Django check 0 issues。证据tasks/logs/T010B.log。
- 未验证：真实原生对话框、真实Chrome浏览器流程与390px截图、实机手动编辑；由Codex浏览器验收补齐。下一步：Codex复核后交用户体验，不自动进入下一阶段。

## 上一快照（T010A：文件服务完成，待 Codex 复核）
- 版本PLAN-r3 / RULES-r6；基线a6e622c，Codex文档改动与spec保留未覆盖。状态DONE_PENDING_CODEX_REVIEW；仅WorkBuddy单执行者，未派agent、未联网、未装依赖、未启动服务、未commit。
- 改动仅backend/workspaces/services.py、test_services.py及本文件/日志；HTTP、模板、选择器未动，旧demo页面兼容。
- 新增：validate_root()只校验不写入；list_directory('')目录+可编辑文件条目（≤100，目录在前）；read_document->(content,sha256 revision)；save_text(path,content,expected_revision)原子替换；list_files(directory='')/read_text/create_text支持/分隔安全相对路径。
- 安全：单一路径校验；逐级lstat普通目录，链接/reparse/隐藏拒绝；文件多硬链拒绝；UNC/设备根拒绝；外部变更conflict、文件消失not_found，失败清理临时文件且原文件不变；保存前复核inode与revision。
- 验证：pytest backend/workspaces/test_services.py 73 passed/1 skipped（文件symlink环境权限跳过，junction/硬链实测）；pytest backend/workspaces 85 passed/1 skipped；ruff backend All checks passed。
- 旧测试调整仅限边界正式变化：sub/escape改为合法子目录案例，后缀列表加入常见代码类型；越界/链接/硬链断言保留。证据tasks/logs/T010A.log。
- 未做：权限位保留未单测；会话grant_id、授权/选择器/页面与HTTP验收属T010B。下一步：Codex复核后派T010B。

## 上一快照（T010派发：按实际文件夹授权与编辑修正第一步）
- 版本PLAN-r3 / RULES-r6；基线a6e622c，开工前git干净。用户直接纠正授权语义，继续第一步，不进入下一业务阶段。
- T010A APPROVED：WorkBuddy扩展文件服务，支持根内相对路径、目录浏览、常见代码文本、版本检查保存。T010B随后接实际目录授权、原生选择器及页面。规格tasks/specs/T010-folder-workspace.md。
- 只有WorkBuddy写实现；Codex先写规格再交接，之后只读复核。无其它活跃执行任务。服务127.0.0.1:8000仍运行，避免重复启动。
- 不再把固定demo当用户工作区；授权不创建或改写任何用户文件。测试仅隔离临时目录或.tools测试夹。

## 上一快照（T009：本机工作区技术验收通过，待用户体验）
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
