"""Data model: project, team members, chat, task tree, queue and delivery."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class AuthThrottle(models.Model):
    bucket = models.CharField(max_length=64, unique=True)
    attempts = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField()


class Project(models.Model):
    """One workspace. The goal is the right-hand end of the task tree."""

    name = models.CharField('项目名称', max_length=120)
    goal_title = models.CharField('目标', max_length=200)
    goal_detail = models.TextField('目标说明', blank=True)
    workspace_path = models.CharField('工作区路径', max_length=500, blank=True)
    workspace_authorized_at = models.DateTimeField('授权时间', null=True, blank=True)
    goal_deadline = models.DateField('目标日期', null=True, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='owned_projects',
    )
    context_revision = models.PositiveIntegerField('上下文版本', default=1)
    policy = models.JSONField('协作策略', default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return self.name

    @property
    def task_count(self) -> int:
        return self.tasks.count()

    @property
    def done_count(self) -> int:
        return self.tasks.filter(status=Task.Status.DONE).count()

    @property
    def member_count(self) -> int:
        return self.members.count()

    @property
    def percent(self) -> int:
        total = self.task_count
        return round(self.done_count * 100 / total) if total else 0


    def _active_tasks(self):
        archived = list(
            self.tasks.filter(parent__isnull=True, title__startswith='归档')
        )
        hidden = set()
        stack = list(archived)
        while stack:
            node = stack.pop()
            hidden.add(node.pk)
            stack.extend(list(node.children.all()))
        return [task for task in self.tasks.all() if task.pk not in hidden]

    @property
    def active_total(self) -> int:
        return len(self._active_tasks())

    @property
    def active_done(self) -> int:
        return sum(1 for task in self._active_tasks() if task.status == Task.Status.DONE)

    @property
    def active_percent(self) -> int:
        total = self.active_total
        return round(100 * self.active_done / total) if total else 0


class ProjectMembership(models.Model):
    """A real account's role inside one project (server mode)."""

    class Role(models.TextChoices):
        OWNER = 'owner', '所有者'
        EDITOR = 'editor', '编辑者'
        VIEWER = 'viewer', '只读'

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name='memberships'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='project_memberships',
    )
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.VIEWER)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['role', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'user'], name='unique_project_membership'
            )
        ]

    def __str__(self) -> str:
        return f'{self.user}@{self.project_id}:{self.role}'


class Invitation(models.Model):
    """One-use invitation link; only a hash of the token is stored."""

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name='invitations'
    )
    role = models.CharField(
        max_length=10,
        choices=ProjectMembership.Role.choices,
        default=ProjectMembership.Role.VIEWER,
    )
    token_hash = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='created_invitations',
    )
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    used_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='used_invitations',
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    @property
    def is_live(self) -> bool:
        from django.utils import timezone

        return (
            self.used_at is None
            and self.revoked_at is None
            and self.expires_at > timezone.now()
        )


class ToolToken(models.Model):
    """Bearer token for the remote HTTP tool bridge (hash stored only)."""

    class Scope(models.TextChoices):
        READ = 'read', '只读'
        EXECUTE = 'execute', '执行'

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name='tool_tokens'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='tool_tokens',
    )
    member = models.ForeignKey(
        'Member',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='tool_tokens',
    )
    name = models.CharField('名称', max_length=80)
    token_hash = models.CharField(max_length=64, unique=True)
    scope = models.CharField(max_length=10, choices=Scope.choices, default=Scope.READ)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    @property
    def is_live(self) -> bool:
        from django.utils import timezone

        if self.revoked_at is not None:
            return False
        return self.expires_at is None or self.expires_at > timezone.now()


class AuditLog(models.Model):
    project = models.ForeignKey(
        Project,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='audit_logs',
    )
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='workroom_audit_logs',
    )
    action = models.CharField(max_length=60)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']


class Member(models.Model):
    """A team member: a person, or an AI that holds a role."""

    class Kind(models.TextChoices):
        HUMAN = 'human', '真人'
        AI = 'ai', 'AI'
        EXTERNAL = 'external', '外部工具'

    class Duty(models.TextChoices):
        PROPOSE = 'propose', '提议'
        REVIEW = 'review', '评审'
        DECIDE = 'decide', '决策'
        EXECUTE = 'execute', '执行'

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='member_profiles',
    )
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.HUMAN)
    name = models.CharField('名称', max_length=80)
    role = models.CharField('角色', max_length=80, blank=True)
    duty = models.CharField(
        '讨论职责', max_length=10, choices=Duty.choices, default=Duty.EXECUTE
    )
    persona = models.TextField('身份与职责', blank=True)
    provider = models.CharField('模型商', max_length=40, blank=True)
    model_name = models.CharField('模型', max_length=120, blank=True)
    base_url = models.CharField('自定义接口地址', max_length=500, blank=True)
    tool = models.CharField('外部工具', max_length=20, blank=True)
    connection_id = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    connection_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='tool_connections')
    device_name = models.CharField(max_length=80, blank=True)
    platform = models.CharField(max_length=20, blank=True)
    capabilities = models.JSONField(default=list, blank=True)
    last_connected_at = models.DateTimeField(null=True, blank=True)
    key_ciphertext = models.TextField('加密后的 Key', blank=True)
    is_active = models.BooleanField('在团队中', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']

    def __str__(self) -> str:
        return f'{self.name}（{self.role}）' if self.role else self.name

    _TOOL_LOGOS = {
        'codex': 'workroom/logos/openai.svg',
        'workbuddy': 'workroom/logos/workbuddy.png',
        'cursor': 'workroom/logos/cursor.svg',
        'claude-code': 'workroom/logos/anthropic.svg',
    }
    _TEXT_LOGOS = (
        ('deepseek', 'workroom/logos/deepseek.svg'),
        ('glm', 'workroom/logos/glm.png'),
        ('智谱', 'workroom/logos/glm.png'),
        ('kimi', 'workroom/logos/kimi.svg'),
        ('moonshot', 'workroom/logos/kimi.svg'),
        ('qwen', 'workroom/logos/qwen.svg'),
        ('gemini', 'workroom/logos/gemini.svg'),
        ('claude', 'workroom/logos/anthropic.svg'),
        ('anthropic', 'workroom/logos/anthropic.svg'),
    )

    @property
    def logo_file(self) -> str:
        tool = (self.tool or '').lower()
        if tool in self._TOOL_LOGOS:
            return self._TOOL_LOGOS[tool]
        text = f'{self.provider or ""} {self.model_name or ""} {self.name or ""}'.lower()
        for key, path in self._TEXT_LOGOS:
            if key in text:
                return path
        return ''

    @property
    def short_name(self) -> str:
        parts = [part.strip() for part in self.name.split('·') if part.strip()]
        return parts[1] if len(parts) > 1 else self.name

    @property
    def initial(self) -> str:
        return (self.name[:1] or '?').upper()

    @property
    def has_key(self) -> bool:
        return bool(self.key_ciphertext)


class Task(models.Model):
    """A node of the tree. ``parent`` null means a first-level branch."""

    class Status(models.TextChoices):
        TODO = 'todo', '待开始'
        DOING = 'doing', '进行中'
        DONE = 'done', '已完成'
        BLOCKED = 'blocked', '受阻'

    class Priority(models.TextChoices):
        LOW = 'low', '低'
        NORMAL = 'normal', '普通'
        HIGH = 'high', '高'
        URGENT = 'urgent', '紧急'

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='tasks')
    parent = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.CASCADE, related_name='children'
    )
    title = models.CharField('标题', max_length=160)
    detail = models.TextField('工作内容', blank=True)
    acceptance = models.TextField('验收条件', blank=True)
    execution_spec = models.JSONField('任务包配置', default=dict, blank=True)
    guide = models.JSONField('直白任务说明', default=dict, blank=True)
    blocked_reason = models.TextField('现在卡在哪里', blank=True)
    unblock_action = models.TextField('怎样才能继续', blank=True)
    prerequisites = models.ManyToManyField(
        'self', symmetrical=False, blank=True, related_name='following_tasks',
        verbose_name='先要完成的任务',
    )
    assignee = models.ForeignKey(
        Member, null=True, blank=True, on_delete=models.SET_NULL, related_name='tasks'
    )
    start_date = models.DateField('开始', null=True, blank=True)
    end_date = models.DateField('截止', null=True, blank=True)
    status = models.CharField(
        max_length=8, choices=Status.choices, default=Status.TODO
    )
    priority = models.CharField(
        max_length=8, choices=Priority.choices, default=Priority.NORMAL
    )
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self) -> str:
        return self.title

    @property
    def is_done(self) -> bool:
        return self.status == self.Status.DONE

    @property
    def pending_delivery(self):
        cached = getattr(self, '_prefetched_objects_cache', {}).get('deliveries')
        if cached is not None:
            for record in cached:
                if record.status == 'pending':
                    return record
            return None
        return self.deliveries.filter(status='pending').first()



class TaskPackage(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='packages')
    context_revision = models.PositiveIntegerField()
    snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class LibraryEntry(models.Model):
    """Project library: rules, artifacts and decisions live here, not in chat."""

    class Kind(models.TextChoices):
        RULE = 'rule', '规则约束'
        ARTIFACT = 'artifact', '产物'
        DECISION = 'decision', '决策'

    class Source(models.TextChoices):
        HUMAN = 'human', '我'
        AI = 'ai', 'AI'
        EXTERNAL = 'external', '外部工具'

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='library')
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.ARTIFACT)
    title = models.CharField('标题', max_length=160)
    body = models.TextField('内容', blank=True)
    summary = models.CharField('一句话结论', max_length=200, blank=True)
    context = models.TextField('背景 / 约束来源', blank=True)
    options = models.TextField('备选方案', blank=True)
    conclusion = models.TextField('结论 / 落地方式', blank=True)
    tags = models.CharField('标签', max_length=120, blank=True)
    version = models.PositiveIntegerField('版本', default=1)
    is_active = models.BooleanField('有效', default=True)
    source = models.CharField(
        '来源', max_length=12, choices=Source.choices, default=Source.HUMAN
    )
    source_ref = models.CharField('来源位置', max_length=120, blank=True)

    @property
    def tag_list(self) -> list[str]:
        return [tag.strip() for tag in self.tags.split(',') if tag.strip()]
    task = models.ForeignKey(
        Task, null=True, blank=True, on_delete=models.SET_NULL, related_name='library'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self) -> str:
        return self.title

    @property
    def kind_label(self) -> str:
        return self.get_kind_display()


class ReplyJob(models.Model):
    """One in-flight model call, so the page can return immediately and be stopped."""

    class Status(models.TextChoices):
        QUEUED = 'queued', '排队中'
        RUNNING = 'running', '进行中'
        DONE = 'done', '已完成'
        FAILED = 'failed', '失败'
        CANCELLED = 'cancelled', '已停止'

    class Mode(models.TextChoices):
        PLAN = 'plan', '拆任务'
        CHAT = 'chat', '群聊'
        DISCUSS = 'discuss', '讨论'
        IDENTITY = 'identity', '自我介绍'
        AGENT = 'agent', '只读 Agent'
        REVIEW = 'review', '交付审核'

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='jobs')
    member = models.ForeignKey(
        Member, null=True, blank=True, on_delete=models.SET_NULL, related_name='jobs'
    )
    prompt = models.TextField()
    mode = models.CharField(max_length=8, choices=Mode.choices, default=Mode.CHAT)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.RUNNING
    )
    phase = models.CharField('阶段', max_length=16, blank=True)
    partial_answer = models.TextField('已生成回答', blank=True)
    partial_reasoning = models.TextField('已生成思考', blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    run_id = models.UUIDField(default=uuid.uuid4, editable=False)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='reply_jobs',
    )
    delivery = models.ForeignKey(
        'Delivery',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='review_jobs',
    )
    error = models.TextField(blank=True)

    class Meta:
        ordering = ['created_at', 'id']

    def __str__(self) -> str:
        return f'job {self.pk} {self.status}'


class ChatMessage(models.Model):
    """One turn in the project conversation; assistant turns may carry a draft."""

    class Role(models.TextChoices):
        USER = 'user', '我'
        ASSISTANT = 'assistant', 'AI'
        SYSTEM = 'system', '系统'

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='messages')
    member = models.ForeignKey(
        Member, null=True, blank=True, on_delete=models.SET_NULL, related_name='messages'
    )
    role = models.CharField(max_length=12, choices=Role.choices)
    content = models.TextField()
    payload = models.JSONField(default=dict, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']

    def __str__(self) -> str:
        return f'{self.get_role_display()}: {self.content[:30]}'

    @property
    def reasoning(self) -> str:
        payload = self.payload if isinstance(self.payload, dict) else {}
        value = payload.get('reasoning')
        return value if isinstance(value, str) else ''

    @property
    def agent_steps(self) -> list[dict]:
        payload = self.payload if isinstance(self.payload, dict) else {}
        steps = payload.get('steps')
        return steps if isinstance(steps, list) else []

    @property
    def phase_label(self) -> str:
        payload = self.payload if isinstance(self.payload, dict) else {}
        return {'proposal': '提议', 'review': '评审', 'decision': '决策'}.get(
            payload.get('phase', ''), ''
        )

    @property
    def reasoning_label(self) -> str:
        payload = self.payload if isinstance(self.payload, dict) else {}
        if payload.get('reasoning_source') == 'model':
            return '思考过程'
        return '判断依据'

    @property
    def draft_tasks(self) -> list[dict]:
        data = self.payload if isinstance(self.payload, dict) else {}
        tasks = data.get('tasks')
        return tasks if isinstance(tasks, list) else []


class TaskClaim(models.Model):
    """An exclusive execution claim on one task (one active claim per task)."""

    class Status(models.TextChoices):
        ACTIVE = 'active', '进行中'
        RELEASED = 'released', '已释放'
        EXPIRED = 'expired', '已过期'
        COMPLETED = 'completed', '已交付'

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='claims')
    run_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    actor_member = models.ForeignKey(
        Member, null=True, blank=True, on_delete=models.SET_NULL, related_name='claims'
    )
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='task_claims',
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.ACTIVE
    )
    context_revision = models.PositiveIntegerField(default=1)
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.CASCADE)
    workspace_key = models.CharField(max_length=80, blank=True)
    package = models.ForeignKey(TaskPackage, null=True, blank=True, on_delete=models.SET_NULL)
    reconfirm_required = models.BooleanField(default=False)
    claimed_at = models.DateTimeField(auto_now_add=True)
    heartbeat_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ['-claimed_at', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['task'],
                condition=Q(status='active'),
                name='unique_active_task_claim',
            ),
            models.UniqueConstraint(
                fields=['project', 'workspace_key'],
                condition=Q(status='active') & ~Q(workspace_key=''),
                name='unique_active_workspace_claim',
            ),
        ]


class Delivery(models.Model):
    """A structured handoff that waits for review; never marks a task done."""

    class Status(models.TextChoices):
        PENDING = 'pending', '待验收'
        ACCEPTED = 'accepted', '已通过'
        RETURNED = 'returned', '已退回'

    class Source(models.TextChoices):
        HUMAN = 'human', '成员'
        EXTERNAL = 'external', '外部工具'
        AI = 'ai', 'AI'

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='deliveries')
    claim = models.ForeignKey(
        TaskClaim, null=True, blank=True, on_delete=models.SET_NULL, related_name='deliveries'
    )
    submitted_by_member = models.ForeignKey(
        Member, null=True, blank=True, on_delete=models.SET_NULL, related_name='deliveries'
    )
    submitted_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='deliveries',
    )
    summary = models.CharField('摘要', max_length=500)
    body = models.TextField('说明', blank=True)
    baseline = models.CharField('基准', max_length=200, blank=True)
    commit_ref = models.CharField('Commit', max_length=120, blank=True)
    changed_files = models.TextField('变更文件', blank=True)
    test_commands = models.TextField('测试命令', blank=True)
    test_exit_code = models.IntegerField('退出码', null=True, blank=True)
    test_output = models.TextField('测试输出', blank=True)
    source = models.CharField(
        max_length=12, choices=Source.choices, default=Source.EXTERNAL
    )
    idempotency_key = models.CharField(max_length=64)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    evidence_ref = models.CharField('证据引用', max_length=300, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='reviewed_deliveries',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField('验收意见', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    package = models.ForeignKey(TaskPackage, null=True, blank=True, on_delete=models.SET_NULL)
    duration_seconds = models.FloatField(null=True, blank=True)
    accounting = models.JSONField(default=dict, blank=True)
    evidence_checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['task', 'idempotency_key'], name='unique_delivery_key'
            )
        ]


class DeliveryReview(models.Model):
    delivery = models.ForeignKey(Delivery, on_delete=models.CASCADE, related_name='independent_reviews')
    actor_key = models.CharField(max_length=80)
    reviewer_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    reviewer_member = models.ForeignKey(Member, null=True, on_delete=models.SET_NULL)
    verdict = models.CharField(max_length=10, choices=[('approved','建议通过'), ('changes','需要修改')])
    note = models.TextField()
    created_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['delivery','actor_key'], name='unique_delivery_reviewer')]


class WorkerHeartbeat(models.Model):
    """Last seen time of an independent queue worker."""

    worker_id = models.CharField(max_length=120, unique=True)
    hostname = models.CharField(max_length=120, blank=True)
    pid = models.IntegerField(default=0)
    current_job = models.ForeignKey(
        ReplyJob, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    started_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_seen_at']



class UserProfile(models.Model):
    """Who the user is, so agents can pick the right lens."""

    class Role(models.TextChoices):
        DEVELOPER = 'developer', '程序员 / 开发者'
        PRODUCT = 'product', '产品经理'
        DESIGNER = 'designer', '设计师'
        OPS = 'ops', '运营'
        FOUNDER = 'founder', '创始人 / 个体'
        STUDENT = 'student', '学生 / 学习者'
        OTHER = 'other', '其他'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='workroom_profile',
    )
    role = models.CharField('主身份', max_length=16, choices=Role.choices, default=Role.DEVELOPER)
    secondary_roles = models.JSONField('次身份', default=list, blank=True)
    domain = models.CharField('领域', max_length=80, blank=True)
    experience = models.CharField('经验', max_length=40, blank=True)
    stack = models.CharField('常用技术/工具', max_length=200, blank=True)
    goal = models.TextField('当前目标', blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class DocumentChunk(models.Model):
    """资料库切块 + 向量：让资料库能被 AI 按语义检索。

    一块对应资料库里某一节内容，检索命中后连同标题一起进 Prompt，
    回答必须带引用，避免模型编造项目事实。
    """

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name='chunks'
    )
    entry = models.ForeignKey(
        LibraryEntry,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='chunks',
    )
    heading = models.CharField('所属标题', max_length=200, blank=True)
    content = models.TextField('切块内容')
    embedding = models.TextField('向量(JSON)')
    dim = models.PositiveIntegerField('维度', default=0)
    model = models.CharField('向量模型', max_length=80, blank=True)
    content_hash = models.CharField('内容哈希', max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']
        indexes = [
            models.Index(fields=['project', 'model', 'dim'], name='chunk_lookup_idx'),
            models.Index(fields=['entry'], name='chunk_entry_idx'),
        ]

    def __str__(self) -> str:
        return f'{self.heading or "未命名"} · {self.content[:20]}'
