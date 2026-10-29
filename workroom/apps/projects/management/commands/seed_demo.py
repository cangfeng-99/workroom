"""Seed three demo projects so the project picker is not empty on first run."""

from __future__ import annotations

from datetime import date, timedelta

from django.core.management.base import BaseCommand

from apps.projects.models import LibraryEntry, Member, Project, Task

# 页面按创建时间倒序，所以这里把最想让人先看到的放在最后创建。
DEMOS = [
    {
        'name': '个人作品站',
        'goal': '新版上线',
        'detail': '把作品集重新做一版，能直接发给客户看。',
        'deadline_days': 12,
        'members': [
            {'kind': 'human', 'name': '我', 'role': '负责人'},
            {
                'kind': 'ai',
                'name': 'DeepSeek',
                'role': '设计',
                'provider': 'deepseek',
                'model': 'deepseek-v4-flash',
                'persona': '你是设计兼前端，先定信息层级和文案，再动页面。'
                '给方案时说清为什么这样排，不要堆装饰。',
            },
        ],
        'library': [
            ('artifact', '首页文案 v1', '首屏一句话讲清做什么，下面直接放三个案例。'),
            ('decision', '先不做博客', '这一版只服务找工作，博客留到以后。'),
        ],
        'tasks': [
            ('首页改版', None, 'DeepSeek', -1, 5, Task.Status.DOING, '首屏主张、作品入口与联系方式'),
            ('案例页', None, '我', 3, 9, Task.Status.TODO, '挑三个项目写清背景、做法与结果'),
            ('部署', None, '我', 9, 11, Task.Status.TODO, '域名、HTTPS 与访问统计'),
        ],
    },
    {
        'name': '册子 App 二期',
        'goal': '完成云同步并提交上架',
        'detail': '鸿蒙应用，先把数据同步跑通，再准备上架材料。',
        'deadline_days': 20,
        'members': [
            {'kind': 'human', 'name': '我', 'role': '负责人'},
            {
                'kind': 'ai',
                'name': 'DeepSeek',
                'role': '前端',
                'provider': 'deepseek',
                'model': 'deepseek-v4-flash',
                'persona': '你是鸿蒙前端工程师，负责页面、状态与交互。'
                '先保证主流程能跑通，再谈动效；不确定的 API 先标出来。',
            },
            {
                'kind': 'ai',
                'name': '智谱 GLM',
                'role': '测试',
                'provider': 'zhipu',
                'model': 'glm-4.6',
                'persona': '你是测试工程师，先想边界、失败路径和回归范围。'
                '不写实现，只出清单和可判定的验收标准。',
            },
        ],
        'library': [
            ('rule', '离线优先', '断网也能编辑，联网后按修改时间合并。'),
            ('decision', '冲突先按后写覆盖', '这一版不做手动合并，先保证不丢数据。'),
        ],
        'tasks': [
            ('数据结构梳理', None, '我', -6, -3, Task.Status.DONE, '统一待办、笔记、账目的本地表结构'),
            ('云同步', None, 'DeepSeek', -2, 8, Task.Status.DOING, '多端一致性与离线队列'),
            ('增量同步', '云同步', 'DeepSeek', 0, 4, Task.Status.TODO, '按修改时间拉取增量'),
            ('冲突处理', '云同步', 'DeepSeek', 4, 8, Task.Status.TODO, '同一记录双端修改的合并策略'),
            ('上架材料', None, '智谱 GLM', 6, 12, Task.Status.TODO, '截图、隐私说明与版本说明'),
        ],
    },
    {
        'name': '开发项目 v1',
        'goal': 'v1 上线',
        'detail': '先跑通登录与任务看板，两周内可试用。',
        'deadline_days': 14,
        'members': [
            {'kind': 'human', 'name': '我', 'role': '负责人'},
            {
                'kind': 'ai',
                'name': 'DeepSeek',
                'role': '后端',
                'provider': 'deepseek',
                'model': 'deepseek-v4-flash',
                'persona': '你是资深后端工程师，负责登录、权限与数据模型。'
                '评审时先指出风险和边界，再给方案；不要写前端代码。',
            },
            {
                'kind': 'ai',
                'name': 'WorkBuddy',
                'role': '执行',
                'provider': 'custom',
                'model': 'workbuddy',
                'persona': '你负责把方案落成可执行步骤，按顺序推进，做完回报结果和阻塞点。',
            },
        ],
        'library': [
            ('rule', '只做 P0', '这版只保证登录和看板能用，其他需求进二期。'),
            ('artifact', '登录接口约定', 'POST /login 返回 token，后续请求走 Authorization 头。'),
            ('decision', '先本机 SQLite', '单机验证阶段不接 MySQL，接口稳定后再换。'),
        ],
        'tasks': [
            ('需求确认', None, '我', 0, 1, Task.Status.DONE, '确认范围、验收标准与时间点'),
            ('登录模块', None, 'DeepSeek', 2, 9, Task.Status.DOING, '账号密码登录与会话保持'),
            ('接口设计', '登录模块', 'DeepSeek', 2, 5, Task.Status.DONE, '定义登录、登出、会话校验接口'),
            ('页面开发', '登录模块', 'DeepSeek', 5, 9, Task.Status.TODO, '登录页、错误提示与跳转'),
            ('任务看板', None, '我', 6, 13, Task.Status.TODO, '横向树视图与节点详情'),
        ],
    },
]


class Command(BaseCommand):
    help = 'Create three demo projects (safe to run twice: existing names are skipped).'

    def handle(self, *args, **options) -> None:
        created_count = 0
        for demo in DEMOS:
            project, created = Project.objects.get_or_create(
                name=demo['name'],
                defaults={
                    'goal_title': demo['goal'],
                    'goal_detail': demo['detail'],
                    'goal_deadline': date.today() + timedelta(days=demo['deadline_days']),
                },
            )
            if not created:
                continue
            created_count += 1
            members: dict[str, Member] = {}
            for spec in demo['members']:
                members[spec['name']] = Member.objects.create(
                    project=project,
                    kind=spec['kind'],
                    name=spec['name'],
                    role=spec.get('role', ''),
                    persona=spec.get('persona', ''),
                    provider=spec.get('provider', ''),
                    model_name=spec.get('model', ''),
                    base_url=spec.get('base_url', ''),
                )
            tasks: dict[str, Task] = {}
            for order, (title, parent, assignee, start, end, status, detail) in enumerate(
                demo['tasks']
            ):
                tasks[title] = Task.objects.create(
                    project=project,
                    parent=tasks.get(parent) if parent else None,
                    title=title,
                    detail=detail,
                    assignee=members.get(assignee),
                    start_date=date.today() + timedelta(days=start),
                    end_date=date.today() + timedelta(days=end),
                    status=status,
                    order=order,
                )
            for kind, title, body in demo.get('library', []):
                LibraryEntry.objects.create(
                    project=project, kind=kind, title=title, body=body
                )
        if created_count:
            self.stdout.write(self.style.SUCCESS(f'seeded {created_count} demo projects'))
        else:
            self.stdout.write('demo projects already exist')
