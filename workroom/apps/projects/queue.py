"""Database queue and worker lease helpers.

Local mode keeps the original in-process daemon thread. Server mode only ever
writes queued rows; ``manage.py workroom_worker`` claims and runs them.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
import uuid
from contextvars import ContextVar
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Project, ReplyJob, WorkerHeartbeat
from .permissions import is_server

CURRENT_RUN = ContextVar("workroom_run", default=None)


class JobStopped(Exception):
    """Cancellation or a lost lease fences all late worker output."""


def active(job_id: int) -> bool:
    query = ReplyJob.objects.filter(pk=job_id, status=ReplyJob.Status.RUNNING)
    run = CURRENT_RUN.get()
    if run is not None:
        query = query.filter(run_id=run[1])
        if is_server():
            query = query.filter(lease_expires_at__gt=timezone.now())
    return query.exists()


def ensure_active(job_id: int) -> None:
    if not active(job_id):
        raise JobStopped()


def update_active(job_id: int, **values) -> bool:
    """Fence progress/completion in the UPDATE itself, including a retried run."""
    query = ReplyJob.objects.filter(pk=job_id, status=ReplyJob.Status.RUNNING)
    run = CURRENT_RUN.get()
    if run is not None:
        query = query.filter(run_id=run[1])
        if is_server():
            query = query.filter(lease_expires_at__gt=timezone.now())
    return bool(query.update(**values))


def run_once(worker_id: str) -> bool:
    """One durable execution. Network calls never hold the claim transaction."""
    from django.db import close_old_connections

    from . import views

    recover_stale()
    WorkerHeartbeat.objects.update_or_create(
        worker_id=worker_id,
        defaults={
            "hostname": socket.gethostname(),
            "pid": os.getpid(),
            "last_seen_at": timezone.now(),
            "current_job": None,
        },
    )
    job = claim_next(worker_id)
    if job is None:
        return False
    heartbeat(job.pk, job.run_id, worker_id)
    stop = threading.Event()
    pulse = threading.Thread(
        target=heartbeat_loop, args=(job.pk, job.run_id, worker_id, stop), daemon=True
    )
    pulse.start()
    marker = CURRENT_RUN.set((job.pk, job.run_id))
    try:
        views._run_job(job.pk)
    except JobStopped:
        pass
    except Exception:
        ReplyJob.objects.filter(
            pk=job.pk, run_id=job.run_id, status=ReplyJob.Status.RUNNING
        ).update(
            status=ReplyJob.Status.FAILED,
            finished_at=timezone.now(),
            error="执行异常，请检查服务器日志后重试。",
            lease_expires_at=None,
        )
    finally:
        stop.set()
        pulse.join(timeout=2)
        CURRENT_RUN.reset(marker)
        WorkerHeartbeat.objects.filter(worker_id=worker_id).update(
            last_seen_at=timezone.now(), current_job=None
        )
        close_old_connections()
    return True


def submit(project: Project, member, text: str, mode: str, user=None, delivery=None) -> ReplyJob:
    if not is_server():
        job = ReplyJob.objects.create(
            project=project, member=member, prompt=text, mode=mode, delivery=delivery
        )
        transaction.on_commit(
            lambda: threading.Thread(target=_run_local, args=(job.pk, job.run_id), daemon=True).start()
        )
        return job
    return ReplyJob.objects.create(
        project=project,
        member=member,
        prompt=text,
        mode=mode,
        status=ReplyJob.Status.QUEUED,
        delivery=delivery,
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )


def _run_local(job_id: int, run_id) -> None:
    from django.db import close_old_connections

    from . import views

    marker = CURRENT_RUN.set((job_id, run_id))
    try:
        views._run_job(job_id)
    except JobStopped:
        pass
    except Exception as exc:
        logging.getLogger(__name__).error(json.dumps({
            'event': 'local_job_failed', 'job_id': job_id, 'run_id': str(run_id),
            'error_type': type(exc).__name__,
            'sqlite_code': getattr(exc.__cause__, 'sqlite_errorname', None),
        }))
        ReplyJob.objects.filter(pk=job_id, run_id=run_id, status=ReplyJob.Status.RUNNING).update(
            status=ReplyJob.Status.FAILED, finished_at=timezone.now(),
            error='执行异常，请检查本机日志，确认原因后再重试。',
        )
    finally:
        CURRENT_RUN.reset(marker)
        close_old_connections()


def cancel(project: Project, job_id: int, user=None) -> bool:
    now = timezone.now()
    changed = ReplyJob.objects.filter(
        pk=job_id,
        project=project,
        status__in=[ReplyJob.Status.QUEUED, ReplyJob.Status.RUNNING],
    ).update(
        status=ReplyJob.Status.CANCELLED,
        finished_at=now,
        lease_expires_at=None,
        error="cancelled by user",
    )
    if changed and is_server():
        from .permissions import audit

        audit(project, user, "job.cancel", f"job={job_id}")
    return bool(changed)


def retry(project: Project, job_id: int, user=None) -> bool:
    now = timezone.now()
    server = is_server()
    run_id = uuid.uuid4()
    changed = ReplyJob.objects.filter(
        pk=job_id,
        project=project,
        status__in=[ReplyJob.Status.FAILED, ReplyJob.Status.CANCELLED],
    ).update(
        status=ReplyJob.Status.QUEUED if server else ReplyJob.Status.RUNNING,
        finished_at=None,
        lease_expires_at=None,
        heartbeat_at=None,
        error="",
        partial_answer="",
        partial_reasoning="",
        phase="",
        run_id=run_id,
        updated_at=now,
    )
    if changed and server:
        from .permissions import audit

        audit(project, user, "job.retry", f"job={job_id}")
    elif changed:
        threading.Thread(target=_run_local, args=(job_id, run_id), daemon=True).start()
    return bool(changed)


def claim_next(worker_id: str) -> ReplyJob | None:
    """Atomically claim one queued job. SQLite uses a short IMMEDIATE transaction."""
    lease = int(getattr(settings, "WORKROOM_JOB_LEASE_SECONDS", 600))
    now = timezone.now()
    with transaction.atomic():
        candidate = (
            ReplyJob.objects.select_for_update()
            .filter(status=ReplyJob.Status.QUEUED)
            .order_by("created_at", "id")
            .first()
        )
        if candidate is None:
            return None
        run_id = uuid.uuid4()
        updated = ReplyJob.objects.filter(pk=candidate.pk, status=ReplyJob.Status.QUEUED).update(
            status=ReplyJob.Status.RUNNING,
            run_id=run_id,
            attempts=candidate.attempts + 1,
            heartbeat_at=now,
            lease_expires_at=now + timedelta(seconds=lease),
            error="",
        )
        if not updated:
            return None
    return ReplyJob.objects.select_related("project", "member").get(pk=candidate.pk)


def heartbeat(job_id: int, run_id, worker_id: str) -> None:
    lease = int(getattr(settings, "WORKROOM_JOB_LEASE_SECONDS", 600))
    now = timezone.now()
    ReplyJob.objects.filter(pk=job_id, run_id=run_id, status=ReplyJob.Status.RUNNING).update(
        heartbeat_at=now, lease_expires_at=now + timedelta(seconds=lease)
    )
    WorkerHeartbeat.objects.filter(worker_id=worker_id).update(
        last_seen_at=now, current_job_id=job_id
    )


def recover_stale() -> int:
    """Mark expired running jobs failed; never auto-retry (would double-charge)."""
    now = timezone.now()
    return ReplyJob.objects.filter(status=ReplyJob.Status.RUNNING, lease_expires_at__lt=now).update(
        status=ReplyJob.Status.FAILED,
        finished_at=now,
        lease_expires_at=None,
        error="worker lease expired; retry manually after checking the run",
    )


def worker_online(seconds: int = 120) -> bool:
    cut = timezone.now() - timedelta(seconds=seconds)
    return WorkerHeartbeat.objects.filter(last_seen_at__gte=cut).exists()


def worker_health() -> list[dict]:
    now = timezone.now()
    return [
        {
            "id": item.worker_id,
            "hostname": item.hostname,
            "last_seen": item.last_seen_at,
            "stale": (now - item.last_seen_at).total_seconds() > 120,
            "current_job": item.current_job_id,
        }
        for item in WorkerHeartbeat.objects.all()[:10]
    ]


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def heartbeat_loop(job_id: int, run_id, worker_id: str, stop: threading.Event) -> None:
    from django.db import close_old_connections

    try:
        while not stop.wait(20):
            try:
                heartbeat(job_id, run_id, worker_id)
            except Exception:  # noqa: BLE001 - retry heartbeat without losing the job
                close_old_connections()
                time.sleep(1)
    finally:
        close_old_connections()
