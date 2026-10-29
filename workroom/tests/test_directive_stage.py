"""New AI tasks land in the matching lifecycle stage."""

from django.test import TestCase

from apps.projects import directives
from apps.projects.models import Project, Task


class PickStageTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='P', goal_title='G')
        self.root = Task.objects.create(
            project=self.project, title='10 全生命周期地图', status=Task.Status.DOING
        )
        for title in (
            '00 立项前期', '10 方案设计', '20 开发实现',
            '30 测试验收', '40 发布试用', '50 复盘迭代',
        ):
            Task.objects.create(project=self.project, parent=self.root, title=title)

    def _pick(self, title: str) -> str:
        stage = directives.pick_stage(self.project, title)
        return stage.title if stage else ''

    def test_release_goes_to_40(self) -> None:
        self.assertTrue(self._pick('写使用说明文档').startswith('40'))

    def test_testing_goes_to_30(self) -> None:
        self.assertTrue(self._pick('补一个测试用例').startswith('30'))

    def test_leading_keyword_wins(self) -> None:
        # 「发布」出现在「测试」之前，按 40 归类
        self.assertTrue(self._pick('开始发布测试').startswith('40'))

    def test_development_is_the_default(self) -> None:
        self.assertTrue(self._pick('随便一件事').startswith('20'))

    def test_unknown_project_returns_none(self) -> None:
        bare = Project.objects.create(name='B', goal_title='G')
        self.assertIsNone(directives.pick_stage(bare, '随便一件事'))
