"""Built-in personas follow the owner's role."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.projects import personas
from apps.projects.models import Member, Project, UserProfile


class PersonaDomainTests(TestCase):
    def _project(self, role: str) -> Project:
        user = get_user_model().objects.create_user(f'u-{role}', password='x')
        UserProfile.objects.create(user=user, role=role)
        return Project.objects.create(name=role, goal_title='G', owner=user)

    def test_product_owner_gets_product_personas(self) -> None:
        project = self._project('product')
        preset = personas.next_for_project(project)
        self.assertEqual(preset['domain'], 'product')

    def test_developer_owner_gets_dev_personas(self) -> None:
        project = self._project('developer')
        preset = personas.next_for_project(project)
        self.assertEqual(preset['domain'], 'dev')

    def test_existing_members_shift_the_preset(self) -> None:
        project = self._project('product')
        first = personas.next_for_project(project)
        Member.objects.create(
            project=project, kind=Member.Kind.AI, name='A',
            role=first['role'], persona=first['persona'],
        )
        second = personas.next_for_project(project)
        self.assertNotEqual(first['key'], second['key'])
