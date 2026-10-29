"""Error/replay boundaries, using fixture keys and mocked providers only."""
import uuid
from unittest import mock

from django.db import transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.projects import ai_client, crypto, queue
from apps.projects.models import ChatMessage, Member, Project, ReplyJob


@override_settings(WORKROOM_MODE='local')
class SubmissionBoundaryTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='边界验证', goal_title='明确需求后再发送')
        self.ai = Member.objects.create(project=self.project, name='隔离AI', kind='ai', key_ciphertext=crypto.protect('not-a-real-s140-key'))
        self.data = dict(message='请拆分一个文档任务并说明验收条件', mode='plan', ai=str(self.ai.pk), submission_id=str(uuid.uuid4()))
        patcher = mock.patch.object(queue.threading, 'Thread')
        self.thread = patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, **changes):
        return self.client.post(reverse('projects:chat_send', args=[self.project.pk]), dict(self.data, **changes))

    def test_same_form_replayed_creates_one_message_and_one_call(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.post().status_code, 302)
            self.assertEqual(self.post().status_code, 302)
        self.assertEqual(ChatMessage.objects.filter(role='user').count(), 1)
        self.assertEqual(ReplyJob.objects.count(), 1)
        self.assertEqual(self.thread.call_count, 1)

    def test_new_form_allows_intentional_identical_message(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.post()
            self.post(submission_id=str(uuid.uuid4()))
        self.assertEqual(ReplyJob.objects.count(), 2)
        self.assertEqual(self.thread.call_count, 2)

    def test_same_id_with_changed_text_is_visible_conflict_without_a_new_call(self):
        self.post()
        response = self.post(message='<script>window.bad=1</script>这是另一次需求')
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, '本次没有发送', status_code=409)
        self.assertContains(response, '&lt;script&gt;', status_code=409)
        self.assertNotContains(response, '<script>window.bad', status_code=409)
        self.assertEqual(ReplyJob.objects.count(), 1)

    def test_same_id_cannot_switch_mode_and_charge_a_second_call(self):
        self.post()
        self.assertEqual(self.post(mode='chat').status_code, 409)
        self.assertEqual(ReplyJob.objects.count(), 1)

    def test_same_id_cannot_switch_ai(self):
        self.post()
        self.assertEqual(self.post(ai='all').status_code, 409)
        self.assertEqual(ReplyJob.objects.count(), 1)

    def test_failed_request_replay_does_not_implicitly_retry(self):
        self.post()
        ReplyJob.objects.update(status='failed')
        self.post()
        self.assertEqual(ReplyJob.objects.get().status, 'failed')

    @override_settings(WORKROOM_MODE='server')
    def test_different_authenticated_senders_are_not_deduplicated_together(self):
        from django.contrib.auth.models import User

        from apps.projects.models import ProjectMembership
        owner = User.objects.create_user('s140-owner')
        editor = User.objects.create_user('s140-editor')
        self.project.owner = owner
        self.project.save(update_fields=['owner'])
        for user, role in [(owner, 'owner'), (editor, 'editor')]:
            ProjectMembership.objects.create(project=self.project, user=user, role=role)
            self.client.force_login(user)
            self.assertEqual(self.post().status_code, 302)
        self.assertEqual(ReplyJob.objects.count(), 2)
        self.assertEqual(set(ReplyJob.objects.values_list('status', flat=True)), {'queued'})
        self.thread.assert_not_called()

    def test_empty_text_has_no_side_effect(self):
        self.assertEqual(self.post(message=' \n ').status_code, 302)
        self.assertFalse(ChatMessage.objects.exists())
        self.assertFalse(ReplyJob.objects.exists())
        self.thread.assert_not_called()

    def test_backend_enforces_text_limit_and_retains_input(self):
        value = '长' * 2000 + '最后一字'
        response = self.post(message=value)
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, '最后一字', status_code=400)
        self.assertFalse(ChatMessage.objects.exists())
        self.assertFalse(ReplyJob.objects.exists())

    def test_invalid_request_id_has_no_side_effect(self):
        self.assertEqual(self.post(submission_id='invalid-id').status_code, 400)
        self.assertFalse(ReplyJob.objects.exists())

    def test_legacy_form_without_id_still_works(self):
        data = dict(self.data)
        data.pop('submission_id')
        self.assertEqual(self.client.post(reverse('projects:chat_send', args=[self.project.pk]), data).status_code, 302)
        self.assertEqual(ReplyJob.objects.count(), 1)

    def test_same_token_in_different_projects_does_not_drop_a_request(self):
        self.post()
        other = Project.objects.create(name='另一个项目', goal_title='独立需求')
        ai = Member.objects.create(project=other, name='AI2', kind='ai', key_ciphertext=self.ai.key_ciphertext)
        self.client.post(reverse('projects:chat_send', args=[other.pk]), dict(self.data, ai=str(ai.pk)))
        self.assertEqual(ReplyJob.objects.count(), 2)

    def test_new_page_has_a_fresh_hidden_form_token(self):
        first = self.client.get(reverse('projects:space', args=[self.project.pk]) + '?tab=chat')
        second = self.client.get(reverse('projects:space', args=[self.project.pk]) + '?tab=chat')
        self.assertContains(first, 'name="submission_id"')
        self.assertNotEqual(first.context['submission_id'], second.context['submission_id'])

    def test_worker_is_started_only_after_commit(self):
        with self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                queue.submit(self.project, self.ai, '隔离', 'plan')
                self.thread.assert_not_called()
        self.thread.assert_called_once()

    def test_rollback_does_not_start_a_model_call(self):
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(RuntimeError), transaction.atomic():
                queue.submit(self.project, self.ai, '不应执行', 'plan')
                raise RuntimeError('isolated transaction rollback')
        self.thread.assert_not_called()
        self.assertFalse(ReplyJob.objects.exists())

    def test_chat_failure_rolls_back_message_with_job(self):
        with mock.patch('apps.projects.views._start_job', side_effect=RuntimeError('fixture failure')):
            with self.assertRaises(RuntimeError):
                self.post()
        self.assertFalse(ChatMessage.objects.exists())
        self.assertFalse(ReplyJob.objects.exists())

    def test_missing_ai_is_failed_instead_of_running_forever(self):
        job = ReplyJob.objects.create(project=self.project, member=None, mode='plan', prompt='成员已经被删除')
        with mock.patch('apps.projects.views._run_one') as provider:
            queue._run_local(job.pk, job.run_id)
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertIn('成员', job.error)
        provider.assert_not_called()

    def test_model_timeout_is_failed_once_without_automatic_retry(self):
        job = ReplyJob.objects.create(project=self.project, member=self.ai, mode='plan', prompt='隔离超时')
        with mock.patch('apps.projects.views._run_one', side_effect=ai_client.PlannerClientError('timeout')) as provider:
            queue._run_local(job.pk, job.run_id)
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertContains(self.client.get(reverse('projects:space', args=[self.project.pk]) + '?tab=chat'), '超时')
        provider.assert_called_once()
        self.thread.assert_not_called()

    def test_cancelled_provider_result_cannot_create_a_draft(self):
        job = ReplyJob.objects.create(project=self.project, member=self.ai, mode='plan', prompt='取消后不落地')
        def late_result(_job):
            queue.cancel(self.project, job.pk)
            return '迟到的草稿', {'tasks': [{'title': '不应创建'}], 'source': 'model'}
        with mock.patch('apps.projects.views._run_one', side_effect=late_result):
            queue._run_local(job.pk, job.run_id)
        job.refresh_from_db()
        self.assertEqual(job.status, 'cancelled')
        self.assertFalse(ChatMessage.objects.exists())

    def test_repeated_cancel_and_retry_start_exactly_one_new_run(self):
        job = ReplyJob.objects.create(project=self.project, member=self.ai)
        self.assertTrue(queue.cancel(self.project, job.pk))
        self.assertFalse(queue.cancel(self.project, job.pk))
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(queue.retry(self.project, job.pk))
            self.assertFalse(queue.retry(self.project, job.pk))
        self.thread.assert_called_once()
