"""Policy contracts must constrain all clients, not just prompt text."""

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.projects import delivery
from apps.projects.models import Member, Project, ProjectMembership, Task


@override_settings(WORKROOM_MODE="server")
class PolicyTests(TestCase):
    def setUp(self):
        from apps.projects.collaboration import default_policy

        self.owner = User.objects.create_user("policy-owner")
        self.project = Project.objects.create(
            name="Policy", goal_title="Ship", policy=default_policy()
        )
        ProjectMembership.objects.create(project=self.project, user=self.owner, role="owner")
        self.a = Member.objects.create(
            project=self.project, name="A", kind="external", tool="codex"
        )
        self.b = Member.objects.create(
            project=self.project, name="B", kind="external", tool="workbuddy"
        )
        self.spec = {
            "work_kind": "code",
            "workspace_key": "main",
            "baseline": "abc123",
            "allowed_paths": ["src/**"],
            "relevant_files": ["src/api.py"],
            "check_commands": ["python -m pytest"],
            "risk": "normal",
        }
        self.task = Task.objects.create(
            project=self.project,
            title="API",
            detail="Build endpoint",
            acceptance="Tests pass",
            execution_spec=self.spec,
        )

    def submit(self, **extra):
        values = dict(
            summary="Implemented",
            baseline="abc123",
            changed_files="src/api.py",
            test_commands="python -m pytest",
            test_exit_code=0,
            test_output="4 passed",
            evidence_ref="CI-1",
            member=self.a,
            user=self.owner,
        )
        values.update(extra)
        return delivery.submit(self.task, **values)[0]

    def test_incomplete_package_rejected_before_claim(self):
        self.task.execution_spec = {}
        self.task.save()
        with self.assertRaises(delivery.DeliveryError):
            delivery.claim(self.task, member=self.a, user=self.owner)
        self.assertFalse(self.task.claims.exists())

    def test_workspace_lock_applies_across_different_tasks(self):
        delivery.claim(self.task, member=self.a, user=self.owner)
        other = Task.objects.create(
            project=self.project,
            title="Second",
            detail="Second endpoint",
            acceptance="Pass",
            execution_spec=self.spec,
        )
        with self.assertRaises(delivery.ClaimConflict):
            delivery.claim(other, member=self.b, user=self.owner)

    def test_distinct_workspace_can_run_and_snapshot_is_saved(self):
        run, _ = delivery.claim(self.task, member=self.a, user=self.owner)
        other = Task.objects.create(
            project=self.project,
            title="Second",
            detail="Build",
            acceptance="Pass",
            execution_spec={**self.spec, "workspace_key": "isolated-tree"},
        )
        delivery.claim(other, member=self.b, user=self.owner)
        self.assertEqual(run.package.snapshot["execution"]["baseline"], "abc123")

    def test_parent_traversal_path_rejected(self):
        self.task.execution_spec = {**self.spec, "allowed_paths": ["../private/**"]}
        self.task.save()
        with self.assertRaises(delivery.DeliveryError):
            delivery.claim(self.task, member=self.a, user=self.owner)

    def test_out_of_scope_delivery_rejected(self):
        delivery.claim(self.task, member=self.a, user=self.owner)
        with self.assertRaises(delivery.DeliveryError):
            self.submit(changed_files="secrets/config.py")

    def test_high_risk_requires_independent_review_and_blocks_self_review(self):
        from apps.projects.collaboration import review_delivery

        self.task.execution_spec = {**self.spec, "risk": "high"}
        self.task.save()
        delivery.claim(self.task, member=self.a, user=self.owner)
        record = self.submit()
        with self.assertRaises(delivery.DeliveryError):
            delivery.accept(record, user=self.owner, evidence_checked=True)
        with self.assertRaises(delivery.DeliveryError):
            review_delivery(record, member=self.a, user=self.owner, verdict="approved", note="Pass")
        review_delivery(
            record, member=self.b, user=self.owner, verdict="approved", note="Checked diff and CI"
        )
        delivery.accept(record, user=self.owner, evidence_checked=True)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "done")

    def test_test_failure_cannot_be_replaced_by_a_generic_evidence_link(self):
        delivery.claim(self.task, member=self.a, user=self.owner)
        record = self.submit(test_exit_code=1)
        with self.assertRaises(delivery.DeliveryError):
            delivery.accept(record, user=self.owner, evidence_checked=True)

    def test_owner_must_explicitly_check_evidence(self):
        delivery.claim(self.task, member=self.a, user=self.owner)
        record = self.submit()
        with self.assertRaises(delivery.DeliveryError):
            delivery.accept(record, user=self.owner)

    def test_changed_context_cannot_accept_an_old_delivery(self):
        delivery.claim(self.task, member=self.a, user=self.owner)
        record = self.submit()
        Project.objects.filter(pk=self.project.pk).update(context_revision=2)
        with self.assertRaises(delivery.DeliveryError):
            delivery.accept(record, user=self.owner, evidence_checked=True)

    def test_unknown_cost_stays_unknown_and_reported_cost_keeps_currency(self):
        from apps.projects.collaboration import metrics

        delivery.claim(self.task, member=self.a, user=self.owner)
        record = self.submit(accounting={"cost_amount": "0.25", "currency": "CNY"})
        self.assertEqual(record.accounting["source"], "reported")
        self.assertEqual(metrics(self.project)["costs"], {"CNY": "0.25"})
        self.assertGreaterEqual(record.duration_seconds, 0)

    def test_viewer_cannot_edit_task_package(self):
        viewer = User.objects.create_user("policy-viewer")
        ProjectMembership.objects.create(project=self.project, user=viewer, role="viewer")
        self.client.force_login(viewer)
        response = self.client.post(
            f"/p/{self.project.pk}/tasks/{self.task.pk}/package/", {"baseline": "hijack"}
        )
        self.assertEqual(response.status_code, 403)
