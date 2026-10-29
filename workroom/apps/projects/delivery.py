"""Atomic task claims and structured delivery / human acceptance."""

from __future__ import annotations

import hashlib
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from . import collaboration
from .models import ChatMessage, Delivery, LibraryEntry, Member, Task, TaskClaim
from .permissions import audit, is_server


class DeliveryError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class ClaimConflict(DeliveryError):
    def __init__(self, message: str, claim: TaskClaim) -> None:
        super().__init__(message)
        self.claim = claim


def _actor_member(task: Task, member: Member | None, user) -> Member | None:
    if member is not None:
        if member.project_id != task.project_id or not member.is_active:
            raise DeliveryError("执行者不属于当前项目或已被移除。")
        return member
    if user is not None and getattr(user, "is_authenticated", False):
        linked = task.project.members.filter(user=user, is_active=True).first()
        if linked:
            return linked
    return None


def owns_claim(claim_row: TaskClaim, member: Member | None, user) -> bool:
    """A token issuer is not the executor: bound members stay distinct."""
    if member is not None:
        return claim_row.actor_member_id == member.pk
    return (
        claim_row.actor_member_id is None
        and getattr(user, "is_authenticated", False)
        and claim_row.actor_user_id == user.pk
    )


def _claim_expiry():
    seconds = int(getattr(settings, "WORKROOM_CLAIM_TTL_SECONDS", 1800))
    return timezone.now() + timedelta(seconds=seconds)


def recover_claims(project=None) -> int:
    now = timezone.now()
    queryset = TaskClaim.objects.filter(status=TaskClaim.Status.ACTIVE, expires_at__lt=now)
    if project is not None:
        queryset = queryset.filter(task__project=project)
    return queryset.update(status=TaskClaim.Status.EXPIRED)


def claim(
    task: Task,
    *,
    member: Member | None = None,
    user=None,
) -> tuple[TaskClaim, bool]:
    """Claim a task; the same actor gets the same run, others get a conflict."""
    actor = _actor_member(task, member, user)
    if actor is None and not getattr(user, "is_authenticated", False):
        raise DeliveryError("需要执行者身份（外部成员或登录账号）。")
    now = timezone.now()
    with transaction.atomic():
        locked = Task.objects.select_for_update().get(pk=task.pk)
        recover_claims(locked.project)
        if locked.status == Task.Status.DONE:
            raise DeliveryError(f"任务 {locked.pk} 已经完成，不需要认领。")
        from .task_explanations import ensure_claimable
        ensure_claimable(locked)
        active = (
            TaskClaim.objects.select_for_update()
            .filter(task=locked, status=TaskClaim.Status.ACTIVE)
            .first()
        )
        if active is not None and active.expires_at <= now:
            active.status = TaskClaim.Status.EXPIRED
            active.save(update_fields=["status"])
            active = None
        if active is not None:
            same = owns_claim(active, actor, user)
            if same:
                if active.expires_at < now:
                    active.status = TaskClaim.Status.EXPIRED
                    active.save(update_fields=["status"])
                else:
                    return active, False
            else:
                owner = (
                    active.actor_member.name
                    if active.actor_member
                    else (active.actor_user.get_username() if active.actor_user else "其他执行者")
                )
                raise ClaimConflict(
                    f"任务 {locked.pk} 已被 {owner} 认领（run {active.run_id}），"
                    "等它交付、释放或过期后再试。",
                    active,
                )
        package = collaboration.snapshot(locked, actor)
        package_policy = package.snapshot['policy']
        workspace = package.snapshot['execution']['workspace_key'] if (
            package_policy['require_package'] and package_policy['serialize_workspace']
            and package.snapshot['execution']['work_kind'] == 'code') else ''
        if workspace:
            conflict = TaskClaim.objects.filter(project=locked.project, workspace_key=workspace,
                status=TaskClaim.Status.ACTIVE, expires_at__gt=now).first()
            if conflict:
                raise ClaimConflict('该工作区有其他任务正在执行，请等待释放或使用独立工作树。', conflict)
        claim_row = TaskClaim.objects.create(
            task=locked,
            project=locked.project,
            workspace_key=workspace,
            package=package,
            actor_member=actor,
            actor_user=user if getattr(user, "is_authenticated", False) else None,
            context_revision=locked.project.context_revision,
            expires_at=_claim_expiry(),
        )
        if locked.status != Task.Status.DOING:
            locked.status = Task.Status.DOING
            locked.save(update_fields=["status"])
        audit(
            locked.project,
            user,
            "task.claim",
            f"task={locked.pk} run={claim_row.run_id} member={actor.pk if actor else '-'}",
        )
    return claim_row, True


def heartbeat(claim_row: TaskClaim, *, member: Member | None = None, user=None) -> TaskClaim:
    with transaction.atomic():
        locked = TaskClaim.objects.select_for_update().filter(pk=claim_row.pk).first()
        if locked is None or locked.status != TaskClaim.Status.ACTIVE:
            raise DeliveryError("执行记录已结束或不存在。")
        if locked.expires_at <= timezone.now():
            raise DeliveryError("执行记录已过期，请重新认领。")
        same = owns_claim(locked, member, user)
        if not same:
            raise DeliveryError("不能更新别人的执行记录。")
        locked.heartbeat_at = timezone.now()
        locked.expires_at = _claim_expiry()
        if locked.task.project.context_revision != locked.context_revision:
            locked.reconfirm_required = True
        locked.save(update_fields=["heartbeat_at", "expires_at", "reconfirm_required"])
    return locked


def active_claim(task: Task, *, member: Member | None = None, user=None) -> TaskClaim | None:
    queryset = TaskClaim.objects.filter(task=task, status=TaskClaim.Status.ACTIVE)
    if member is not None:
        queryset = queryset.filter(actor_member=member)
    elif getattr(user, "is_authenticated", False):
        queryset = queryset.filter(actor_user=user)
    return queryset.first()


def _delivery_key(task: Task, actor: str, summary: str, body: str, claim_id) -> str:
    material = f"{task.pk}|{actor}|{summary}|{body}|{claim_id}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def submit(
    task: Task,
    *,
    summary: str,
    body: str = "",
    baseline: str = "",
    commit_ref: str = "",
    changed_files: str = "",
    test_commands: str = "",
    test_exit_code: int | None = None,
    test_output: str = "",
    evidence_ref: str = "",
    idempotency_key: str = "",
    member: Member | None = None,
    user=None,
    source: str = Delivery.Source.EXTERNAL,
    require_claim: bool = True,
    accounting=None,
) -> tuple[Delivery, bool]:
    """Store one structured delivery. Returns (delivery, created)."""
    text = str(summary or "").strip()
    if not text:
        raise DeliveryError("summary 不能为空。")
    limits = {
        "summary": 500,
        "body": 20000,
        "baseline": 200,
        "commit_ref": 120,
        "changed_files": 8000,
        "test_commands": 8000,
        "test_output": 20000,
        "evidence_ref": 300,
    }
    values = {
        "summary": text,
        "body": str(body or ""),
        "baseline": str(baseline or ""),
        "commit_ref": str(commit_ref or ""),
        "changed_files": str(changed_files or ""),
        "test_commands": str(test_commands or ""),
        "test_output": str(test_output or ""),
        "evidence_ref": str(evidence_ref or ""),
        "accounting": collaboration.accounting_data(accounting),
    }
    for field, limit in limits.items():
        if len(values[field]) > limit:
            raise DeliveryError(f"{field} 超过 {limit} 字符上限。")
    if test_exit_code is not None and not -255 <= int(test_exit_code) <= 255:
        raise DeliveryError("test_exit_code 超出合理范围。")

    actor = _actor_member(task, member, user)
    with transaction.atomic():
        locked = Task.objects.select_for_update().get(pk=task.pk)
        if len(idempotency_key) > 64:
            raise DeliveryError("idempotency_key 不能超过 64 字符。")
        if idempotency_key:
            existing = Delivery.objects.filter(task=locked, idempotency_key=idempotency_key).first()
            if existing is not None:
                same_actor = (
                    existing.submitted_by_member_id == actor.pk
                    if actor is not None
                    else existing.submitted_by_member_id is None
                    and existing.submitted_by_user_id == getattr(user, "pk", None)
                )
                if not same_actor or any(getattr(existing, k) != v for k, v in values.items()):
                    raise DeliveryError("交付幂等键已用于其他执行者或不同内容。")
                return existing, False
        claim_row = (
            TaskClaim.objects.select_for_update()
            .filter(task=locked, status=TaskClaim.Status.ACTIVE)
            .first()
        )
        owns = (
            claim_row is not None
            and claim_row.expires_at > timezone.now()
            and owns_claim(claim_row, actor, user)
        )
        if owns and claim_row.context_revision != locked.project.context_revision:
            raise DeliveryError('项目规则已变更，请读取最新任务包并确认上下文版本后再交付。')
        if require_claim and not owns:
            raise DeliveryError("提交前必须先认领该任务；外部工具只能提交自己认领的执行。")
        if not owns and not require_claim:
            claim_row, _ = claim(locked, member=actor, user=user)
            claim_row = TaskClaim.objects.get(pk=claim_row.pk)
        collaboration.validate_submission(claim_row.package if claim_row else None, values)
        key = (idempotency_key or "").strip()[:64] or _delivery_key(
            locked,
            str(actor.pk if actor else getattr(user, "pk", "")),
            values["summary"],
            values["body"],
            claim_row.pk if claim_row else "",
        )
        existing = Delivery.objects.filter(task=locked, idempotency_key=key).first()
        if existing is not None:
            return existing, False
        try:
            delivery = Delivery.objects.create(
                task=locked,
                claim=claim_row,
                package=claim_row.package if claim_row else None,
                duration_seconds=max(0, (timezone.now() - claim_row.claimed_at).total_seconds()) if claim_row else None,
                submitted_by_member=actor,
                submitted_by_user=user if getattr(user, "is_authenticated", False) else None,
                summary=values["summary"][:500],
                body=values["body"],
                baseline=values["baseline"],
                commit_ref=values["commit_ref"],
                changed_files=values["changed_files"],
                test_commands=values["test_commands"],
                test_exit_code=test_exit_code,
                test_output=values["test_output"],
                evidence_ref=values["evidence_ref"],
                accounting=values['accounting'],
                source=source,
                idempotency_key=key,
            )
        except IntegrityError as exc:
            existing = Delivery.objects.filter(task=locked, idempotency_key=key).first()
            if existing is not None:
                return existing, False
            raise DeliveryError("交付保存冲突，请重试。") from exc
        if locked.status != Task.Status.DOING:
            locked.status = Task.Status.DOING
            locked.save(update_fields=["status"])

        ChatMessage.objects.create(
            project=locked.project,
            member=actor,
            role=ChatMessage.Role.ASSISTANT,
            content=_delivery_text(delivery),
            payload={
                "source": "external-delivery",
                "task": locked.pk,
                "delivery": delivery.pk,
            },
        )
        LibraryEntry.objects.create(
            project=locked.project,
            kind=LibraryEntry.Kind.ARTIFACT,
            title=f"{locked.title} · 交付"[:160],
            body=delivery.body or delivery.summary,
            summary=delivery.summary[:200],
            task=locked,
            source=LibraryEntry.Source.EXTERNAL,
            source_ref=f"task:{locked.pk} delivery:{delivery.pk}",
        )
        if not is_server() and claim_row:
            claim_row.status = TaskClaim.Status.RELEASED
            claim_row.save(update_fields=['status'])
        audit(
            locked.project,
            user,
            "delivery.submit",
            f"task={locked.pk} delivery={delivery.pk} claim={claim_row.pk if claim_row else '-'}",
        )
    return delivery, True


def confirm_context(task, revision, *, member=None, user=None):
    with transaction.atomic():
        locked = Task.objects.select_for_update().select_related('project').get(pk=task.pk)
        actor = _actor_member(locked, member, user)
        claim_row = active_claim(locked, member=actor, user=user)
        if claim_row is None or claim_row.expires_at <= timezone.now():
            raise DeliveryError('请先认领任务。')
        if revision != locked.project.context_revision:
            raise DeliveryError('上下文版本不匹配，请重新读取最新任务包。')
        package = collaboration.snapshot(locked, actor)
        policy = package.snapshot['policy']
        workspace = package.snapshot['execution']['workspace_key'] if (
            policy['require_package'] and policy['serialize_workspace']
            and package.snapshot['execution']['work_kind'] == 'code') else ''
        if claim_row.workspace_key and workspace != claim_row.workspace_key:
            raise DeliveryError('工作区已变更，请先释放旧执行再重新认领。')
        recover_claims(locked.project)
        if workspace:
            conflict = TaskClaim.objects.filter(project=locked.project, workspace_key=workspace,
                status=TaskClaim.Status.ACTIVE).exclude(pk=claim_row.pk).first()
            if conflict:
                raise ClaimConflict('该工作区已被其他任务占用。', conflict)
        claim_row.project = locked.project
        claim_row.workspace_key = workspace
        claim_row.package = package
        claim_row.context_revision = revision
        claim_row.reconfirm_required = False
        claim_row.save(update_fields=['context_revision', 'reconfirm_required', 'package', 'project', 'workspace_key'])
        audit(locked.project, user, 'task.context.confirm', f'run={claim_row.run_id} revision={revision}')
    return claim_row


def _delivery_text(delivery: Delivery) -> str:
    lines = [f"交付：{delivery.summary}"]
    if delivery.body:
        lines.append("")
        lines.append(delivery.body)
    facts = []
    if delivery.baseline:
        facts.append(f"基准 {delivery.baseline}")
    if delivery.commit_ref:
        facts.append(f"commit {delivery.commit_ref}")
    if delivery.changed_files:
        facts.append("变更 " + delivery.changed_files.replace("\n", " / ")[:400])
    if delivery.test_commands:
        facts.append("测试 " + delivery.test_commands.replace("\n", " / ")[:300])
    if delivery.test_exit_code is not None:
        facts.append(f"退出码 {delivery.test_exit_code}")
    if delivery.evidence_ref:
        facts.append(f"证据 {delivery.evidence_ref}")
    if facts:
        lines.append("")
        lines.append(" · ".join(facts))
    lines.append("")
    lines.append("状态：待人工验收（AI 意见只是建议，不会自动通过）。")
    return "\n".join(lines)


def review_prompt(delivery: Delivery) -> str:
    task = delivery.task
    lines = [
        f"请审核任务 {task.pk}「{task.title}」的交付，只给建议，不要宣布通过。",
        f"任务要求：{task.detail or '（未填写）'}",
        f"验收条件：{task.acceptance or '（未填写，明确说明证据不足）'}",
        "",
        f"交付摘要：{delivery.summary}",
        f"说明：{delivery.body or '（无）'}",
        f"基准：{delivery.baseline or '（无）'}",
        f"Commit：{delivery.commit_ref or '（无）'}",
        f"变更文件：{delivery.changed_files or '（无）'}",
        f"测试命令：{delivery.test_commands or '（无）'}",
        f"退出码：{delivery.test_exit_code if delivery.test_exit_code is not None else '（无）'}",
        f"测试输出：{delivery.test_output[:1500] if delivery.test_output else '（无）'}",
        f"证据引用：{delivery.evidence_ref or '（无）'}",
        "",
        "请按验收条件逐条判断证据是否充分；缺证据就明确写“不足”，不要凭自报通过。"
        "给出：1) 建议（通过/退回）2) 逐条理由 3) 下一步由谁做什么。",
    ]
    return "\n".join(lines)


def accept(delivery: Delivery, *, user, note: str = "", evidence_ref: str = "", evidence_checked=False) -> Delivery:
    with transaction.atomic():
        locked = Delivery.objects.select_for_update().select_related("task").get(pk=delivery.pk)
        if locked.status != Delivery.Status.PENDING:
            raise DeliveryError("这条交付已经处理过。")
        collaboration.validate_acceptance(locked, evidence_checked=evidence_checked)
        if not (
            evidence_ref.strip()
            or locked.evidence_ref
            or (locked.changed_files and locked.test_commands and locked.test_exit_code == 0)
        ):
            raise DeliveryError("交付缺少证据：请补充证据引用，或变更文件及通过的测试记录。")
        task = Task.objects.select_for_update().get(pk=locked.task_id)
        locked.status = Delivery.Status.ACCEPTED
        locked.reviewed_by = user
        locked.reviewed_at = timezone.now()
        locked.review_note = str(note or "")[:4000]
        locked.evidence_checked_at = timezone.now() if evidence_checked else None
        if evidence_ref:
            locked.evidence_ref = str(evidence_ref)[:300]
        locked.save(
            update_fields=[
                "status",
                "reviewed_by",
                "reviewed_at",
                "review_note",
                "evidence_ref",
                "evidence_checked_at",
            ]
        )
        task.status = Task.Status.DONE
        task.save(update_fields=["status"])
        TaskClaim.objects.filter(task=task, status=TaskClaim.Status.ACTIVE).update(
            status=TaskClaim.Status.COMPLETED
        )
        audit(
            task.project,
            user,
            "delivery.accept",
            f"task={task.pk} delivery={locked.pk} note={locked.review_note[:200]}",
        )
    return locked


def return_delivery(delivery: Delivery, *, user, note: str, evidence_ref: str = "") -> Delivery:
    reason = str(note or "").strip()
    if not reason:
        raise DeliveryError("退回必须写明原因。")
    with transaction.atomic():
        locked = Delivery.objects.select_for_update().select_related("task").get(pk=delivery.pk)
        if locked.status != Delivery.Status.PENDING:
            raise DeliveryError("这条交付已经处理过。")
        task = Task.objects.select_for_update().get(pk=locked.task_id)
        locked.status = Delivery.Status.RETURNED
        locked.reviewed_by = user
        locked.reviewed_at = timezone.now()
        locked.review_note = reason[:4000]
        if evidence_ref:
            locked.evidence_ref = str(evidence_ref)[:300]
        locked.save(
            update_fields=[
                "status",
                "reviewed_by",
                "reviewed_at",
                "review_note",
                "evidence_ref",
            ]
        )
        if not is_server() or task.status == Task.Status.DONE:
            task.status = Task.Status.DOING if is_server() else Task.Status.TODO
            task.save(update_fields=["status"])
        TaskClaim.objects.filter(task=task, status=TaskClaim.Status.ACTIVE).update(
            status=TaskClaim.Status.RELEASED
        )
        ChatMessage.objects.create(
            project=task.project,
            role=ChatMessage.Role.SYSTEM,
            content=f"任务 #{task.pk}「{task.title}」的交付被退回：{reason}",
        )
        audit(
            task.project,
            user,
            "delivery.return",
            f"task={task.pk} delivery={locked.pk} reason={reason[:200]}",
        )
    return locked
