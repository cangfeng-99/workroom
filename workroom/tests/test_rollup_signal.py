"""Parent stage status follows child writes automatically."""

from django.test import TestCase

from apps.projects.models import Project, Task


class RollupSignalTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='R', goal_title='G')
        self.stage = Task.objects.create(
            project=self.project, title='20 开发实现', status=Task.Status.DOING
        )

    def _child(self, title: str, status: str) -> Task:
        return Task.objects.create(
            project=self.project, parent=self.stage, title=title, status=status
        )

    def test_all_children_done_flips_stage(self) -> None:
        first = self._child('a', Task.Status.DONE)
        self._child('b', Task.Status.TODO)
        self.stage.refresh_from_db()
        self.assertEqual(self.stage.status, Task.Status.DOING)

        Task.objects.filter(pk=first.pk).update(status=Task.Status.DONE)
        Task.objects.filter(pk=self.stage.pk).update(status=Task.Status.DOING)
        second = Task.objects.get(project=self.project, title='b')
        second.status = Task.Status.DONE
        second.save(update_fields=['status'])

        self.stage.refresh_from_db()
        self.assertEqual(self.stage.status, Task.Status.DONE)

    def test_new_todo_child_keeps_stage_going(self) -> None:
        self._child('a', Task.Status.DONE)
        self._child('b', Task.Status.TODO)
        self.stage.refresh_from_db()
        self.assertEqual(self.stage.status, Task.Status.DOING)

    def test_delete_child_recomputes(self) -> None:
        self._child('a', Task.Status.DONE)
        blocker = self._child('b', Task.Status.BLOCKED)
        self.stage.refresh_from_db()
        self.assertEqual(self.stage.status, Task.Status.BLOCKED)

        blocker.delete()
        self.stage.refresh_from_db()
        self.assertEqual(self.stage.status, Task.Status.DONE)

    def test_three_levels_bubble_up(self) -> None:
        branch = Task.objects.create(
            project=self.project, parent=self.stage, title='branch', status=Task.Status.DOING
        )
        Task.objects.create(
            project=self.project, parent=branch, title='leaf-a', status=Task.Status.DONE
        )
        leaf = Task.objects.create(
            project=self.project, parent=branch, title='leaf-b', status=Task.Status.TODO
        )

        stem = Task.objects.create(
            project=self.project, title='10 全生命周期', status=Task.Status.DOING
        )
        self.stage.parent = stem
        self.stage.save(update_fields=['parent'])

        leaf.status = Task.Status.DONE
        leaf.save(update_fields=['status'])

        branch.refresh_from_db()
        self.stage.refresh_from_db()
        stem.refresh_from_db()
        self.assertEqual(branch.status, Task.Status.DONE)
        self.assertEqual(self.stage.status, Task.Status.DONE)
        self.assertEqual(stem.status, Task.Status.DONE)
