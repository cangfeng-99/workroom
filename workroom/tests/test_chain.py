"""Dependency chain tracing around a focused task."""

from django.test import TestCase

from apps.projects import chain
from apps.projects.models import Project, Task


class ChainTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='D', goal_title='G')
        self.a = Task.objects.create(project=self.project, title='A')
        self.b = Task.objects.create(project=self.project, title='B')
        self.c = Task.objects.create(project=self.project, title='C')
        self.side = Task.objects.create(project=self.project, title='无关任务')
        self.b.prerequisites.add(self.a)
        self.c.prerequisites.add(self.b)

    def test_upstream_and_downstream(self) -> None:
        result = chain.build(self.project, self.b.pk)
        self.assertEqual(result['upstream'], [self.a.pk])
        self.assertEqual(result['downstream'], [self.c.pk])
        self.assertEqual(result['size'], 3)

    def test_isolated_task_has_empty_chain(self) -> None:
        result = chain.build(self.project, self.side.pk)
        self.assertEqual(result['upstream'], [])
        self.assertEqual(result['downstream'], [])
        self.assertEqual(result['size'], 1)
        self.assertEqual(result['links'], [])

    def test_links_only_include_chain_members(self) -> None:
        result = chain.build(self.project, self.c.pk)
        self.assertIn((self.c.pk, self.b.pk), result['links'])
        self.assertIn((self.b.pk, self.a.pk), result['links'])
        self.assertTrue(all(self.side.pk not in pair for pair in result['links']))
