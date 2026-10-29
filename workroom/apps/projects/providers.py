"""Model provider presets: pick a vendor, then only the API key is typed.

Only the base URL is authoritative here. The model name is a *default* that the
owner can override in the advanced block, because vendors rename and retire
model IDs far more often than they move their endpoint.

Every preset URL must pass :func:`ai_client.normalize_base_url` and every
default model must pass :func:`ai_client.validate_model_name`; that is
enforced by ``test_ai`` so a typo cannot ship.
"""

from __future__ import annotations

from typing import TypedDict


class Provider(TypedDict):
    """One selectable vendor."""

    label: str
    base_url: str
    model: str


CUSTOM = 'custom'

PROVIDERS: dict[str, Provider] = {
    'deepseek': {
        'label': 'DeepSeek 深度求索',
        'base_url': 'https://api.deepseek.com',
        'model': 'deepseek-v4-flash',
    },
    'dashscope': {
        'label': '阿里云百炼 · 通义千问',
        'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'model': 'qwen-plus',
    },
    'moonshot': {
        'label': '月之暗面 Kimi',
        'base_url': 'https://api.moonshot.cn/v1',
        'model': 'kimi-k3',
    },
    'zhipu': {
        'label': '智谱 GLM',
        'base_url': 'https://open.bigmodel.cn/api/paas/v4',
        'model': 'glm-4.6',
    },
    'ark': {
        'label': '火山方舟 · 豆包（需填接入点）',
        'base_url': 'https://ark.cn-beijing.volces.com/api/v3',
        'model': '',
    },
    'siliconflow': {
        'label': '硅基流动 SiliconFlow',
        'base_url': 'https://api.siliconflow.cn/v1',
        'model': 'deepseek-ai/DeepSeek-V3',
    },
    'openai': {
        'label': 'OpenAI',
        'base_url': 'https://api.openai.com/v1',
        'model': 'gpt-5-mini',
    },
    CUSTOM: {
        'label': '自定义（自己填接口地址）',
        'base_url': '',
        'model': '',
    },
}

CHOICES: tuple[tuple[str, str], ...] = tuple(
    (key, item['label']) for key, item in PROVIDERS.items()
)

DEFAULT = 'deepseek'


def get(key: str | None) -> Provider | None:
    """Return the preset for ``key`` or ``None`` when it is not offered."""
    return PROVIDERS.get(key or '')


def needs_model(key: str | None) -> bool:
    """True when this vendor has no safe default model name."""
    preset = get(key)
    return preset is not None and not preset['model']
