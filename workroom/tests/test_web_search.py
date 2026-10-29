"""Kickoff research: Tavily block and no-key fallback."""

from unittest import mock

from django.test import TestCase

from apps.projects import ai_client, web_search


class ResearchTests(TestCase):
    def test_without_key_marks_unverified(self) -> None:
        with mock.patch.dict('os.environ', {'TAVILY_API_KEY': ''}), mock.patch.object(
            web_search, 'ENV_FILE', web_search.Path('__missing__.env')
        ), mock.patch(
            'apps.projects.agent_research.available', return_value=False
        ):
            block = web_search.research_block('做一个记账工具')
        self.assertIn('需核实', block)

    def test_results_include_source_url(self) -> None:
        items = [
            {'title': '同类产品 A', 'url': 'https://example.com/a', 'content': '做法是…'}
        ]
        with mock.patch.object(web_search, 'available', return_value=True), mock.patch.object(
            web_search, 'search', return_value=items
        ):
            block = web_search.research_block('做一个记账工具')
        self.assertIn('同类产品 A', block)
        self.assertIn('https://example.com/a', block)

    def test_research_is_injected_into_prompt(self) -> None:
        messages = ai_client.discussion_messages(
            phase='proposal',
            member={'name': 'GLM', 'role': '产品', 'persona': ''},
            user_message='【立项会】做一个记账工具',
            project_context='Agent开发',
            transcript='',
            kickoff=True,
            research='调研材料：竞品 A 的做法',
        )
        self.assertIn('调研材料', messages[0]['content'])


    def test_agent_research_is_used_without_tavily(self) -> None:
        with mock.patch.dict('os.environ', {'TAVILY_API_KEY': ''}), mock.patch.object(
            web_search, 'ENV_FILE', web_search.Path('__missing__.env')
        ), mock.patch(
            'apps.projects.agent_research.available', return_value=True
        ), mock.patch(
            'apps.projects.agent_research.research',
            return_value='竞品 A｜做法｜可借鉴｜https://example.com/a',
        ):
            block = web_search.research_block('做一个记账工具')
        self.assertIn('Codex', block)
        self.assertIn('https://example.com/a', block)


class AgentResearchTests(TestCase):
    def test_falls_back_to_next_agent(self) -> None:
        from apps.projects import agent_research

        with mock.patch.object(agent_research, '_a2a_ready', return_value=True),                 mock.patch.object(
                    agent_research, '_run_a2a', side_effect=['', '竞品 B｜做法｜https://b']
                ):
            text = agent_research.research('记账工具')
        self.assertIn('竞品 B', text)

    def test_cli_agent_is_used_when_a2a_missing(self) -> None:
        from apps.projects import agent_research

        with mock.patch.object(agent_research, '_a2a_ready', return_value=False),                 mock.patch.object(agent_research, 'CLI_CMD', 'cursor-agent -p {prompt}'),                 mock.patch.object(agent_research, '_run_cli', return_value='CLI 结果'):
            text = agent_research.research('记账工具')
        self.assertIn('CLI 结果', text)
