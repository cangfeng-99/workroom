"""Explicitly attach an existing project to an account (never automatic)."""

from __future__ import annotations

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.projects.models import Member, Project, ProjectMembership
from apps.projects.permissions import audit


class Command(BaseCommand):
    help = '把已有项目交给指定账号，并要求 --confirm；旧数据不会自动归给注册者。'

    def add_arguments(self, parser) -> None:
        parser.add_argument('project', help='项目 id 或唯一名称')
        parser.add_argument('username', help='接收项目的账号')
        parser.add_argument('--confirm', action='store_true', help='确认执行归属变更')

    def handle(self, *args, **options) -> None:
        ref = str(options['project']).strip().lstrip('#')
        if ref.isdigit():
            project = Project.objects.filter(pk=int(ref)).first()
        else:
            matches = list(Project.objects.filter(name__iexact=ref)[:2])
            project = matches[0] if len(matches) == 1 else None
        if project is None:
            raise CommandError('找不到唯一的项目。')
        user = User.objects.filter(username=options['username']).first()
        if user is None:
            raise CommandError('找不到该账号，请先注册。')
        if not options['confirm']:
            raise CommandError('这是归属变更，请加 --confirm 再执行。')

        with transaction.atomic():
            ProjectMembership.objects.update_or_create(
                project=project,
                user=user,
                defaults={'role': ProjectMembership.Role.OWNER},
            )
            ProjectMembership.objects.filter(
                project=project, role=ProjectMembership.Role.OWNER
            ).exclude(user=user).update(role=ProjectMembership.Role.EDITOR)
            project.owner = user
            project.save(update_fields=['owner'])
            Member.objects.get_or_create(
                project=project,
                user=user,
                defaults={
                    'kind': Member.Kind.HUMAN,
                    'name': user.get_username()[:80],
                    'role': '负责人',
                },
            )
            audit(
                project,
                user,
                'project.assign_owner',
                f'project={project.pk} user={user.pk}',
            )
        self.stdout.write(
            self.style.SUCCESS(f'项目 #{project.pk}「{project.name}」已交给 {user.username}。')
        )
