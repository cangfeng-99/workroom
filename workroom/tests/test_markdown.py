"""Tests for the chat Markdown renderer."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.projects.templatetags.markdown_tags import render_markdown


class MarkdownTests(SimpleTestCase):
    def test_bold_and_inline_code(self) -> None:
        html = render_markdown('**第 4 步** 用 `login` 接口')
        self.assertIn('<strong>第 4 步</strong>', html)
        self.assertIn('<code>login</code>', html)

    def test_bullets(self) -> None:
        html = render_markdown('- 甲\n- 乙')
        self.assertIn('<ul>', html)
        self.assertIn('<li>甲</li>', html)
        self.assertIn('<li>乙</li>', html)

    def test_numbered(self) -> None:
        html = render_markdown('1. 一\n2. 二')
        self.assertIn('<ol>', html)
        self.assertIn('<li value="2">二</li>', html)

    def test_heading(self) -> None:
        self.assertIn('<h4>', render_markdown('## 计划'))

    def test_paragraphs(self) -> None:
        html = render_markdown('第一段\n\n第二段')
        self.assertEqual(html.count('<p>'), 2)

    def test_html_is_escaped(self) -> None:
        html = render_markdown('<script>alert(1)</script>')
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)

    def test_code_block(self) -> None:
        html = render_markdown('```\nprint(1)\n```')
        self.assertIn('<pre><code>', html)
        self.assertIn('print(1)', html)
