"""Forms for the project board: members, tasks and explicit workspace path.

Every field is an explicit allowlist. The client never chooses a project, an
owner or a member kind beyond the two documented values, and a member update
can only carry ``status``.
"""

from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model

from projects.models import ProjectMember, TaskNode


class MemberForm(forms.Form):
    """Add a human member by exact username, or a named AI role entry."""

    kind = forms.ChoiceField(label='类型', choices=ProjectMember.Kind.choices)
    username = forms.CharField(label='已有账号用户名', max_length=150, required=False)
    name = forms.CharField(label='AI 成员名称', max_length=80, required=False)
    role = forms.CharField(label='分工角色', max_length=80, required=False)

    def __init__(self, *args, project, **kwargs) -> None:
        self.project = project
        super().__init__(*args, **kwargs)

    def clean(self):
        data = super().clean()
        kind = data.get('kind')
        if kind == ProjectMember.Kind.HUMAN:
            username = (data.get('username') or '').strip()
            if not username:
                raise forms.ValidationError('请输入已有账号的用户名。')
            user = get_user_model().objects.filter(username=username, is_active=True).first()
            if user is None:
                raise forms.ValidationError('找不到这个可用账号；不会自动创建新账号。')
            if self.project.members.filter(user=user).exists():
                raise forms.ValidationError('该账号已经是本项目成员。')
            data['user'] = user
            data['name'] = user.username
        elif kind == ProjectMember.Kind.AI:
            name = (data.get('name') or '').strip()
            if not name:
                raise forms.ValidationError('请填写 AI 成员名称。')
            data['name'] = name
            data['user'] = None
        return data


class MemberUpdateForm(forms.ModelForm):
    """Only the collaborative role can be edited; identity stays fixed."""

    class Meta:
        model = ProjectMember
        fields = ('role',)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields['role'].label = '分工角色'


class TaskForm(forms.ModelForm):
    """Owner form for creating and editing a task; ``parent`` only on create."""

    class Meta:
        model = TaskNode
        fields = (
            'title', 'description', 'assignee', 'status', 'start_date', 'end_date', 'parent',
        )

    def __init__(self, *args, project, include_parent: bool = True, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.project = project
        # The model's cross-project check runs during _post_clean, before the
        # view assigns the project on commit=False.
        if self.instance.project_id is None:
            self.instance.project = project
        self.fields['assignee'].queryset = project.members.all()
        self.fields['assignee'].label = '负责人'
        self.fields['title'].label = '任务标题'
        self.fields['description'].label = '任务内容'
        self.fields['status'].label = '状态'
        self.fields['start_date'].label = '开始日期'
        self.fields['end_date'].label = '结束日期'
        for name in ('start_date', 'end_date'):
            self.fields[name].widget = forms.DateInput(
                format='%Y-%m-%d', attrs={'type': 'date'}
            )
        if include_parent:
            self.fields['parent'].queryset = project.tasks.all()
            self.fields['parent'].label = '父任务（拆分为子任务）'
        else:
            # A task cannot be moved to another parent after creation, so no
            # cycle can be introduced by editing.
            self.fields.pop('parent')

    def clean(self):
        data = super().clean()
        assignee = data.get('assignee')
        if assignee is not None and assignee.project_id != self.project.pk:
            raise forms.ValidationError('负责人必须属于同一个项目。')
        parent = data.get('parent')
        if parent is not None and parent.project_id != self.project.pk:
            raise forms.ValidationError('父任务必须属于同一个项目。')
        start = data.get('start_date')
        end = data.get('end_date')
        if start and end and end < start:
            raise forms.ValidationError({'end_date': '结束日期不能早于开始日期。'})
        return data


class TaskStatusForm(forms.ModelForm):
    """The only thing a human member may change: their own task's status."""

    class Meta:
        model = TaskNode
        fields = ('status',)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields['status'].label = '状态'


class WorkspaceForm(forms.Form):
    """Explicit folder path posted by the owner; validated by the file service."""

    path = forms.CharField(label='工作空间文件夹完整路径', max_length=1024, strip=False)
