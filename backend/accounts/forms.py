"""Account forms: native Django user creation with Chinese labels."""

from __future__ import annotations

from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User


class SignupForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = '用户名'
        self.fields['username'].help_text = '必填，150 个字符以内；可使用字母、数字和 @/./+/-/_。'
        self.fields['password1'].label = '密码'
        self.fields['password1'].help_text = '至少 8 位，不能是纯数字或常见密码。'
        self.fields['password2'].label = '确认密码'
        self.fields['password2'].help_text = '再次输入相同的密码。'
