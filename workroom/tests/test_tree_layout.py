"""Tests for the column tree layout."""

from __future__ import annotations

from django.test import TestCase

from apps.projects.models import Project, Task
from apps.projects.tree import NODE_WIDTH, build_tree


class ColumnLayoutTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='P', goal_title='目标')
        self.a = Task.objects.create(project=self.project, title='A')
        self.a1 = Task.objects.create(
            project=self.project, title='A1', parent=self.a
        )
        self.b = Task.objects.create(project=self.project, title='B')
        self.b1 = Task.objects.create(
            project=self.project, title='B1', parent=self.b
        )
        self.b2 = Task.objects.create(
            project=self.project, title='B2', parent=self.b1
        )

    def test_one_column_per_root(self) -> None:
        tree = build_tree(self.project.tasks.all())
        self.assertEqual(len(tree['columns']), 2)
        self.assertEqual(len(tree['nodes']), 5)

    def test_nodes_stay_inside_their_column(self) -> None:
        tree = build_tree(self.project.tasks.all())
        columns = tree['columns']
        for node in tree['nodes']:
            column = next(
                (
                    col
                    for col in columns
                    if col['x'] <= node['x'] <= col['x'] + col['w']
                ),
                None,
            )
            self.assertIsNotNone(column, node['task'].title)
            self.assertLessEqual(node['x'] + NODE_WIDTH, column['x'] + column['w'] + 1)

    def test_goal_is_at_the_end_of_the_axis(self) -> None:
        tree = build_tree(self.project.tasks.all())
        goal = tree['goal']
        self.assertTrue(
            all(goal['x'] >= node['x'] + NODE_WIDTH for node in tree['nodes'])
        )
        self.assertEqual(goal['y'], min(node['y'] for node in tree['nodes']))

    def test_empty_project(self) -> None:
        empty = Project.objects.create(name='Empty', goal_title='x')
        tree = build_tree(empty.tasks.all())
        self.assertEqual(tree['nodes'], [])
        self.assertEqual(tree['columns'], [])
