"""Account flows and login gating (T012A)."""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from workspaces import grants


class SignupTests(TestCase):
    url = '/accounts/signup/'

    def test_signup_creates_hashed_user_and_logs_in(self) -> None:
        response = self.client.post(self.url, {
            'username': 'alice', 'password1': 'Str0ng-Pass!234', 'password2': 'Str0ng-Pass!234',
        })

        self.assertRedirects(
            response, settings.LOGIN_REDIRECT_URL, fetch_redirect_response=False
        )
        user = get_user_model().objects.get(username='alice')
        self.assertNotEqual(user.password, 'Str0ng-Pass!234')
        self.assertTrue(user.password.startswith('pbkdf2_'))
        self.assertTrue(user.check_password('Str0ng-Pass!234'))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(self.client.session['_auth_user_id'], str(user.pk))

    def test_signup_rejects_duplicate_username(self) -> None:
        get_user_model().objects.create_user('alice', password='Str0ng-Pass!234')

        response = self.client.post(self.url, {
            'username': 'alice', 'password1': 'Str0ng-Pass!234', 'password2': 'Str0ng-Pass!234',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(get_user_model().objects.filter(username='alice').count(), 1)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_signup_rejects_weak_or_mismatched_passwords(self) -> None:
        cases = (
            {'username': 'weak', 'password1': '123', 'password2': '123'},
            {'username': 'mismatch', 'password1': 'Str0ng-Pass!234', 'password2': 'Other-Pass!234'},
        )
        for data in cases:
            response = self.client.post(self.url, data)
            self.assertEqual(response.status_code, 200, data['username'])
            self.assertFalse(get_user_model().objects.filter(username=data['username']).exists())

    def test_signup_requires_csrf_and_is_no_store(self) -> None:
        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.post(self.url, {
            'username': 'alice', 'password1': 'Str0ng-Pass!234', 'password2': 'Str0ng-Pass!234',
        })
        self.assertEqual(response.status_code, 403)
        self.assertIn('no-store', self.client.get(self.url)['Cache-Control'])


class LoginLogoutTests(TestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_user('alice', password='Str0ng-Pass!234')

    def test_login_success_redirects_home_and_clears_legacy_grant(self) -> None:
        session = self.client.session
        session[grants.SESSION_KEY] = {'root': 'D:/x', 'grant_id': 'g', 'user_id': '1'}
        session[grants.LEGACY_SESSION_KEY] = 'D:/x'
        session.save()

        response = self.client.post('/accounts/login/', {'username': 'alice', 'password': 'Str0ng-Pass!234'})

        self.assertRedirects(
            response, settings.LOGIN_REDIRECT_URL, fetch_redirect_response=False
        )
        self.assertEqual(self.client.session['_auth_user_id'], str(self.user.pk))
        self.assertNotIn(grants.SESSION_KEY, self.client.session)
        self.assertNotIn(grants.LEGACY_SESSION_KEY, self.client.session)

    def test_failed_login_grants_nothing(self) -> None:
        response = self.client.post('/accounts/login/', {'username': 'alice', 'password': 'wrong'})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_external_next_is_rejected_but_internal_next_is_used(self) -> None:
        response = self.client.post('/accounts/login/', {
            'username': 'alice', 'password': 'Str0ng-Pass!234', 'next': 'https://evil.example/x',
        })
        self.assertRedirects(
            response, settings.LOGIN_REDIRECT_URL, fetch_redirect_response=False
        )

        self.client.logout()
        response = self.client.post('/accounts/login/', {
            'username': 'alice', 'password': 'Str0ng-Pass!234', 'next': '/workspace/',
        })
        self.assertRedirects(response, '/workspace/', fetch_redirect_response=False)

    def test_logout_requires_post_flushes_grant(self) -> None:
        self.client.force_login(self.user)
        session = self.client.session
        session[grants.SESSION_KEY] = {'root': 'D:/x', 'grant_id': 'g', 'user_id': str(self.user.pk)}
        session.save()

        self.assertEqual(self.client.get('/accounts/logout/').status_code, 405)
        response = self.client.post('/accounts/logout/')

        # Logout still lands on the public home page, not the project list.
        self.assertRedirects(response, '/', fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertNotIn(grants.SESSION_KEY, self.client.session)

    def test_login_page_is_no_store(self) -> None:
        self.assertIn('no-store', self.client.get('/accounts/login/')['Cache-Control'])


class WorkspaceGateTests(TestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_user('alice')
        self.other = get_user_model().objects.create_user('bob')

    def test_anonymous_workspace_redirects_to_login(self) -> None:
        response = self.client.get('/workspace/')

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith('/accounts/login/?next='))

    def test_anonymous_folder_metadata_is_401_json(self) -> None:
        response = self.client.post('/workspace/folders/', {'path': ''})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {'error': 'authentication_required'})
        self.assertEqual(self.client.get('/workspace/folders/').status_code, 405)

    def test_grant_is_bound_to_the_logged_in_user(self) -> None:
        self.client.force_login(self.other)
        session = self.client.session
        session[grants.SESSION_KEY] = {'root': 'D:/x', 'grant_id': 'g', 'user_id': str(self.user.pk)}
        session.save()

        body = self.client.get('/workspace/').content.decode('utf-8')
        denied = self.client.post('/workspace/', {'action': 'create', 'name': 'x.txt', 'content': 'x'})

        self.assertIn('未授权', body)
        self.assertEqual(denied.status_code, 403)
