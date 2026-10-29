"""Shared MCP schemas: stdio and HTTP expose one contract."""

PROTOCOL = '2024-11-05'

PROJECT = {
    'type': 'string',
    'description': '项目 id 或名称，例如 “开发项目 v1”。令牌已绑定项目时可省略；本地模式必填',
}

TOOLS = [
    {
        'name': 'list_projects',
        'description': '列出所有项目和当前进度',
        'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    },
    {
        'name': 'get_project',
        'description': '读取一个项目的目标、任务树、资料库和最近的 AI 输出',
        'inputSchema': {
            'type': 'object',
            'properties': {'project': PROJECT},
            'required': ['project'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'list_tasks',
        'description': '列出任务，可按状态过滤',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'project': PROJECT,
                'status': {
                    'type': 'string',
                    'description': 'todo / doing / done / blocked，或中文状态',
                },
            },
            'required': ['project'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'create_task',
        'description': '在项目里新建一个任务',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'project': PROJECT,
                'title': {'type': 'string'},
                'detail': {'type': 'string'},
                'assignee': {'type': 'string', 'description': '成员名称，可省略'},
                'start_date': {'type': 'string', 'description': 'YYYY-MM-DD'},
                'end_date': {'type': 'string', 'description': 'YYYY-MM-DD'},
            },
            'required': ['project', 'title'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'update_task_status',
        'description': '回报执行状态；完成实现后提交交付，等待本人确认，不要直接置done。受阻须提供具体原因与下一步。',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'project': PROJECT,
                'task': {'type': 'string', 'description': '任务 id 或标题'},
                'status': {'type': 'string', 'description': 'todo / doing / done / blocked'},
                'reason': {'type': 'string', 'description': '设为blocked时说明具体卡在哪里'},
                'next_action': {'type': 'string', 'description': '设为blocked时说明需要谁做什么才能继续'},
            },
            'required': ['project', 'task', 'status'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'ask_project_knowledge',
        'description': '按项目资料库回答问题，回答带引用；资料库没有相关内容时明确说明，不编造。',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'project': PROJECT,
                'question': {'type': 'string', 'description': '要问的问题'},
            },
            'required': ['project', 'question'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'read_memory',
        'description': '读取项目长期记忆与今日记录；没有授权工作区时返回提示',
        'inputSchema': {
            'type': 'object',
            'properties': {'project': PROJECT},
            'required': ['project'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'append_memory',
        'description': '把一条结论/决定写入项目记忆；scope=daily 写今日记录，long 写长期记忆',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'project': PROJECT,
                'text': {'type': 'string', 'description': '要记住的内容，一句话'},
                'scope': {'type': 'string', 'description': 'daily 或 long'},
            },
            'required': ['project', 'text'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'add_library_entry',
        'description': '往资料库写一条规则、产物或决策',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'project': PROJECT,
                'title': {'type': 'string'},
                'body': {'type': 'string'},
                'kind': {'type': 'string', 'description': 'rule / artifact / decision'},
                'summary': {'type': 'string'},
                'tags': {'type': 'string', 'description': '逗号分隔'},
            },
            'required': ['project', 'title'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'next_task',
        'description': '领取某个成员的下一条待办（含任务说明与关联资料）',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'project': PROJECT,
                'assignee': {'type': 'string', 'description': '成员名称，例如 WorkBuddy'},
            },
            'required': ['project', 'assignee'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'claim_task',
        'description': '认领任务，把它标记为进行中',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'project': PROJECT,
                'task': {'type': 'string', 'description': '任务 id 或标题'},
            },
            'required': ['project', 'task'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'submit_result',
        'description': '提交任务结果与证据，保存为待本人确认；单人模式不调用AI审核。提交不等于完成，不要再把任务直接置为done。',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'project': PROJECT,
                'task': {'type': 'string', 'description': '任务 id 或标题'},
                'summary': {'type': 'string', 'description': '一句话交付摘要'},
                'body': {'type': 'string', 'description': '详细说明或改动列表'},
                'tool': {'type': 'string', 'description': 'workbuddy / codex / cursor'},
                'artifact_title': {'type': 'string'},
            },
            'required': ['project', 'task', 'summary'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'get_inbox',
        'description': '查看 @我的消息和下一条待办，适合定时轮询',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'project': PROJECT,
                'assignee': {'type': 'string', 'description': '成员名称'},
            },
            'required': ['project', 'assignee'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'post_message',
        'description': '以外部成员身份在项目对话里发言，参与讨论',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'project': PROJECT,
                'content': {'type': 'string'},
                'tool': {'type': 'string', 'description': 'workbuddy / codex / cursor'},
                'member': {'type': 'string', 'description': '成员名称，可省略'},
            },
            'required': ['project', 'content'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'wait_for_work',
        'description': '长轮询收件箱：有 @ 或停止请求立即返回，最多等 timeout 秒',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'project': PROJECT,
                'assignee': {'type': 'string', 'description': '成员名称'},
                'timeout': {'type': 'integer', 'description': '最多等待秒数，默认 20，最大 25'},
            },
            'required': ['project', 'assignee'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'report_progress',
        'description': '上报阶段进展（plan/doing/verify/done），项目对话里立即可见',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'project': PROJECT,
                'task': {'type': 'string', 'description': '任务 id 或标题，可省略'},
                'stage': {'type': 'string', 'description': 'plan / doing / verify / done'},
                'note': {'type': 'string'},
                'tool': {'type': 'string'},
            },
            'required': ['project', 'stage', 'note'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'get_latest_plan',
        'description': '读取最近一次 Agent 计划及其执行步骤',
        'inputSchema': {
            'type': 'object',
            'properties': {'project': PROJECT},
            'required': ['project'],
            'additionalProperties': False,
        },
    },
]


def _extend_tools():
    text = {'type': 'string'}
    integer = {'type': 'integer'}
    extras = {
        'review_delivery': ('对他人的待验收交付提交独立复核', {'delivery':integer,'verdict':text,'note':text}),
        'get_task_context': ('读取完整任务、验收条件和有效规则正文', {'task':text}),
        'get_library_entry': ('读取单条资料的完整正文和版本', {'entry':text}),
        'heartbeat_task': ('更新自己执行的心跳，提示规则版本变化', {'task':text,'run_id':text}),
        'release_task': ('释放自己持有的任务认领', {'task':text}),
        'list_deliveries': ('读取待验收或已处理的交付', {'status':text}),
        'whoami': ('读取当前令牌绑定的项目和身份', {}),
        'confirm_task_context': ('读取最新任务包后明确确认规则版本', {'task':text,'revision':integer}),
    }
    for name, (description, props) in extras.items():
        required = ['project'] + ([next(iter(props))] if name in {'get_task_context','get_library_entry','heartbeat_task','release_task'} else [])
        if name == 'whoami':
            required = []
        if name == 'confirm_task_context':
            required = ['project', 'task', 'revision']
        if name == 'review_delivery':
            required = ['project','delivery','verdict','note']
        TOOLS.append({'name':name,'description':description,'inputSchema':{
            'type':'object','properties':{'project':PROJECT, **props},
            'required':required,'additionalProperties':False}})
    additions = {
        'get_project': {'page':integer,'task_limit':integer,'library_limit':integer},
        'create_task': {'acceptance':text},
        'claim_task': {'tool':text,'member':text},
        'submit_result': {**{key:text for key in ['baseline','commit_ref','changed_files',
            'test_commands','test_output','evidence_ref','idempotency_key','member']},
            'test_exit_code':{'type':['integer','null']}, 'accounting':{'type':'object'}, 'review':{'type':'boolean'}},
    }
    for tool in TOOLS:
        tool['inputSchema']['properties'].update(additions.get(tool['name'], {}))

    # 合法取值写进契约：客户端从 tools/list 就能读到，校验器也能拦下错值，
    # 而不是等到业务代码深处才报「未知状态」，或者被静默兜底。
    enums = {
        ('update_task_status', 'status'): [
            'todo', 'doing', 'done', 'blocked', '待开始', '进行中', '已完成', '受阻',
        ],
        ('add_library_entry', 'kind'): ['rule', 'artifact', 'decision'],
        ('append_memory', 'scope'): ['daily', 'long'],
        ('review_delivery', 'verdict'): ['approved', 'changes'],
    }
    for tool in TOOLS:
        props = tool['inputSchema'].get('properties', {})
        for (tool_name, field), allowed in enums.items():
            if tool['name'] == tool_name and field in props:
                # 复制一份再写：同类型的字段共用同一个 dict 实例，
                # 原地赋值会把 enum 传染给所有使用该实例的字段。
                props[field] = {**props[field], 'enum': allowed}

    # project 不是硬性必填：令牌已绑定项目时 _project() 会用令牌里的项目兜底，
    # 写成 required 会把合法调用挡在校验层。缺项目又没令牌时报错仍然清楚。
    for tool in TOOLS:
        schema = tool['inputSchema']
        required = schema.get('required') or []
        if 'project' in required:
            schema['required'] = [key for key in required if key != 'project']


_extend_tools()
