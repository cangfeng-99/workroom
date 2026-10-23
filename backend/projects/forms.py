"""Project form: only name and description come from the client."""

from __future__ import annotations

from django import forms

from projects.models import Project


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ('name', 'description')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].label = '项目名称'
        self.fields['name'].widget.attrs['maxlength'] = 120
        self.fields['description'].label = '项目说明（可选）'
        self.fields['description'].widget.attrs['rows'] = 4
