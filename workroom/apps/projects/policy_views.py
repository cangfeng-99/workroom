"""Project-owner policy and task-package forms, separate from execution code."""

from django import forms
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from . import collaboration
from .delivery import DeliveryError
from .library import bump_context
from .models import Task
from .permissions import audit, project_for


class PolicyForm(forms.Form):
    require_package = forms.BooleanField(label="领取前必须完成任务包", required=False)
    serialize_workspace = forms.BooleanField(
        label="同一工作区一次只允许一个软件任务", required=False
    )
    independent_high_risk = forms.BooleanField(label="高风险交付必须独立复核", required=False)
    require_checks = forms.BooleanField(
        label="软件交付必须通过约定检查并由负责人核对", required=False
    )


class PackageForm(forms.Form):
    plain_summary = forms.CharField(label="这项任务具体要做什么", required=False, max_length=800,
                                   widget=forms.Textarea(attrs={"rows": 2}))
    work_steps = forms.CharField(label="按什么顺序做（每行一步）", required=False, max_length=12000,
                                widget=forms.Textarea(attrs={"rows": 5}))
    frontend_result = forms.CharField(label="页面要做成什么样（每行一项）", required=False, max_length=12000,
                                     widget=forms.Textarea(attrs={"rows": 3}))
    backend_result = forms.CharField(label="后端要做什么（每行一项）", required=False, max_length=12000,
                                    widget=forms.Textarea(attrs={"rows": 3}))
    done_result = forms.CharField(label="看到什么结果才算完成（每行一项）", required=False, max_length=12000,
                                 widget=forms.Textarea(attrs={"rows": 3}))
    prerequisites = forms.ModelMultipleChoiceField(label="开始前先完成哪些任务", queryset=Task.objects.none(), required=False)
    detail = forms.CharField(
        label="工作内容", widget=forms.Textarea(attrs={"rows": 3}), max_length=20000
    )
    acceptance = forms.CharField(
        label="验收条件", widget=forms.Textarea(attrs={"rows": 3}), max_length=8000
    )
    work_kind = forms.ChoiceField(
        label="任务类型", choices=[("code", "软件开发"), ("general", "文档、研究等普通任务")]
    )
    workspace_key = forms.CharField(
        label="工作区标识",
        initial="main",
        max_length=80,
        help_text="共享同一文件夹的任务使用同一标识；不同标识须对应真实独立工作树。",
    )
    baseline = forms.CharField(label="代码基准版本", max_length=200, required=False)
    allowed_paths = forms.CharField(
        label="允许修改的相对路径（每行一条）",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="例如 src/**；这会检查交付清单，不代替本机沙箱权限。",
    )
    relevant_files = forms.CharField(
        label="相关文件（每行一条）", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )
    check_commands = forms.CharField(
        label="检查命令（每行一条）",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="这里只记录要求，不会在服务器直接执行。",
    )
    risk = forms.ChoiceField(
        label="风险", choices=[("low", "低"), ("normal", "普通"), ("high", "高：权限、数据迁移等")]
    )

    def __init__(self, *args, task=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.task = task
        if task:
            self.fields['prerequisites'].queryset = task.project.tasks.exclude(pk=task.pk)

    def clean_prerequisites(self):
        chosen = self.cleaned_data['prerequisites']
        if self.task:
            from .task_explanations import validate_prerequisites
            try:
                validate_prerequisites(self.task, chosen)
            except DeliveryError as exc:
                raise forms.ValidationError(exc.message) from None
        return chosen

    def clean(self):
        data = super().clean()
        if not self.errors:
            try:
                self.spec = collaboration.execution_spec(
                    {
                        key: value
                        for key, value in data.items()
                        if key not in {"detail", "acceptance"}
                    }
                )
            except DeliveryError as exc:
                raise forms.ValidationError(exc.message) from None
        return data


@require_http_methods(["GET", "POST"])
def policy_view(request, pk):
    project = project_for(request, pk, owner=True)
    form = PolicyForm(
        request.POST if request.method == "POST" else None,
        initial=collaboration.policy_for(project),
    )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            project.policy = form.cleaned_data
            project.save(update_fields=["policy"])
            bump_context(project)
            audit(project, request.user, "project.policy", "更新协作策略")
        return redirect("projects:policy", pk=pk)
    return render(
        request,
        "projects/policy.html",
        dict(project=project, form=form, metrics=collaboration.metrics(project), owner_controls=True),
    )


@require_http_methods(["GET", "POST"])
def package_view(request, pk, task_id):
    project = project_for(request, pk, owner=True)
    task = get_object_or_404(Task, pk=task_id, project=project)
    guide = task.guide if isinstance(task.guide, dict) else {}
    form = PackageForm(
        request.POST if request.method == "POST" else None,
        initial={
            **collaboration.execution_spec(task.execution_spec),
            "detail": task.detail,
            "acceptance": task.acceptance,
            "plain_summary": guide.get('summary', ''),
            "work_steps": '\n'.join(guide.get('steps', [])),
            "frontend_result": '\n'.join(guide.get('frontend', [])),
            "backend_result": '\n'.join(guide.get('backend', [])),
            "done_result": '\n'.join(guide.get('outcomes', [])),
            "prerequisites": task.prerequisites.all(),
        },
        task=task,
    )
    if request.method == "GET":
        for key in ["allowed_paths", "relevant_files", "check_commands"]:
            form.initial[key] = "\n".join(form.initial[key])
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                from .models import Project
                from .task_explanations import validate_prerequisites
                Project.objects.select_for_update().get(pk=project.pk)
                has_plain_fields = any(key in request.POST for key in ['plain_summary', 'work_steps', 'frontend_result', 'backend_result', 'done_result'])
                change_prerequisites = has_plain_fields or 'prerequisites' in request.POST
                if change_prerequisites:
                    validate_prerequisites(task, form.cleaned_data['prerequisites'])
                task.execution_spec = form.spec
                task.detail = form.cleaned_data["detail"]
                task.acceptance = form.cleaned_data["acceptance"]
                if has_plain_fields:
                    task.guide = dict(guide, summary=form.cleaned_data['plain_summary'],
                                      steps=collaboration.lines(form.cleaned_data['work_steps']),
                                      frontend=collaboration.lines(form.cleaned_data['frontend_result']),
                                      backend=collaboration.lines(form.cleaned_data['backend_result']),
                                      outcomes=collaboration.lines(form.cleaned_data['done_result']))
                task.save(update_fields=["execution_spec", "detail", "acceptance", "guide"])
                if change_prerequisites:
                    task.prerequisites.set(form.cleaned_data['prerequisites'])
                bump_context(project)
                audit(project, request.user, "task.package", f"task={task.pk}")
        except DeliveryError as exc:
            form.add_error('prerequisites', exc.message)
        else:
            return redirect("projects:task_delivery", pk=pk, task_id=task_id)
    return render(request, "projects/package.html", dict(project=project, task=task, form=form, owner_controls=True))
