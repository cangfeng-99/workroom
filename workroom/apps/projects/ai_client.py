"""HTTPS Chat Completions client for one project AI member.

The key is decrypted only for the duration of one request. This module never
logs it and never puts it in an error message.

Network rules:
- HTTPS on port 443 only, no userinfo/query/fragment/backslash/``..``;
- resolve every DNS answer and refuse the request if *any* answer is not a
  globally routable address (loopback, private, link-local, reserved, ...);
- pin the verified address while keeping the original hostname for TLS/SNI;
- no redirects, no proxy environment, 60 s timeout, 256 KiB response ceiling.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import re
import socket
import ssl
from urllib.parse import urlsplit

MAX_KEY_CHARS = 512
MAX_BODY_BYTES = 8 * 1024 * 1024
TIMEOUT_SECONDS = 600
MAX_TOKENS = 16384
PORT = 443

_HOST_RE = re.compile(
    r'^(?=.{1,253}$)'
    r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?'
    r'(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$'
)
_PATH_RE = re.compile(r'^(?:/[A-Za-z0-9._-]+)*$')

_MESSAGES = {
    'invalid_url': '模型地址无效：请填写 https:// 开头的域名，443 端口，不能包含账号、查询参数或 .. 。',
    'invalid_key': 'API Key 无效：请检查是否为空、过长，或包含空格、换行及异常字符。',
    'invalid_model': '模型名称无效，请检查后重试。',
    'dns': '无法解析模型地址的域名，请检查网络或地址。',
    'network': '连接模型服务失败，请检查网络后重试。',
    'timeout': '模型服务响应超时，请稍后重试。',
    'tls': '模型服务的 HTTPS 证书校验失败，请确认地址。',
    'redirect': '模型地址返回了重定向；出于安全考虑不会跟随。',
    'auth': '模型服务拒绝了 API Key（401），请检查后重试。',
    'forbidden': '模型服务拒绝访问（403），请检查账号权限。',
    'rate_limited': '模型服务限流（429），请稍后重试。',
    'server': '模型服务暂时不可用（5xx），请稍后重试。',
    'http': '模型服务返回了异常状态。',
    'too_large': '模型返回内容过大，已停止读取。',
    'empty': '模型返回了空响应。',
    'truncated': '模型返回内容不完整（连接被截断）。',
    'malformed': '模型返回的不是有效 JSON 任务草案。',
    'output_limit': '模型输出达到长度上限，草案尚未完成。请缩小目标范围后重试。',
}

SYSTEM_PROMPT = (
    '你是一个项目任务规划助手。只根据用户给出的目标、起止日期和项目成员角色，'
    '把工作拆成可执行的任务树。不得读取或假设任何文件、命令、代码执行结果；'
    '不得调用工具；不得输出任务之外的内容。成员只是负责人候选，不代表已经执行任务。'
    '分配任务时参考每个成员的角色与身份设定，把任务交给最合适的人或 AI。'
    '只输出一个 JSON 对象，不要 Markdown 代码块，不要注释。'
)

_SCHEMA = """返回格式（严格 JSON）：
{
  "tasks": [
    {
      "ref": "t1",
      "parent_ref": null,
      "prerequisite_refs": [],
      "title": "任务标题",
      "detail": "任务内容",
      "start_date": "YYYY-MM-DD",
      "end_date": "YYYY-MM-DD",
      "assignee_id": 12,
      "priority": "normal"
    }
  ]
}

规则：
- tasks 为 1 到 15 个任务；ref 是唯一的短 ASCII 标识（字母、数字、_ 或 -）。
- 恰好一个根任务（parent_ref 为 null）且必须排在第一位；其余任务必须引用此前出现过的 ref。
- parent_ref 只表示层级。prerequisite_refs 表示必须先完成的任务编号数组，没有前置就用 []；只能引用同一份草稿中的 ref，允许引用后面的任务，不能引用自己或形成循环。
- 任务树深度不超过 5；日期为 YYYY-MM-DD 且落在整体起止日期内，结束日期不早于开始日期。
- assignee_id 只能取给定成员的 id，或为 null；priority 只能是 low、normal、high、urgent。
- title 最多 160 字，detail 最多 4000 字。不要遗漏字段，不要添加其他顶层字段。"""


class PlannerClientError(Exception):
    """A safe, user-facing failure. ``code`` is used by tests and callers."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        self.message = message or _MESSAGES.get(code, '调用模型失败，请稍后重试。')
        super().__init__(self.message)


def normalize_base_url(raw: str) -> tuple[str, str]:
    """Return ``(host, request_path)`` for a validated base URL."""
    if not isinstance(raw, str):
        raise PlannerClientError('invalid_url')
    value = raw.strip()
    if not value or len(value) > 500:
        raise PlannerClientError('invalid_url')
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise PlannerClientError('invalid_url')
    if '\\' in value or '\u3000' in value or ' ' in value:
        raise PlannerClientError('invalid_url')
    try:
        parts = urlsplit(value)
    except ValueError as exc:
        raise PlannerClientError('invalid_url') from exc
    if parts.scheme.lower() != 'https' or not parts.netloc:
        raise PlannerClientError('invalid_url')
    if parts.username is not None or parts.password is not None or '@' in parts.netloc:
        raise PlannerClientError('invalid_url')
    if parts.query or parts.fragment:
        raise PlannerClientError('invalid_url')
    try:
        port = parts.port
    except ValueError as exc:
        raise PlannerClientError('invalid_url') from exc
    if port not in (None, PORT):
        raise PlannerClientError('invalid_url')
    host = (parts.hostname or '').lower()
    if not host or not _HOST_RE.fullmatch(host):
        raise PlannerClientError('invalid_url')
    path = (parts.path or '').rstrip('/')
    if path and not _PATH_RE.fullmatch(path):
        raise PlannerClientError('invalid_url')
    segments = [segment for segment in path.split('/') if segment]
    if any(segment in ('.', '..') for segment in segments):
        raise PlannerClientError('invalid_url')
    path = '/' + '/'.join(segments) if segments else ''
    if path.endswith('/chat/completions'):
        raise PlannerClientError('invalid_url')
    return host, f'{path}/chat/completions'


def validate_api_key(raw: str) -> str:
    if not isinstance(raw, str) or not raw or len(raw) > MAX_KEY_CHARS:
        raise PlannerClientError('invalid_key')
    if any(not 32 < ord(char) < 127 for char in raw):
        raise PlannerClientError('invalid_key')
    return raw


def validate_model_name(raw: str) -> str:
    if not isinstance(raw, str):
        raise PlannerClientError('invalid_model')
    value = raw.strip()
    if not value or len(value) > 200:
        raise PlannerClientError('invalid_model')
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise PlannerClientError('invalid_model')
    return value


def resolve_public_ips(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve all answers and reject the whole request on any non-global IP."""
    try:
        infos = socket.getaddrinfo(host, PORT, type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError, UnicodeError) as exc:
        raise PlannerClientError('dns') from exc
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        raw_ip = info[4][0]
        try:
            address = ipaddress.ip_address(str(raw_ip).split('%', 1)[0])
        except ValueError as exc:
            raise PlannerClientError('dns') from exc
        if not address.is_global or address.is_multicast or address.is_reserved:
            raise PlannerClientError('dns', '模型地址解析到了非公网地址，已拒绝连接。')
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise PlannerClientError('dns')
    # Prefer IPv4 (common on Windows dev machines) while keeping a verified
    # IPv6 answer available when it is the only option.
    addresses.sort(key=lambda item: item.version != 4)
    return addresses


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to the verified IP but keep the hostname for certificate checks."""

    def __init__(self, host: str, ip, timeout: int, context: ssl.SSLContext) -> None:
        super().__init__(host=host, port=PORT, timeout=timeout, context=context)
        self._pinned_ip = str(ip)

    def connect(self) -> None:
        sock = socket.create_connection((self._pinned_ip, PORT), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


def _build_messages(
    objective: str,
    start_date: str,
    end_date: str,
    instructions: str,
    members: list[dict],
) -> list[dict]:
    member_lines = [
        f'- id={member["id"]} 名称={member["name"]}'
        f' 类型={member["kind"]} 角色={member["role"] or "未填写"}'
        + (
            f' 身份设定={str(member["persona"]).strip()[:400]}'
            if member.get('persona')
            else ''
        )
        for member in members
    ]
    user_prompt = '\n'.join(
        [
            f'项目整体目标：{objective}',
            f'整体开始日期：{start_date}',
            f'整体结束日期：{end_date}',
            '项目指令：',
            instructions or '（未填写）',
            '项目成员（仅可作为负责人，不代表会执行）：',
            '\n'.join(member_lines) if member_lines else '（还没有成员）',
            '',
            _SCHEMA,
        ]
    )
    return [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {'role': 'user', 'content': user_prompt},
    ]


def _http_error(status: int) -> PlannerClientError:
    if status in (301, 302, 303, 307, 308):
        return PlannerClientError('redirect')
    if status == 401:
        return PlannerClientError('auth')
    if status == 403:
        return PlannerClientError('forbidden')
    if status == 429:
        return PlannerClientError('rate_limited')
    if 500 <= status <= 599:
        return PlannerClientError('server')
    return PlannerClientError('http', f'模型服务返回了异常状态（{status}）。')


def _post_chat(
    *,
    base_url: str,
    model: str,
    api_key: str,
    messages: list[dict],
    json_mode: bool,
) -> str:
    """Send one Chat Completions request and return the message content text."""
    host, path = normalize_base_url(base_url)
    key = validate_api_key(api_key)
    model_name = validate_model_name(model)
    addresses = resolve_public_ips(host)
    payload = {
        'model': model_name,
        'messages': messages,
        'stream': False,
        'max_tokens': MAX_TOKENS,
    }
    if json_mode:
        payload['response_format'] = {'type': 'json_object'}
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')

    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    connection = _PinnedHTTPSConnection(host, addresses[0], TIMEOUT_SECONDS, context)
    response = None
    try:
        connection.request(
            'POST',
            path,
            body=body,
            headers={
                'Authorization': f'Bearer {key}',
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'Connection': 'close',
            },
        )
        response = connection.getresponse()
        status = response.status
        if status != 200:
            raise _http_error(status)
        raw = response.read(MAX_BODY_BYTES + 1)
    except PlannerClientError:
        raise
    except TimeoutError as exc:
        raise PlannerClientError('timeout') from exc
    except ssl.SSLError as exc:
        raise PlannerClientError('tls') from exc
    except http.client.IncompleteRead as exc:
        raise PlannerClientError('truncated') from exc
    except (OSError, http.client.HTTPException) as exc:
        raise PlannerClientError('network') from exc
    finally:
        if response is not None:
            response.close()
        connection.close()

    if len(raw) > MAX_BODY_BYTES:
        raise PlannerClientError('too_large')
    if not raw:
        raise PlannerClientError('empty')
    try:
        envelope = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise PlannerClientError('malformed') from exc
    if not isinstance(envelope, dict):
        raise PlannerClientError('malformed')
    choices = envelope.get('choices')
    if not isinstance(choices, list) or not choices:
        raise PlannerClientError('malformed')
    first = choices[0]
    if isinstance(first, dict) and first.get('finish_reason') == 'length':
        raise PlannerClientError('output_limit')
    message = first.get('message') if isinstance(first, dict) else None
    content = message.get('content') if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise PlannerClientError('malformed')
    reasoning = ''
    if isinstance(message, dict):
        raw_reasoning = message.get('reasoning_content') or message.get('reasoning')
        if isinstance(raw_reasoning, str):
            reasoning = raw_reasoning.strip()
    return content, reasoning


def complete_json(
    *, base_url: str, model: str, api_key: str, messages: list[dict]
) -> dict:
    """One non-streaming call that must return a JSON object."""
    content, _reasoning = _post_chat(
        base_url=base_url,
        model=model,
        api_key=api_key,
        messages=messages,
        json_mode=True,
    )
    try:
        payload = json.loads(content)
    except (ValueError, RecursionError) as exc:
        raise PlannerClientError('malformed') from exc
    if not isinstance(payload, dict):
        raise PlannerClientError('malformed')
    return payload


def fetch_plan(
    *,
    base_url: str,
    model: str,
    api_key: str,
    objective: str,
    start_date: str,
    end_date: str,
    instructions: str,
    members: list[dict],
) -> dict:
    """Call the model once and return the parsed JSON task draft."""
    content, _reasoning = _post_chat(
        base_url=base_url,
        model=model,
        api_key=api_key,
        messages=_build_messages(objective, start_date, end_date, instructions, members),
        json_mode=True,
    )
    try:
        payload = json.loads(content)
    except (ValueError, RecursionError) as exc:
        raise PlannerClientError('malformed') from exc
    if not isinstance(payload, dict):
        raise PlannerClientError('malformed')
    return payload


def _build_reply_messages(message: str, project_context: str, member: dict) -> list[dict]:
    persona = str(member.get('persona') or '').strip()
    system = (
        '你在一个项目协作群里，群里有真人和多个 AI，各自负责不同的事。'
        f'你现在是「{member["name"]}」，角色是 {member["role"] or "成员"}。'
        + (f'你的身份设定：{persona}' if persona else '')
        + '针对用户这句话，用中文回应。格式固定：'
        '第一行写「判断依据：」加一到三句你依据什么做判断（不要写成长篇推理流水账）；'
        '然后另起一行写「回答：」加 2 到 4 句结论、风险或下一步。'
        '不要输出 JSON，不要列任务清单，不要客套、不要自我介绍。'
    )
    user = f'项目：{project_context or "（未填写）"}\n用户：{message}'
    return [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': user},
    ]


def fetch_identity(
    *,
    base_url: str,
    model: str,
    api_key: str,
    name: str,
    project_context: str,
    roster: list[dict],
) -> dict:
    """Ask a newly added AI to define its own role, duty and persona."""
    lines = [
        f'- {item["name"]}：{item.get("role") or "未定"} / {item.get("duty") or "未定"}'
        for item in roster
    ]
    system = (
        '你刚加入一个项目协作群。请根据项目目标和现有成员，为自己确定一个互补的角色，'
        '不要和现有成员重复；如果现有成员已经覆盖某个角色，必须换一个互补的。' 
        'persona 里必须写清 1-2 条硬规则（你负责什么、先看什么、明确不做什么）。' 
        '只输出一个 JSON 对象，不要 Markdown。格式：'
        '{"role": "角色，8 字以内", "duty": "propose|review|decide|execute", '
        '"persona": "2-3 句身份与职责，说明你负责什么、先看什么、不做什么", '
        '"intro": "1-2 句在群里自我介绍，直接、不客套"}'
    )
    user = '\n'.join(
        [
            f'你的名字：{name}',
            f'项目：{project_context or "（未填写）"}',
            '现有成员：',
            '\n'.join(lines) if lines else '（还没有其他 AI）',
        ]
    )
    content, _reasoning = _post_chat(
        base_url=base_url,
        model=model,
        api_key=api_key,
        messages=[
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user},
        ],
        json_mode=True,
    )
    try:
        data = json.loads(content)
    except (ValueError, RecursionError) as exc:
        raise PlannerClientError('malformed') from exc
    if not isinstance(data, dict):
        raise PlannerClientError('malformed')
    duty = data.get('duty')
    if duty not in ('propose', 'review', 'decide', 'execute'):
        duty = 'execute'
    return {
        'role': str(data.get('role') or '').strip()[:80],
        'duty': duty,
        'persona': str(data.get('persona') or '').strip()[:2000],
        'intro': str(data.get('intro') or '').strip()[:600],
    }


def split_reply(body: str, provider_reasoning: str) -> dict:
    """Turn a raw reply into answer / reasoning parts."""
    basis = ''
    for marker in ('回答：', '回答:'):
        if marker in body:
            head, tail = body.split(marker, 1)
            basis = head.strip()
            for prefix in ('判断依据：', '判断依据:', '依据：', '依据:'):
                if basis.startswith(prefix):
                    basis = basis[len(prefix):].strip()
                    break
            body = tail.strip()
            break

    final_reasoning = provider_reasoning.strip() or basis
    if provider_reasoning.strip():
        source = 'model'
    elif basis:
        source = 'self'
    else:
        source = ''
    if len(body) > 2000:
        body = body[:2000].rstrip() + '…'
    return {
        'text': body,
        'reasoning': final_reasoning[:6000],
        'reasoning_source': source,
    }


def fetch_reply(
    *,
    base_url: str,
    model: str,
    api_key: str,
    message: str,
    project_context: str,
    member: dict,
) -> dict:
    """Call the model once and return the opinion plus any reasoning it exposes."""
    content, reasoning = _post_chat(
        base_url=base_url,
        model=model,
        api_key=api_key,
        messages=_build_reply_messages(message, project_context, member),
        json_mode=False,
    )
    return split_reply(content.strip(), reasoning)


def stream_messages(*, base_url: str, model: str, api_key: str, messages: list[dict]):
    """Yield ('reasoning'|'content', text) chunks for an arbitrary message list."""
    host, path = normalize_base_url(base_url)
    key = validate_api_key(api_key)
    model_name = validate_model_name(model)
    addresses = resolve_public_ips(host)
    body = json.dumps(
        {
            'model': model_name,
            'messages': messages,
            'stream': True,
            'max_tokens': MAX_TOKENS,
        },
        ensure_ascii=False,
    ).encode('utf-8')

    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    connection = _PinnedHTTPSConnection(host, addresses[0], TIMEOUT_SECONDS, context)
    response = None
    try:
        connection.request(
            'POST',
            path,
            body=body,
            headers={
                'Authorization': f'Bearer {key}',
                'Content-Type': 'application/json',
                'Accept': 'text/event-stream',
                'Connection': 'close',
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            raise _http_error(response.status)
        total = 0
        received = False
        for raw in response:
            total += len(raw)
            if total > MAX_BODY_BYTES:
                raise PlannerClientError('too_large')
            line = raw.decode('utf-8', 'replace').strip()
            if not line or not line.startswith('data:'):
                continue
            data = line[5:].strip()
            if data == '[DONE]':
                break
            try:
                chunk = json.loads(data)
            except ValueError:
                continue
            choices = chunk.get('choices') if isinstance(chunk, dict) else None
            if not isinstance(choices, list) or not choices:
                continue
            choice = choices[0]
            delta = choice.get('delta') if isinstance(choice, dict) else None
            if not isinstance(delta, dict):
                continue
            reasoning = delta.get('reasoning_content') or delta.get('reasoning')
            if isinstance(reasoning, str) and reasoning:
                received = True
                yield 'reasoning', reasoning
            content = delta.get('content')
            if isinstance(content, str) and content:
                received = True
                yield 'content', content
        if not received:
            raise PlannerClientError('empty')
    except PlannerClientError:
        raise
    except TimeoutError as exc:
        raise PlannerClientError('timeout') from exc
    except ssl.SSLError as exc:
        raise PlannerClientError('tls') from exc
    except http.client.IncompleteRead as exc:
        raise PlannerClientError('truncated') from exc
    except (OSError, http.client.HTTPException) as exc:
        raise PlannerClientError('network') from exc
    finally:
        if response is not None:
            response.close()
        connection.close()


def stream_reply(
    *,
    base_url: str,
    model: str,
    api_key: str,
    message: str,
    project_context: str,
    member: dict,
):
    """Stream one role reply."""
    yield from stream_messages(
        base_url=base_url,
        model=model,
        api_key=api_key,
        messages=_build_reply_messages(message, project_context, member),
    )


_DUTY_TEXT = {
    'proposal': '现在是提议阶段：直接给出你的方案或判断，2 到 4 句，说清理由和前提；'
    '不要评价别人，不要客套，不要输出 JSON。',
    'review': '现在是评审阶段：阅读其他人的提议，指出最大的风险、遗漏或不可行之处，'
    '并给出一条修改建议。2 到 3 句，直接说问题，不要重复别人的方案。',
    'decision': '现在是决策阶段。第一行写【已达成一致】或【仍需讨论】，正文固定五段：'
    '结论；依据（来源/测试/文件，没有就写需核实）；反方意见（谁反对、反对什么，没有写“无”）；'
    '未解决/需核实；置信度（高/中/低）。不要模棱两可，不要输出 JSON。',
}


_KICKOFF_TEXT = {
    'proposal': (
        '现在是立项会第 1 轮（澄清与用户画像）。必须覆盖三块，每块 2-4 句：'
        '① 目标：一句话说清要做什么、给谁用；'
        '② 用户画像：至少 3 类用户（谁、什么场景、最大的痛点），不要只写程序员；'
        '③ 边界：这一版明确不做什么。'
        '不要展开技术方案，不要列任务。'
    ),
    'review': (
        '现在是立项会第 2 轮（挑问题）。针对上一轮的画像和判断：'
        '指出最容易被忽略的一类用户、最难的技术点、最可能受阻的地方；'
        '竞品只能基于你确定知道的事实，不确定的写「需核实」，不许编数字。'
    ),
    'decision': (
        '现在是立项会第 3 轮（收口）。输出一份立项简报，固定四段：'
        '第一行写【已达成一致】或【仍需讨论】，正文固定五段：'
        '结论（做/不做/缩小范围）；依据（来源/测试/文件，没有写需核实）；'
        '反方意见（谁反对、反对什么，没有写“无”）；未解决/需核实；置信度（高/中/低）。'
        '仍需讨论时写清下一轮要解决的具体问题。'
    ),
}


def discussion_messages(
    *,
    phase: str,
    member: dict,
    user_message: str,
    project_context: str,
    transcript: str,
    kickoff: bool = False,
    research: str = '',
) -> list[dict]:
    """Prompts for one speaker in a proposal / review / decision round."""
    persona = str(member.get('persona') or '').strip()
    system = (
        '你在一个项目协作群里参与一次多人讨论，群里有真人和多个 AI。'
        f'你现在是「{member["name"]}」，角色是 {member.get("role") or "成员"}。'
        + (f'你的身份设定：{persona}' if persona else '')
        + (
            _KICKOFF_TEXT.get(phase, _KICKOFF_TEXT['proposal'])
            if kickoff
            else _DUTY_TEXT.get(phase, _DUTY_TEXT['proposal'])
        )
        + (('\n\n' + research) if research else '')
    )
    parts = [
        f'项目：{project_context or "（未填写）"}',
        f'用户：{user_message}',
    ]
    if transcript:
        parts.append('此前讨论：')
        parts.append(transcript)
    return [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': '\n'.join(parts)},
    ]


def prompt_draft_messages(message: str, project_context: str = '', identity: str = '') -> list[dict]:
    """Ask the model to turn a rough request into an editable 7-field prompt."""
    system = (
        '你是需求分析师。把用户的一句话整理成一份可执行的提示词，'
        '输出 JSON，字段固定为 role/task/context/goal/constraints/output/acceptance，全部是字符串。'
        'role 要具体（如“资深 Django 后端工程师”），不要写“AI 助手”；'
        'constraints 用分号分隔不能做什么；output 说清交付形态；acceptance 要可判定。'
        '不要输出 JSON 以外的内容。'
    )
    parts = [f'项目背景：{project_context or "（未填写）"}']
    if identity:
        parts.append(f'用户身份：{identity}')
    parts.append(f'用户原话：{message}')
    return [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': '\n'.join(parts)},
    ]
