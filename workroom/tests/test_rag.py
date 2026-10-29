"""RAG：切块、索引、检索、回答与 MCP 工具。"""

from __future__ import annotations

from django.test import TestCase

from apps.projects import mcp, rag
from apps.projects.models import DocumentChunk, LibraryEntry, Project


class ChunkTests(TestCase):
    def test_short_text_single_chunk(self) -> None:
        chunks = rag.chunk_text('第一段。\n\n第二段。')
        self.assertEqual(len(chunks), 1)

    def test_long_text_multiple_chunks_with_overlap(self) -> None:
        text = '。'.join(f'第{i}条规则' for i in range(200))
        chunks = rag.chunk_text(text, size=100, overlap=20)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 100 for chunk in chunks))


class IndexAndSearchTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='知识库项目', goal_title='上线')
        LibraryEntry.objects.create(
            project=self.project,
            kind=LibraryEntry.Kind.RULE,
            title='验收流程',
            body='交付后由负责人按验收标准逐项核对测试输出与改动文件，不合格退回重做。',
        )
        LibraryEntry.objects.create(
            project=self.project,
            kind=LibraryEntry.Kind.DECISION,
            title='数据库选型',
            body='单人本地版使用 SQLite，MySQL 尚未接入，保留为后续明确选型。',
        )

    def test_index_creates_chunks(self) -> None:
        result = rag.index_project(self.project)
        self.assertEqual(result['created'], 2)
        self.assertEqual(DocumentChunk.objects.filter(project=self.project).count(), 2)

    def test_reindex_skips_unchanged(self) -> None:
        rag.index_project(self.project)
        again = rag.index_project(self.project)
        self.assertEqual(again['created'], 0)
        self.assertEqual(again['skipped'], 2)

    def test_search_hits_relevant_entry(self) -> None:
        rag.index_project(self.project)
        hits = rag.search(self.project, '验收不合格怎么办', k=2)
        self.assertTrue(hits)
        self.assertEqual(hits[0]['title'], '验收流程')

    def test_answer_has_citations(self) -> None:
        rag.index_project(self.project)
        result = rag.answer(self.project, '数据库用的什么')
        self.assertTrue(result['citations'])
        self.assertIn(result['mode'], {'extractive', 'llm'})
        self.assertIn('SQLite', result['citations'][0]['title'] + result['citations'][0]['snippet'])

    def test_search_without_index_returns_empty(self) -> None:
        self.assertEqual(rag.search(self.project, '任意问题'), [])


class McpKnowledgeToolTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='问答项目', goal_title='上线')
        LibraryEntry.objects.create(
            project=self.project,
            kind=LibraryEntry.Kind.RULE,
            title='谁能提交交付',
            body='只有认领任务的成员可以提交交付，负责人核对证据后再确认完成。',
        )
        rag.index_project(self.project)

    def test_tool_returns_answer_with_citation(self) -> None:
        text = mcp.ask_project_knowledge('问答项目', '谁可以提交交付')
        self.assertIn('引用', text)
        self.assertIn('谁能提交交付', text)


class KnowledgeViewTests(TestCase):
    def setUp(self) -> None:
        from django.contrib.auth import get_user_model

        self.user = get_user_model().objects.create_user(
            username='rag_tester', password='pass-12345'
        )
        self.project = Project.objects.create(
            name='页面项目', goal_title='上线', owner=self.user
        )
        LibraryEntry.objects.create(
            project=self.project,
            kind=LibraryEntry.Kind.RULE,
            title='发布前检查',
            body='发布前必须跑完整测试并保留输出，负责人确认后才算通过。',
        )
        rag.index_project(self.project)
        self.client.force_login(self.user)

    def test_page_renders(self) -> None:
        from django.urls import reverse

        response = self.client.get(
            reverse('projects:knowledge', args=[self.project.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '知识库问答')

    def test_post_question_returns_citation(self) -> None:
        from django.urls import reverse

        response = self.client.post(
            reverse('projects:knowledge', args=[self.project.pk]),
            {'action': 'ask', 'q': '发布前要做什么'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '引用')
        self.assertContains(response, '发布前检查')


class VectorStoreTests(TestCase):
    def test_default_store_is_sqlite(self) -> None:
        from apps.projects.vector_store import get_store

        self.assertEqual(get_store().name, 'sqlite')

    def test_chroma_requires_package(self) -> None:
        import os

        from apps.projects.vector_store import get_store

        os.environ['WORKROOM_VECTOR_STORE'] = 'chroma'
        try:
            with self.assertRaises(RuntimeError):
                get_store('/tmp/rag-chroma-test')
        finally:
            os.environ.pop('WORKROOM_VECTOR_STORE', None)
