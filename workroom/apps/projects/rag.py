"""资料库语义检索（RAG）：切块、向量化、检索、带引用的回答。

设计取舍见 workroom/docs/RAG.md：
- 数据量在几千块以内，向量直接存 SQLite，余弦在内存算，不引入向量库；
- 换向量库只需要替换 VectorStore 的实现，检索逻辑不动；
- 没有配置向量接口时退化为哈希向量（可跑通全链路，但语义能力有限）。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import urllib.request

from django.conf import settings

from .models import DocumentChunk, LibraryEntry, Project
from .vector_store import get_store

CHUNK_SIZE = 400
CHUNK_OVERLAP = 80
MOCK_DIM = 256
MOCK_MODEL = 'hash-bigram-256'
MAX_CHUNKS_PER_ENTRY = 40


class RagError(Exception):
    """能直接展示给用户的失败原因。"""


# --------------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------------

def _env(name: str, default: str = '') -> str:
    return (os.environ.get(name) or default).strip()


def embed_config() -> dict:
    """向量接口配置。为空时用本地哈希向量。"""
    return {
        'base_url': _env('WORKROOM_EMBED_BASE_URL'),
        'model': _env('WORKROOM_EMBED_MODEL'),
        'api_key': _env('WORKROOM_EMBED_API_KEY'),
    }


def chat_config() -> dict:
    """可选：回答用的对话接口。为空时用抽取式回答。"""
    return {
        'base_url': _env('WORKROOM_RAG_CHAT_BASE_URL'),
        'model': _env('WORKROOM_RAG_CHAT_MODEL'),
        'api_key': _env('WORKROOM_RAG_CHAT_API_KEY'),
    }


def active_model() -> str:
    cfg = embed_config()
    return cfg['model'] or MOCK_MODEL


def active_dim() -> int:
    return 0 if embed_config()['base_url'] else MOCK_DIM


# --------------------------------------------------------------------------
# 向量
# --------------------------------------------------------------------------

def _hash_embed(text: str) -> list[float]:
    """字符 bigram 哈希到固定维度，确定性、无依赖，用于本地演示与测试。"""
    vec = [0.0] * MOCK_DIM
    cleaned = re.sub(r'\s+', ' ', text or '')
    if not cleaned:
        return vec
    tokens = [cleaned[i:i + 2] for i in range(max(1, len(cleaned) - 1))]
    for token in tokens:
        digest = hashlib.md5(token.encode('utf-8')).digest()
        index = int.from_bytes(digest[:2], 'big') % MOCK_DIM
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vec[index] += sign
    norm = math.sqrt(sum(value * value for value in vec))
    if norm:
        vec = [value / norm for value in vec]
    return vec


def _remote_embed(texts: list[str]) -> list[list[float]]:
    cfg = embed_config()
    url = cfg['base_url'].rstrip('/') + '/embeddings'
    payload = json.dumps({'model': cfg['model'], 'input': texts}).encode('utf-8')
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {cfg["api_key"]}',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode('utf-8'))
    except Exception as exc:  # noqa: BLE001 - 统一报可读错误
        raise RagError(f'向量接口调用失败：{exc}') from exc
    data = body.get('data') or []
    if len(data) != len(texts):
        raise RagError('向量接口返回条数与请求不一致。')
    return [item['embedding'] for item in data]


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    if embed_config()['base_url']:
        return _remote_embed(texts)
    return [_hash_embed(text) for text in texts]


# --------------------------------------------------------------------------
# 切块
# --------------------------------------------------------------------------

def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """按段落聚合切块，超长段落按标点硬切并保留重叠。"""
    text = (text or '').strip()
    if not text:
        return []
    paragraphs = [part.strip() for part in re.split(r'\n\s*\n', text) if part.strip()]
    chunks: list[str] = []
    buffer = ''
    for paragraph in paragraphs:
        if len(paragraph) > size:
            if buffer:
                chunks.append(buffer)
                buffer = ''
            start = 0
            while start < len(paragraph):
                pieces = paragraph[start:start + size]
                chunks.append(pieces)
                start += size - overlap
            continue
        if len(buffer) + len(paragraph) + 1 <= size:
            buffer = f'{buffer}\n{paragraph}'.strip()
        else:
            if buffer:
                chunks.append(buffer)
            buffer = paragraph
    if buffer:
        chunks.append(buffer)
    return [chunk for chunk in chunks if chunk.strip()]


def entry_text(entry: LibraryEntry) -> str:
    """把一条资料拼成可检索的正文，保留字段语义。"""
    parts: list[str] = [f'《{entry.title}》']
    if entry.summary:
        parts.append(f'结论：{entry.summary}')
    if entry.body:
        parts.append(entry.body)
    if entry.context:
        parts.append(f'背景：{entry.context}')
    if entry.options:
        parts.append(f'备选方案：{entry.options}')
    if entry.conclusion:
        parts.append(f'落地方式：{entry.conclusion}')
    return '\n\n'.join(part.strip() for part in parts if part and part.strip())


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


# --------------------------------------------------------------------------
# 入库
# --------------------------------------------------------------------------

def index_project(project: Project, force: bool = False) -> dict:
    """把项目资料库切成块并写入向量。返回统计信息。"""
    model = active_model()
    created = 0
    skipped = 0
    removed = 0
    entries = project.library.filter(is_active=True).prefetch_related('chunks')
    for entry in entries:
        text = entry_text(entry)
        if not text:
            continue
        chunks = chunk_text(text)[:MAX_CHUNKS_PER_ENTRY]
        if not chunks:
            continue
        hashes = [_digest(chunk) for chunk in chunks]
        existing = list(entry.chunks.all())
        if (
            not force
            and len(existing) == len(chunks)
            and {item.content_hash for item in existing} == set(hashes)
            and all(item.model == model for item in existing)
        ):
            skipped += 1
            continue
        vectors = embed_texts(chunks)
        dim = len(vectors[0]) if vectors else 0
        entry.chunks.all().delete()
        removed += len(existing)
        DocumentChunk.objects.bulk_create([
            DocumentChunk(
                project=project,
                entry=entry,
                heading=entry.title,
                content=chunk,
                embedding=json.dumps(vector, ensure_ascii=False),
                dim=dim,
                model=model,
                content_hash=digest,
            )
            for chunk, vector, digest in zip(chunks, vectors, hashes)
        ])
        created += len(chunks)
    store = get_store(getattr(settings, 'DATA_DIR', None))
    store.rebuild(project)

    return {
        'entries': entries.count(),
        'created': created,
        'skipped': skipped,
        'removed': removed,
        'model': model,
        'mode': 'remote' if embed_config()['base_url'] else 'local',
    }


def index_status(project: Project) -> dict:
    total = project.chunks.count()
    stale = project.chunks.exclude(model=active_model()).count()
    entries = project.library.filter(is_active=True).count()
    return {
        'chunks': total,
        'stale': stale,
        'entries': entries,
        'model': active_model(),
        'mode': 'remote' if embed_config()['base_url'] else 'local',
        'ready': bool(total and not stale),
    }


# --------------------------------------------------------------------------
# 检索
# --------------------------------------------------------------------------

def search(project: Project, question: str, k: int = 8) -> list[dict]:
    """向量召回 + 关键词加分，返回带来源的命中列表。"""
    query = (question or '').strip()
    if not query:
        return []
    vector = embed_texts([query])[0]
    weight = 0.15 if embed_config()['base_url'] else 0.55
    store = get_store(getattr(settings, 'DATA_DIR', None))
    return store.search(
        project,
        query,
        vector,
        model=active_model(),
        dim=0,
        k=k,
        keyword_weight=weight,
    )


# --------------------------------------------------------------------------
# 回答
# --------------------------------------------------------------------------

def _build_prompt(question: str, hits: list[dict]) -> list[dict]:
    blocks = []
    for index, hit in enumerate(hits, start=1):
        blocks.append(f'[{index}] 《{hit["title"]}》\n{hit["content"]}')
    system = (
        '你是项目资料库问答助手。只能依据给出的资料回答，不要补充资料以外的内容。'
        '每条结论后用 [编号] 标注引用来源；资料不足时直接说「资料库中没有找到相关内容」。'
    )
    user = '\n\n'.join([
        '资料：',
        '\n\n'.join(blocks),
        f'问题：{question}',
        '请用不超过 200 字回答，并保留引用编号。',
    ])
    return [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': user},
    ]


def _ask_model(messages: list[dict]) -> str:
    cfg = chat_config()
    url = cfg['base_url'].rstrip('/') + '/chat/completions'
    payload = json.dumps({
        'model': cfg['model'],
        'messages': messages,
        'temperature': 0.2,
    }).encode('utf-8')
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {cfg["api_key"]}',
        },
        method='POST',
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body = json.loads(response.read().decode('utf-8'))
    try:
        return body['choices'][0]['message']['content'].strip()
    except (KeyError, IndexError) as exc:
        raise RagError('对话接口返回格式不符合预期。') from exc


def answer(project: Project, question: str, k: int = 5) -> dict:
    """返回 {answer, citations, mode}。没有对话接口时给抽取式答案。"""
    hits = search(project, question, k=max(k, 8))
    if not hits:
        return {
            'answer': '资料库里还没有可检索的内容。先在项目资料库添加规则或决策，再重建索引。',
            'citations': [],
            'mode': 'empty',
        }
    top = hits[:k]
    citations = [
        {
            'entry_id': hit['entry_id'],
            'title': hit['title'],
            'score': hit['score'],
            'snippet': hit['content'][:120],
        }
        for hit in top
    ]
    if chat_config()['base_url']:
        text = _ask_model(_build_prompt(question, top))
        mode = 'llm'
    else:
        lines = ['资料库中与问题最接近的内容：', '']
        for index, hit in enumerate(top[:3], start=1):
            lines.append(f'[{index}] 《{hit["title"]}》：{hit["content"][:160]}')
        lines.append('')
        lines.append('（未配置对话接口，以上为原文摘录，不做生成。）')
        text = '\n'.join(lines)
        mode = 'extractive'
    return {'answer': text, 'citations': citations, 'mode': mode}
