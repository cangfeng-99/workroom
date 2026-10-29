"""Stage header status is derived from its children, not stored by hand."""

from django.test import TestCase

from apps.projects.models import Project, Task
from apps.projects.views import _stage_status


class StageStatusTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='S', goal_title='G')
        self.stage = Task.objects.create(
            project=self.project, title='20 开发实现', status=Task.Status.DOING
        )

    def _child(self, status: str) -> Task:
        return Task.objects.create(
            project=self.project, parent=self.stage, title=f'c-{status}', status=status
        )

    def test_all_done_becomes_done(self) -> None:
        items = [self._child(Task.Status.DONE), self._child(Task.Status.DONE)]
        self.assertEqual(_stage_status(self.stage, items), Task.Status.DONE)

    def test_all_todo_becomes_todo(self) -> None:
        items = [self._child(Task.Status.TODO), self._child(Task.Status.TODO)]
        self.assertEqual(_stage_status(self.stage, items), Task.Status.TODO)

    def test_mixed_falls_back_to_doing(self) -> None:
        items = [self._child(Task.Status.DONE), self._child(Task.Status.TODO)]
        self.assertEqual(_stage_status(self.stage, items), Task.Status.DOING)

    def test_blocked_wins_unless_all_done(self) -> None:
        items = [self._child(Task.Status.DONE), self._child(Task.Status.BLOCKED)]
        self.assertEqual(_stage_status(self.stage, items), Task.Status.BLOCKED)

    def test_empty_keeps_stored_status(self) -> None:
        self.assertEqual(_stage_status(self.stage, []), Task.Status.DOING)

    def test_explicit_blocked_survives_finished_children(self) -> None:
        blocked = Task.objects.create(
            project=self.project, title='40 发布试用', status=Task.Status.BLOCKED,
            blocked_reason='发布材料还缺截图', unblock_action='先补截图',
        )
        items = [self._child(Task.Status.DONE), self._child(Task.Status.DONE)]
        self.assertEqual(_stage_status(blocked, items), Task.Status.BLOCKED)
