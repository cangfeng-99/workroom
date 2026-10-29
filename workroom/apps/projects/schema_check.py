"""Runtime schema validation shared by every MCP entry point.

The stdio server, the REST endpoint and the HTTP bridge all end up in
``mcp.call_tool``, so validating there gives all three one contract instead of
three different answers to "why did my call fail".

Two rules shaped this module:

* An error must name the field and say how to fix it. "参数不符合schema" is
  unactionable for a model — it can only retry blindly and burn a round trip.
* Recoverable literals are normalised, not rejected. ``"0"`` in an integer field
  and ``"true"`` in a boolean field are what clients actually send; refusing them
  buys nothing. The rewrite is reported back so the caller can stop doing it.

Unknown fields are dropped with a note rather than failing the call: an extra
key is almost always harmless, while a rejected call costs the whole action.
"""

from __future__ import annotations

import json
import re

_TYPE_NAMES = {
    'string': '文本',
    'integer': '整数',
    'number': '数字',
    'boolean': 'true/false',
    'object': 'JSON 对象',
    'array': '数组',
    'null': 'null',
}

_SAMPLES = {
    'string': '内容',
    'integer': 0,
    'number': 0,
    'boolean': True,
    'object': {},
    'array': [],
    'null': None,
}

MAX_PROBLEMS = 6
_INT_RE = re.compile(r'^-?\d+$')


def type_name(value) -> str:
    """Human name for the type of a received value."""
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, int):
        return 'integer'
    if isinstance(value, float):
        return 'number'
    if isinstance(value, str):
        return 'string'
    if isinstance(value, dict):
        return 'object'
    if isinstance(value, list):
        return 'array'
    return type(value).__name__


def _label(expected) -> str:
    if isinstance(expected, list):
        return ' 或 '.join(_TYPE_NAMES.get(item, str(item)) for item in expected)
    return _TYPE_NAMES.get(expected, str(expected))


def _describe(value) -> str:
    """Type name plus a short literal, so the caller sees what it actually sent."""
    name = type_name(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        text = json.dumps(value, ensure_ascii=False)
        if len(text) > 40:
            text = text[:37] + '...'
        return f'{name} {text}'
    if isinstance(value, (list, dict)):
        return f'{name}（{len(value)} 项）'
    return name


def matches(value, expected) -> bool:
    """Type check. ``integer`` must not accept bool, which is an int subclass."""
    if expected is None:
        return True
    if isinstance(expected, list):
        return any(matches(value, item) for item in expected)
    if expected == 'integer':
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == 'number':
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == 'string':
        return isinstance(value, str)
    if expected == 'boolean':
        return isinstance(value, bool)
    if expected == 'object':
        return isinstance(value, dict)
    if expected == 'array':
        return isinstance(value, list)
    if expected == 'null':
        return value is None
    return True


def _coerce(value, expected):
    """Convert obvious string literals. Returns ``(value, note)``."""
    if expected is None or matches(value, expected):
        return value, None
    kinds = expected if isinstance(expected, list) else [expected]
    if not isinstance(value, str):
        return value, None
    text = value.strip()
    if 'integer' in kinds and _INT_RE.match(text):
        return int(text), f'把文本 "{text}" 当作整数 {int(text)}'
    if 'number' in kinds:
        try:
            return float(text), f'把文本 "{text}" 当作数字 {float(text)}'
        except ValueError:
            pass
    if 'boolean' in kinds and text.lower() in ('true', 'false'):
        flag = text.lower() == 'true'
        return flag, f'把文本 "{text}" 当作布尔值 {str(flag).lower()}'
    return value, None


def example(schema) -> str:
    """Smallest useful argument object, used as the fix-it reference.

    ``project`` is optional on a token-bound call but mandatory in local mode, so
    it is always shown — an example without it would fail when pasted locally.
    """
    props = schema.get('properties', {})
    keys = list(schema.get('required') or [])
    if 'project' in props and 'project' not in keys:
        keys.insert(0, 'project')
    if not keys:
        keys = list(props)[:1]
    if not keys:
        return ''
    data = {}
    for key in keys:
        spec = props.get(key, {})
        kind = spec.get('type')
        if isinstance(kind, list):
            kind = next((item for item in kind if item), 'string')
        sample = _SAMPLES.get(kind, '内容')
        if key == 'project':
            sample = '项目 id 或名称'
        elif key == 'task':
            sample = '任务 id 或标题'
        elif key == 'title':
            sample = '任务标题'
        data[key] = sample
    return json.dumps(data, ensure_ascii=False)


def check(args, schema, tool: str = ''):
    """Validate ``args`` against ``schema``.

    Returns ``(clean_args, errors, warnings)``. ``errors`` blocks the call and
    ``warnings`` records something that was repaired. Never raises: the caller
    decides whether a problem is fatal.
    """
    if not isinstance(args, dict):
        return {}, [f'参数必须是 JSON 对象，收到 {_describe(args)}。'], []

    props = schema.get('properties', {})
    clean: dict = {}
    errors: list[str] = []
    warnings: list[str] = []
    strict_unknown = schema.get('additionalProperties') is False

    for key in schema.get('required', []):
        if key not in args or args[key] is None:
            desc = props.get(key, {}).get('description')
            errors.append(f'缺少必填字段 {key}' + (f'（{desc}）' if desc else ''))

    for key, raw in args.items():
        if key not in props:
            if strict_unknown:
                warnings.append(f'忽略未知字段 {key}')
            continue
        spec = props[key]
        value, note = _coerce(raw, spec.get('type'))
        if note:
            warnings.append(f'{key}: {note}')
        if not matches(value, spec.get('type')) and spec.get('type') is not None:
            expected = _label(spec.get('type'))
            hint = spec.get('description')
            message = f'字段 {key} 应为{expected}，收到 {_describe(raw)}'
            if hint:
                message += f'（{hint}）'
            errors.append(message)
            continue
        allowed = spec.get('enum')
        if allowed and value not in allowed:
            errors.append(
                f'字段 {key} 只能是 {" / ".join(str(item) for item in allowed)}，'
                f'收到 {json.dumps(value, ensure_ascii=False)}'
            )
            continue
        clean[key] = value
    return clean, errors, warnings


def explain(tool: str, errors, warnings, schema) -> str:
    """Build the message a model can act on."""
    head = f'参数校验未通过（{tool}）：'
    lines = [head]
    for index, item in enumerate(errors[:MAX_PROBLEMS], 1):
        lines.append(f'  {index}. {item}')
    rest = len(errors) - MAX_PROBLEMS
    if rest > 0:
        lines.append(f'  ……另有 {rest} 处问题')
    if warnings:
        lines.append('已自动处理：' + '；'.join(warnings[:4]))
    fields = ', '.join(schema.get('properties', {})) or '（无参数）'
    lines.append(f'可用字段：{fields}')
    sample = example(schema)
    if sample:
        lines.append(f'最小可用调用：{sample}')
    return '\n'.join(lines)


def check_tool(name: str, args):
    """Look the schema up by tool name.

    Returns ``(clean_args, errors, warnings, schema)``. Unknown tools are left to
    the dispatcher, which already reports them properly.
    """
    from tool_schema import TOOLS

    schema = next((tool['inputSchema'] for tool in TOOLS if tool['name'] == name), None)
    if schema is None:
        return (args if isinstance(args, dict) else {}), [], [], {}
    clean, errors, warnings = check(args, schema, tool=name)
    return clean, errors, warnings, schema
