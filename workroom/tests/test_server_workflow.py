"""Server collaboration regressions: distinct actors, leases and evidence."""

from datetime import timedelta
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.projects import delivery, mcp
from apps.projects.auth_views import _hash_token
from apps.projects.models import (
    Delivery,
    Invitation,
    Member,
    Project,
    ProjectMembership,
    Task,
    TaskClaim,
)


@override_settings(WORKROOM_MODE="server")
class WorkflowTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner")
        self.project = Project.objects.create(name="shared", goal_title="ship", owner=self.owner)
        ProjectMembership.objects.create(project=self.project, user=self.owner, role="owner")
        self.a = Member.objects.create(
            project=self.project, kind="external", name="A", tool="codex"
        )
        self.b = Member.objects.create(
            project=self.project, kind="external", name="B", tool="workbuddy"
        )
        self.task = Task.objects.create(project=self.project, title="Implement", assignee=self.a)

    def test_same_token_issuer_does_not_merge_two_external_actors(self):
        delivery.claim(self.task, member=self.a, user=self.owner)
        with self.assertRaises(delivery.ClaimConflict):
            delivery.claim(self.task, member=self.b, user=self.owner)

    def test_project_settings_owner_only_and_context_revision(self):
        url = f'/p/{self.project.pk}/settings/'
        editor = User.objects.create_user('editor')
        ProjectMembership.objects.create(project=self.project, user=editor, role='editor')
        self.client.force_login(editor)
        self.assertEqual(self.client.post(url, {'name': 'changed'}).status_code, 403)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).status_code, 200)
        revision = self.project.context_revision
        response = self.client.post(url, {
            'name': 'Server team', 'goal_title': 'Collaborate', 'goal_detail': 'Linux deployment',
            'goal_deadline': '2026-12-01',
        })
        self.assertEqual(response.status_code, 302)
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, 'Server team')
        self.assertGreater(self.project.context_revision, revision)
        self.assertEqual(self.project.owner_id, self.owner.pk)

    def test_failed_job_can_be_seen_and_manually_retried(self):
        from apps.projects.models import ReplyJob

        job = ReplyJob.objects.create(project=self.project, mode='single', status='failed')
        self.client.force_login(self.owner)
        response = self.client.get(reverse('projects:space', args=[self.project.pk]) + '?tab=chat')
        self.assertContains(response, reverse('projects:job_retry', args=[self.project.pk, job.pk]))
        self.client.post(reverse('projects:job_retry', args=[self.project.pk, job.pk]))
        job.refresh_from_db()
        self.assertEqual(job.status, 'queued')

    def test_expired_claim_can_be_taken_by_another_actor(self):
        claim, _ = delivery.claim(self.task, member=self.a, user=self.owner)
        TaskClaim.objects.filter(pk=claim.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        other, _ = delivery.claim(self.task, member=self.b, user=self.owner)
        self.assertEqual(other.actor_member, self.b)

    def test_other_actor_cannot_heartbeat_same_issuer_claim(self):
        claim, _ = delivery.claim(self.task, member=self.a, user=self.owner)
        with self.assertRaises(delivery.DeliveryError):
            delivery.heartbeat(claim, member=self.b, user=self.owner)

    def test_expired_claim_cannot_submit_or_revive(self):
        claim, _ = delivery.claim(self.task, member=self.a, user=self.owner)
        TaskClaim.objects.filter(pk=claim.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        with self.assertRaises(delivery.DeliveryError):
            delivery.heartbeat(claim, member=self.a, user=self.owner)
        with self.assertRaises(delivery.DeliveryError):
            delivery.submit(self.task, summary="done", member=self.a, user=self.owner)

    def test_stale_rules_require_explicit_confirmation(self):
        delivery.claim(self.task, member=self.a, user=self.owner)
        self.project.context_revision += 1
        self.project.save(update_fields=['context_revision'])
        self.task.refresh_from_db()
        with self.assertRaises(delivery.DeliveryError):
            delivery.submit(self.task, summary='done', member=self.a, user=self.owner)
        delivery.confirm_context(self.task, self.project.context_revision, member=self.a, user=self.owner)
        record, created = delivery.submit(self.task, summary='done', member=self.a, user=self.owner)
        self.assertTrue(created)
        self.assertEqual(record.status, 'pending')

    def test_accept_requires_evidence(self):
        delivery.claim(self.task, member=self.a, user=self.owner)
        record, _ = delivery.submit(self.task, summary="done", member=self.a, user=self.owner)
        with self.assertRaises(delivery.DeliveryError):
            delivery.accept(record, user=self.owner)
        self.task.refresh_from_db()
        self.assertNotEqual(self.task.status, "done")

    def test_duplicate_after_acceptance_does_not_need_a_new_claim(self):
        delivery.claim(self.task, member=self.a, user=self.owner)
        record, _ = delivery.submit(
            self.task,
            summary="done",
            idempotency_key="delivery-1",
            evidence_ref="CI job 1",
            member=self.a,
            user=self.owner,
        )
        delivery.accept(record, user=self.owner)
        again, created = delivery.submit(
            self.task,
            summary="done",
            idempotency_key="delivery-1",
            evidence_ref="CI job 1",
            member=self.a,
            user=self.owner,
        )
        self.assertEqual(again.pk, record.pk)
        self.assertFalse(created)
        self.assertEqual(Delivery.objects.count(), 1)

    def test_invite_does_not_demote_existing_owner(self):
        Invitation.objects.create(
            project=self.project,
            token_hash=_hash_token("invite-test"),
            role="viewer",
            expires_at=timezone.now() + timedelta(hours=1),
            created_by=self.owner,
        )
        self.client.force_login(self.owner)
        self.client.post(reverse("projects:join_invite", args=["invite-test"]))
        self.assertEqual(self.project.memberships.get(user=self.owner).role, "owner")

    def test_server_token_cannot_impersonate_member_when_unbound(self):
        ctx = SimpleNamespace(
            project_id=self.project.pk,
            user=self.owner,
            member=None,
            scope="execute",
            can_execute=True,
        )
        with self.assertRaises(mcp.McpError):
            mcp.claim_task(str(self.project.pk), str(self.task.pk), tool="codex", ctx=ctx)
