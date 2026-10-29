from django.test import TestCase, override_settings
from django.urls import reverse

from apps.projects import delivery, directives, mcp, user_profile
from apps.projects.models import Delivery, Member, Project, ReplyJob, Task


@override_settings(WORKROOM_MODE="local")
class PersonalDeliveryTests(TestCase):
    def setUp(self):
        self.owner = user_profile.local_user()
        self.project = Project.objects.create(name="单人", goal_title="交付", owner=self.owner)
        self.actor = Member.objects.create(
            project=self.project, name="Codex", kind="external", tool="codex"
        )
        self.task = Task.objects.create(
            project=self.project, title="写一个功能", assignee=self.actor, detail="把结果交付"
        )
        self.url = reverse("projects:task_delivery", args=[self.project.pk, self.task.pk])
        self.values = {
            "action": "submit",
            "summary": "功能已实现",
            "evidence_ref": "reports/result.md",
            "idempotency_key": "personal-case",
        }

    def record(self, **extra):
        run, _ = delivery.claim(self.task, member=self.actor, user=self.owner)
        row, _ = delivery.submit(
            self.task,
            summary="已实现",
            evidence_ref="reports/check.md",
            member=self.actor,
            user=self.owner,
            **extra,
        )
        return row

    def test_page_available_without_login_and_does_not_offer_ai_review(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "由你确认")
        self.assertNotContains(response, "提交独立复核意见")

    def test_submit_is_pending_without_job_and_owner_can_confirm(self):
        response = self.client.post(self.url, self.values)
        self.assertEqual(response.status_code, 302)
        record = Delivery.objects.get(task=self.task)
        self.task.refresh_from_db()
        self.assertNotEqual(self.task.status, "done")
        self.assertEqual(record.status, "pending")
        self.assertEqual(ReplyJob.objects.count(), 0)
        response = self.client.post(
            self.url, {"action": "accept", "delivery": record.pk, "evidence_checked": "on"}
        )
        self.assertEqual(response.status_code, 302)
        record.refresh_from_db()
        self.task.refresh_from_db()
        self.assertEqual(record.status, "accepted")
        self.assertEqual(record.reviewed_by, self.owner)
        self.assertEqual(self.task.status, "done")

    def test_duplicate_submit_does_not_duplicate_record(self):
        self.client.post(self.url, self.values)
        self.client.post(self.url, self.values)
        self.assertEqual(Delivery.objects.filter(task=self.task).count(), 1)
        self.assertEqual(ReplyJob.objects.count(), 0)

    def test_error_keeps_input(self):
        response = self.client.post(
            self.url, {**self.values, "summary": "", "body": "保留我的说明"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "保留我的说明")
        self.assertEqual(Delivery.objects.count(), 0)

    def test_confirmation_requires_checkbox_and_evidence(self):
        record = self.record()
        with self.assertRaises(delivery.DeliveryError):
            delivery.accept(record, user=self.owner)
        record.evidence_ref = ""
        record.save(update_fields=["evidence_ref"])
        with self.assertRaises(delivery.DeliveryError):
            delivery.accept(record, user=self.owner, evidence_checked=True)

    def test_failed_check_cannot_be_overridden_by_evidence_reference(self):
        record = self.record(test_commands="pytest", test_exit_code=1, test_output="1 failed")
        with self.assertRaises(delivery.DeliveryError):
            delivery.accept(record, user=self.owner, evidence_checked=True)

    def test_high_risk_local_mcp_never_enqueues_review_even_if_requested(self):
        self.task.execution_spec = {"risk": "high"}
        self.task.save()
        text = mcp.submit_result(
            str(self.project.pk),
            str(self.task.pk),
            "已实现",
            tool="codex",
            review=True,
            evidence_ref="reports/check.md",
        )
        self.assertIn("待你确认", text)
        self.assertEqual(ReplyJob.objects.count(), 0)
        record = Delivery.objects.get(task=self.task)
        delivery.accept(record, user=self.owner, evidence_checked=True)

    def test_return_requires_reason_and_rework_can_be_resubmitted(self):
        self.client.post(self.url, self.values)
        record = Delivery.objects.get(task=self.task)
        response = self.client.post(
            self.url, {"action": "return", "delivery": record.pk, "note": ""}
        )
        self.assertEqual(response.status_code, 200)
        response = self.client.post(
            self.url, {"action": "return", "delivery": record.pk, "note": "错误提示没有显示"}
        )
        self.assertEqual(response.status_code, 302)
        self.task.refresh_from_db()
        record.refresh_from_db()
        self.assertEqual(self.task.status, "todo")
        self.assertEqual(record.status, "returned")
        self.assertContains(self.client.get(self.url), "错误提示没有显示")
        self.client.post(
            self.url,
            {**self.values, "summary": "已补错误提示", "idempotency_key": "personal-rework"},
        )
        self.assertEqual(Delivery.objects.filter(task=self.task).count(), 2)

    def test_other_project_delivery_cannot_be_confirmed(self):
        record = self.record()
        other = Project.objects.create(name="其它")
        task = Task.objects.create(project=other, title="别的任务")
        url = reverse("projects:task_delivery", args=[other.pk, task.pk])
        self.assertEqual(
            self.client.post(
                url, {"action": "accept", "delivery": record.pk, "evidence_checked": "on"}
            ).status_code,
            404,
        )
        record.refresh_from_db()
        self.assertEqual(record.status, "pending")

    def test_status_tools_and_ai_markers_cannot_confirm_delivery(self):
        self.record()
        with self.assertRaises(mcp.McpError):
            mcp.update_task_status(str(self.project.pk), str(self.task.pk), "done")
        text = directives.apply(self.project, f"好了 [[status:{self.task.title}|done]]")
        self.task.refresh_from_db()
        self.assertNotEqual(self.task.status, "done")
        self.assertIn("确认", text)

    def test_local_human_cannot_submit_using_another_tools_live_claim(self):
        delivery.claim(self.task, member=self.actor, user=self.owner)
        with self.assertRaises(delivery.DeliveryError):
            delivery.submit(self.task, summary="抢交", user=self.owner, require_claim=False)
        self.assertEqual(Delivery.objects.count(), 0)

    def test_stale_package_cannot_be_accepted(self):
        record = self.record()
        self.project.context_revision += 1
        self.project.save(update_fields=["context_revision"])
        with self.assertRaisesMessage(delivery.DeliveryError, "规则已变化"):
            delivery.accept(record, user=self.owner, evidence_checked=True)

    def test_declared_checks_require_matching_command_and_output(self):
        self.task.execution_spec = {"check_commands": ["pytest login_checks"], "risk": "high"}
        self.task.save(update_fields=["execution_spec"])
        record = self.record(
            test_commands="pytest something_else", test_exit_code=0, test_output="passed"
        )
        with self.assertRaisesMessage(delivery.DeliveryError, "检查记录不完整"):
            delivery.accept(record, user=self.owner, evidence_checked=True)
        record.test_commands = "pytest login_checks"
        record.save(update_fields=["test_commands"])
        delivery.accept(record, user=self.owner, evidence_checked=True)

    def test_pending_delivery_cannot_be_completed_by_status_button(self):
        self.record()
        url = reverse("projects:task_status", args=[self.project.pk, self.task.pk])
        response = self.client.post(url, {"status": "done"})
        self.assertRedirects(response, self.url)
        self.task.refresh_from_db()
        self.assertNotEqual(self.task.status, "done")

    def test_ai_done_marker_without_delivery_is_only_a_report(self):
        text = directives.apply(self.project, f"[[status:{self.task.title}|done]]")
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "todo")
        self.assertIn("状态没有自动变更", text)

    def test_personal_form_still_requires_csrf(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(self.url, self.values).status_code, 403)
        self.assertEqual(Delivery.objects.count(), 0)

    def test_submission_releases_execution_but_leaves_result_pending(self):
        record = self.record()
        record.claim.refresh_from_db()
        self.assertEqual(record.claim.status, "released")
        self.assertEqual(record.status, "pending")
