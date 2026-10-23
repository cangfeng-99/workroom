"""Projects, their team members and the project task tree (T016A).

A project only remembers where its folder lives. Members are collaboration
records: a human member points at an existing account, an AI member is only a
named role entry and is never a login. Roles never grant file access or
administrative rights; the project owner keeps both.
"""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Project(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='projects'
    )
    name = models.CharField(max_length=120)
    description = models.TextField(max_length=2000, blank=True)
    workspace_path = models.CharField(max_length=1024, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-updated_at', '-pk')

    def __str__(self) -> str:
        return self.name


class ProjectMember(models.Model):
    """One collaboration role in a project: a real account or a named AI slot."""

    class Kind(models.TextChoices):
        HUMAN = 'human', '真人'
        AI = 'ai', 'AI'

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='members')
    kind = models.CharField(max_length=8, choices=Kind.choices)
    name = models.CharField(max_length=150)
    role = models.CharField(max_length=80, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='project_memberships',
        null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('pk',)
        constraints: ClassVar[list] = [
            models.UniqueConstraint(
                fields=('project', 'user'),
                condition=models.Q(user__isnull=False),
                name='uniq_project_member_user',
            )
        ]

    def __str__(self) -> str:
        return f'{self.project_id}:{self.name}'

    def clean(self) -> None:
        super().clean()
        if self.kind == self.Kind.HUMAN:
            if self.user is None:
                raise ValidationError({'user': '真人成员必须关联一个已有账号。'})
            if not self.user.is_active:
                raise ValidationError({'user': '该账号当前不可用。'})
            if self.name and self.name != self.user.username:
                raise ValidationError({'name': '真人成员的名字取账号用户名。'})
        elif self.user is not None:
            raise ValidationError({'user': 'AI 成员不是登录账号，不能关联用户。'})

    def save(self, *args, **kwargs):
        # The display name of a human member is always the account username.
        if self.kind == self.Kind.HUMAN and self.user_id is not None:
            self.name = self.user.username
        return super().save(*args, **kwargs)


class TaskNode(models.Model):
    """One dated task in a project; parents mean "split into", not "after"."""

    class Status(models.TextChoices):
        TODO = 'todo', '待开始'
        IN_PROGRESS = 'in_progress', '进行中'
        BLOCKED = 'blocked', '受阻'
        REVIEW = 'review', '待验收'
        DONE = 'done', '已完成'

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='tasks')
    parent = models.ForeignKey(
        'self', on_delete=models.PROTECT, related_name='children', null=True, blank=True
    )
    title = models.CharField(max_length=160)
    description = models.TextField(max_length=4000, blank=True)
    assignee = models.ForeignKey(
        ProjectMember, on_delete=models.SET_NULL, related_name='assigned_tasks',
        null=True, blank=True,
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.TODO)
    start_date = models.DateField()
    end_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('start_date', 'pk')

    def __str__(self) -> str:
        return self.title

    def clean(self) -> None:
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({'end_date': '结束日期不能早于开始日期。'})
        if self.parent_id is not None and self.parent.project_id != self.project_id:
            raise ValidationError({'parent': '父任务必须属于同一个项目。'})
        if self.assignee_id is not None and self.assignee.project_id != self.project_id:
            raise ValidationError({'assignee': '负责人必须属于同一个项目。'})
