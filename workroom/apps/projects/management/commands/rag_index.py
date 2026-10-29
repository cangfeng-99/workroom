"""把项目资料库切成块并生成向量，供知识库问答检索。"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.projects import rag
from apps.projects.models import Project


class Command(BaseCommand):
    help = '重建项目资料库的检索索引（切块 + 向量）'

    def add_arguments(self, parser):
        parser.add_argument('--project', type=int, help='项目 id；不填则处理全部项目')
        parser.add_argument('--force', action='store_true', help='忽略内容哈希，强制重算')

    def handle(self, *args, **options):
        if options['project']:
            projects = [Project.objects.filter(pk=options['project']).first()]
            if projects[0] is None:
                raise CommandError(f'项目 {options["project"]} 不存在')
        else:
            projects = list(Project.objects.all())

        if not projects:
            self.stdout.write('没有项目，先创建一个。')
            return

        mode = '远程向量接口' if rag.embed_config()['base_url'] else '本地哈希向量（未配置接口）'
        self.stdout.write(f'向量方式：{mode}，模型：{rag.active_model()}')

        for project in projects:
            result = rag.index_project(project, force=options['force'])
            self.stdout.write(
                f'[{project.pk}] {project.name}：{result["entries"]} 条资料，'
                f'新建 {result["created"]} 块，跳过 {result["skipped"]} 条未变，'
                f'清理 {result["removed"]} 块'
            )
        self.stdout.write(self.style.SUCCESS('索引完成'))
