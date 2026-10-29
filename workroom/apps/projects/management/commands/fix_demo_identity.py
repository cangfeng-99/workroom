"""Align demo data with the identity model (safe to run twice)."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.projects.models import Member

PERSONAS = {
    ('开发项目 v1', 'DeepSeek'): '你是资深后端工程师，负责登录、权限与数据模型。'
    '评审时先指出风险和边界，再给方案；不要写前端代码。',
    ('开发项目 v1', 'WorkBuddy'): '你负责把方案落成可执行步骤，按顺序推进，'
    '做完回报结果和阻塞点。',
    ('册子 App 二期', 'DeepSeek'): '你是鸿蒙前端工程师，负责页面、状态与交互。'
    '先保证主流程能跑通，再谈动效；不确定的 API 先标出来。',
    ('册子 App 二期', '智谱 GLM'): '你是测试工程师，先想边界、失败路径和回归范围。'
    '不写实现，只出清单和可判定的验收标准。',
    ('个人作品站', 'DeepSeek'): '你是设计兼前端，先定信息层级和文案，再动页面。'
    '给方案时说清为什么这样排，不要堆装饰。',
}

DUTIES = {
    ('开发项目 v1', 'DeepSeek'): 'propose',
    ('开发项目 v1', 'WorkBuddy'): 'decide',
    ('册子 App 二期', 'DeepSeek'): 'propose',
    ('册子 App 二期', '智谱 GLM'): 'review',
    ('个人作品站', 'DeepSeek'): 'propose',
}

PROVIDERS = {
    ('开发项目 v1', 'DeepSeek'): ('deepseek', 'deepseek-v4-flash'),
    ('开发项目 v1', 'WorkBuddy'): ('custom', 'workbuddy'),
    ('册子 App 二期', 'DeepSeek'): ('deepseek', 'deepseek-v4-flash'),
    ('册子 App 二期', '智谱 GLM'): ('zhipu', 'glm-4.6'),
    ('个人作品站', 'DeepSeek'): ('deepseek', 'deepseek-v4-flash'),
}


class Command(BaseCommand):
    help = 'Rename 通义千问 to 智谱 GLM and fill empty AI personas in demo projects.'

    def handle(self, *args, **options) -> None:
        renamed = Member.objects.filter(kind='ai', name='通义千问').update(
            name='智谱 GLM',
            role='测试',
            provider='zhipu',
            model_name='glm-4.6',
            base_url='',
        )
        filled = 0
        for member in Member.objects.filter(kind='ai', persona='').select_related('project'):
            key = (member.project.name, member.name)
            text = PERSONAS.get(key)
            if text:
                member.persona = text
                member.save(update_fields=['persona'])
                filled += 1

        duties = 0
        for member in Member.objects.filter(kind='ai', duty='execute').select_related(
            'project'
        ):
            value = DUTIES.get((member.project.name, member.name))
            if value:
                member.duty = value
                member.save(update_fields=['duty'])
                duties += 1

        configured = 0
        for member in Member.objects.filter(kind='ai', provider='').select_related('project'):
            pair = PROVIDERS.get((member.project.name, member.name))
            if pair:
                member.provider, member.model_name = pair
                member.save(update_fields=['provider', 'model_name'])
                configured += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'renamed {renamed} member(s), filled {filled} persona(s), '
                f'configured {configured} provider(s), duties {duties}'
            )
        )
