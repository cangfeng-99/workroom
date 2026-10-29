"""Owner-controlled project basics; changes advance the shared context."""

from django import forms
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .library import bump_context
from .models import Project
from .permissions import audit, is_server, project_for


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ['name', 'goal_title', 'goal_detail', 'goal_deadline']
        widgets = {
            'goal_detail': forms.Textarea(attrs={'rows': 5}),
            'goal_deadline': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }


@require_http_methods(['GET', 'POST'])
def settings_view(request, pk):
    if not is_server():
        raise Http404()
    project = project_for(request, pk, owner=True)
    form = ProjectForm(request.POST if request.method == 'POST' else None, instance=project)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            form.save()
            bump_context(project)
            audit(project, request.user, 'project.settings', '更新项目基础信息')
        return redirect('projects:space', pk=pk)
    return render(request, 'projects/settings.html', {'project': project, 'form': form, 'owner_controls': True})
