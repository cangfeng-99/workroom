"""Durable execution and HTTP collaboration contracts (no model network)."""

import hashlib
import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.projects import queue
from apps.projects.models import (
    ChatMessage,
    Delivery,
    Member,
    Project,
    ProjectMembership,
    ReplyJob,
    Task,
    ToolToken,
)


@override_settings(WORKROOM_MODE="server")
class RuntimeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("runtime-owner")
        self.project = Project.objects.create(name="runtime", goal_title="ship", owner=self.user)
        ProjectMembership.objects.create(project=self.project, user=self.user, role="owner")
        self.ai = Member.objects.create(project=self.project, name="reviewer", kind="ai")

    def test_submission_only_persists_and_two_workers_do_not_claim_same_job(self):
        with patch("threading.Thread.start") as start:
            job = queue.submit(self.project, self.ai, "hello", "chat", self.user)
        start.assert_not_called()
        self.assertEqual(job.status, "queued")
        one = queue.claim_next("worker-one")
        self.assertEqual(one.pk, job.pk)
        self.assertIsNone(queue.claim_next("worker-two"))

    def test_independent_worker_completes_queued_job(self):
        job = queue.submit(self.project, self.ai, "hello", "chat", self.user)
        answer = {"text": "test answer", "reasoning": "", "reasoning_source": ""}
        with patch("apps.projects.views._stream_one", return_value=answer):
            self.assertTrue(queue.run_once("test-worker"))
        job.refresh_from_db()
        self.assertEqual(job.status, "done")
        self.assertEqual(ChatMessage.objects.get(project=self.project).content, "test answer")

    def test_cancel_during_provider_response_discards_output(self):
        job = queue.submit(self.project, self.ai, "hello", "chat", self.user)

        def cancelled(_job):
            queue.cancel(self.project, job.pk, self.user)
            return {"text": "late", "reasoning": "", "reasoning_source": ""}

        with patch("apps.projects.views._stream_one", side_effect=cancelled):
            queue.run_once("cancel-worker")
        self.assertFalse(ChatMessage.objects.filter(project=self.project).exists())
        job.refresh_from_db()
        self.assertEqual(job.status, "cancelled")

    def test_expired_run_fails_without_automatic_paid_retry(self):
        job = queue.submit(self.project, self.ai, "hello", "chat", self.user)
        queue.claim_next("lost-worker")
        ReplyJob.objects.filter(pk=job.pk).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(queue.recover_stale(), 1)
        self.assertIsNone(queue.claim_next("new-worker"))
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")

    def test_cancelled_old_worker_is_fenced_after_manual_retry(self):
        job = queue.submit(self.project, self.ai, "hello", "chat", self.user)
        old = queue.claim_next("old")
        marker = queue.CURRENT_RUN.set((job.pk, old.run_id))
        try:
            queue.cancel(self.project, job.pk, self.user)
            queue.retry(self.project, job.pk, self.user)
            queue.claim_next("new")
            self.assertFalse(queue.active(job.pk))
        finally:
            queue.CURRENT_RUN.reset(marker)

    def test_queued_cancel_is_terminal(self):
        job = queue.submit(self.project, self.ai, "hello", "chat", self.user)
        queue.cancel(self.project, job.pk, self.user)
        self.assertIsNone(queue.claim_next("worker"))

    def test_cancel_and_retry_between_output_and_completion_cannot_finish_new_run(self):
        from apps.projects import views

        job = queue.submit(self.project, self.ai, 'hello', 'chat', self.user)
        original = views._job_message

        def rescheduled(*args, **kwargs):
            result = original(*args, **kwargs)
            queue.cancel(self.project, job.pk, self.user)
            queue.retry(self.project, job.pk, self.user)
            queue.claim_next('replacement')
            return result

        with patch('apps.projects.views._stream_one', return_value={
            'text': 'before cancellation', 'reasoning': '', 'reasoning_source': '',
        }), patch('apps.projects.views._job_message', side_effect=rescheduled):
            queue.run_once('original')
        job.refresh_from_db()
        self.assertEqual(job.status, 'running')


@override_settings(WORKROOM_MODE="server")
class HttpToolsTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("http-owner")
        self.project = Project.objects.create(name="owned", goal_title="ship", owner=self.owner)
        ProjectMembership.objects.create(project=self.project, user=self.owner, role="owner")
        self.member = Member.objects.create(
            project=self.project, name="Codex", tool="codex", kind="external"
        )
        self.task = Task.objects.create(project=self.project, title="work", assignee=self.member)
        self.raw = "wrk_" + "a" * 40
        self.token = ToolToken.objects.create(
            project=self.project,
            user=self.owner,
            member=self.member,
            name="test",
            scope="execute",
            token_hash=hashlib.sha256(self.raw.encode()).hexdigest(),
        )

    def call(self, name, **args):
        return self.client.post(
            reverse("projects:tool_api", args=[name]),
            data=json.dumps({"project": str(self.project.pk), **args}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + self.raw,
        )

    def test_missing_revoked_read_only_cross_project_and_removed_member(self):
        url = reverse("projects:tool_api", args=["get_project"])
        self.assertEqual(
            self.client.post(url, "{}", content_type="application/json").status_code, 401
        )
        other = Project.objects.create(name="private", goal_title="private")
        self.assertEqual(self.call("get_project", project=str(other.pk)).status_code, 404)
        self.token.scope = "read"
        self.token.save()
        self.assertEqual(self.call("claim_task", task=str(self.task.pk)).status_code, 403)
        self.token.revoked_at = timezone.now()
        self.token.save()
        self.assertEqual(self.call("get_project").status_code, 401)

    def test_claim_submit_repeat_and_human_accept(self):
        self.assertEqual(self.call("claim_task", task=str(self.task.pk)).status_code, 200)
        args = dict(
            task=str(self.task.pk),
            summary="work delivered",
            idempotency_key="http-delivery",
            evidence_ref="test-run-42",
        )
        self.assertEqual(self.call("submit_result", **args).status_code, 200)
        self.assertEqual(self.call("submit_result", **args).status_code, 200)
        self.assertEqual(Delivery.objects.count(), 1)
        self.assertEqual(
            self.call("update_task_status", task=str(self.task.pk), status="done").status_code, 400
        )
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("projects:task_delivery", args=[self.project.pk, self.task.pk]),
            {"action": "accept", "delivery": Delivery.objects.get().pk, "note": "checked evidence"},
        )
        self.assertEqual(response.status_code, 302)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "done")

    def test_viewer_cannot_accept_or_bypass_done_endpoint(self):
        viewer = User.objects.create_user("http-viewer")
        ProjectMembership.objects.create(project=self.project, user=viewer, role="viewer")
        self.client.force_login(viewer)
        url = reverse("projects:task_delivery", args=[self.project.pk, self.task.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(
            self.client.post(url, {"action": "accept", "delivery": 1}).status_code, 403
        )
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("projects:task_status", args=[self.project.pk, self.task.pk]),
            {"status": "done"},
        )
        self.assertEqual(response.status_code, 403)
