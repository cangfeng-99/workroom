import os
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.projects import ai_client, crypto, delivery, mcp, planner, queue, views
from apps.projects.models import ChatMessage, Delivery, Member, Project, ReplyJob, Task


@override_settings(WORKROOM_MODE="local")
class DraftDependenciesTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name="主链路", goal_title="先确定范围，再写交付说明")
        self.actor = Member.objects.create(project=self.project, name="Codex", kind="external", tool="codex")

    def payload(self):
        today = date.today().isoformat()
        rows = []
        for ref, title, parent, required in [("root", "交付准备", None, []), ("scope", "先确定范围", "root", []), ("notes", "再写交付说明", "root", ["scope"])]:
            rows.append(dict(ref=ref, title=title, parent_ref=parent, prerequisite_refs=required,
                             detail="写清楚内容并由本人核对。", acceptance="说明与约定相符。", start_date=today, end_date=today,
                             assignee_id=self.actor.pk, priority="normal", execution_spec={"work_kind": "general"}))
        return {"tasks": rows}

    def validate(self, payload):
        return planner.validate(payload, [self.actor], date.today(), date.today() + timedelta(days=14))

    def draft(self, payload=None):
        return ChatMessage.objects.create(project=self.project, role="assistant", content="隔离草稿，尚未执行。", payload=payload or self.payload())

    def apply(self, draft):
        return self.client.post(reverse("projects:draft_apply", args=[self.project.pk, draft.pk]))

    def test_model_validator_preserves_real_dependencies(self):
        rows = self.validate(self.payload())
        self.assertEqual(rows[-1].get("prerequisite_refs"), ["scope"])

    def test_forward_reference_is_valid(self):
        payload = self.payload()
        payload["tasks"][1]["prerequisite_refs"] = ["notes"]
        payload["tasks"][2]["prerequisite_refs"] = []
        self.assertEqual(self.validate(payload)[1].get("prerequisite_refs"), ["notes"])

    def test_duplicate_references_are_normalized(self):
        payload = self.payload()
        payload["tasks"][-1]["prerequisite_refs"] = ["scope", " scope ", "scope"]
        self.assertEqual(self.validate(payload)[-1].get("prerequisite_refs"), ["scope"])

    def test_old_model_draft_without_field_still_validates_and_applies(self):
        payload = self.payload()
        for row in payload["tasks"]:
            row.pop("prerequisite_refs")
        self.validate(payload)
        self.assertEqual(self.apply(self.draft(payload)).status_code, 302)
        self.assertEqual(self.project.tasks.count(), 3)

    def test_unknown_reference_is_rejected_before_model_draft_is_saved(self):
        payload = self.payload()
        payload["tasks"][-1]["prerequisite_refs"] = ["outside"]
        with self.assertRaises(planner.PlanError):
            self.validate(payload)

    def test_self_reference_is_rejected(self):
        payload = self.payload()
        payload["tasks"][-1]["prerequisite_refs"] = ["notes"]
        with self.assertRaises(planner.PlanError):
            self.validate(payload)

    def test_cycle_is_rejected(self):
        payload = self.payload()
        payload["tasks"][1]["prerequisite_refs"] = ["notes"]
        with self.assertRaises(planner.PlanError):
            self.validate(payload)

    def test_dependency_field_must_be_an_array_of_nonempty_strings(self):
        for value in ["scope", "", {}, {"ref": "scope"}, [None], [True], [" "]]:
            with self.subTest(value=value):
                payload = self.payload()
                payload["tasks"][-1]["prerequisite_refs"] = value
                with self.assertRaises(planner.PlanError):
                    self.validate(payload)

    def test_apply_materializes_foreign_keys_and_remains_idempotent(self):
        draft = self.draft()
        self.assertEqual(self.apply(draft).status_code, 302)
        scope = self.project.tasks.get(title="先确定范围")
        notes = self.project.tasks.get(title="再写交付说明")
        self.assertEqual(list(notes.prerequisites.all()), [scope])
        self.apply(draft)
        self.assertEqual(self.project.tasks.count(), 3)
        self.assertEqual(notes.prerequisites.count(), 1)

    def test_forward_reference_is_linked_after_all_tasks_exist(self):
        payload = self.payload()
        payload["tasks"][1]["prerequisite_refs"] = ["notes"]
        payload["tasks"][2]["prerequisite_refs"] = []
        self.assertEqual(self.apply(self.draft(payload)).status_code, 302)
        scope = self.project.tasks.get(title="先确定范围")
        self.assertEqual(scope.prerequisites.get().title, "再写交付说明")

    def test_invalid_saved_draft_never_creates_a_partial_tree(self):
        for ref in ["missing", "notes"]:
            with self.subTest(ref=ref):
                payload = self.payload()
                payload["tasks"][-1]["prerequisite_refs"] = [ref]
                draft = self.draft(payload)
                response = self.apply(draft)
                self.assertEqual(response.status_code, 400)
                self.assertContains(response, "草稿暂未保存为任务", status_code=400)
                self.assertContains(response, "返回对话", status_code=400)
                draft.refresh_from_db()
                self.assertIsNone(draft.applied_at)
                self.assertEqual(self.project.tasks.count(), 0)

    def test_foreign_task_id_cannot_be_used_as_reference(self):
        foreign = Task.objects.create(project=Project.objects.create(name="别人的项目"), title="不应成为前置")
        payload = self.payload()
        payload["tasks"][-1]["prerequisite_refs"] = [f"#{foreign.pk}"]
        response = self.apply(self.draft(payload))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.project.tasks.exists())
        self.assertFalse(foreign.following_tasks.exists())

    def test_invalid_parent_with_dependencies_is_rejected_without_half_tree(self):
        payload = self.payload()
        payload["tasks"][-1]["parent_ref"] = "not-a-parent"
        self.assertEqual(self.apply(self.draft(payload)).status_code, 400)
        self.assertFalse(self.project.tasks.exists())

    def test_failure_while_linking_dependencies_rolls_back_all_tasks(self):
        draft = self.draft()
        with mock.patch.object(Task.prerequisites.related_manager_cls, "set", side_effect=RuntimeError("isolated write failure")):
            with self.assertRaises(RuntimeError):
                self.apply(draft)
        draft.refresh_from_db()
        self.assertIsNone(draft.applied_at)
        self.assertFalse(self.project.tasks.exists())

    def test_preview_names_dependencies_before_confirmation_and_escapes_text(self):
        payload = self.payload()
        payload["tasks"][1]["title"] = "先确定范围<script>oops()</script>"
        self.draft(payload)
        response = self.client.get(reverse("projects:space", args=[self.project.pk]), {"tab": "chat"})
        self.assertContains(response, "前置：")
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>oops()")
        self.assertFalse(self.project.tasks.exists())

    def test_invalid_reference_in_error_page_is_escaped(self):
        payload = self.payload()
        payload["tasks"][-1]["prerequisite_refs"] = ["<script>oops()</script>"]
        response = self.apply(self.draft(payload))
        self.assertContains(response, "&lt;script&gt;", status_code=400)
        self.assertNotContains(response, "<script>oops()", status_code=400)

    def test_model_contract_documents_dependency_field(self):
        self.assertIn('"prerequisite_refs"', ai_client._SCHEMA)

    def test_csrf_is_still_required_for_apply(self):
        draft = self.draft()
        response = Client(enforce_csrf_checks=True).post(reverse("projects:draft_apply", args=[self.project.pk, draft.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.project.tasks.exists())

    def test_local_publication_survives_another_simultaneous_writer(self):
        root = Path(__file__).resolve().parents[2]
        env = {key: value for key, value in os.environ.items() if not key.startswith('WORKROOM_')}
        env['PYTHONIOENCODING'] = 'utf-8'
        with tempfile.TemporaryDirectory(prefix='S139-sqlite-', dir=root / '.tools') as folder:
            # 子进程要跑一次完整 migrate，冷启动实测 40s，30s 会误报超时
            result = subprocess.run([sys.executable, str(Path(__file__).with_name('_sqlite_publish_fixture.py')), folder], cwd=root / 'workroom', env=env, text=True, encoding='utf-8', capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('publication and concurrent update both committed', result.stdout)

    def test_unexpected_local_worker_failure_is_recorded_instead_of_stuck_running(self):
        job = ReplyJob.objects.create(project=self.project, status="running")
        with mock.patch.object(views, '_run_job', side_effect=RuntimeError('isolated worker failure')):
            with self.assertLogs('apps.projects.queue', level='ERROR'):
                queue._run_local(job.pk, job.run_id)
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertIsNotNone(job.finished_at)
        self.assertNotIn('isolated worker failure', job.error)

    def test_expected_worker_stop_keeps_cancellation(self):
        job = ReplyJob.objects.create(project=self.project, status="cancelled")
        with mock.patch.object(views, '_run_job', side_effect=queue.JobStopped):
            queue._run_local(job.pk, job.run_id)
        job.refresh_from_db()
        self.assertEqual(job.status, 'cancelled')

    def test_local_failure_and_manual_retry_are_visible_only_in_its_project(self):
        job = ReplyJob.objects.create(project=self.project, status='failed', error='本机失败原因S139')
        ReplyJob.objects.create(project=Project.objects.create(name='其他项目'), status='failed', error='不属于本页的失败S139')
        response = self.client.get(reverse('projects:space', args=[self.project.pk]), {'tab': 'chat'})
        self.assertContains(response, '本机失败原因S139')
        self.assertContains(response, f'手动重试 #{job.pk}')
        self.assertNotContains(response, '不属于本页的失败S139')

    def test_local_retry_starts_once_and_replaces_run_identity(self):
        job = ReplyJob.objects.create(project=self.project, status='failed')
        before = job.run_id
        with mock.patch.object(queue.threading, 'Thread') as thread:
            self.assertTrue(queue.retry(self.project, job.pk, None))
            self.assertFalse(queue.retry(self.project, job.pk, None))
        job.refresh_from_db()
        self.assertEqual(job.status, 'running')
        self.assertNotEqual(job.run_id, before)
        self.assertEqual(thread.call_count, 1)
        self.assertEqual(thread.call_args.kwargs['args'], (job.pk, job.run_id))

    def test_old_cancelled_run_cannot_publish_after_manual_retry(self):
        job = ReplyJob.objects.create(project=self.project, status='cancelled')
        old_run = job.run_id
        with mock.patch.object(queue.threading, 'Thread'):
            queue.retry(self.project, job.pk, None)
        job.refresh_from_db()
        marker = queue.CURRENT_RUN.set((job.pk, old_run))
        try:
            self.assertFalse(queue.update_active(job.pk, partial_answer='stale cancelled response'))
        finally:
            queue.CURRENT_RUN.reset(marker)
        marker = queue.CURRENT_RUN.set((job.pk, job.run_id))
        try:
            self.assertTrue(queue.active(job.pk))
            self.assertTrue(queue.update_active(job.pk, partial_answer='current retry response'))
        finally:
            queue.CURRENT_RUN.reset(marker)

    @override_settings(WORKROOM_MODE='server')
    def test_server_retry_stays_queued_for_its_independent_worker(self):
        job = ReplyJob.objects.create(project=self.project, status='failed')
        with mock.patch.object(queue.threading, 'Thread') as thread:
            self.assertTrue(queue.retry(self.project, job.pk, None))
        job.refresh_from_db()
        self.assertEqual(job.status, 'queued')
        thread.assert_not_called()

    def test_main_flow_from_mocked_plan_to_tool_delivery_and_human_confirmation(self):
        ai = Member.objects.create(project=self.project, name="隔离规划模型", kind="ai", provider="deepseek", model_name="fixture", key_ciphertext=crypto.protect("not-a-real-key"))
        job = ReplyJob.objects.create(project=self.project, member=ai, prompt=self.project.goal_title, mode="plan")
        with mock.patch("apps.projects.views.ai_client.fetch_plan", return_value=self.payload()) as provider:
            views._run_job(job.pk)
        self.assertEqual(provider.call_count, 1)
        job.refresh_from_db()
        self.assertEqual(job.status, "done")
        draft = ChatMessage.objects.get(project=self.project, role="assistant")
        self.assertEqual(self.apply(draft).status_code, 302)
        scope = self.project.tasks.get(title="先确定范围")
        notes = self.project.tasks.get(title="再写交付说明")
        self.assertIn("先确定范围", mcp.get_task_context(str(self.project.pk), str(notes.pk)))
        with self.assertRaises((delivery.DeliveryError, mcp.McpError)):
            mcp.claim_task(str(self.project.pk), str(notes.pk), tool="codex")
        mcp.claim_task(str(self.project.pk), str(scope.pk), tool="codex")
        mcp.submit_result(str(self.project.pk), str(scope.pk), "范围说明已交付", tool="codex", evidence_ref="隔离用例的范围核对记录", idempotency_key="scope")
        record = Delivery.objects.get(task=scope)
        scope.refresh_from_db()
        self.assertNotEqual(scope.status, "done")
        response = self.client.post(reverse("projects:task_delivery", args=[self.project.pk, scope.pk]), {"action": "accept", "delivery": record.pk, "evidence_checked": "on"})
        self.assertEqual(response.status_code, 302)
        scope.refresh_from_db()
        self.assertEqual(scope.status, "done")
        mcp.claim_task(str(self.project.pk), str(notes.pk), tool="codex")
        mcp.submit_result(str(self.project.pk), str(notes.pk), "说明交付待本人核对", tool="codex", evidence_ref="隔离用例的说明核对记录", idempotency_key="notes")
        notes.refresh_from_db()
        self.assertNotEqual(notes.status, "done")
        response = self.client.get(reverse("projects:space", args=[self.project.pk]), {"tab": "progress"})
        self.assertEqual(response.context["progress"]["counts"]["done"], 1)
        self.assertEqual(response.context["progress"]["counts"]["pending"], 1)
        self.assertEqual(ReplyJob.objects.count(), 1)
