"""Human-visible claim, evidence and acceptance workflow."""

import secrets

from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from . import collaboration, delivery, queue
from .models import Delivery, ReplyJob, Task
from .permissions import is_server, project_for, role_of


@require_http_methods(["GET", "POST"])
def task_delivery(request, pk, task_id):
    if not is_server():
        return personal_task_delivery(request, pk, task_id)
    project = project_for(request, pk, write=request.method == "POST")
    task = get_object_or_404(Task, project=project, pk=task_id)
    error = ""
    if request.method == "POST":
        try:
            action = request.POST.get("action", "")
            if action == "claim":
                delivery.claim(task, user=request.user)
            elif action == "confirm_context":
                delivery.confirm_context(task, int(request.POST.get("revision", 0)), user=request.user)
            elif action == "submit":
                code = request.POST.get("test_exit_code", "").strip()
                record, created = delivery.submit(
                    task,
                    summary=request.POST.get("summary", ""),
                    body=request.POST.get("body", ""),
                    changed_files=request.POST.get("changed_files", ""),
                    baseline=request.POST.get("baseline", ""),
                    commit_ref=request.POST.get("commit_ref", ""),
                    test_commands=request.POST.get("test_commands", ""),
                    test_exit_code=int(code) if code else None,
                    test_output=request.POST.get("test_output", ""),
                    evidence_ref=request.POST.get("evidence_ref", ""),
                    idempotency_key=request.POST.get("idempotency_key", ""),
                    user=request.user,
                    source=Delivery.Source.HUMAN,
                    accounting={'cost_amount':request.POST.get('cost_amount',''), 'currency':request.POST.get('currency','')}
                        if request.POST.get('cost_amount','').strip() else None,
                )
                risk = str((task.execution_spec or {}).get("risk") or "normal").lower()
                if created and risk == "high":
                    reviewer = (
                        project.members.filter(kind="ai", duty="review", is_active=True)
                        .exclude(key_ciphertext="")
                        .first()
                    )
                    if reviewer is None:
                        reviewer = (
                            project.members.filter(kind="ai", is_active=True)
                            .exclude(key_ciphertext="")
                            .first()
                        )
                    if reviewer:
                        job = queue.submit(
                            project,
                            reviewer,
                            delivery.review_prompt(record),
                            ReplyJob.Mode.REVIEW,
                            user=request.user,
                        )
                        job.delivery = record
                        job.save(update_fields=["delivery"])
            elif action == 'independent_review':
                record = get_object_or_404(Delivery, task=task, pk=request.POST.get('delivery'))
                collaboration.review_delivery(record, user=request.user,
                    verdict=request.POST.get('verdict',''), note=request.POST.get('note',''))
            elif action in {"accept", "return"}:
                project_for(request, pk, owner=True)
                record = get_object_or_404(Delivery, task=task, pk=request.POST.get("delivery"))
                if action == "accept":
                    delivery.accept(
                        record,
                        user=request.user,
                        note=request.POST.get("note", ""),
                        evidence_ref=request.POST.get("evidence_ref", ""),
                        evidence_checked=request.POST.get('evidence_checked') == 'on',
                    )
                else:
                    delivery.return_delivery(
                        record, user=request.user, note=request.POST.get("note", "")
                    )
            else:
                raise delivery.DeliveryError("未知操作。")
        except (delivery.DeliveryError, ValueError) as exc:
            error = getattr(exc, "message", "测试退出码必须是整数。")
        else:
            return redirect(reverse("projects:task_delivery", args=[pk, task_id]))
    package_error = ''
    try:
        collaboration.package_data(task)
    except delivery.DeliveryError as exc:
        package_error = exc.message
    return render(
        request,
        "projects/delivery.html",
        {
            "project": project,
            "task": task,
            "error": error,
            "records": task.deliveries.select_related("submitted_by_member", "reviewed_by", 'package')
                .prefetch_related('independent_reviews__reviewer_member','independent_reviews__reviewer_user'),
            'package_error': package_error,
            'package_spec': collaboration.execution_spec(task.execution_spec),
            "can_edit": role_of(request.user, project) in {"owner", "editor"},
            "can_review": role_of(request.user, project) == "owner",
            "claim": delivery.active_claim(task, user=request.user),
        },
    )


def personal_task_delivery(request, pk, task_id):
    """Local human confirmation; never schedules a model or impersonates a tool."""
    from . import user_profile
    project = project_for(request, pk, write=request.method == 'POST')
    task = get_object_or_404(Task, pk=task_id, project=project)
    actor = request.user if request.user.is_authenticated else (project.owner or user_profile.local_user())
    error = ''
    fields = ['summary', 'body', 'baseline', 'commit_ref', 'changed_files',
              'test_commands', 'test_output', 'evidence_ref', 'test_exit_code', 'idempotency_key', 'note']
    values = {key: request.POST.get(key, '') for key in fields}
    if request.method == 'POST':
        try:
            action = request.POST.get('action', '')
            if action == 'submit':
                raw_code = values['test_exit_code'].strip()
                delivery.submit(task, summary=values['summary'], body=values['body'],
                                baseline=values['baseline'], commit_ref=values['commit_ref'],
                                changed_files=values['changed_files'], test_commands=values['test_commands'],
                                test_exit_code=int(raw_code) if raw_code else None,
                                test_output=values['test_output'], evidence_ref=values['evidence_ref'],
                                idempotency_key=values['idempotency_key'], user=actor,
                                source=Delivery.Source.HUMAN, require_claim=False)
            elif action in {'accept', 'return'}:
                record = get_object_or_404(Delivery, task=task, pk=request.POST.get('delivery'))
                if action == 'accept':
                    delivery.accept(record, user=actor, note=values['note'],
                                    evidence_ref=values['evidence_ref'],
                                    evidence_checked=request.POST.get('evidence_checked') == 'on')
                else:
                    delivery.return_delivery(record, user=actor, note=values['note'])
            else:
                raise delivery.DeliveryError('请选择提交、确认完成或退回修改。')
        except (delivery.DeliveryError, ValueError) as exc:
            error = getattr(exc, 'message', '检查退出码必须是整数。')
        else:
            return redirect('projects:task_delivery', pk=pk, task_id=task_id)
    records = task.deliveries.select_related('submitted_by_member', 'reviewed_by', 'package').order_by('-pk')
    pending = records.filter(status=Delivery.Status.PENDING).exists()
    values['idempotency_key'] = values['idempotency_key'] or 'personal-' + secrets.token_urlsafe(18)
    spec = collaboration.execution_spec(task.execution_spec)
    if request.method == 'GET':
        values['baseline'] = spec['baseline']
        values['test_commands'] = '\n'.join(spec['check_commands'])
    return render(request, 'projects/personal_delivery.html', {
        'project': project, 'task': task, 'records': records, 'pending': pending,
        'error': error, 'form_values': values, 'package_spec': spec,
        'can_submit': not pending and task.status != Task.Status.DONE,
    })


@require_POST
def retry_job(request, pk, job_id):
    project = project_for(request, pk, write=True)
    queue.retry(project, job_id, request.user)
    return redirect(reverse("projects:space", args=[pk]) + "?tab=chat")


@require_POST
def dismiss_job(request, pk, job_id):
    """Hide one failed run.

    A failure stays in the database for audit but moves to 已停止, which is the
    existing "settled, do nothing more" state, so it stops showing up under
    「最近失败的运行」 without deleting the record.
    """
    project = project_for(request, pk, write=True)
    project.jobs.filter(pk=job_id, status=ReplyJob.Status.FAILED).update(
        status=ReplyJob.Status.CANCELLED
    )
    return redirect(reverse("projects:space", args=[pk]) + "?tab=chat")


@require_POST
def dismiss_failed_jobs(request, pk):
    """Clear the whole failed-run list in one go."""
    project = project_for(request, pk, write=True)
    project.jobs.filter(status=ReplyJob.Status.FAILED).update(
        status=ReplyJob.Status.CANCELLED
    )
    return redirect(reverse("projects:space", args=[pk]) + "?tab=chat")
