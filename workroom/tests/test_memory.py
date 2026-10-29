"""Long-term memory files and MCP tools."""

import tempfile
from pathlib import Path

from django.test import TestCase

from apps.projects import mcp, memory
from apps.projects.models import Project


class MemoryTests(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Project.objects.create(
            name='M', goal_title='G', workspace_path=self.tmp.name
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_append_and_read(self) -> None:
        memory.append(self.project, '决定：先做单人版', scope='long')
        memory.append(self.project, '今天完成了记忆页')
        block = memory.read_block(self.project)
        self.assertIn('先做单人版', block)
        self.assertIn('记忆页', block)
        self.assertTrue((Path(self.tmp.name) / '.workroom' / 'MEMORY.md').exists())

    def test_mcp_tools(self) -> None:
        text = mcp.append_memory('M', '通过 MCP 写入一条')
        self.assertIn('已写入', text)
        self.assertIn('通过 MCP 写入一条', mcp.read_memory('M'))

    def test_no_workspace_raises(self) -> None:
        other = Project.objects.create(name='N', goal_title='G')
        result = mcp.read_memory('N')
        self.assertIn('还没有授权工作区', result)
