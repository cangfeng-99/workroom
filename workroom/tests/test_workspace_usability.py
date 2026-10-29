"""T070 usability regressions: @ candidates, full task detail, product brief.

These cover the server-rendered contract. Keyboard/IME behaviour is verified in
a real browser and recorded in tasks/reports/T070-ui-result.json.
"""

from __future__ import annotations

import json
import re

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.projects.models import LibraryEntry, Member, Project, ProjectMembership, Task


def mention_payload(html: str) -> list[dict]:
    match = re.search(
        r'<script id="mention-candidates" type="application/json">(.*?)</script>',
        html,
        re.S,
    )
    if not match:
        return []
    return json.loads(match.group(1))


class SpaceFixture(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(
            name='T070', goal_title='上线到GitHub并有用户使用', goal_detail='用户原话：先给内部试用'
        )
        self.human = Member.objects.create(
            project=self.project, kind=Member.Kind.HUMAN, name='张三', role='产品'
        )
        self.ai = Member.objects.create(
            project=self.project, kind=Member.Kind.AI, name='小助', role='评审'
        )
        self.external = Member.objects.create(
            project=self.project, kind=Member.Kind.EXTERNAL, name='WorkBuddy', role='执行'
        )
        self.inactive = Member.objects.create(
            project=self.project, kind=Member.Kind.HUMAN, name='离职同事', is_active=False
        )
        self.task = Task.objects.create(
            project=self.project,
            title='修复长文详情',
            detail='第一段。\n第二段。',
            acceptance='pytest 通过',
            execution_spec={
                'work_kind': 'code',
                'workspace_key': 'T070-workbuddy-isolated',
                'baseline': 'workroom-sha256:abc',
                'risk': 'high',
                'allowed_paths': ['workroom/static/workroom/app.js'],
                'relevant_files': ['workroom/templates/projects/space.html'],
                'check_commands': ['python -m pytest tests -q'],
            },
        )

    def url(self, query: str = '') -> str:
        base = reverse('projects:space', args=[self.project.pk])
        return f'{base}?{query}' if query else base


class MentionCandidateTests(SpaceFixture):
    def test_all_active_members_are_candidates_with_their_kind(self) -> None:
        html = self.client.get(self.url('tab=chat')).content.decode('utf-8')
        candidates = mention_payload(html)
        names = {item['name'] for item in candidates}
        self.assertEqual(names, {'张三', '小助', 'WorkBuddy'})
        kinds = {item['name']: item['kind'] for item in candidates}
        self.assertEqual(kinds['张三'], 'human')
        self.assertEqual(kinds['小助'], 'ai')
        self.assertEqual(kinds['WorkBuddy'], 'external')
        labels = {item['name']: item['kindLabel'] for item in candidates}
        self.assertEqual(labels['WorkBuddy'], '外部工具')

    def test_inactive_members_and_other_projects_do_not_leak(self) -> None:
        other = Project.objects.create(name='其他', goal_title='别的')
        Member.objects.create(project=other, kind=Member.Kind.HUMAN, name='别组的人')
        html = self.client.get(self.url('tab=chat')).content.decode('utf-8')
        names = {item['name'] for item in mention_payload(html)}
        self.assertNotIn('离职同事', names)
        self.assertNotIn('别组的人', names)

    def test_candidate_names_stay_escaped_in_json_script(self) -> None:
        Member.objects.create(
            project=self.project,
            kind=Member.Kind.HUMAN,
            name='<script>alert(1)</script>',
        )
        html = self.client.get(self.url('tab=chat')).content.decode('utf-8')
        self.assertNotIn('<script>alert(1)</script>', html)
        names = {item['name'] for item in mention_payload(html)}
        self.assertIn('<script>alert(1)</script>', names)

    def test_composer_exposes_mention_menu_and_routing_note(self) -> None:
        html = self.client.get(self.url('tab=chat')).content.decode('utf-8')
        self.assertIn('data-mention-menu', html)
        self.assertIn('data-mention-button', html)
        self.assertIn('会写入对方收件箱', html)


class TaskDetailTests(SpaceFixture):
    LONG = ('超长说明' * 700) + '\n\n尾段落：完整正文必须可读。'

    def test_full_task_detail_renders_every_section(self) -> None:
        parent = Task.objects.create(project=self.project, title='总目标节点')
        task = Task.objects.create(
            project=self.project,
            parent=parent,
            title='子任务：完整详情',
            detail=self.LONG,
            acceptance='逐条验收：\n1. 全文可见\n2. 键盘可关闭',
            execution_spec=self.task.execution_spec,
        )
        html = self.client.get(self.url(f'tab=tasks&task={task.pk}')).content.decode('utf-8')
        self.assertIn('data-task-reader', html)
        self.assertIn(self.LONG.split('\n')[0], html)
        self.assertIn('尾段落：完整正文必须可读。', html)
        self.assertIn('逐条验收', html)
        self.assertIn('总目标节点', html)
        self.assertIn('workroom/static/workroom/app.js', html)
        self.assertIn('python -m pytest tests -q', html)
        self.assertIn('workroom-sha256:abc', html)
        self.assertIn('T070-workbuddy-isolated', html)
        self.assertIn('高', html)
        self.assertIn(f'data-task-id="{task.pk}"', html)
        self.assertIn(f'focus={task.pk}', html)
        self.assertIn('data-task-close', html)

    def test_task_detail_escapes_user_markup(self) -> None:
        task = Task.objects.create(
            project=self.project,
            title='<img src=x onerror=alert(1)>',
            detail='<script>alert(2)</script>',
            acceptance='<style>body{display:none}</style>',
        )
        html = self.client.get(self.url(f'tab=tasks&task={task.pk}')).content.decode('utf-8')
        self.assertNotIn('<img src=x onerror=alert(1)>', html)
        self.assertNotIn('<script>alert(2)</script>', html)
        self.assertNotIn('<style>body{display:none}</style>', html)
        self.assertIn('&lt;script&gt;alert(2)&lt;/script&gt;', html)

    def test_task_from_another_project_is_not_selectable(self) -> None:
        other = Project.objects.create(name='别的项目', goal_title='x')
        foreign = Task.objects.create(project=other, title='别组任务')
        html = self.client.get(self.url(f'tab=tasks&task={foreign.pk}')).content.decode('utf-8')
        self.assertNotIn('data-task-reader', html)
        self.assertNotIn('别组任务', html)

    def test_tree_node_still_links_to_detail(self) -> None:
        html = self.client.get(self.url('tab=tasks')).content.decode('utf-8')
        self.assertIn(f'task={self.task.pk}', html)


@override_settings(WORKROOM_MODE='server')
class TaskDeliveryLinkTests(SpaceFixture):
    def setUp(self) -> None:
        super().setUp()
        owner = User.objects.create_user('owner-delivery')
        ProjectMembership.objects.create(project=self.project, user=owner, role='owner')
        self.client.force_login(owner)

    def test_reader_links_to_delivery_records(self) -> None:
        html = self.client.get(self.url(f'tab=tasks&task={self.task.pk}')).content.decode('utf-8')
        self.assertIn(
            reverse('projects:task_delivery', args=[self.project.pk, self.task.pk]), html
        )


class LibraryReaderTests(SpaceFixture):
    def test_long_entry_opens_read_only_reader(self) -> None:
        body = ('资料正文' * 900) + '\n最后一行。'
        entry = LibraryEntry.objects.create(
            project=self.project,
            kind=LibraryEntry.Kind.ARTIFACT,
            title='长资料',
            body=body,
            context='背景很长的背景',
            conclusion='结论落地方式',
        )
        html = self.client.get(self.url(f'tab=library&entry={entry.pk}')).content.decode(
            'utf-8'
        )
        self.assertIn('data-library-reader', html)
        self.assertIn('资料正文' * 900, html)
        self.assertIn('最后一行。', html)
        self.assertIn('背景很长的背景', html)
        self.assertIn('结论落地方式', html)
        self.assertIn(f'focusEntry={entry.pk}', html)


class ProductBriefTests(SpaceFixture):
    def make_artifact(self, project=None, **overrides):
        values = {
            'project': project or self.project,
            'kind': LibraryEntry.Kind.ARTIFACT,
            'title': '产品说明 v1',
            'summary': '先做内部可用的协作工作台',
            'body': '产品说明全文：' + ('目标用户与边界。' * 400),
            'context': '用户原话与调研',
            'options': '方案 A / 方案 B',
            'conclusion': '首版标准：登录、项目、任务树、交付记录可用。',
            'tags': 'product-definition, 首版',
            'version': 3,
            'is_active': True,
        }
        values.update(overrides)
        return LibraryEntry.objects.create(**values)

    def test_active_artifact_provides_brief_entry_with_full_text(self) -> None:
        entry = self.make_artifact()
        html = self.client.get(self.url('tab=tasks')).content.decode('utf-8')
        self.assertIn('data-product-brief', html)
        self.assertIn('产品说明', html)
        self.assertIn('首版标准', html)
        self.assertIn(entry.body, html)
        self.assertIn('目标用户与边界。', html)
        self.assertIn('首版标准：登录、项目、任务树、交付记录可用。', html)
        self.assertIn('v3', html)

    def test_user_goal_is_not_replaced_by_product_brief(self) -> None:
        self.make_artifact()
        self.client.get(self.url('tab=tasks'))
        self.project.refresh_from_db()
        self.assertEqual(self.project.goal_title, '上线到GitHub并有用户使用')
        html = self.client.get(self.url('tab=chat')).content.decode('utf-8')
        self.assertIn('上线到GitHub并有用户使用', html)
        self.assertIn('用户原话：先给内部试用', html)

    def test_no_brief_without_active_artifact(self) -> None:
        html = self.client.get(self.url('tab=tasks')).content.decode('utf-8')
        self.assertNotIn('data-product-brief', html)

        self.make_artifact(is_active=False)
        html = self.client.get(self.url('tab=tasks')).content.decode('utf-8')
        self.assertNotIn('data-product-brief', html)

        other = Project.objects.create(name='没有说明的项目', goal_title='别的目标')
        self.make_artifact(project=other)
        html = self.client.get(self.url('tab=tasks')).content.decode('utf-8')
        self.assertNotIn('data-product-brief', html)

    def test_artifact_without_the_tag_is_not_a_brief(self) -> None:
        self.make_artifact(tags='范围,一期')
        html = self.client.get(self.url('tab=tasks')).content.decode('utf-8')
        self.assertNotIn('data-product-brief', html)

    def test_brief_never_exposes_member_keys(self) -> None:
        self.make_artifact()
        self.ai.key_ciphertext = 'SEALED-KEY-MUST-NOT-LEAK'
        self.ai.save(update_fields=['key_ciphertext'])
        html = self.client.get(self.url('tab=tasks')).content.decode('utf-8')
        self.assertNotIn('SEALED-KEY-MUST-NOT-LEAK', html)
