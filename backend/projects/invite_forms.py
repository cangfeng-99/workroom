"""Invitation creation form: role label plus a fixed 1/7/30 day lifetime."""

from __future__ import annotations

from django import forms


class InviteCreateForm(forms.Form):
    role = forms.CharField(
        max_length=80, required=False, label='分工角色',
        widget=forms.TextInput(attrs={'placeholder': '例如：前端 / 测试'}),
    )
    days = forms.ChoiceField(
        required=False,
        choices=(('1', '1 天'), ('7', '7 天'), ('30', '30 天')),
        initial='7',
        label='有效期',
    )

    def clean_days(self) -> int:
        return int(self.cleaned_data['days'] or '7')
