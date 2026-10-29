"""页面冒烟：关键路由能打开，不依赖登录态在本地模式下的行为。"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.projects.models import LibraryEntry, Project


class PageSmokeTests(TestCase):
    """只要这些页面 200，就说明模板、路由、上下文没炸。"""

    def setUp(self) -> None:
        self.user = get_user_model().objects.create_user(
            username='smoke_user', password='pass-12345'
        )
        self.project = Project.objects.create(
            name='冒烟项目', goal_title='跑通', owner=self.user
        )
        LibraryEntry.objects.create(
            project=self.project,
            kind=LibraryEntry.Kind.RULE,
            title='规则一条',
            body='冒烟用资料。',
        )
        self.client.force_login(self.user)

    def test_index(self) -> None:
        self.assertEqual(self.client.get(reverse('projects:index')).status_code, 200)

    def test_project_space_default(self) -> None:
        url = reverse('projects:space', args=[self.project.pk])
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_project_tabs(self) -> None:
        url = reverse('projects:space', args=[self.project.pk])
        for tab in ('tasks', 'library', 'chat', 'progress'):
            with self.subTest(tab=tab):
                response = self.client.get(url, {'tab': tab})
                self.assertEqual(response.status_code, 200)

    def test_knowledge_page(self) -> None:
        url = reverse('projects:knowledge', args=[self.project.pk])
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_local_pages(self) -> None:
        for name in ('policy',):
            with self.subTest(name=name):
                self.assertEqual(
                    self.client.get(
                        reverse(f'projects:{name}', args=[self.project.pk])
                    ).status_code,
                    200,
                )

    def test_guide(self) -> None:
        self.assertEqual(self.client.get(reverse('projects:guide')).status_code, 200)

    def test_server_only_pages_404_in_local_mode(self) -> None:
        """单人模式没有项目设置和工具连接页，这是既有行为，先用测试钉住。"""
        for name in ('settings', 'connections'):
            with self.subTest(name=name):
                self.assertEqual(
                    self.client.get(
                        reverse(f'projects:{name}', args=[self.project.pk])
                    ).status_code,
                    404,
                )

    def test_healthz(self) -> None:
        self.assertEqual(self.client.get(reverse('projects:healthz')).status_code, 200)


class TaskFilterTests(TestCase):
    """任务页的搜索与筛选：命中子任务时要保留上级，不然树会断。"""

    def setUp(self) -> None:
        from apps.projects.models import Task

        self.user = get_user_model().objects.create_user(
            username='filter_user', password='pass-12345'
        )
        self.project = Project.objects.create(
            name='筛选项目', goal_title='跑通', owner=self.user
        )
        self.parent = Task.objects.create(
            project=self.project, title='阶段一 搭建', status=Task.Status.DOING
        )
        self.child = Task.objects.create(
            project=self.project,
            title='登录模块',
            detail='做账号密码登录',
            parent=self.parent,
            status=Task.Status.TODO,
        )
        self.other = Task.objects.create(
            project=self.project, title='支付模块', status=Task.Status.DONE
        )
        self.client.force_login(self.user)
        self.url = reverse('projects:space', args=[self.project.pk])

    def test_keyword_keeps_parent(self) -> None:
        response = self.client.get(self.url, {'tab': 'tasks', 'q': '登录'})
        self.assertContains(response, '登录模块')
        self.assertContains(response, '阶段一 搭建')
        self.assertNotContains(response, '支付模块')

    def test_status_filter(self) -> None:
        response = self.client.get(self.url, {'tab': 'tasks', 'status': 'done'})
        self.assertContains(response, '支付模块')
        self.assertNotContains(response, '登录模块')

    def test_clear_filter_link_appears(self) -> None:
        response = self.client.get(self.url, {'tab': 'tasks', 'q': '登录'})
        self.assertContains(response, '清除')


class TaskArchiveTests(TestCase):
    """归档：任务移入「归档」分支后默认隐藏，可在归档视图恢复。"""

    def setUp(self) -> None:
        from apps.projects.models import Task

        self.user = get_user_model().objects.create_user(
            username='archive_user', password='pass-12345'
        )
        self.project = Project.objects.create(
            name='归档项目', goal_title='跑通', owner=self.user
        )
        self.task = Task.objects.create(project=self.project, title='临时任务')
        self.client.force_login(self.user)

    def test_archive_hides_task_and_restore_brings_it_back(self) -> None:
        from apps.projects.models import Task

        self.client.post(
            reverse('projects:task_archive', args=[self.project.pk, self.task.pk])
        )
        self.task.refresh_from_db()
        self.assertIsNotNone(self.task.parent_id)
        self.assertTrue(self.task.parent.title.startswith('归档'))

        space = reverse('projects:space', args=[self.project.pk])
        self.assertNotContains(self.client.get(space, {'tab': 'tasks'}), '临时任务')

        self.client.post(
            reverse('projects:task_restore', args=[self.project.pk, self.task.pk])
        )
        self.task.refresh_from_db()
        self.assertIsNone(self.task.parent_id)
        self.assertContains(self.client.get(space, {'tab': 'tasks'}), '临时任务')
        self.assertTrue(Task.objects.filter(project=self.project).exists())
