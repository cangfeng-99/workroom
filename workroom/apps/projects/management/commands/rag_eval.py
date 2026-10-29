"""跑 RAG 评测集：命中率、逐题明细、失败类型。

评测集格式（JSON 数组）：
[
  {"question": "验收流程是什么", "expect": ["验收标准", "证据"]},
  {"question": "谁可以提交交付", "expect": ["负责人", "提交"]}
]
expect 里任一关键词出现在 Top-K 命中内容里，算该题命中。
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.projects import rag
from apps.projects.models import Project


class Command(BaseCommand):
    help = '用评测集检查检索命中率'

    def add_arguments(self, parser):
        parser.add_argument('--project', type=int, required=True, help='项目 id')
        parser.add_argument('--file', type=str, required=True, help='评测集 JSON 路径')
        parser.add_argument('--k', type=int, default=5, help='取前几块参与判定，默认 5')

    def handle(self, *args, **options):
        project = Project.objects.filter(pk=options['project']).first()
        if project is None:
            raise CommandError(f'项目 {options["project"]} 不存在')

        path = Path(options['file']).expanduser()
        if not path.exists():
            raise CommandError(f'评测集不存在：{path}')
        try:
            cases = json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as exc:
            raise CommandError(f'评测集不是合法 JSON：{exc}') from exc
        if not isinstance(cases, list) or not cases:
            raise CommandError('评测集必须是非空数组')

        status = rag.index_status(project)
        if not status['chunks']:
            raise CommandError('这个项目还没有索引，先跑 rag_index')

        total = 0
        hit = 0
        missing: list[str] = []
        for case in cases:
            question = str(case.get('question') or '').strip()
            expects = [str(item).strip() for item in (case.get('expect') or []) if str(item).strip()]
            if not question or not expects:
                continue
            total += 1
            hits = rag.search(project, question, k=options['k'])
            joined = '\n'.join(item['content'] for item in hits)
            matched = [word for word in expects if word in joined]
            top_title = hits[0]['title'] if hits else '（无命中）'
            if matched:
                hit += 1
                self.stdout.write(f'✓ {question} → {top_title}（命中：{"、".join(matched)}）')
            else:
                missing.append(question)
                self.stdout.write(
                    self.style.WARNING(f'✗ {question} → {top_title}（期望：{"、".join(expects)}）')
                )

        if not total:
            raise CommandError('评测集里没有有效题目（需要 question 与 expect）')

        rate = hit / total * 100
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'命中率：{hit}/{total} = {rate:.0f}%（Top-{options["k"]}）'))
        if missing:
            self.stdout.write('失败题目：')
            for item in missing:
                self.stdout.write(f'  - {item}')
