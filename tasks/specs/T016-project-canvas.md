# T016 项目协作画布

2026-10-23，PLAN-r7 / RULES-r10，基线83d1a0b，根D:\Users\28369\Desktop\AgentWorkspace。用户明确纠正T015视觉并要求继续；本轮实现真人/AI角色、多级任务、时间线的手动持久化闭环，随后交用户体验。

## 能力边界和设计约定

| 模块 | 职责 | 依赖 |
|---|---|---|
| projects（既有） | 注册后创建项目，保存文件夹位置 | accounts |
| workspace（既有） | 本机文件夹选择/显式授权/文件读写 | owner与会话grant |
| collaboration-members | 添加既有账号真人、命名AI成员与分工角色 | projects |
| task-tree | 项目内多级父子任务、时间段、负责人、状态、内容 | projects、collaboration-members |
| project-canvas | 左项目导航、中时间树、右详情/团队 | 上述模块 |

保持现有Django模板、SQLite、静态JS/CSS，不装新依赖或框架。时间向右推进，DFS层级行向下展开，父子连线表示拆分关系，不能把并行任务错误表示成先后依赖。节点按日期位置呈现，层级折叠/缩放/搜索用于浏览，节点可点开编辑。无任务时显示真实空状态与“创建整体任务”，禁止种入演示数据。

## T016A 后端契约（WorkBuddy第一片）

允许改projects/models.py、board_forms.py、board_views.py、urls.py、views.py中project_new创建/跳转相关、projects/migrations/0002_*.py、projects/test_board.py，及临时最小board.html（供后端渲染，B替换）。不改原file服务/grants/picker、settings、现有auth、vendor、rules/spec、用户DB；不运行真实migrate/服务/commit，不派其它agent。

1. ProjectMember：project FK CASCADE、kind human/ai、name(150以兼容auth用户名；AI输入限80)、role(80)、user nullable FK CASCADE、created_at；同project+非空user唯一。human必须是现有活跃User，name取其username；AI user必须空，只表示“未连接”。role用于分工，不推导管理员权限。每个新项目创建owner的human成员（role项目负责人）；增量迁移为既有项目补owner成员，不修改Project既有字段。更新角色仅owner。添加真人以username精确匹配，重复返回400而非500，未知用户不创建账号。不增加删除权限/全局用户列表。
2. TaskNode：project FK CASCADE、parent self nullable PROTECT、title(160)、description(4000)、assignee nullable ProjectMember SET_NULL、status choices todo/in_progress/blocked/review/done（中文待开始/进行中/受阻/待验收/已完成）、start_date/end_date DateFields、created_at/updated_at。开始/结束必填且end>=start；parent/assignee必须同项目，server ModelForm queryset限定并验证。parent仅创建时设定，编辑不允许改；这样UI不会创建循环。无任意深度业务限制，序列化和遍历使用迭代，避免递归崩溃。
3. URL name（projects命名空间）：board GET /<pk>/board/；member_add POST /<pk>/board/members/；member_update POST /<pk>/board/members/<member_pk>/；task_add POST /<pk>/board/tasks/；task_update POST /<pk>/board/tasks/<task_pk>/；board_workspace POST /<pk>/board/workspace/。所有装饰器login_required/never_cache及正确method；POST全部CSRF，不返回跨账号资源细节。
4. 访问：owner或该project真人成员能读board；陌生人404。只有owner管理成员、创建/修改任务结构/分配/日期/内容及工作空间；成员仅能更新assignee.user为本人的任务status，其余字段不接受（表单allowlist），其它任务更新403。AI不是可登录账号。成员GET不得包含workspace_path/grant/目录，不扩展workspaces原owner-only访问；UI中其文件入口禁用。
5. workspace动作：owner显式POST path，Workspace(Path(path)).validate_root通过后才更新Project.workspace_path并set_grant(user+project_id+新grant_id)。GET不授权、无效输入不破坏已有grant/位置。选择目录浏览仍调用现有POST /workspace/folders/，前端B实现选择器；禁止执行命令、文件上传、读取新目录文件内容。旧页写入拒绝仍由原grant_id保证。
6. project_new创建时事务内创建Project+owner成员，成功跳board，更新已有测试中该预期跳转；其它detail/link/open语义保留。board错误渲染400保留表单输入。
7. board上下文：project、is_owner、visible_projects（本人创建或成员身份，无重复）、members、tasks（select_related）、task_form、member_form、workspace_form、editing_task/edit_form（?task=id时）。canvas_data使用json_script安全输出，字典含project{id,name,description}、members[{id,name,kind,role}]、tasks[{id,parent_id,title,description,status,status_label,assignee_id,assignee_name,start_date,end_date}]。URL用reverse给模板；不在JSON插HTML，不含路径/密钥。
8. RED→GREEN实际测试：owner与成员读/陌生404、成员禁止管理、仅本人任务status、跨项目父任务/负责人/节点/成员拒绝、倒置日期拒绝、重复/未知真人、AI user为空、GET不写、CSRF/方法、工作空间显式授权和无效路径保留grant、json_script转义（如</script>），项目创建事务/owner成员。运行focused，再全pytest+ruff+check/makemigrations --check --dry-run；不改skip/抑制。每片回填简短结果tasks/reports/T016A.md和tasks/logs/T016A.log并自然退出。

## T016B 界面（A完成复核后WorkBuddy第二片）

允许新增projects/static/projects/canvas.css/js、改board.html、core/base.html增加sidebar block、项目列表/详情/新建入口文案及tests必要预期。禁止改A已定接口、模型/vendor/auth/file协议，不装依赖，不改用户数据。沿用本地Motion可选增强；Django真实POST表单为准。

- 视觉参考用户描述的Codex桌面结构：窄浅灰左栏，真实项目列表与新建项目、当前工作空间入口；顶部紧凑项目标题/团队头像/操作；中央占满可用区域的淡点阵画布和时间标尺；右侧详情面板。灰白/黑字、小蓝色强调，避免大卡片管理后台和大段技术提示。
- 首次新项目展示步骤：选择工作空间→添加团队→创建整体任务。文件夹实际通过现有目录API的页内dialog浏览，另明确“授权并设为工作空间”POST。已配置路径只对owner显示；文件入口仍指向原项目open。选择器加载时保护输入、8秒超时可重试、ESC/关闭中止，过期响应忽略。
- 空画布“创建整体任务”；新增节点/子任务真实表单：标题、内容、开始/结束日期、负责人、状态；点节点右侧详情可编辑和“拆分子任务”，owner可操作；普通成员只显示本人任务状态表单。无AI调用的“自动拆分”不得作为可用按钮。
- 时间树按真实日期横向位置、层级行和SVG连线呈现；节点显示标题、简短内容、状态文字、负责人、日期。搜索、折叠子树、缩放与重置可用；画布内部滚动而非整个页面溢出。可切换任务列表/大纲作为窄屏与无JS降级，不能显示假的进度数字。
- 团队面板新增真人（现有用户名）或AI（名称），角色可填项目经理/前端/后端/测试等；AI清晰显示未连接，添加不触发工具/API；真实成员只读团队。邀请链接提示后续，不做假按钮。
- input/textarea/JSON全安全转义，JS用textContent和DOM API，不把用户内容插入innerHTML。native dialog、焦点、ESC、键盘、系统减弱动效；旧账号/文件页照常可用。
- 1440/768/390布局；节点详情、团队/添加表单均可交互。技术通过后Codex用临时账号/文件夹实测与截图，不碰admin/开发项目。

## 验收与停止条件

核心链：注册/登录→新建项目直达画布→选择并明确授权文件夹→添加真人/AI与角色→整体任务→多级子任务/日期/分配→时间树和详情状态→刷新保留→成员只能更新本人状态且无文件权限。后端权限/CSRF与旧文件回归不减，资源本地/无脚本错误；不承诺无限节点同时显示或自动执行。T016是手动管理闭环，不是邀请链接或模型连接已验收。执行者遇到范围/新依赖冲突先回报，不反复派同任务；只一个写入者。
