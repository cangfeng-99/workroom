"""User identity: setup page, redirect, and split lens."""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.projects import user_profile
from apps.projects.models import Project, UserProfile


class ProfileSetupTests(TestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_user('dev', password='x')
        self.client.force_login(self.user)

    def test_index_redirects_without_profile(self) -> None:
        with override_settings(WORKROOM_MODE='server'):
            response = self.client.get('/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/profile/', response['Location'])

    def test_post_saves_role_and_lens(self) -> None:
        with override_settings(WORKROOM_MODE='server'):
            response = self.client.post(
                '/profile/',
                {
                    'role': 'product',
                    'secondary': ['designer'],
                    'domain': '电商后台',
                    'experience': '5 年',
                    'stack': 'Figma',
                    'goal': '做一版 MVP',
                },
            )
        self.assertEqual(response.status_code, 302)
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.role, 'product')
        self.assertIn('designer', profile.secondary_roles)
        block = user_profile.prompt_block(
            Project.objects.create(name='P', goal_title='G', owner=self.user)
        )
        self.assertIn('产品经理', block)
        self.assertIn('MVP', block)
        self.assertIn('信息架构', block)

    def test_profile_skips_redirect(self) -> None:
        UserProfile.objects.create(user=self.user, role='developer')
        with override_settings(WORKROOM_MODE='server'):
            response = self.client.get('/')
        self.assertNotEqual(response.status_code, 302)


class LocalProfileTests(TestCase):
    def test_local_profile_without_login(self) -> None:
        response = self.client.get('/profile/')
        self.assertEqual(response.status_code, 200)
        response = self.client.post(
            '/profile/', {'role': 'founder', 'domain': '本地个人'}
        )
        self.assertEqual(response.status_code, 302)
        profile = UserProfile.objects.get(user__username='workroom_local')
        self.assertEqual(profile.role, 'founder')
        block = user_profile.prompt_block(
            Project.objects.create(name='Local', goal_title='G')
        )
        self.assertIn('创始人', block)
