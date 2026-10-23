"""T017 invitation contracts: signed one-time links, consumption and safety."""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import signing
from django.db import IntegrityError
from django.test import Client, TestCase
from django.utils import timezone
from workspaces import grants

from projects import invitations
from projects.invitation_logging import InvitationTokenFilter
from projects.models import Project, ProjectInvitation, ProjectMember, TaskNode

SALT = 'projects.invite.v1'


class InviteTestBase(TestCase):
    def setUp(self) -> None:
        User = get_user_model()
        self.alice = User.objects.create_user('alice')
        self.bob = User.objects.create_user('bob')
        self.carol = User.objects.create_user('carol')
        self.client = Client()
        self.client.force_login(self.alice)

    # -- helpers -------------------------------------------------------
    def make_project(self, name: str = '甲项目', owner=None) -> Project:
        project = Project.objects.create(owner=owner or self.alice, name=name)
        ProjectMember.objects.create(
            project=project, kind=ProjectMember.Kind.HUMAN,
            user=project.owner, role='项目负责人',
        )
        return project

    def make_invitation(self, project: Project, role: str = '前端', days: int = 7,
                        **overrides) -> ProjectInvitation:
        data = {
            'project': project,
            'created_by': project.owner,
            'role': role,
            'expires_at': timezone.now() + timedelta(days=days),
        }
        data.update(overrides)
        return ProjectInvitation.objects.create(**data)

    def join_path(self, invitation: ProjectInvitation) -> str:
        return f'/projects/join/{invitations.build_token(invitation)}/'

    def as_user(self, user) -> Client:
        client = Client()
        client.force_login(user)
        return client

    def posted_join(self, client: Client, invitation: ProjectInvitation, **extra):
        data = {'role': 'owner', 'user': str(self.alice.pk), 'path': 'D:/secret'}
        data.update(extra)
        return client.post(self.join_path(invitation), data)


class InvitationModelAndTokenTests(InviteTestBase):
    def test_uuid_pk_and_signed_token_round_trip(self) -> None:
        project = self.make_project()
        invitation = self.make_invitation(project)

        self.assertIsInstance(invitation.pk, uuid.UUID)
        token = invitations.build_token(invitation)
        self.assertNotIn(str(invitation.pk), token)
        self.assertTrue(token)
        parsed = invitations.parse_token(token)
        self.assertEqual(parsed.pk, invitation.pk)
        # The raw token is never stored on the record.
        for field in ProjectInvitation._meta.get_fields():
            if field.concrete and not field.is_relation:
                value = getattr(invitation, field.attname)
                if isinstance(value, str):
                    self.assertNotEqual(value, token)

    def test_token_signed_with_another_salt_is_rejected(self) -> None:
        project = self.make_project()
        invitation = self.make_invitation(project)
        foreign = signing.Signer(salt='projects.invite.v2').sign_object(
            {'id': str(invitation.pk)}
        )

        self.assertIsNone(invitations.parse_token(foreign))
        self.assertEqual(self.client.get(f'/projects/join/{foreign}/').status_code, 404)

    def test_bad_payload_and_plain_uuid_are_rejected(self) -> None:
        project = self.make_project()
        invitation = self.make_invitation(project)
        signer = signing.Signer(salt=SALT)
        cases = [
            signer.sign_object('just-a-string'),
            signer.sign_object({'id': 'not-a-uuid'}),
            signer.sign_object({'other': str(invitation.pk)}),
            str(uuid.uuid4()),
            invitation.pk.hex,
            'garbage',
        ]
        for token in cases:
            with self.subTest(token=token[:12]):
                self.assertIsNone(invitations.parse_token(token))
                self.assertEqual(
                    self.client.get(f'/projects/join/{token}/').status_code, 404
                )

    def test_tampered_signature_is_rejected_without_consuming(self) -> None:
        project = self.make_project()
        invitation = self.make_invitation(project)
        token = invitations.build_token(invitation)
        tampered = token[:-2] + ('AA' if token[-2:] != 'AA' else 'BB')

        self.assertIsNone(invitations.parse_token(tampered))
        self.assertEqual(
            self.client.get(f'/projects/join/{tampered}/').status_code, 404
        )
        invitation.refresh_from_db()
        self.assertIsNone(invitation.used_at)

    def test_valid_link_can_be_rendered_again(self) -> None:
        project = self.make_project()
        invitation = self.make_invitation(project)

        first = self.client.get(self.join_path(invitation))
        second = self.client.get(self.join_path(invitation))

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)


class InvitationJoinTests(InviteTestBase):
    def test_join_rejects_methods_other_than_get_and_post(self) -> None:
        project = self.make_project()
        invite = self.make_invitation(project)
        client = self.as_user(self.bob)
        for method in ('put', 'patch', 'delete'):
            self.assertEqual(getattr(client, method)(self.join_path(invite)).status_code, 405)
        invite.refresh_from_db()
        self.assertIsNone(invite.used_at)
        self.assertFalse(project.members.filter(user=self.bob).exists())

    def test_get_does_not_create_member_or_consume(self) -> None:
        project = self.make_project()
        invitation = self.make_invitation(project)

        response = Client().get(self.join_path(invitation))

        self.assertEqual(response.status_code, 200)
        invitation.refresh_from_db()
        self.assertIsNone(invitation.used_at)
        self.assertFalse(ProjectMember.objects.filter(project=project, user=self.bob).exists())
        self.assertEqual(ProjectInvitation.objects.count(), 1)

    def test_join_page_shows_only_project_name_and_role(self) -> None:
        project = self.make_project(name='<b>甲项目</b>')
        project.workspace_path = 'D:/owner/private'
        project.save(update_fields=['workspace_path'])
        TaskNode.objects.create(
            project=project, title='秘密任务', start_date='2026-10-01',
            end_date='2026-10-02',
        )
        invitation = self.make_invitation(project, role='<i>测试</i>')

        body = Client().get(self.join_path(invitation)).content.decode('utf-8')

        self.assertIn('&lt;b&gt;甲项目&lt;/b&gt;', body)
        self.assertIn('&lt;i&gt;测试&lt;/i&gt;', body)
        self.assertNotIn('<b>甲项目</b>', body)
        self.assertNotIn('秘密任务', body)
        self.assertNotIn('owner/private', body)
        self.assertNotIn('alice', body)

    def test_first_join_creates_human_member_with_invitation_role(self) -> None:
        project = self.make_project()
        invitation = self.make_invitation(project, role='后端')

        response = self.posted_join(self.as_user(self.bob), invitation)

        self.assertRedirects(
            response, f'/projects/{project.pk}/board/', fetch_redirect_response=False
        )
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.used_at)
        self.assertEqual(invitation.used_by, self.bob)
        member = ProjectMember.objects.get(project=project, user=self.bob)
        self.assertEqual(member.kind, ProjectMember.Kind.HUMAN)
        self.assertEqual(member.role, '后端')
        self.assertEqual(member.name, 'bob')

    def test_forged_fields_do_not_change_role_or_grant_file_access(self) -> None:
        project = self.make_project()
        invitation = self.make_invitation(project, role='后端')
        bob_client = self.as_user(self.bob)

        self.posted_join(
            bob_client, invitation, role='owner', user=str(self.alice.pk),
            owner=str(self.bob.pk), path='D:/secret', kind='ai',
        )

        member = ProjectMember.objects.get(project=project, user=self.bob)
        self.assertEqual(member.role, '后端')
        self.assertEqual(project.owner, self.alice)
        self.assertEqual(ProjectMember.objects.filter(project=project, user=self.bob).count(), 1)
        self.assertNotIn(grants.SESSION_KEY, bob_client.session)
        self.assertEqual(bob_client.get(f'/workspace/?project={project.pk}').status_code, 404)

    def test_repeat_join_is_idempotent_and_keeps_role(self) -> None:
        project = self.make_project()
        invitation = self.make_invitation(project, role='后端')
        bob_client = self.as_user(self.bob)
        self.posted_join(bob_client, invitation)
        member = ProjectMember.objects.get(project=project, user=self.bob)
        member.role = '测试'
        member.save(update_fields=['role'])
        invitation.used_at = timezone.now()
        used_at = invitation.used_at
        invitation.save(update_fields=['used_at'])
        invitation.refresh_from_db()

        response = bob_client.post(self.join_path(invitation))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            ProjectMember.objects.filter(project=project, user=self.bob).count(), 1
        )
        member.refresh_from_db()
        self.assertEqual(member.role, '测试')
        invitation.refresh_from_db()
        self.assertEqual(invitation.used_at, used_at)

    def test_second_user_cannot_use_a_consumed_link(self) -> None:
        project = self.make_project()
        invitation = self.make_invitation(project)
        self.posted_join(self.as_user(self.bob), invitation)
        invitation.refresh_from_db()

        response = self.posted_join(self.as_user(self.carol), invitation)

        self.assertEqual(response.status_code, 410)
        self.assertFalse(ProjectMember.objects.filter(project=project, user=self.carol).exists())
        invitation.refresh_from_db()
        self.assertEqual(invitation.used_by, self.bob)

    def test_expired_and_revoked_and_used_by_other_are_410(self) -> None:
        project = self.make_project()
        expired = self.make_invitation(project, expires_at=timezone.now() - timedelta(minutes=1))
        revoked = self.make_invitation(project)
        revoked.revoked_at = timezone.now()
        revoked.save(update_fields=['revoked_at'])
        used = self.make_invitation(project, used_at=timezone.now(), used_by=self.carol)

        for invitation in (expired, revoked, used):
            with self.subTest(invitation=invitation.pk):
                self.assertEqual(self.client.get(self.join_path(invitation)).status_code, 410)
                self.assertEqual(self.posted_join(self.as_user(self.bob), invitation).status_code, 410)

        self.assertFalse(ProjectMember.objects.filter(project=project, user=self.bob).exists())
        self.assertIsNone(ProjectInvitation.objects.get(pk=expired.pk).used_at)
        self.assertIsNone(ProjectInvitation.objects.get(pk=revoked.pk).used_at)

    def test_existing_member_is_not_consumed_and_keeps_role(self) -> None:
        project = self.make_project()
        membership = ProjectMember.objects.create(
            project=project, kind=ProjectMember.Kind.HUMAN, user=self.bob, role='前端',
        )
        invitation = self.make_invitation(project, role='测试')

        response = self.posted_join(self.as_user(self.bob), invitation)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'/projects/{project.pk}/board/')
        membership.refresh_from_db()
        self.assertEqual(membership.role, '前端')
        invitation.refresh_from_db()
        self.assertIsNone(invitation.used_at)
        self.assertEqual(ProjectMember.objects.filter(project=project, user=self.bob).count(), 1)

    def test_owner_link_is_not_consumed(self) -> None:
        project = self.make_project()
        invitation = self.make_invitation(project)

        response = self.client.post(self.join_path(invitation))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'/projects/{project.pk}/board/')
        invitation.refresh_from_db()
        self.assertIsNone(invitation.used_at)
        self.assertEqual(ProjectMember.objects.filter(project=project).count(), 1)

    def test_member_creation_failure_rolls_back_consumption(self) -> None:
        project = self.make_project()
        invitation = self.make_invitation(project)

        with mock.patch.object(
            ProjectMember.objects, 'get_or_create', side_effect=IntegrityError('boom')
        ):
            response = self.posted_join(self.as_user(self.bob), invitation)

        self.assertEqual(response.status_code, 400)
        invitation.refresh_from_db()
        self.assertIsNone(invitation.used_at)
        self.assertIsNone(invitation.used_by)
        self.assertFalse(ProjectMember.objects.filter(project=project, user=self.bob).exists())

    def test_join_requires_csrf(self) -> None:
        project = self.make_project()
        invitation = self.make_invitation(project)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.bob)

        response = csrf_client.post(self.join_path(invitation))

        self.assertEqual(response.status_code, 403)
        invitation.refresh_from_db()
        self.assertIsNone(invitation.used_at)

    def test_anonymous_page_offers_login_and_signup_without_joining(self) -> None:
        project = self.make_project()
        invitation = self.make_invitation(project)
        self.client.logout()

        response = self.client.get(self.join_path(invitation))
        body = response.content.decode('utf-8')

        self.assertEqual(response.status_code, 200)
        self.assertIn('/accounts/login/?next=', body)
        self.assertIn('/accounts/signup/?next=', body)
        invitation.refresh_from_db()
        self.assertIsNone(invitation.used_at)
        self.assertFalse(ProjectMember.objects.filter(project=project, user=self.bob).exists())

    def test_anonymous_post_redirects_to_login_instead_of_joining(self) -> None:
        project = self.make_project()
        invitation = self.make_invitation(project)
        self.client.logout()

        response = self.posted_join(self.client, invitation)

        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/?next=', response['Location'])
        self.assertFalse(ProjectMember.objects.filter(project=project, user=self.bob).exists())
        self.assertIsNone(ProjectInvitation.objects.get(pk=invitation.pk).used_at)

    def test_cross_project_token_cannot_join_another_project(self) -> None:
        alice_project = self.make_project('甲项目')
        bob_project = self.make_project('乙项目', owner=self.bob)
        invitation = self.make_invitation(alice_project)
        token = invitations.build_token(invitation)

        response = self.as_user(self.carol).post(
            f'/projects/join/{token}/', {'project': str(bob_project.pk)}
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            ProjectMember.objects.filter(project=bob_project, user=self.carol).exists()
        )
        self.assertTrue(
            ProjectMember.objects.filter(project=alice_project, user=self.carol).exists()
        )


class InvitationManagementTests(InviteTestBase):
    def test_anonymous_is_redirected_and_non_owner_gets_404(self) -> None:
        project = self.make_project()
        ProjectMember.objects.create(
            project=project, kind=ProjectMember.Kind.HUMAN, user=self.bob, role='前端',
        )
        anonymous = Client()

        self.assertEqual(anonymous.get(f'/projects/{project.pk}/invitations/').status_code, 302)
        self.assertEqual(
            self.as_user(self.bob).get(f'/projects/{project.pk}/invitations/').status_code, 404
        )
        self.assertEqual(
            self.as_user(self.bob).post(f'/projects/{project.pk}/invitations/new/').status_code, 404
        )

    def test_create_uses_default_seven_days_and_redirects(self) -> None:
        project = self.make_project()

        response = self.client.post(
            f'/projects/{project.pk}/invitations/new/', {'role': '前端'}
        )

        self.assertRedirects(
            response, f'/projects/{project.pk}/invitations/', fetch_redirect_response=False
        )
        invitation = ProjectInvitation.objects.get(project=project)
        self.assertEqual(invitation.role, '前端')
        self.assertEqual(invitation.created_by, self.alice)
        delta = invitation.expires_at - timezone.now()
        self.assertGreater(delta, timedelta(days=6, hours=23))
        self.assertLessEqual(delta, timedelta(days=7))

    def test_create_accepts_one_and_thirty_days_but_rejects_other_values(self) -> None:
        project = self.make_project()
        for days in ('1', '30'):
            self.client.post(
                f'/projects/{project.pk}/invitations/new/', {'role': 'x', 'days': days}
            )
        expires = list(ProjectInvitation.objects.values_list('expires_at', flat=True))
        self.assertEqual(len(expires), 2)
        self.assertLess(max(expires) - min(expires), timedelta(days=30))

        response = self.client.post(
            f'/projects/{project.pk}/invitations/new/',
            {'role': '保留的角色', 'days': '3650'},
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, '保留的角色', status_code=400)
        self.assertEqual(ProjectInvitation.objects.count(), 2)

    def test_create_is_post_only_and_requires_csrf(self) -> None:
        project = self.make_project()
        self.assertEqual(
            self.client.get(f'/projects/{project.pk}/invitations/new/').status_code, 405
        )
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.alice)
        self.assertEqual(
            csrf_client.post(f'/projects/{project.pk}/invitations/new/', {'role': 'x'}).status_code,
            403,
        )
        self.assertEqual(ProjectInvitation.objects.count(), 0)

    def test_list_shows_state_and_link_only_for_valid_invitations(self) -> None:
        project = self.make_project()
        valid = self.make_invitation(project, role='前端')
        revoked = self.make_invitation(project, role='撤销角色')
        revoked.revoked_at = timezone.now()
        revoked.save(update_fields=['revoked_at'])
        used = self.make_invitation(project, role='已用角色', used_at=timezone.now(), used_by=self.bob)
        expired = self.make_invitation(
            project, role='过期角色', expires_at=timezone.now() - timedelta(days=1)
        )

        body = self.client.get(f'/projects/{project.pk}/invitations/').content.decode('utf-8')

        self.assertIn('有效', body)
        self.assertIn('已撤销', body)
        self.assertIn('已使用', body)
        self.assertIn('已过期', body)
        self.assertIn(f'/projects/join/{invitations.build_token(valid)}/', body)
        for other in (revoked, used, expired):
            self.assertNotIn(invitations.build_token(other), body)

    def test_list_is_capped_at_fifty_recent_rows(self) -> None:
        project = self.make_project()
        for index in range(55):
            self.make_invitation(project, role=f'角色{index}')

        response = self.client.get(f'/projects/{project.pk}/invitations/')

        self.assertEqual(len(response.context['invitations']), 50)
        self.assertNotIn('角色0', response.content.decode('utf-8'))

    def test_revoke_is_owner_scoped_post_only_and_effective(self) -> None:
        project = self.make_project()
        other_project = self.make_project('乙项目', owner=self.bob)
        invitation = self.make_invitation(project)
        revisit = self.make_invitation(project)

        self.assertEqual(
            self.client.get(
                f'/projects/{project.pk}/invitations/{invitation.pk}/revoke/'
            ).status_code,
            405,
        )
        bob_client = self.as_user(self.bob)
        self.assertEqual(
            bob_client.post(
                f'/projects/{project.pk}/invitations/{invitation.pk}/revoke/'
            ).status_code,
            404,
        )
        self.assertEqual(
            bob_client.post(
                f'/projects/{other_project.pk}/invitations/{invitation.pk}/revoke/'
            ).status_code,
            404,
        )
        self.assertIsNone(ProjectInvitation.objects.get(pk=invitation.pk).revoked_at)

        response = self.client.post(
            f'/projects/{project.pk}/invitations/{invitation.pk}/revoke/'
        )

        self.assertRedirects(
            response, f'/projects/{project.pk}/invitations/', fetch_redirect_response=False
        )
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.revoked_at)
        self.assertEqual(
            self.client.get(self.join_path(invitation)).status_code, 410
        )
        self.assertEqual(
            self.client.get(self.join_path(revisit)).status_code, 200
        )

    def test_revoke_requires_csrf(self) -> None:
        project = self.make_project()
        invitation = self.make_invitation(project)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.alice)

        self.assertEqual(
            csrf_client.post(
                f'/projects/{project.pk}/invitations/{invitation.pk}/revoke/'
            ).status_code,
            403,
        )
        self.assertIsNone(ProjectInvitation.objects.get(pk=invitation.pk).revoked_at)

    def test_member_board_has_no_invitation_entry_or_link(self) -> None:
        project = self.make_project()
        invitation = self.make_invitation(project)
        ProjectMember.objects.create(
            project=project, kind=ProjectMember.Kind.HUMAN, user=self.bob, role='测试',
        )

        owner_body = self.client.get(f'/projects/{project.pk}/board/').content.decode('utf-8')
        member_body = self.as_user(self.bob).get(
            f'/projects/{project.pk}/board/'
        ).content.decode('utf-8')

        self.assertIn(f'/projects/{project.pk}/invitations/', owner_body)
        self.assertNotIn('邀请链接为后续功能', owner_body)
        self.assertNotIn(f'/projects/{project.pk}/invitations/', member_body)
        self.assertNotIn(invitations.build_token(invitation), member_body)

    def test_member_still_has_no_owner_workspace_access(self) -> None:
        project = self.make_project()
        ProjectMember.objects.create(
            project=project, kind=ProjectMember.Kind.HUMAN, user=self.bob, role='测试',
        )
        bob_client = self.as_user(self.bob)

        self.assertEqual(
            bob_client.get(f'/workspace/?project={project.pk}').status_code, 404
        )
        self.assertEqual(
            bob_client.post('/workspace/', {'action': 'create', 'name': 'x.txt', 'content': 'x'}).status_code,
            403,
        )
        self.assertNotIn(grants.SESSION_KEY, bob_client.session)


class InvitationLoggingTests(InviteTestBase):
    def test_token_is_scrubbed_from_request_and_server_logs(self) -> None:
        project = self.make_project()
        invitation = self.make_invitation(project)
        token = invitations.build_token(invitation)
        logger = logging.getLogger('django.server')
        records: list[str] = []

        class Collector(logging.Handler):
            def emit(self, record) -> None:
                records.append(self.format(record))

        handler = Collector()
        handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        self.addCleanup(logger.removeHandler, handler)
        self.addCleanup(logger.setLevel, logging.NOTSET)

        logger.info('"%s" %s %s', 'GET', f'/projects/join/{token}/', 'HTTP/1.1')
        logger.info('"%s" %s %s', 'GET', '/projects/', 'HTTP/1.1')
        logging.getLogger('django.request').warning(
            'Not Found: %s', f'/projects/join/{token}/?next=%2Fprojects%2Fjoin%2F{token}%2F'
        )

        combined = '\n'.join(records)
        self.assertNotIn(token, combined)
        self.assertIn('/projects/join/<redacted>/', combined)
        self.assertIn('GET /projects/ HTTP/1.1', combined.replace('"', ''))

    def test_filter_ignores_records_without_tokens(self) -> None:
        record = logging.LogRecord(
            'django.request', logging.INFO, '', 0, 'GET %s 200', ('/projects/',), None
        )
        InvitationTokenFilter().filter(record)

        self.assertEqual(record.getMessage(), 'GET /projects/ 200')

    def test_filter_is_registered_on_request_and_server_loggers(self) -> None:
        for name in ('django', 'django.request', 'django.server'):
            with self.subTest(logger=name):
                logger = logging.getLogger(name)
                attached = list(logger.filters)
                for handler in logger.handlers:
                    attached.extend(handler.filters)
                self.assertTrue(
                    any(isinstance(item, InvitationTokenFilter) for item in attached),
                    name,
                )
        self.assertTrue(InvitationTokenFilter().filter(
            logging.LogRecord('django.request', logging.INFO, '', 0, 'x', (), None)
        ))


class InvitationProjectListTests(InviteTestBase):
    def test_joined_project_appears_only_for_the_member(self) -> None:
        joined = self.make_project('甲项目', owner=self.carol)
        own = self.make_project('乙项目', owner=self.bob)
        self.make_project('丁项目', owner=self.alice)
        ProjectMember.objects.create(
            project=joined, kind=ProjectMember.Kind.HUMAN, user=self.bob, role='后端',
        )
        joined.workspace_path = 'D:/owner/private'
        joined.save(update_fields=['workspace_path'])

        bob_body = self.as_user(self.bob).get('/projects/').content.decode('utf-8')
        alice_body = self.client.get('/projects/').content.decode('utf-8')

        self.assertIn('参与的项目', bob_body)
        self.assertIn('甲项目', bob_body)
        self.assertIn('后端', bob_body)
        self.assertIn(f'/projects/{joined.pk}/board/', bob_body)
        self.assertNotIn('owner/private', bob_body)
        self.assertNotIn('参与的项目', alice_body)
        self.assertIn(own.name, bob_body)
        self.assertNotIn('甲项目', alice_body)
