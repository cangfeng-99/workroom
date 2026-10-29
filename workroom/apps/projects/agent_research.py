"""Delegate competitor research to any local agent (A2A-Hub or a CLI)."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import time
from pathlib import Path

A2A = Path(os.environ.get('A2A_HOME', r'D:\A2A-Hub'))
ANSI = re.compile(r'\x1b\[[0-9;]*m')

# 优先顺序可配置，例如 RESEARCH_AGENTS=codex,workbuddy,deepseek,cursor
AGENTS = [
    item.strip()
    for item in os.environ.get(
        'RESEARCH_AGENTS', 'codex,workbuddy,deepseek,claude-code'
    ).split(',')
    if item.strip()
]
# 任意 CLI，例如 RESEARCH_CLI=cursor-agent -p {prompt}
CLI_CMD = os.environ.get('RESEARCH_CLI', '').strip()

_PROMPT = (
    '用网络搜索调研这个想法：{idea}\n'
    '输出 3 到 5 个同类产品或开源方案，每条一行，格式：'
    '名称｜他们的做法｜可借鉴的点｜来源 URL。'
    '不确定的数字、定价、市占率写「需核实」，不要编造。只输出列表。'
)


def _a2a_ready() -> bool:
    return (A2A / 'run.py').exists() and (A2A / '.venv' / 'Scripts' / 'python.exe').exists()


def available() -> bool:
    return _a2a_ready() or bool(CLI_CMD)


def _clean(raw: str) -> str:
    text = ANSI.sub('', raw).replace('\r', '')
    kept = []
    for line in text.split('\n'):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(('INFO', '──', '◐', '✗', 'taskId=')):
            continue
        if re.match(r'^\d{2}:\d{2}:\d{2}\s+(INFO|WARNING|ERROR)', stripped):
            continue
        if '● completed' in line:
            head = line.split('● completed')[0].rstrip()
            if head:
                kept.append(head)
            continue
        kept.append(line.rstrip())
    return '\n'.join(kept).strip()


def _run_a2a(agent: str, prompt: str, timeout: int) -> str:
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    try:
        proc = subprocess.run(
            [
                str(A2A / '.venv' / 'Scripts' / 'python.exe'),
                str(A2A / 'run.py'),
                'ask',
                prompt,
                '--agent',
                agent,
            ],
            cwd=str(A2A),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ''
    return _clean((proc.stdout or '') + (proc.stderr or ''))


def _run_cli(prompt: str, timeout: int) -> str:
    if not CLI_CMD:
        return ''
    args = [part.replace('{prompt}', prompt) for part in shlex.split(CLI_CMD)]
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ''
    return _clean((proc.stdout or '') + (proc.stderr or ''))


def research(idea: str, timeout: int = 120) -> str:
    prompt = _PROMPT.format(idea=(idea or '').strip()[:300])
    deadline = time.monotonic() + timeout
    if _a2a_ready():
        for agent in AGENTS:
            remaining = deadline - time.monotonic()
            if remaining < 10:
                break
            text = _run_a2a(agent, prompt, int(min(60, remaining)))
            if text:
                return text[:4000]
    remaining = deadline - time.monotonic()
    if CLI_CMD and remaining >= 10:
        text = _run_cli(prompt, int(min(60, remaining)))
        if text:
            return text[:4000]
    return ''
