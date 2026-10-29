"""C4: independent regression for the execution/review contract (C1)."""

from unittest import mock

from django.test import TestCase, override_settings

from apps.projects import crypto, mcp, tool_api
from apps.projects.models import (
    Delivery,
    Member,
    Project,
    ReplyJob,
    Task,
)


class ContractRegressionTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='C4', goal_title='上线')
        self.external = Member.objects.create(
            project=self.project,
            kind=Member.Kind.EXTERNAL,
            tool='codex',
            name='Codex',
            role='执行',
        )
        self.reviewer = Member.objects.create(
            project=self.project,
            kind=Member.Kind.AI,
            name='DeepSeek',
            role='评审',
            key_ciphertext=crypto.protect('sk-test'),
        )
        self.task = Task.objects.create(
            project=self.project,
            title='改登录页',
            detail='按钮换绿色',
            assignee=self.external,
            execution_spec={'risk': 'normal'},
        )

    def _submit(self, **kwargs):
        with mock.patch('apps.projects.views._run_job'):
            return mcp.submit_result(
                'C4',
                '改登录页',
                '按钮已换',
                '改了 login.css',
                'codex',
                **kwargs,
            )

    def test_medium_delivery_stays_pending_without_review(self) -> None:
        revision = self.project.context_revision
        text = self._submit()
        self.assertIn('不自动审核', text)
        delivery = Delivery.objects.get(task__project=self.project)
        self.assertEqual(delivery.status, Delivery.Status.PENDING)
        self.assertFalse(ReplyJob.objects.filter(project=self.project).exists())
        self.project.refresh_from_db()
        self.assertEqual(self.project.context_revision, revision)

    @override_settings(WORKROOM_MODE='server')
    def test_high_risk_review_does_not_accept_delivery(self) -> None:
        self.task.execution_spec = {'risk': 'high'}
        self.task.save(update_fields=['execution_spec'])
        text = self._submit()
        self.assertIn('审核', text)
        self.assertEqual(ReplyJob.objects.get(project=self.project).mode, ReplyJob.Mode.REVIEW)
        delivery = Delivery.objects.get(task__project=self.project)
        self.assertEqual(delivery.status, Delivery.Status.PENDING)

    @override_settings(WORKROOM_MODE='server')
    def test_forced_review_only_adds_one_job(self) -> None:
        self._submit(review=True)
        self.assertEqual(ReplyJob.objects.filter(project=self.project).count(), 1)

    def test_read_scope_cannot_submit(self) -> None:
        self.assertIn('submit_result', tool_api.EXECUTE_TOOLS)
        self.assertNotIn('submit_result', tool_api.READ_TOOLS)
        self.assertIn('get_inbox', tool_api.READ_TOOLS)


class WebDeliveryGateTests(TestCase):
    def setUp(self) -> None:
        from django.contrib.auth import get_user_model

        from apps.projects.models import ProjectMembership

        self.project = Project.objects.create(name='Web', goal_title='上线')
        self.user = get_user_model().objects.create_user('owner', password='x')
        ProjectMembership.objects.create(
            project=self.project,
            user=self.user,
            role=ProjectMembership.Role.OWNER,
        )
        Member.objects.create(
            project=self.project,
            kind=Member.Kind.AI,
            name='DeepSeek',
            role='评审',
            key_ciphertext=crypto.protect('sk-test'),
        )
        self.task = Task.objects.create(
            project=self.project,
            title='网页交付',
            detail='走网页表单',
            execution_spec={'risk': 'normal'},
        )
        self.url = f'/p/{self.project.pk}/tasks/{self.task.pk}/delivery/'
        self.client.force_login(self.user)

    def _submit(self) -> None:
        from django.test import override_settings

        with override_settings(WORKROOM_MODE='server'), mock.patch(
            'apps.projects.views._run_job'
        ):
            self.client.post(self.url, {'action': 'claim'})
            self.client.post(
                self.url,
                {
                    'action': 'submit',
                    'summary': '完成',
                    'body': '说明',
                    'idempotency_key': 'web-test-1',
                },
            )

    def test_web_normal_delivery_skips_review(self) -> None:
        self._submit()
        self.assertEqual(Delivery.objects.filter(task=self.task).count(), 1)
        self.assertFalse(ReplyJob.objects.filter(project=self.project).exists())

    def test_web_high_risk_creates_review(self) -> None:
        self.task.execution_spec = {'risk': 'high'}
        self.task.save(update_fields=['execution_spec'])
        self._submit()
        self.assertTrue(ReplyJob.objects.filter(project=self.project).exists())
