"""Forms for one AI member's model connection."""

from __future__ import annotations

from django import forms

from . import ai_client, providers
from .models import Member


class NewMemberForm(forms.Form):
    """Add an AI: only the connection is required, identity is self-assigned."""

    name = forms.CharField(
        label='名称',
        max_length=80,
        widget=forms.TextInput(attrs={'placeholder': '例如：Kimi', 'autocomplete': 'off'}),
    )
    provider = forms.ChoiceField(label='模型商', choices=providers.CHOICES)
    model_name = forms.CharField(
        label='模型名称',
        required=False,
        max_length=120,
        widget=forms.TextInput(
            attrs={'placeholder': '留空使用模型商默认模型', 'autocomplete': 'off'}
        ),
    )
    base_url = forms.CharField(
        label='自定义接口地址',
        required=False,
        max_length=500,
        widget=forms.URLInput(
            attrs={'placeholder': 'https://api.example.com/v1', 'autocomplete': 'off'}
        ),
    )
    api_key = forms.CharField(
        label='API Key',
        required=True,
        max_length=ai_client.MAX_KEY_CHARS,
        strip=False,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={'autocomplete': 'off', 'spellcheck': 'false'},
        ),
        error_messages={
            'required': '新接入的 AI 需要填 API Key。',
            'max_length': 'API Key 不能超过 512 个字符。',
        },
    )

    def clean_name(self) -> str:
        return (self.cleaned_data.get('name') or '').strip()

    def clean_api_key(self) -> str:
        value = self.cleaned_data.get('api_key') or ''
        try:
            return ai_client.validate_api_key(value)
        except ai_client.PlannerClientError as exc:
            raise forms.ValidationError(exc.message) from exc

    def clean(self):
        data = super().clean()
        provider = data.get('provider') or ''
        preset = providers.get(provider)
        if preset is None:
            self.add_error('provider', '模型商不可用，请刷新后重试。')
            return data
        if provider == providers.CUSTOM:
            base_url = (data.get('base_url') or '').strip()
            model = (data.get('model_name') or '').strip()
            if not base_url:
                self.add_error('base_url', '选择「自定义」时必须填接口地址。')
            else:
                try:
                    ai_client.normalize_base_url(base_url)
                except ai_client.PlannerClientError as exc:
                    self.add_error('base_url', exc.message)
            if not model:
                self.add_error('model_name', '选择「自定义」时必须填模型名称。')
        else:
            base_url = preset['base_url']
            model = (data.get('model_name') or '').strip() or preset['model']
        data['resolved_base_url'] = base_url
        data['resolved_model'] = model
        return data


class MemberConfigForm(forms.Form):
    name = forms.CharField(
        label='名称',
        max_length=80,
        widget=forms.TextInput(attrs={'placeholder': '例如：DeepSeek', 'autocomplete': 'off'}),
        error_messages={'required': '请填写名称。'},
    )
    role = forms.CharField(
        label='角色',
        required=False,
        max_length=80,
        widget=forms.TextInput(attrs={'placeholder': '例如：后端 / 架构 / 测试'}),
    )
    duty = forms.ChoiceField(
        label='讨论职责',
        choices=Member.Duty.choices,
        widget=forms.Select(),
        help_text='提议出方案，评审挑问题，决策拍板，执行落地。',
    )
    persona = forms.CharField(
        label='身份与职责',
        required=False,
        max_length=2000,
        widget=forms.Textarea(
            attrs={
                'rows': 5,
                'placeholder': '例如：你是资深后端架构师，负责登录、权限与数据模型。'
                '评审时先指出风险和边界，再给方案；不要写前端代码。',
            }
        ),
    )
    provider = forms.ChoiceField(
        label='模型商',
        choices=providers.CHOICES,
        widget=forms.Select(),
        error_messages={'required': '请选择模型商。'},
    )
    model_name = forms.CharField(
        label='模型名称',
        required=False,
        max_length=120,
        widget=forms.TextInput(
            attrs={'placeholder': '留空使用模型商默认模型', 'autocomplete': 'off'}
        ),
    )
    base_url = forms.CharField(
        label='自定义接口地址',
        required=False,
        max_length=500,
        widget=forms.URLInput(
            attrs={'placeholder': 'https://api.example.com/v1', 'autocomplete': 'off'}
        ),
    )
    api_key = forms.CharField(
        label='API Key',
        required=False,
        max_length=ai_client.MAX_KEY_CHARS,
        strip=False,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={
                'autocomplete': 'off',
                'spellcheck': 'false',
                'placeholder': '留空表示不修改已保存的 Key',
            },
        ),
        error_messages={'max_length': 'API Key 不能超过 512 个字符。'},
    )
    clear_key = forms.BooleanField(label='清除已保存的 Key', required=False)

    def clean_name(self) -> str:
        value = (self.cleaned_data.get('name') or '').strip()
        if not value:
            raise forms.ValidationError('请填写名称。')
        return value

    def clean_api_key(self) -> str:
        value = self.cleaned_data.get('api_key') or ''
        if not value:
            return ''
        try:
            return ai_client.validate_api_key(value)
        except ai_client.PlannerClientError as exc:
            raise forms.ValidationError(exc.message) from exc

    def clean(self):
        data = super().clean()
        provider = data.get('provider') or ''
        preset = providers.get(provider)
        if preset is None:
            self.add_error('provider', '模型商不可用，请刷新后重试。')
            return data

        if provider == providers.CUSTOM:
            base_url = (data.get('base_url') or '').strip()
            model = (data.get('model_name') or '').strip()
            if not base_url:
                self.add_error('base_url', '选择「自定义」时必须填接口地址。')
            else:
                try:
                    ai_client.normalize_base_url(base_url)
                except ai_client.PlannerClientError as exc:
                    self.add_error('base_url', exc.message)
            if not model:
                self.add_error('model_name', '选择「自定义」时必须填模型名称。')
        else:
            base_url = preset['base_url']
            model = (data.get('model_name') or '').strip() or preset['model']
            if not model:
                self.add_error('model_name', '这个模型商没有默认模型，请手动填写。')

        data['resolved_base_url'] = base_url
        data['resolved_model'] = model
        return data


class ExternalMemberForm(forms.Form):
    """Identity of an external tool that joined the team (no model/key)."""

    name = forms.CharField(
        label='名称',
        max_length=80,
        widget=forms.TextInput(attrs={'placeholder': '例如：WorkBuddy'}),
    )
    role = forms.CharField(
        label='角色',
        required=False,
        max_length=80,
        widget=forms.TextInput(attrs={'placeholder': '例如：执行 / 前端'}),
    )
    persona = forms.CharField(
        label='职责说明',
        required=False,
        max_length=2000,
        widget=forms.Textarea(
            attrs={'rows': 4, 'placeholder': '例如：负责改代码、跑测试，做完回报任务状态。'}
        ),
    )

    def clean_name(self) -> str:
        return (self.cleaned_data.get('name') or '').strip()
