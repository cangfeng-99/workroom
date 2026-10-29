from django.test import TestCase, override_settings
from django.urls import reverse

from apps.projects.models import Project, Task
from apps.projects import collaboration, delivery, mcp
from apps.projects.task_explanations import explanation, validate_prerequisites


@override_settings(WORKROOM_MODE='local')
class ClarityRenderingTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='说明项目', goal_title='做清楚一个项目')
        self.task = Task.objects.create(project=self.project, title='写登录页面', status='blocked')

    def test_blocked_task_says_missing_reason_and_who_should_fill_it(self):
        response = self.client.get(reverse('projects:space', args=[self.project.pk]), {'tab': 'tasks', 'task': self.task.pk})
        self.assertContains(response, '还没有填写具体原因')
        self.assertContains(response, '请负责人补充')

    def test_task_tree_defaults_to_readable_expandable_branches(self):
        response = self.client.get(reverse('projects:space', args=[self.project.pk]), {'tab': 'tasks'})
        self.assertContains(response, 'data-task-branch')
        self.assertContains(response, '查看怎么做')
        self.assertContains(response, '切换到连线图')

    def test_recorded_reason_and_action_are_both_visible(self):
        self.task.blocked_reason = '测试服务器还没有返回登录结果。'
        self.task.unblock_action = '请后端成员先修复登录接口，再由前端联调。'
        self.task.save()
        response = self.client.get(reverse('projects:space', args=[self.project.pk]), {'tab': 'tasks', 'task': self.task.pk})
        self.assertContains(response, self.task.blocked_reason)
        self.assertContains(response, self.task.unblock_action)

    def test_user_text_is_escaped_in_plain_guide_and_blocker(self):
        self.task.guide = {'summary': '<script>alert(1)</script>', 'steps': ['<img src=x onerror=alert(2)>']}
        self.task.blocked_reason = '<script>alert(3)</script>'
        self.task.save()
        html = self.client.get(reverse('projects:space', args=[self.project.pk]), {'tab': 'tasks', 'task': self.task.pk}).content.decode()
        self.assertNotIn('<script>alert', html)
        self.assertIn('&lt;script&gt;', html)


class TaskReasonTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='任务依据', goal_title='x')
        self.first = Task.objects.create(project=self.project, title='先明确登录接口')
        self.second = Task.objects.create(project=self.project, title='再接入登录页面', status='blocked', guide={'planning': True})
        self.second.prerequisites.add(self.first)

    def test_dependency_reason_updates_when_predecessor_is_finished(self):
        state = explanation(self.second)
        self.assertEqual(state['label'], '等前置任务')
        self.assertIn(self.first.title, state['primary']['text'])
        self.first.status = 'done'
        self.first.save()
        state = explanation(self.second)
        self.assertEqual(state['label'], '待准备')
        self.assertFalse(any(b['kind']=='prerequisite' for b in state['blockers']))

    def test_cross_project_dependency_and_transitive_cycle_are_rejected(self):
        other = Project.objects.create(name='其它项目')
        foreign = Task.objects.create(project=other, title='不该泄露')
        with self.assertRaisesMessage(delivery.DeliveryError, '同一个项目'):
            validate_prerequisites(self.second, [foreign])
        with self.assertRaisesMessage(delivery.DeliveryError, '循环'):
            validate_prerequisites(self.first, [self.second])

    def test_unfinished_predecessor_cannot_be_bypassed_by_changing_status(self):
        from apps.projects.models import Member
        actor = Member.objects.create(project=self.project, name='执行者', kind='external', tool='codex')
        self.second.status = 'todo'
        self.second.save()
        with self.assertRaisesMessage(delivery.DeliveryError, '先完成'):
            delivery.claim(self.second, member=actor)

    def test_server_and_mcp_status_updates_require_explanation(self):
        with self.assertRaisesMessage(mcp.McpError, 'reason'):
            mcp.update_task_status(str(self.project.pk), str(self.second.pk), 'blocked')
        mcp.update_task_status(str(self.project.pk), str(self.second.pk), 'blocked', reason='接口还没有完成', next_action='后端先完成接口')
        self.second.refresh_from_db()
        self.assertEqual(self.second.blocked_reason, '接口还没有完成')
        mcp.update_task_status(str(self.project.pk), str(self.second.pk), 'todo')
        self.second.refresh_from_db()
        self.assertEqual(self.second.blocked_reason, '')

    def test_task_package_includes_the_same_plain_reasons(self):
        self.second.guide['steps'] = ['先等接口完成', '再验证页面']
        self.second.save()
        package = collaboration.package_data(self.second, validate=False)
        self.assertEqual(package['plain_instructions']['steps'], ['先等接口完成', '再验证页面'])
        self.assertEqual(package['readiness']['label'], '等前置任务')
        self.assertEqual(package['prerequisites'][0]['id'], self.first.pk)

    def test_pending_delivery_explains_waiting_and_rejects_repeat_execution(self):
        from apps.projects.models import Delivery, Member
        record = Delivery.objects.create(task=self.first, summary='已交付', idempotency_key='clarity-pending')
        state = explanation(self.first)
        self.assertEqual(state['label'], '等负责人验收')
        self.assertIn(f'交付 #{record.pk}', state['primary']['text'])
        actor = Member.objects.create(project=self.project, name='执行者', kind='external', tool='codex')
        with self.assertRaisesMessage(delivery.DeliveryError, '不要重复执行'):
            delivery.claim(self.first, member=actor)

    def test_owner_form_rejects_foreign_and_cyclic_prerequisites(self):
        from apps.projects.policy_views import PackageForm
        other = Project.objects.create(name='其它项目')
        foreign = Task.objects.create(project=other, title='其它任务')
        fields = dict(detail='工作', acceptance='结果', work_kind='general', workspace_key='main', risk='normal')
        form = PackageForm({**fields, 'prerequisites': [foreign.pk]}, task=self.first)
        self.assertFalse(form.is_valid())
        self.assertIn('prerequisites', form.errors)
        form = PackageForm({**fields, 'prerequisites': [self.second.pk]}, task=self.first)
        self.assertFalse(form.is_valid())
        self.assertIn('循环', str(form.errors['prerequisites']))


@override_settings(WORKROOM_MODE='server')
class ExplanationPermissionTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        from apps.projects.models import ProjectMembership
        self.owner = User.objects.create_user('clarity-owner')
        self.viewer = User.objects.create_user('clarity-viewer')
        self.project = Project.objects.create(name='权限', owner=self.owner)
        ProjectMembership.objects.create(project=self.project, user=self.owner, role='owner')
        ProjectMembership.objects.create(project=self.project, user=self.viewer, role='viewer')
        self.task = Task.objects.create(project=self.project, title='登录', status='todo', guide={'outcomes':['旧标准']})

    def test_reason_is_required_and_persisted_through_http(self):
        self.client.force_login(self.owner)
        url=reverse('projects:task_status', args=[self.project.pk,self.task.pk])
        self.assertEqual(self.client.post(url, {'status':'blocked'}).status_code,400)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status,'todo')
        self.assertEqual(self.client.post(url, {'status':'blocked','blocked_reason':'接口故障','unblock_action':'后端先修复'}).status_code,302)
        self.task.refresh_from_db()
        self.assertEqual(self.task.blocked_reason,'接口故障')
        self.assertEqual(self.task.unblock_action,'后端先修复')

    def test_viewer_cannot_change_reason_or_package(self):
        self.client.force_login(self.viewer)
        for name in ['task_status','package']:
            url=reverse('projects:'+name,args=[self.project.pk,self.task.pk])
            self.assertEqual(self.client.post(url,{'status':'blocked','blocked_reason':'篡改','unblock_action':'绕过'}).status_code,403)
        self.task.refresh_from_db()
        self.assertEqual(self.task.blocked_reason,'')

    def test_editing_acceptance_updates_the_plain_completion_criteria(self):
        self.client.force_login(self.owner)
        url=reverse('projects:task_acceptance',args=[self.project.pk,self.task.pk])
        self.assertEqual(self.client.post(url,{'acceptance':'新的结果\n手机也通过'}).status_code,302)
        self.task.refresh_from_db()
        self.assertEqual(self.task.guide['outcomes'],['新的结果','手机也通过'])
