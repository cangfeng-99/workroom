"""Server-mode identity, roles, invitations and encryption (T056 A)."""

from __future__ import annotations

import re
from datetime import timedelta

from cryptography.fernet import Fernet
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.projects import crypto
from apps.projects.auth_views import _hash_token
from apps.projects.models import (
    ChatMessage,
    Invitation,
    Member,
    Project,
    ProjectMembership,
    ReplyJob,
)
from config.settings import validate_server_settings

KEY = Fernet.generate_key().decode('ascii')
SERVER = {
    'WORKROOM_MODE': 'server',
    'WORKROOM_ALLOW_REGISTRATION': True,
    'WORKROOM_ENCRYPTION_KEY': KEY,
    'WORKROOM_INVITE_TTL_HOURS': 72,
}


def make_project(owner: User, name: str = 'P') -> Project:
    project = Project.objects.create(name=name, goal_title='上线', owner=owner)
    ProjectMembership.objects.create(
        project=project, user=owner, role=ProjectMembership.Role.OWNER
    )
    return project


def add_member(project: Project, user: User, role: str) -> ProjectMembership:
    return ProjectMembership.objects.create(project=project, user=user, role=role)


@override_settings(**SERVER)
class ServerLoginTests(TestCase):
    def test_anonymous_is_redirected_to_login_with_next(self) -> None:
        response = self.client.get(reverse('projects:index'))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith('/login/'))
        self.assertIn('next=', response['Location'])

    def test_health_is_public(self) -> None:
        response = self.client.get(reverse('projects:healthz'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])

    def test_registration_can_be_closed(self) -> None:
        with override_settings(WORKROOM_ALLOW_REGISTRATION=False):
            response = self.client.get(reverse('projects:register'))
        self.assertEqual(response.status_code, 404)

    def test_register_logs_in_and_creates_account(self) -> None:
        response = self.client.post(
            reverse('projects:register'),
            {'username': 'alice', 'password': 'a-long-password-1', 'password2': 'a-long-password-1'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username='alice').exists())
        response = self.client.get(reverse('projects:index'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/profile/', response['Location'])

    def test_login_rejects_unsafe_next(self) -> None:
        User.objects.create_user('alice', password='a-long-password-1')
        response = self.client.post(
            reverse('projects:login'),
            {'username': 'alice', 'password': 'a-long-password-1', 'next': 'https://evil.example/'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/')

    def test_logout_requires_post(self) -> None:
        user = User.objects.create_user('alice', password='a-long-password-1')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('projects:logout')).status_code, 405)
        self.assertEqual(self.client.post(reverse('projects:logout')).status_code, 302)

    def test_csrf_is_enforced_for_writes(self) -> None:
        owner = User.objects.create_user('alice', password='a-long-password-1')
        project = make_project(owner)
        client = Client(enforce_csrf_checks=True)
        client.force_login(owner)
        response = client.post(reverse('projects:chat_send', args=[project.pk]), {'message': 'hi'})
        self.assertEqual(response.status_code, 403)


@override_settings(**SERVER)
class ServerIsolationTests(TestCase):
    def setUp(self) -> None:
        self.alice = User.objects.create_user('alice', password='a-long-password-1')
        self.bob = User.objects.create_user('bob', password='a-long-password-1')
        self.project = make_project(self.alice, 'Alice 项目')
        Member.objects.create(project=self.project, kind=Member.Kind.HUMAN, name='alice')

    def test_other_account_cannot_list_or_open_project(self) -> None:
        self.client.force_login(self.bob)
        html = self.client.get(reverse('projects:index')).content.decode('utf-8')
        self.assertNotIn('Alice 项目', html)
        self.assertEqual(
            self.client.get(reverse('projects:space', args=[self.project.pk])).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                reverse('projects:chat_send', args=[self.project.pk]), {'message': 'x'}
            ).status_code,
            404,
        )

    def test_viewer_reads_but_cannot_write(self) -> None:
        add_member(self.project, self.bob, ProjectMembership.Role.VIEWER)
        self.client.force_login(self.bob)
        self.assertEqual(
            self.client.get(reverse('projects:space', args=[self.project.pk])).status_code,
            200,
        )
        response = self.client.post(
            reverse('projects:chat_send', args=[self.project.pk]), {'message': 'x'}
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ChatMessage.objects.count(), 0)

    def test_editor_can_write_but_not_manage(self) -> None:
        add_member(self.project, self.bob, ProjectMembership.Role.EDITOR)
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse('projects:chat_send', args=[self.project.pk]), {'message': '我来协作'}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.client.get(reverse('projects:team', args=[self.project.pk])).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(reverse('projects:delete', args=[self.project.pk])).status_code,
            403,
        )

    def test_owner_can_manage_team(self) -> None:
        self.client.force_login(self.alice)
        self.assertEqual(
            self.client.get(reverse('projects:team', args=[self.project.pk])).status_code,
            200,
        )

    def test_project_creation_makes_creator_owner(self) -> None:
        self.client.force_login(self.bob)
        self.client.post(reverse('projects:index'), {'name': '新项目', 'goal': '目标'})
        project = Project.objects.get(name='新项目')
        self.assertEqual(project.owner, self.bob)
        membership = project.memberships.get(user=self.bob)
        self.assertEqual(membership.role, ProjectMembership.Role.OWNER)
        self.assertTrue(project.members.filter(kind=Member.Kind.HUMAN, user=self.bob).exists())

    def test_last_owner_cannot_be_demoted(self) -> None:
        self.client.force_login(self.alice)
        membership = self.project.memberships.get(user=self.alice)
        response = self.client.post(
            reverse('projects:team', args=[self.project.pk]),
            {'action': 'role', 'membership_id': membership.pk, 'role': 'viewer'},
        )
        self.assertEqual(response.status_code, 200)
        membership.refresh_from_db()
        self.assertEqual(membership.role, ProjectMembership.Role.OWNER)

    def test_server_disables_host_connectors_and_agent_files(self) -> None:
        self.client.force_login(self.alice)
        self.assertEqual(
            self.client.get(reverse('projects:connect')).status_code, 200
        )
        self.assertEqual(
            self.client.post(
                reverse('projects:connect_client', args=['workbuddy'])
            ).status_code,
            404,
        )
        html = self.client.get(
            reverse('projects:space', args=[self.project.pk]) + '?tab=chat'
        ).content.decode('utf-8')
        self.assertNotIn('data-agent-toggle', html)
        self.client.post(
            reverse('projects:chat_send', args=[self.project.pk]),
            {'message': '看下文件', 'mode': 'agent'},
        )
        self.assertFalse(ReplyJob.objects.filter(mode=ReplyJob.Mode.AGENT).exists())


@override_settings(**SERVER)
class InvitationTests(TestCase):
    def setUp(self) -> None:
        self.owner = User.objects.create_user('alice', password='a-long-password-1')
        self.bob = User.objects.create_user('bob', password='a-long-password-1')
        self.project = make_project(self.owner, '邀请项目')

    def _invite(self, role: str = 'viewer') -> tuple[Invitation, str]:
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse('projects:team', args=[self.project.pk]),
            {'action': 'invite', 'role': role},
        )
        html = response.content.decode('utf-8')
        url = re.search(r'(/join/[A-Za-z0-9_\-]+/)', html).group(1)
        invitation = Invitation.objects.get(project=self.project)
        return invitation, url

    def test_invite_is_hashed_and_joins_once(self) -> None:
        invitation, url = self._invite('viewer')
        self.assertNotIn(url.rsplit('/', 2)[-2], invitation.token_hash)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url).status_code, 302)
        membership = self.project.memberships.get(user=self.bob)
        self.assertEqual(membership.role, ProjectMembership.Role.VIEWER)
        self.assertTrue(self.project.members.filter(user=self.bob).exists())
        self.assertEqual(self.client.post(url).status_code, 410)

    def test_expired_and_revoked_invites_are_rejected(self) -> None:
        invitation, url = self._invite()
        invitation.expires_at = timezone.now() - timedelta(minutes=1)
        invitation.save(update_fields=['expires_at'])
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(url).status_code, 410)

        invitation.expires_at = timezone.now() + timedelta(hours=1)
        invitation.revoked_at = timezone.now()
        invitation.save(update_fields=['expires_at', 'revoked_at'])
        self.assertEqual(self.client.post(url).status_code, 410)

    def test_expired_invite_by_hash_is_not_live(self) -> None:
        raw = 'known-token'
        Invitation.objects.create(
            project=self.project,
            role='viewer',
            token_hash=_hash_token(raw),
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        self.client.force_login(self.bob)
        self.assertEqual(
            self.client.get(reverse('projects:join_invite', args=[raw])).status_code,
            410,
        )


class ServerConfigTests(TestCase):
    def _valid(self) -> dict:
        return {
            'WORKROOM_SECRET_KEY': 'test-production-secret-' + '0123456789AbCdEf' * 3,
            'WORKROOM_ALLOWED_HOSTS': 'work.example.com',
            'WORKROOM_PUBLIC_ORIGIN': 'https://work.example.com',
            'WORKROOM_ENCRYPTION_KEY': KEY,
        }

    def test_valid_config_has_no_errors(self) -> None:
        self.assertEqual(validate_server_settings(self._valid()), [])

    def test_missing_secret_host_and_https_fail(self) -> None:
        env = self._valid()
        env['WORKROOM_SECRET_KEY'] = 'short'
        env['WORKROOM_ALLOWED_HOSTS'] = '*'
        env['WORKROOM_PUBLIC_ORIGIN'] = 'http://work.example.com'
        errors = ' '.join(validate_server_settings(env))
        self.assertIn('SECRET_KEY', errors)
        self.assertIn('ALLOWED_HOSTS', errors)
        self.assertIn('https', errors)

    def test_bad_encryption_key_fails(self) -> None:
        env = self._valid()
        env['WORKROOM_ENCRYPTION_KEY'] = 'not-a-fernet-key'
        self.assertTrue(validate_server_settings(env))


@override_settings(WORKROOM_MODE='server', WORKROOM_ENCRYPTION_KEY=KEY)
class FernetTests(TestCase):
    def test_roundtrip_and_prefix(self) -> None:
        token = crypto.protect('sk-secret')
        self.assertTrue(token.startswith('fernet:v1:'))
        self.assertNotIn('sk-secret', token)
        self.assertEqual(crypto.unprotect(token), 'sk-secret')

    def test_wrong_key_fails_closed(self) -> None:
        token = crypto.protect('sk-secret')
        other = Fernet.generate_key().decode('ascii')
        with override_settings(WORKROOM_ENCRYPTION_KEY=other):
            with self.assertRaises(crypto.CryptoError):
                crypto.unprotect(token)

    def test_old_dpapi_token_is_not_cleared(self) -> None:
        with self.assertRaises(crypto.CryptoError):
            crypto.unprotect('dpapi:v1:AAAA')
