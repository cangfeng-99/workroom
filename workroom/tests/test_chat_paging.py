"""Chat log renders in pages instead of dumping every message."""

from django.test import TestCase
from django.urls import reverse

from apps.projects.models import ChatMessage, Member, Project


class ChatPagingTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='C', goal_title='G')
        self.member = Member.objects.create(project=self.project, name='我')
        for n in range(50):
            ChatMessage.objects.create(
                project=self.project, member=self.member,
                role=ChatMessage.Role.ASSISTANT, content=f'消息 {n}',
            )

    def _messages(self, query: str = '') -> list:
        url = reverse('projects:space', args=[self.project.pk]) + '?tab=chat' + query
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return response.context['messages'], response.context

    def test_first_page_is_bounded(self) -> None:
        messages, context = self._messages()
        self.assertEqual(len(messages), 20)
        self.assertTrue(context['has_earlier'])
        self.assertEqual(messages[-1].content, '消息 49')

    def test_earlier_page_walks_backwards(self) -> None:
        first, _ = self._messages()
        older, context = self._messages(f'&before={first[0].pk}')
        self.assertEqual(len(older), 20)
        self.assertTrue(context['has_earlier'])
        self.assertTrue(all(item.pk < first[0].pk for item in older))

        oldest, context = self._messages(f'&before={older[0].pk}')
        self.assertEqual(len(oldest), 10)
        self.assertFalse(context['has_earlier'])

    def test_short_history_has_no_link(self) -> None:
        ChatMessage.objects.filter(project=self.project).delete()
        ChatMessage.objects.create(
            project=self.project, member=self.member,
            role=ChatMessage.Role.ASSISTANT, content='只有一条',
        )
        messages, context = self._messages()
        self.assertEqual(len(messages), 1)
        self.assertFalse(context['has_earlier'])
