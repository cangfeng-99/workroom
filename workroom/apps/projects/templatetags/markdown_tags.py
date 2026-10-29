"""Minimal, escaping-first Markdown for chat bubbles.

Supports headings, unordered/ordered lists, bold, inline code and fenced code.
Raw HTML is escaped before parsing, so model output cannot inject markup.
"""

from __future__ import annotations

import html
import re

from django import template
from django.utils.safestring import mark_safe

register = template.Library()

_BOLD = re.compile(r'\*\*(.+?)\*\*')
_CODE = re.compile(r'`([^`\n]+)`')
_HEADING = re.compile(r'^(#{1,4})\s+(.*)$')
_UL = re.compile(r'^[-*]\s+(.*)$')
_OL = re.compile(r'^(\d+)[.)]\s+(.*)$')


def _inline(text: str) -> str:
    text = _CODE.sub(lambda m: f'<code>{m.group(1)}</code>', text)
    return _BOLD.sub(lambda m: f'<strong>{m.group(1)}</strong>', text)


def render_markdown(value: str) -> str:
    source = html.escape(str(value or ''))
    lines = source.split('\n')
    out: list[str] = []
    list_type: str | None = None
    in_code = False
    code_lines: list[str] = []

    def close_list() -> None:
        nonlocal list_type
        if list_type:
            out.append(f'</{list_type}>')
            list_type = None

    for line in lines:
        stripped = line.strip()
        if stripped.startswith('```'):
            if in_code:
                out.append('<pre><code>' + '\n'.join(code_lines) + '</code></pre>')
                code_lines = []
                in_code = False
            else:
                close_list()
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        if not stripped:
            close_list()
            continue

        heading = _HEADING.match(stripped)
        if heading:
            close_list()
            level = min(len(heading.group(1)) + 2, 6)
            out.append(f'<h{level}>{_inline(heading.group(2))}</h{level}>')
            continue

        bullet = _UL.match(stripped)
        if bullet:
            if list_type != 'ul':
                close_list()
                out.append('<ul>')
                list_type = 'ul'
            out.append(f'<li>{_inline(bullet.group(1))}</li>')
            continue

        numbered = _OL.match(stripped)
        if numbered:
            if list_type != 'ol':
                close_list()
                out.append('<ol>')
                list_type = 'ol'
            out.append(
                f'<li value="{numbered.group(1)}">{_inline(numbered.group(2))}</li>'
            )
            continue

        close_list()
        out.append(f'<p>{_inline(stripped)}</p>')

    if in_code:
        out.append('<pre><code>' + '\n'.join(code_lines) + '</code></pre>')
    close_list()
    return mark_safe('\n'.join(out))


register.filter('markdown', render_markdown)
