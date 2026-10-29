"""Task-tree drift: code moved but no task was added."""

import os
import tempfile
from datetime import timedelta
from pathlib import Path

from django.test import TestCase
from django.utils import timezone

from apps.projects import drift
from apps.projects.models import Project, Task


class DriftHintTests(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'apps').mkdir()
        self.project = Project.objects.create(name='D', goal_title='G')

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_old(self, name: str = 'a.py', hours: int = 0) -> Path:
        path = self.root / 'apps' / name
        path.write_text('x = 1', encoding='utf-8')
        stamp = (timezone.now() - timedelta(hours=hours)).timestamp()
        os.utime(path, (stamp, stamp))
        return path

    def test_no_code_returns_empty(self) -> None:
        self.assertEqual(drift.hint(self.project, self.root), '')

    def test_fresh_code_without_tasks_is_flagged(self) -> None:
        self._write_old(hours=30)
        hint = drift.hint(self.project, self.root)
        self.assertIn('任务树没有对应节点', hint)
        self.assertIn('30 小时前', hint)

    def test_task_newer_than_code_is_quiet(self) -> None:
        self._write_old(hours=48)
        Task.objects.create(project=self.project, title='刚补的节点')
        self.assertEqual(drift.hint(self.project, self.root), '')

    def test_recent_change_within_threshold_is_quiet(self) -> None:
        self._write_old(hours=2)
        self.assertEqual(drift.hint(self.project, self.root), '')

    def test_ignores_pycache_and_migrations(self) -> None:
        cache = self.root / 'apps' / '__pycache__'
        cache.mkdir()
        (cache / 'x.py').write_text('x', encoding='utf-8')
        migrations = self.root / 'apps' / 'migrations'
        migrations.mkdir()
        (migrations / '0001.py').write_text('x', encoding='utf-8')
        self.assertEqual(drift.hint(self.project, self.root), '')

    def test_frozen_build_never_flags(self) -> None:
        self._write_old(hours=30)
        with self.settings(FROZEN=True):
            self.assertEqual(drift.hint(self.project, self.root), '')

    def test_missing_apps_dir_never_flags(self) -> None:
        empty = self.root / 'empty'
        empty.mkdir()
        self.assertEqual(drift.hint(self.project, empty), '')
