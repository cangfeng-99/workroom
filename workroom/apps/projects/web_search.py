"""Competitor research for kickoff discussions.

Uses Tavily when TAVILY_API_KEY is present (env or workroom/.env);
otherwise returns a clearly-marked fallback so prompts can say 需核实.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = 'https://api.tavily.com/search'
ENV_FILE = Path(__file__).resolve().parents[2] / '.env'


def _key() -> str:
    value = os.environ.get('TAVILY_API_KEY', '').strip()
    if value:
        return value
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding='utf-8', errors='replace').splitlines():
            if line.strip().startswith('TAVILY_API_KEY='):
                return line.split('=', 1)[1].strip().strip('"').strip("'")
    return ''


def available() -> bool:
    return bool(_key())


def search(query: str, max_results: int = 4, timeout: int = 20) -> list[dict]:
    key = _key()
    if not key:
        return []
    body = json.dumps(
        {
            'api_key': key,
            'query': query[:200],
            'max_results': max_results,
            'include_answer': True,
            'search_depth': 'basic',
        }
    ).encode()
    request = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode('utf-8'))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return []
    items = []
    for row in data.get('results') or []:
        if not isinstance(row, dict):
            continue
        items.append(
            {
                'title': str(row.get('title') or '')[:120],
                'url': str(row.get('url') or '')[:300],
                'content': str(row.get('content') or '').strip()[:400],
            }
        )
    return items


def research_block(idea: str) -> str:
    text = (idea or '').strip()
    if not text:
        return ''
    if not available():
        from . import agent_research

        if agent_research.available():
            text = agent_research.research(text)
            if text:
                return (
                    '由外部 Agent（Codex / WorkBuddy 等）联网调研（来源以它给出的 URL 为准；'
                    '没有来源的数字必须标注「需核实」）：\n' + text
                )
        return (
            '未配置搜索 API，外部 Agent 也不可用：竞品部分只能基于模型已有知识，'
            '所有具体数字、定价、市占率必须标注「需核实」，不得编造。'
        )
    queries = [text[:80], f'{text[:60]} 同类产品 对比']
    lines = ['搜索到的竞品材料（引用时保留来源，没有来源的写需核实）：']
    seen: set[str] = set()
    for query in queries:
        for item in search(query):
            if not item['url'] or item['url'] in seen:
                continue
            seen.add(item['url'])
            lines.append(
                f"- {item['title']}｜来源：{item['url']}｜{item['content']}"
            )
    if len(lines) == 1:
        lines.append('搜索没有返回可用结果；竞品部分按「需核实」处理。')
    return '\n'.join(lines)
