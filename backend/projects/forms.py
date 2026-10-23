"""Project form: only server-approved fields come from the client."""

from __future__ import annotations

from django import forms

from projects.models import Project


class ProjectForm(forms.ModelForm):
    """The owner and workspace path are never taken from the browser."""

    class Meta:
        model = Project
        fields = ('name', 'description', 'instructions')

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields['name'].label = '项目名称'
        self.fields['name'].widget.attrs['maxlength'] = 120
        self.fields['description'].label = '项目说明（可选）'
        self.fields['description'].widget.attrs['rows'] = 3
        self.fields['instructions'].label = '项目指令（可选）'
        self.fields['instructions'].widget.attrs['rows'] = 5
        self.fields['instructions'].widget.attrs['maxlength'] = 6000
