"""向量检索的可替换实现。

默认走 SQLite（向量存 DocumentChunk，内存算余弦），换 Chroma 只需要
设置 WORKROOM_VECTOR_STORE=chroma 并安装 chromadb；检索入口不变。
"""

from __future__ import annotations

import json
import math
import os
import re

from .models import DocumentChunk, Project

CHROMA_DIR_NAME = 'chroma'


def _keywords(question: str) -> list[str]:
    """中文按 bigram 切，英文按词切；用于给检索做关键词加分。"""
    cleaned = re.sub(r'[^\w\u4e00-\u9fff]+', ' ', question or '')
    tokens: list[str] = []
    for word in cleaned.split():
        if re.search(r'[\u4e00-\u9fff]', word):
            if len(word) <= 2:
                tokens.append(word)
            else:
                tokens.extend(word[i:i + 2] for i in range(len(word) - 1))
        elif len(word) >= 2:
            tokens.append(word.lower())
    return [token for token in dict.fromkeys(tokens) if token.strip()]


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _shape(chunk: DocumentChunk, score: float, question: str) -> dict:
    return {
        'chunk_id': chunk.pk,
        'entry_id': chunk.entry_id,
        'title': chunk.heading or (chunk.entry.title if chunk.entry else ''),
        'content': chunk.content,
        'score': round(score, 4),
        'keywords': [word for word in _keywords(question) if word and word in chunk.content],
    }


class SqliteVectorStore:
    """把向量存在业务表里，检索时全量算余弦。千级数据毫秒级。"""

    name = 'sqlite'

    def search(
        self,
        project: Project,
        question: str,
        vector: list[float],
        *,
        model: str,
        dim: int,
        k: int,
        keyword_weight: float,
    ) -> list[dict]:
        chunks = list(
            project.chunks.filter(model=model).select_related('entry')
        )
        if not chunks:
            return []
        keywords = _keywords(question)
        scored: list[dict] = []
        for chunk in chunks:
            try:
                stored = json.loads(chunk.embedding)
            except (TypeError, ValueError):
                continue
            hits = [
                word for word in keywords if word and word in chunk.content
            ]
            bonus = keyword_weight * (len(hits) / len(keywords)) if keywords else 0.0
            scored.append(_shape(chunk, _cosine(vector, stored) + bonus, question))
        scored.sort(key=lambda item: item['score'], reverse=True)
        return scored[:k]

    def rebuild(self, project: Project) -> None:  # 数据本来就在 DocumentChunk 里
        return None

    def drop(self, project: Project) -> None:
        return None


class ChromaVectorStore:
    """可选实现：把向量交给 Chroma，SQLite 只保留原文。

    chromadb 不是必装依赖；没装时给出明确提示，不影响默认实现。
    """

    name = 'chroma'

    def __init__(self, persist_dir: str) -> None:
        try:
            import chromadb  # noqa: F401
        except ImportError as exc:  # pragma: no cover - 取决于本机是否装了
            raise RuntimeError(
                '未安装 chromadb；执行 pip install chromadb 或改用 WORKROOM_VECTOR_STORE=sqlite'
            ) from exc
        self._chromadb = chromadb
        self._dir = persist_dir

    def _collection(self, project: Project):
        client = self._chromadb.PersistentClient(path=self._dir)
        return client.get_or_create_collection(
            name=f'project_{project.pk}', metadata={'hnsw:space': 'cosine'}
        )

    def search(
        self,
        project: Project,
        question: str,
        vector: list[float],
        *,
        model: str,
        dim: int,
        k: int,
        keyword_weight: float,
    ) -> list[dict]:
        collection = self._collection(project)
        if collection.count() == 0:
            return []
        result = collection.query(query_embeddings=[vector], n_results=min(k * 2, 50))
        ids = (result.get('ids') or [[]])[0]
        distances = (result.get('distances') or [[]])[0]
        if not ids:
            return []
        numeric = [int(item) for item in ids if str(item).isdigit()]
        chunks = {
            chunk.pk: chunk
            for chunk in project.chunks.filter(pk__in=numeric).select_related('entry')
        }
        scored: list[dict] = []
        for raw_id, distance in zip(ids, distances):
            chunk = chunks.get(int(raw_id)) if str(raw_id).isdigit() else None
            if chunk is None:
                continue
            scored.append(_shape(chunk, 1.0 - float(distance), question))
        scored.sort(key=lambda item: item['score'], reverse=True)
        return scored[:k]

    def rebuild(self, project: Project) -> None:
        collection = self._collection(project)
        collection.delete(where={'project': project.pk})
        chunks = list(project.chunks.filter(project=project).select_related('entry'))
        if not chunks:
            return
        collection.add(
            ids=[str(chunk.pk) for chunk in chunks],
            embeddings=[json.loads(chunk.embedding) for chunk in chunks],
            metadatas=[{'project': project.pk, 'entry': chunk.entry_id or 0} for chunk in chunks],
        )

    def drop(self, project: Project) -> None:
        self._collection(project).delete(where={'project': project.pk})


def get_store(persist_dir: str | None = None) -> SqliteVectorStore | ChromaVectorStore:
    kind = (os.environ.get('WORKROOM_VECTOR_STORE') or 'sqlite').strip().lower()
    if kind == 'chroma':
        return ChromaVectorStore(persist_dir or CHROMA_DIR_NAME)
    return SqliteVectorStore()
