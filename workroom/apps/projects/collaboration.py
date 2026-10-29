"""Shared, server-enforced policy and immutable task handoffs. No shell execution."""

import json
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from fnmatch import fnmatchcase

from django.db import transaction

from .models import Delivery, DeliveryReview, TaskPackage
from .permissions import audit, is_server


def default_policy():
    return dict(
        require_package=True,
        serialize_workspace=True,
        independent_high_risk=True,
        require_checks=True,
    )


def policy_for(project):
    defaults = default_policy()
    defaults["require_package"] = False  # Legacy projects opt in explicitly.
    policy = {key: bool(project.policy.get(key, value)) for key, value in defaults.items()}
    if not is_server():
        policy['independent_high_risk'] = False
    return policy


def _error(message):
    from .delivery import DeliveryError

    raise DeliveryError(message)


def lines(value):
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


def relative_path(value):
    path = str(value).replace("\\", "/").strip()
    if not path or path.startswith("/") or ":" in path or ".." in path.split("/") or "\x00" in path:
        _error("文件范围必须使用工作区内的相对路径，不能含绝对路径或 ..。")
    return path.removeprefix("./")


def execution_spec(value):
    if not isinstance(value, dict):
        _error("任务包必须是对象。")
    spec = dict(
        work_kind=value.get("work_kind", "code"),
        workspace_key=value.get("workspace_key", "main"),
        baseline=str(value.get("baseline", "")).strip(),
        risk=value.get("risk", "normal"),
    )
    if spec["work_kind"] not in {"code", "general"} or spec["risk"] not in {
        "low",
        "normal",
        "high",
    }:
        _error("任务类型或风险等级无效。")
    if not isinstance(spec["workspace_key"], str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]{1,80}", spec["workspace_key"]
    ):
        _error("工作区标识只接受1至80个字母、数字、下划线、点或短横线。")
    if len(spec["baseline"]) > 200:
        _error("基准版本不能超过200字符。")
    for key in ["allowed_paths", "relevant_files", "check_commands"]:
        values = lines(value.get(key, []))
        if len(values) > 100 or any(len(x) > 1000 for x in values):
            _error("任务包列表过长。")
        spec[key] = [relative_path(x) for x in values] if key != "check_commands" else values
    return spec


def package_data(task, *, validate=True):
    policy = policy_for(task.project)
    spec = execution_spec(task.execution_spec)
    if validate and policy["require_package"]:
        missing = [
            label
            for value, label in [(task.detail, "工作内容"), (task.acceptance, "验收条件")]
            if not value.strip()
        ]
        if spec["work_kind"] == "code":
            missing += [
                label
                for value, label in [
                    (spec["baseline"], "基准版本"),
                    (spec["allowed_paths"], "允许修改的范围"),
                    (spec["check_commands"], "检查命令"),
                ]
                if not value
            ]
        if missing:
            _error("任务包尚不完整，请负责人补充：" + "、".join(missing))
    data = dict(
        task_id=task.pk,
        title=task.title,
        detail=task.detail,
        acceptance=task.acceptance,
        project_id=task.project_id,
        goal=task.project.goal_title,
        context_revision=task.project.context_revision,
        policy=policy,
        execution=spec,
        rules=list(
            task.project.library.filter(is_active=True, kind__in=["rule", "decision"]).values(
                "id", "title", "kind", "version", "body", "summary"
            )
        ),
    )
    from .task_explanations import explanation
    readable = explanation(task)
    data['plain_instructions'] = task.guide
    data['readiness'] = {key: readable[key] for key in ['label', 'blockers', 'next_action', 'owner']}
    data['prerequisites'] = [dict(id=row.pk, title=row.title, status=row.status)
                             for row in readable['prerequisites']]
    if len(json.dumps(data, ensure_ascii=False).encode()) > 256 * 1024:
        _error("任务包超过256KiB，请负责人整理规则或缩小任务。")
    return data


def snapshot(task, actor=None):
    data = package_data(task)
    data['executor'] = dict(member_id=actor.pk, name=actor.name, tool=actor.tool,
        connection_id=str(actor.connection_id) if actor.connection_id else None,
        model=actor.model_name or None, provider=actor.provider or None) if actor else None
    return TaskPackage.objects.create(task=task, context_revision=task.project.context_revision, snapshot=data)


def path_allowed(path, patterns):
    path = relative_path(path)
    return any(
        fnmatchcase(path, pattern) or (pattern.endswith("/**") and path == pattern[:-3])
        for pattern in patterns
    )


def validate_submission(package, values):
    if package is None or not package.snapshot["policy"]["require_package"]:
        return
    spec = package.snapshot["execution"]
    if spec["work_kind"] == "code":
        if values["baseline"] != spec["baseline"]:
            _error("交付基准与认领时的任务包不一致。")
        if not lines(values["changed_files"]):
            _error("软件任务交付须填写变更文件。")
        if any(
            not path_allowed(path, spec["allowed_paths"]) for path in lines(values["changed_files"])
        ):
            _error("交付文件超出任务包允许范围，请先由负责人修改范围并重新确认。")


def accounting_data(value):
    if not value:
        return {}
    if not isinstance(value, dict) or set(value) - {
        "cost_amount",
        "currency",
        "model",
        "provider",
        "usage_count",
        "usage_unit",
    }:
        _error("费用记录字段不正确。")
    result = {
        key: str(val)[:120] for key, val in value.items() if key not in {"cost_amount", "currency"}
    }
    amount = value.get("cost_amount")
    if amount not in (None, ""):
        try:
            number = Decimal(str(amount))
        except InvalidOperation:
            _error("费用必须是有效数字。")
        currency = str(value.get("currency", "")).upper()
        if (
            not number.is_finite()
            or number < 0
            or number > 1000000
            or not re.fullmatch("[A-Z]{3}", currency)
        ):
            _error("费用必须非负且提供三位币种代码。")
        result.update(cost_amount=str(number), currency=currency)
    result["source"] = "reported"
    return result


def review_delivery(record, *, member=None, user=None, verdict, note):
    from .delivery import _actor_member

    if verdict not in {"approved", "changes"} or not str(note or "").strip():
        _error("复核须选择结论并写明证据和理由。")
    with transaction.atomic():
        locked = (
            Delivery.objects.select_for_update()
            .select_related("task", "submitted_by_member")
            .get(pk=record.pk)
        )
        if locked.status != "pending":
            _error("仅待验收交付可以复核。")
        actor = _actor_member(locked.task, member, user)
        if actor is None and not getattr(user, "is_authenticated", False):
            _error("需要复核者身份。")
        same = (
            actor.pk == locked.submitted_by_member_id
            if actor
            else (locked.submitted_by_member_id is None and locked.submitted_by_user_id == user.pk)
        )
        if same:
            _error("独立复核不能由原执行者完成。")
        key = f"member:{actor.pk}" if actor else f"user:{user.pk}"
        review, _ = DeliveryReview.objects.update_or_create(
            delivery=locked,
            actor_key=key,
            defaults=dict(
                reviewer_member=actor,
                reviewer_user=user if getattr(user, "is_authenticated", False) else None,
                verdict=verdict,
                note=str(note).strip()[:4000],
            ),
        )
        audit(
            locked.task.project,
            user,
            "delivery.independent_review",
            f"delivery={locked.pk} actor={key} verdict={verdict}",
        )
        return review


def validate_acceptance(record, *, evidence_checked):
    package = record.package
    if not is_server():
        if not evidence_checked:
            _error('请先勾选已核对交付结果和检查证据。')
        if record.test_exit_code is not None and record.test_exit_code != 0:
            _error('这次检查未通过，请退回修改并重新提交通过的记录。')
        if package:
            if package.context_revision != record.task.project.context_revision:
                _error('任务要求或规则已变化，请退回后按最新要求重新交付。')
            checks = package.snapshot['execution']['check_commands']
            if checks and (record.test_exit_code != 0 or not record.test_output.strip()
                           or not set(checks).issubset(lines(record.test_commands))):
                _error('任务约定的检查记录不完整，请补齐命令、通过退出码和输出后重新交付。')
        return
    if package is None or not package.snapshot["policy"]["require_package"]:
        return
    if package.context_revision != record.task.project.context_revision:
        _error("交付后的任务包或规则已变化，请重新确认并交付。")
    spec = package.snapshot["execution"]
    policy = package.snapshot["policy"]
    if policy["require_checks"] and spec["work_kind"] == "code":
        if not evidence_checked:
            _error("负责人须明确核对检查证据。")
        if (
            record.test_exit_code != 0
            or not record.test_output.strip()
            or not set(spec["check_commands"]).issubset(lines(record.test_commands))
        ):
            _error("缺少任务包要求的通过检查记录与输出。")
    reviews = list(record.independent_reviews.all())
    if any(x.verdict == "changes" for x in reviews):
        _error("独立复核仍有待修改意见，请先解决。")
    if (
        spec["risk"] == "high"
        and policy["independent_high_risk"]
        and not any(x.verdict == "approved" for x in reviews)
    ):
        _error("高风险交付必须由其他执行者独立复核。")


def metrics(project):
    totals = defaultdict(Decimal)
    actors = {}
    first = set()
    unknown = 0
    for record in project_delivery_rows(project):
        label = record.submitted_by_member.name if record.submitted_by_member else "成员"
        key = (
            f"member:{record.submitted_by_member_id}"
            if record.submitted_by_member_id
            else f"user:{record.submitted_by_user_id}"
        )
        row = actors.setdefault(
            key, dict(name=label, deliveries=0, accepted=0, returned=0, first_pass=0)
        )
        row["deliveries"] += 1
        row["accepted"] += record.status == "accepted"
        row["returned"] += record.status == "returned"
        if record.task_id not in first and record.status == "accepted":
            row["first_pass"] += 1
        first.add(record.task_id)
        amount = record.accounting.get("cost_amount")
        if amount is None:
            unknown += 1
        else:
            totals[record.accounting["currency"]] += Decimal(amount)
    return dict(
        actors=list(actors.values()),
        costs={k: str(v) for k, v in totals.items()},
        unknown_cost_count=unknown,
    )


def project_delivery_rows(project):
    return (
        Delivery.objects.filter(task__project=project)
        .select_related("submitted_by_member")
        .order_by("created_at", "pk")
        .iterator()
    )
