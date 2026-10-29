from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.projects import progress
from apps.projects.models import Delivery, Member, Project, ProjectMembership, ReplyJob, Task


@override_settings(WORKROOM_MODE="local")
class ProgressTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name="阶段项目", goal_title="完成能验收的小工具")

    def task(self, title="具体工作", **fields):
        return Task.objects.create(project=self.project, title=title, **fields)

    def summary(self):
        tasks = list(self.project.tasks.select_related("project", "assignee").prefetch_related("prerequisites__assignee", "deliveries"))
        return progress.summarize(tasks, today=date(2026, 10, 27))

    def test_nested_containers_do_not_inflate_leaf_progress(self):
        root = self.task("总目标", status="done")
        first = self.task("第一阶段", parent=root, status="done")
        module = self.task("模块", parent=first, status="done")
        self.task("已完成的工作", parent=module, status="done")
        self.task("未完成的工作", parent=module)
        second = self.task("第二阶段", parent=root)
        self.task(parent=second)
        result = self.summary()
        self.assertEqual((result["total"], result["counts"]["done"], result["percent"]), (3, 1, 33))
        self.assertEqual([s["title"] for s in result["stages"]], [first.title, second.title])
        self.assertNotEqual(result["stages"][0]["label"], "阶段已记录完成")

    def test_archived_root_and_all_descendants_are_excluded(self):
        archived = self.task("归档：旧路线")
        mid = self.task("旧模块", parent=archived)
        self.task("旧工作", parent=mid, status="done")
        self.task("当前工作")
        result = self.summary()
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["archived_count"], 3)

    def test_multiple_root_stages_and_loose_tasks_are_counted_once(self):
        for name in ["设计", "开发"]:
            stage = self.task(name)
            self.task(parent=stage)
        loose = self.task("临时记录")
        result = self.summary()
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["stages"][-1]["title"], "未分阶段的任务")
        self.assertEqual(result["stages"][-1]["rows"][0]["task"], loose)

    def test_loose_child_of_overall_container_is_not_lost(self):
        root = self.task("总目标")
        stage = self.task("实现阶段", parent=root)
        self.task(parent=stage)
        loose = self.task("还未分组的工作", parent=root)
        result = self.summary()
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["stages"][-1]["rows"][0]["task"], loose)

    def test_latest_pending_delivery_is_not_done_even_if_legacy_status_done(self):
        task = self.task(status="done")
        Delivery.objects.create(task=task, summary="旧通过", status="accepted", idempotency_key="old")
        latest = Delivery.objects.create(task=task, summary="新交付", idempotency_key="new")
        result = self.summary()
        self.assertEqual(result["counts"]["done"], 0)
        self.assertEqual(result["counts"]["pending"], 1)
        self.assertEqual(result["next"]["kind"], "review")
        self.assertEqual(result["next"]["row"]["delivery"], latest)

    def test_accepted_newer_delivery_replaces_old_returned_or_pending(self):
        task = self.task(status="done")
        Delivery.objects.create(task=task, summary="旧退回", status="returned", idempotency_key="older")
        Delivery.objects.create(task=task, summary="已确认", status="accepted", idempotency_key="newer")
        result = self.summary()
        self.assertEqual(result["counts"]["done"], 1)
        self.assertEqual(result["percent"], 100)
        self.assertIsNone(result["next"])

    def test_stage_delivery_is_an_action_without_becoming_an_extra_leaf(self):
        stage = self.task("阶段交付", status="doing")
        self.task(parent=stage)
        Delivery.objects.create(task=stage, summary="阶段证据", idempotency_key="stage-delivery")
        result = self.summary()
        self.assertEqual((result["total"], result["counts"]["pending"]), (1, 0))
        self.assertEqual(result["next"]["kind"], "review")
        self.assertEqual(result["next"]["row"]["task"], stage)

    def test_legacy_done_with_latest_returned_still_shows_real_review_note(self):
        task = self.task(status="done")
        Delivery.objects.create(task=task, summary="退回", status="returned", review_note="仍未修复末行S138", idempotency_key="legacy-returned")
        result = self.summary()
        self.assertEqual(result["counts"]["done"], 0)
        self.assertIn("仍未修复末行S138", str(result["next"]["row"]["readable"]["blockers"]))

    def test_returned_reason_and_action_are_preserved(self):
        task = self.task(status="doing")
        Delivery.objects.create(task=task, summary="退回", status="returned", review_note="登录失败时输入丢失，请先修复末行S138", idempotency_key="returned")
        result = self.summary()
        self.assertEqual(result["counts"]["returned"], 1)
        self.assertEqual(result["next"]["kind"], "revise")
        self.assertIn("末行S138", str(result["next"]["row"]["readable"]["blockers"]))

    def test_prerequisites_and_missing_package_do_not_get_recommended_to_execute(self):
        self.project.policy = {"require_package": True}
        self.project.save()
        before = self.task("前置", status="blocked", blocked_reason="等待确认", unblock_action="先核对范围")
        needs_before = self.task("依赖未就绪", status="doing")
        needs_before.prerequisites.add(before)
        self.task("缺任务包")
        ready = self.task("可以先分析", execution_spec={"work_kind": "general"})
        result = self.summary()
        self.assertEqual(result["counts"]["blocked"], 3)
        self.assertEqual(result["next"]["row"]["task"], ready)

    def test_only_blocked_tasks_provide_real_recovery_instead_of_execute(self):
        task = self.task(status="blocked", blocked_reason="接口未提供", unblock_action="先补接口定义")
        result = self.summary()
        self.assertEqual(result["next"]["kind"], "blocked")
        self.assertEqual(result["next"]["row"]["task"], task)
        self.assertIn("先补接口定义", result["next"]["description"])

    def test_parent_blocker_and_status_are_separate_from_leaf_completion(self):
        stage = self.task("待确认阶段", status="blocked", blocked_reason="发布材料还缺截图", unblock_action="先补截图")
        self.task(parent=stage, status="done")
        result = self.summary()
        self.assertEqual(result["percent"], 100)
        self.assertIn("阶段", result["stages"][0]["label"])
        self.assertIn("先补截图", str(result["stages"][0]["readable"]["blockers"]))

    def test_dates_are_real_and_overdue_does_not_imply_execution_failed(self):
        stage = self.task("真实时间", start_date=date(2026, 10, 20), end_date=date(2026, 10, 25))
        self.task(parent=stage)
        result = self.summary()
        self.assertTrue(result["stages"][0]["overdue"])
        self.assertEqual(result["stages"][0]["task"].end_date, date(2026, 10, 25))
        self.assertIsNone(result["stages"][0]["rows"][0]["task"].end_date)

    def test_percent_cannot_round_to_100_before_last_task_is_done(self):
        Task.objects.bulk_create([Task(project=self.project, title=str(i), status="done" if i else "todo") for i in range(201)])
        result = self.summary()
        self.assertEqual(result["percent"], 99)
        self.assertEqual(sum(result["counts"].values()), 201)

    def test_summarize_has_no_queries_with_prefetched_tasks(self):
        owner = Member.objects.create(project=self.project, name="我")
        stage = self.task("阶段", assignee=owner)
        first = self.task(parent=stage, assignee=owner)
        second = self.task(parent=stage, assignee=owner)
        second.prerequisites.add(first)
        Delivery.objects.create(task=first, summary="退回", status="returned", review_note="修改", idempotency_key="query")
        tasks = list(self.project.tasks.select_related("project", "assignee").prefetch_related("prerequisites__assignee", "deliveries"))
        with self.assertNumQueries(0):
            result = progress.summarize(tasks)
        self.assertEqual(result["total"], 2)

    def test_empty_project_does_not_invent_milestones(self):
        result = self.summary()
        self.assertEqual((result["total"], result["percent"], result["stages"], result["next"]), (0, 0, [], None))

    def test_progress_get_is_readonly_and_does_not_recover_jobs(self):
        self.task()
        job = ReplyJob.objects.create(project=self.project, status="running")
        ReplyJob.objects.filter(pk=job.pk).update(created_at=timezone.now() - timezone.timedelta(hours=1))
        before = (Task.objects.count(), Project.objects.count(), ReplyJob.objects.count())
        response = self.client.get(reverse("projects:space", args=[self.project.pk]), {"tab": "progress"})
        self.assertContains(response, "阶段进度")
        job.refresh_from_db()
        self.assertEqual(job.status, "running")
        self.assertEqual(before, (Task.objects.count(), Project.objects.count(), ReplyJob.objects.count()))

    def test_render_full_text_and_escape_user_data(self):
        stage = self.task("阶段<script>oops</script>", detail="阶段目标完整末行S138", acceptance="本人核对交付")
        self.task(parent=stage, status="blocked", blocked_reason="原因" * 120 + "原因末行S138", unblock_action="<img src=x onerror=oops()>解除末行S138")
        response = self.client.get(reverse("projects:space", args=[self.project.pk]), {"tab": "progress"})
        self.assertContains(response, "原因末行S138")
        self.assertContains(response, "解除末行S138")
        self.assertContains(response, "阶段目标完整末行S138")
        self.assertNotContains(response, "<script>oops</script>")
        self.assertContains(response, "&lt;img")

    def test_header_recommends_leaf_and_review_link(self):
        stage = self.task("不是要执行的阶段", status="doing")
        task = self.task("需要核对的交付", parent=stage, status="doing")
        Delivery.objects.create(task=task, summary="完成", idempotency_key="header")
        response = self.client.get(reverse("projects:space", args=[self.project.pk]))
        self.assertContains(response, f'/p/{self.project.pk}/tasks/{task.pk}/delivery/')
        self.assertEqual(response.context["next_task"], task)
        self.assertEqual(response.context["progress"]["total"], 1)

    def test_home_and_workspace_share_the_same_leaf_and_delivery_counts(self):
        stage = self.task("已标完成的阶段", status="done")
        task = self.task(parent=stage, status="done")
        Delivery.objects.create(task=task, summary="仍待确认", idempotency_key="home")
        home = self.client.get(reverse("projects:index"))
        self.assertEqual(home.context["projects"][0].personal_progress["counts"]["done"], 0)
        self.assertContains(home, "1 项具体任务")
        self.assertContains(home, "0% · 0/1")
        workspace = self.client.get(reverse("projects:space", args=[self.project.pk]), {"tab": "progress"})
        self.assertContains(workspace, 'data-count="0"')
        self.assertContains(workspace, '0 / 1 项具体任务')

    @override_settings(WORKROOM_MODE="server")
    def test_server_permission_is_unchanged_and_new_tab_is_local_only(self):
        owner = get_user_model().objects.create_user(username="progress-owner")
        stranger = get_user_model().objects.create_user(username="progress-stranger")
        self.project.owner = owner
        self.project.save()
        ProjectMembership.objects.create(project=self.project, user=owner, role="owner")
        url = reverse("projects:space", args=[self.project.pk]) + "?tab=progress"
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(owner)
        response = self.client.get(url)
        self.assertEqual(response.context["tab"], "tasks")
        self.assertNotContains(response, 'href="?tab=progress"')
