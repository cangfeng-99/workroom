"""Concentrated project setup: workspace authorization and initial members.

A folder path is only remembered when the owner ticks the separate
authorization checkbox; choosing a directory never grants file access. Initial
human members must be existing active accounts, and an AI member is only a
named role entry with no login. Nothing here creates accounts or shares files.
"""

from __future__ import annotations

from pathlib import Path

from django import forms
from django.contrib.auth import get_user_model
from workspaces.services import Workspace, WorkspaceError

from projects.forms import ProjectForm
from projects.models import ProjectMember

INVALID_ROOT = '该文件夹当前不可用（需为已存在的普通目录，不能是链接、UNC 或设备路径）。'


class ProjectSetupForm(ProjectForm):
    """One sectioned form; the workspace is optional and explicitly granted."""

    setup_path = forms.CharField(
        label='工作空间文件夹完整路径', max_length=1024, required=False, strip=False
    )
    authorize_workspace = forms.BooleanField(
        label='本次登录同时授权这个文件夹', required=False
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields['setup_path'].widget.attrs.update(
            {'placeholder': '例如 D:\\项目\\资料', 'autocomplete': 'off', 'spellcheck': 'false'}
        )

    def clean(self):
        data = super().clean()
        if not data.get('authorize_workspace'):
            # A path without the explicit checkbox is remembered by neither the
            # project nor the session, but the typed value stays on screen.
            return data
        raw = data.get('setup_path') or ''
        if not raw:
            raise forms.ValidationError({'setup_path': '勾选授权后，请填写或选择文件夹。'})
        try:
            Workspace(Path(raw)).validate_root()
        except (WorkspaceError, TypeError, ValueError):
            raise forms.ValidationError({'setup_path': INVALID_ROOT})
        data['setup_path'] = str(Path(raw))
        return data


class InitialMemberForm(forms.Form):
    """One optional row in the initial-team formset.

    A completely empty row is skipped. Human rows resolve an exact active
    account; AI rows only keep a name and role.
    """

    kind = forms.ChoiceField(
        label='类型', choices=ProjectMember.Kind.choices, required=False, initial='human'
    )
    username = forms.CharField(label='已有账号用户名', max_length=150, required=False)
    name = forms.CharField(label='AI 成员名称', max_length=80, required=False)
    role = forms.CharField(label='分工角色', max_length=80, required=False)

    def clean(self):
        data = super().clean()
        kind = data.get('kind') or ProjectMember.Kind.HUMAN
        username = (data.get('username') or '').strip()
        name = (data.get('name') or '').strip()
        role = (data.get('role') or '').strip()
        data['skip'] = False
        if not username and not name and not role:
            data['skip'] = True
            return data
        if kind == ProjectMember.Kind.AI:
            if not name:
                raise forms.ValidationError('AI 成员请填写名称。')
            data['kind'] = kind
            data['name'] = name
            data['user'] = None
            data['role'] = role
            return data
        if kind != ProjectMember.Kind.HUMAN:
            raise forms.ValidationError('成员类型无效。')
        if not username:
            raise forms.ValidationError('真人成员请填写已有账号的用户名。')
        user = get_user_model().objects.filter(username=username, is_active=True).first()
        if user is None:
            raise forms.ValidationError('找不到这个可用账号；不会自动创建新账号。')
        data['kind'] = kind
        data['name'] = user.username
        data['user'] = user
        data['role'] = role
        return data


InitialMemberFormSet = forms.formset_factory(
    InitialMemberForm, extra=3, max_num=10, validate_max=True, absolute_max=10
)
