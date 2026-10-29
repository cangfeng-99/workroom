from django.test import SimpleTestCase

from apps.projects.views import _decision_ready


class DecisionReadyTests(SimpleTestCase):
    def _text(self, dissent='产品担心范围过大', confidence='中', extra=''):
        return (
            '【已达成一致】\n结论：先做单人版\n依据：路线文档 + 测试通过\n'
            f'反方意见：{dissent}\n未解决：打包时间\n置信度：{confidence}\n{extra}'
        )

    def test_complete_decision_is_ready(self) -> None:
        self.assertTrue(_decision_ready(self._text()))

    def test_missing_section_is_not_ready(self) -> None:
        self.assertFalse(_decision_ready('结论：做\n依据：无'))

    def test_need_more_round(self) -> None:
        self.assertFalse(_decision_ready(self._text(extra='仍需讨论')))

    def test_no_dissent_with_high_confidence(self) -> None:
        self.assertFalse(_decision_ready(self._text(dissent='无', confidence='高')))

    def test_no_dissent_with_medium_confidence(self) -> None:
        self.assertTrue(_decision_ready(self._text(dissent='无', confidence='中')))
