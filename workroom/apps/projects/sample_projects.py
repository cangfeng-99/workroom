"""Opt-in practice project. No completed work, provider calls or file writes."""

from django.conf import settings
from django.db import transaction

from desktop_support import DesktopError, operation_lock

from .models import AuditLog, LibraryEntry, Member, Project, Task
from .user_profile import local_user

NAME = "练习 · 个人待办工具"
MARKER = "workroom:example:personal-todo:v1"
PHASES = (
    ("scope-phase", "1. 明确范围和页面", "先约定第一版交付什么，再画出页面与数据流。"),
    ("build-phase", "2. 做出可用的待办工具", "让登录、数据保存和待办操作真正连通。"),
    ("check-phase", "3. 检查并交付结果", "核对完整流程，留下检查记录，再由本人确认。"),
)

# key, phase, title, summary, frontend, backend, steps, acceptance, prerequisites, work kind
LEAVES = (
    (
        "scope",
        "scope-phase",
        "写清楚第一版要交付什么",
        "把范围写成一张可核对清单，先不开始写代码。",
        ["列出注册、登录、自己的待办列表和编辑入口；先不做团队、支付、通知。"],
        ["确认数据只属于当前用户；未登录不能访问自己的待办接口。"],
        [
            "写出一个用户从注册到完成待办的流程。",
            "列出本版必须有的功能和暂时不做的功能。",
            "逐项写出通过标准，再开始后面的设计。",
        ],
        "清单包含账号与待办增删改查、本人数据隔离、暂不做内容；每项都能判断完成与否。",
        (),
        "analysis",
    ),
    (
        "screens",
        "scope-phase",
        "画出登录页与待办页",
        "先用简单草图说明输入、按钮和错误提示的位置。",
        [
            "登录页有账号、密码、提交和错误提示；待办页有列表、输入框、完成与删除操作。",
            "画出加载、空列表、请求失败、保存成功四种状态，窄屏能看到全部操作。",
        ],
        ["把每个页面需要的输入和返回数据记下来；本步不假装接口已经实现。"],
        [
            "根据已确认范围画两页草图。",
            "给每个按钮标出触发什么请求、失败显示在哪里。",
            "自己走一遍完整流程，记录遗漏的提示。",
        ],
        "两页草图、状态和请求对应表齐全，别人能看懂点击之后发生什么。",
        ("scope",),
        "analysis",
    ),
    (
        "init",
        "build-phase",
        "准备 Django 项目和检查入口",
        "先准备独立代码目录、环境和真实基准，再让后续代码任务开始。",
        ["能在本机浏览器打开最小启动页；此步先不做待办交互。"],
        [
            "创建 Django 的 config/manage.py、accounts/todos 应用，配置 SQLite、模板和静态目录。",
            "固定开发依赖并准备测试入口；运行 WorkRoom 的 exe 不等于已经具备练习项目的 Python 开发环境。",
        ],
        [
            "先由本人选择独立空目录，初始化 Git 并提交起始 README，记录真实起点版本。",
            "按实际目录填写本任务包的基准和允许文件，再交给工具继续。",
            "创建虚拟环境、安装锁定版本的 Django，执行 startproject/startapp，并记录依赖清单。",
            "准备 templates、static 和 tests，运行 Django check；数据库、密钥和虚拟环境不要提交进 Git。",
        ],
        "独立目录能运行最小页面和 Django check；依赖与启动步骤可复现，任务包记录真实版本；没有把 WorkRoom 程序目录当成代码工作区。",
        ("scope",),
        "code",
    ),
    (
        "data",
        "build-phase",
        "设计用户与待办数据",
        "把待办属于谁、保存哪些字段先定下来。",
        ["表单字段与数据字段对应；标题为空时有明确提示。"],
        [
            "使用 Django 自带用户模型；Todo 有 owner 外键、title、is_completed、created_at、updated_at。",
            "开发时使用 SQLite；生成并检查迁移，标题必填，用户删除时的关联行为写清楚。",
        ],
        [
            "确认真实项目目录和当前代码版本。",
            "编写 Todo 模型和迁移，先看迁移会改变什么。",
            "运行迁移和 Django check，验证用户能关联自己的待办。",
        ],
        "新建数据库能迁移成功；必填与用户关联正确；记录实际检查命令和输出。",
        ("init",),
        "code",
    ),
    (
        "auth-api",
        "build-phase",
        "实现注册登录与退出后端",
        "用现成认证能力处理密码和会话，不自己保存明文密码。",
        ["约定登录成功的跳转和错误时返回给页面的提示。"],
        [
            "使用 Django 用户认证、密码哈希、session 和 CSRF；注册检查重复账号，登录错误不泄露密码。",
            "退出使用 POST；待办页面与接口要求登录，使用框架提供的表单或认证视图。",
        ],
        [
            "核对用户模型和登录表单。",
            "接入注册、登录、POST退出与登录门禁。",
            "测试重复账号、错误密码、缺CSRF、未登录访问和成功路径。",
        ],
        "能注册、登录、退出；错误提示清楚；未登录请求受保护；密码和密钥没有进入日志。",
        ("data",),
        "code",
    ),
    (
        "auth-ui",
        "build-phase",
        "做出登录页面和退出入口",
        "让用户看得懂登录状态，也能从错误中恢复。",
        [
            "用 Django 模板和 CSS 做账号密码表单；label明确、键盘可提交、错误不靠颜色表达。",
            "提交中避免重复操作；失败保留账号、不回填密码；成功到待办列表，列表有退出入口。",
        ],
        ["连接已经实现的认证视图，保持 CSRF 和会话行为，不用前端布尔值冒充已登录。"],
        [
            "按草图实现表单与布局。",
            "接真实后端成功和失败路径。",
            "用手机宽度和键盘操作检查提示、焦点和跳转。",
        ],
        "真实账号能进入列表，错密码有提示；窄屏不裁切，密码失败后不会显示在页面中。",
        ("screens", "auth-api"),
        "code",
    ),
    (
        "todo-api",
        "build-phase",
        "实现自己的待办增删改查",
        "让待办真正保存，并且所有操作都限定当前用户。",
        ["约定新建、编辑、完成、删除后的反馈与列表刷新方式。"],
        [
            "Django 视图/表单创建和更新 Todo；查询始终按 request.user 过滤。",
            "更新、完成、删除使用 POST 并保留CSRF；无效ID或别人的ID返回明确拒绝。",
        ],
        [
            "先写当前用户的列表查询。",
            "补充新建、改标题、切换完成、删除。",
            "测试空标题、不存在ID、重复提交和未登录请求。",
        ],
        "操作后刷新仍保留数据；不能读取或修改别人的待办；无效输入不会产生半条数据。",
        ("data", "auth-api"),
        "code",
    ),
    (
        "todo-ui",
        "build-phase",
        "做出能直接操作的待办页面",
        "把列表和真实后端接起来，让每次操作有结果。",
        [
            "支持新建、编辑标题、完成和删除；空列表说明下一步，删除前有确认。",
            "错误文本完整可读，按钮与输入框在390/768/1440宽度下可用，不用假数据代替真实保存。",
        ],
        ["页面读取当前用户数据，提交到已有视图；失败保留可安全恢复的输入。"],
        [
            "先接列表与新建。",
            "再接编辑、完成、删除及对应反馈。",
            "刷新页面并重新登录，确认数据来自数据库。",
        ],
        "用户能完整操作自己的待办；刷新不丢数据，失败能恢复，长标题和窄屏不会遮住操作。",
        ("screens", "todo-api", "auth-ui"),
        "code",
    ),
    (
        "ownership",
        "build-phase",
        "验证两个人的数据互不影响",
        "用两个测试账号核对越权路径，不能只看正常登录。",
        ["A用户页面不显示B用户的内容，错误时也不展示别人的标题。"],
        ["用 Django TestCase/Client 建立两个用户，覆盖列表、详情、更新、完成和删除的越权请求。"],
        [
            "分别创建A和B的待办。",
            "用A请求B的ID，逐项验证读取和写入都被拒绝。",
            "检查B原数据不变，保存测试输出。",
        ],
        "两名测试用户的全部越权场景被拒绝，正常操作仍通过；测试实际运行并留下输出。",
        ("todo-api",),
        "code",
    ),
    (
        "flow",
        "check-phase",
        "走完注册到删除待办的完整流程",
        "从空数据库开始走主流程，检查前后端是否真正连通。",
        ["核对注册、错误登录、成功登录、列表、新建、编辑、完成、删除、退出和窄屏。"],
        ["在临时数据库运行迁移和测试；核对未登录/越权/无效输入，不能用真实用户数据演练删除。"],
        [
            "准备独立测试数据，不使用实际账号密钥。",
            "按流程逐项操作并记录结果，发现问题回到对应任务修复。",
            "重跑失败项和必要回归，保留命令、退出码与输出。",
        ],
        "主流程与失败路径有真实记录；未解决的问题写清原因，不把计划当测试证据。",
        ("auth-ui", "todo-ui", "ownership"),
        "code",
    ),
    (
        "deliver",
        "check-phase",
        "提交结果并由本人确认",
        "把结果与证据交到一起，再判断是否达到原先要求。",
        ["准备可打开的页面或截图，说明做到了哪些状态。"],
        ["提供代码版本、变更范围、实际检查命令/退出码/输出；本步不增加新业务功能。"],
        [
            "在交付页填写真实结果与证据位置。",
            "核对最初范围，未通过的写原因退回。",
            "本人检查后确认，不能让工具代替自己验收。",
        ],
        "完成标准逐项可核对；有真实证据且本人明确确认，未通过则保留退回意见。",
        ("flow",),
        "analysis",
    ),
    (
        "save",
        "check-phase",
        "写下启动方法并保存备份",
        "让下次打开时知道怎么运行，也能找回项目记录。",
        ["说明从哪里进入页面、如何操作和有哪些尚未完成的功能。"],
        ["记录依赖/迁移/启动/检查方式；备份项目记录与代码，分别说明存放位置。"],
        [
            "写一份自己能照着执行的README。",
            "导出WorkRoom项目备份，代码另外提交Git或文件备份。",
            "记录下一步与已知限制，避免新聊天重复猜测。",
        ],
        "启动步骤可复现，备份可找到；记录、代码和密钥的保存方式清楚。",
        ("deliver",),
        "analysis",
    ),
)


def open_example(owner=None):
    if settings.WORKROOM_MODE != "local":
        raise DesktopError("练习项目仅供本机单人版使用。")
    with operation_lock(settings.DATA_DIR), transaction.atomic():
        owner = owner or local_user()
        marker = (
            LibraryEntry.objects.select_related("project")
            .filter(source_ref=MARKER, project__owner=owner)
            .order_by("pk")
            .first()
        )
        if marker:
            return marker.project, False
        project = Project.objects.create(
            name=NAME,
            goal_title="做一个可注册登录、只管理自己待办的小工具",
            goal_detail="固定练习模板：先看范围，再做页面和后端，最后自己核对交付。所有任务尚未完成，日期与真实代码基准由你补充。",
            owner=owner,
            policy={"require_package": True},
        )
        person = Member.objects.create(
            project=project, kind="human", name="我", role="练习负责人", user=owner
        )
        nodes = {}
        for order, (key, title, summary) in enumerate(PHASES):
            nodes[key] = Task.objects.create(
                project=project,
                title=title,
                detail=summary + "\n这是练习阶段，展开子任务查看实施和验收。",
                acceptance="下面各项交付经本人核对，阶段结果再由本人确认。",
                assignee=person,
                order=order,
                guide=dict(
                    summary=summary,
                    example=True,
                    steps=[
                        "展开本阶段任务。",
                        "先处理前置条件已满足的一项。",
                        "核对每项结果，再确认阶段。",
                    ],
                    frontend=["页面效果见下面的具体任务，阶段节点不代表已经实现。"],
                    backend=["实现与检查见下面的具体任务，当前没有自动运行代码。"],
                    outcomes=["每项有结果与证据，未完成项保留真实状态。"],
                ),
            )
        for order, row in enumerate(LEAVES, len(PHASES)):
            key, phase, title, summary, frontend, backend, steps, acceptance, requires, kind = row
            detail = "\n".join(
                [
                    summary,
                    "\n页面要达到：",
                    *frontend,
                    "\n后端要达到：",
                    *backend,
                    "\n实施步骤：",
                    *steps,
                    "\n这是固定练习内容。代码任务执行前按实际项目修改文件范围，填写真实代码版本；这里没有已经写好的代码或检查结果。",
                ]
            )
            nodes[key] = Task.objects.create(
                project=project,
                parent=nodes[phase],
                title=title,
                detail=detail,
                acceptance=acceptance,
                assignee=person,
                order=order,
                execution_spec=dict(
                    work_kind=kind,
                    workspace_key="main",
                    baseline="",
                    allowed_paths=[
                        "config/",
                        "manage.py",
                        "accounts/",
                        "todos/",
                        "templates/",
                        "static/",
                        "tests/",
                        "requirements*.txt",
                        ".gitignore",
                        "README.md",
                    ]
                    if kind == "code"
                    else [],
                    relevant_files=[],
                    check_commands=["python manage.py check", "python manage.py test"]
                    if kind == "code"
                    else [],
                    risk="normal",
                ),
                guide=dict(
                    summary=summary,
                    example=True,
                    steps=list(steps),
                    frontend=list(frontend),
                    backend=list(backend),
                    outcomes=[acceptance],
                ),
            )
        for row in LEAVES:
            nodes[row[0]].prerequisites.set(nodes[key] for key in row[8])
        LibraryEntry.objects.create(
            project=project,
            kind="artifact",
            title="练习说明：固定模板，不是真实交付",
            summary="按自己的情况修改任务，真实执行后再确认完成。",
            body="此项目由本人主动打开练习入口创建。没有连接AI、调用模型、创建代码文件、预填完成记录或授权工作区。重复打开保留修改；可从项目首页删除，再主动创建新示例。日期留空，代码任务基准和文件范围需要按实际项目补齐。",
            source="human",
            source_ref=MARKER,
        )
        AuditLog.objects.create(
            project=project,
            actor_user=owner,
            action="example.created",
            detail="Explicit personal practice project; all tasks todo, no model calls/files/workspace authorisation or fake delivery.",
        )
        return project, True
