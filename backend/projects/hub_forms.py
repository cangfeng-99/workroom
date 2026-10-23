"""Forms for the project space: real activity notes and owner instructions."""

from __future__ import annotations

from django import forms

from projects.models import Project


class ProjectMessageForm(forms.Form):
    content = forms.CharField(
        label='发布动态', max_length=4000,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': '记录进展、决定或需要团队知道的事情…',
            'maxlength': 4000,
        }),
    )


class ProjectInstructionsForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ('instructions',)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields['instructions'].label = '项目指令'
        self.fields['instructions'].required = False
        self.fields['instructions'].widget.attrs.update({
            'rows': 6,
            'maxlength': 6000,
            'placeholder': '写下团队协作约定、交付标准或验收要求…',
        })
