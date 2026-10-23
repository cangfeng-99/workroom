# T018 项目配置与项目空间

PLAN-r9 / RULES-r12，基线9a6548a。用户五张截图及明确选择：资产先显示已授权本机文件，不上传。已授权本轮继续，仅Codex+WorkBuddy、单写入者。

## 目标与设计契约
1. 项目入口：浅薄荷背景、绿色主操作、真实项目卡片、搜索；本人/参与项目保持区分。模板卡可预填自己的项目指令，不种入假任务/假进度。保留授权/关联事实，可放折叠详情；旧安全断言不得删弱。
2. 新建项目：一个有分区的表单集中配置名称、说明、指令、选择工作空间、显式授权、可选初始真人/AI成员。空配置也可创建，owner自动加入。选择目录不等于授权。
3. 项目内默认动态，横向“动态、计划、任务、资产”，右侧项目配置。动态是真实成员留言（作者/时间）与底部发布表单，AI未连接不假回答；计划表格/看板/现有任务树，任务页真实列表和关键词/状态筛选，来自同一TaskNode。表格列标题/状态/负责人/优先级/标签/日期；新增与编辑打开原画布表单，无假拖拽、假撤销。
4. 资产仅owner且本项目有效会话grant才列本机目录；可进子目录/返回，显示类型/时间/大小。安全普通PDF/图片/大文件只显示元数据，可编辑内容仍守旧类型/64KiB限制。成员不得触发FS或泄露根路径。无上传、云配额或权限分享。
5. 配置：owner可编辑指令；团队和邀请入口实际可用；连接器/技能/定时执行明确未接入、禁用。AI角色仍是未连接条目。参考结构密度，不复制品牌/私有文字/插画。
6. 原生标签/按钮/focus与空错权限状态；320/768/1440无页面横溢，表格内部可滚；减弱动效沿用；新增样式限定范围，不破坏文件工作区。

## 路由、数据与边界
- projects:hub `/projects/<pk>/space/` GET；tab白名单activity/plan/tasks/assets，view table/kanban；创建和项目卡进入hub，旧board/detail/workspace保持。复用board_views._accessible_project/_visible_projects，owner或human member可读，其他404。留言POST仅owner/member；指令POST仅owner；CSRF/no-store/方法限制。
- Project新增instructions TextField blank/max6000；ProjectMessage(project,author SET_NULL,content max4000,created_at)；TaskNode新增priority low/normal/high/urgent默认normal及labels Char200blank。生成0004增量迁移，不操作真实DB。
- ProjectForm仍忽略客户端owner/workspace_path。新的工作空间字段setup_path及authorize_workspace，勾选后Workspace.validate_root，项目/owner/初始成员atomic成功后才set_grant绑定user/project/newUUID。未勾选不隐式授予；旧link_grant协议与边界兼容。目录选择复用现有POST/workspace/folders/页面内picker，不加原生弹窗/新依赖。
- 初始成员formset最多10；kind/name/role沿现有MemberForm：human精确活跃现有账号，拒绝owner重复/同账号重复；AI无user。错误不创建部分记录、不改变当前grant，输入保留。成员可后续加。不要索要密钥。
- TaskForm兼容旧POST缺priority/labels：创建默认，编辑保留当前值；显式labels空可清空。parent只创建时设置、成员仅更新自己任务状态的规则不变。
- Workspace增加独立list_assets，复用_resolve_directory/_check_segment/_check_file_stat/_is_hidden及link/reparse检查，max100目录优先。只stat不读文件内容，不放宽原list_directory/read/save权限和限制。
- 建议hub_views/hub_forms/setup_forms、space模板和局部、space.css/js。避免膨胀canvas.js，仅必要URL new=task自动打开原表单、页签/返回hub入口。初始GET空画布也必须能打开创建。

## 执行与允许范围
根D:\Users\28369\Desktop\AgentWorkspace。先读AGENTS/current最新快照、本spec和相关源码。允许backend/projects/**、workspaces/services.py及针对性测试、core/base模板与app.css必要链接、tasks/current和T018日志。两段同一任务：A配置/权限/元数据与测试，B界面接入；每段针对检查。WB唯一写入；Codex只读复核，结束后接管迁移/浏览器。不派agent、不联网、不安装、不调模型、不commit、不起新服务、不操作用户目录/真实DB，保留admin/开发项目。

## 验收与停止
运行`.venv\Scripts\python.exe -m pytest -q backend/projects backend/workspaces`，Ruff backend/tools、manage.py check、makemigrations --check --dry-run、Node --check新JS。新测试覆盖创建原子/伪造字段/团队重复/显式授权/错误保留；项目权限/留言/指令；成员/无grant不读FS，目录穿越/link/hardlink/hidden拒绝，PDF元数据不读内容；priority旧POST兼容。旧断言仅真实创建重定向board改hub可更新，安全断言不得删弱。
Codex最后完整集、备份迁移并核对旧记录、真实Chrome新建/四页签/邀请双账号/成员文件边界和截图窄屏。未接AI/未远程发布如实保留。相同错误两次无新证据即报告；通道超时不重复任务。结束回填current、tasks/logs/T018.log与500字左右最终摘要（文件、命令/退出码、未测项）。
