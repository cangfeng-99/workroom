"""User identity -> prompt lens for agents."""

from __future__ import annotations

from .models import Project, UserProfile
from .permissions import is_server

_LENS = {
    UserProfile.Role.DEVELOPER: (
        '按程序员的视角拆分：先定架构和模块边界，再拆接口、实现、联调、测试、部署；'
        '每个任务要能对应到具体文件/命令，避免空泛的“优化一下”。'
    ),
    UserProfile.Role.PRODUCT: (
        '按产品经理的视角拆分：先定目标用户、场景、MVP 范围和验收指标，'
        '再拆需求、交互、上线验证；少讲技术实现，多讲为什么做和怎么判定有效。'
    ),
    UserProfile.Role.DESIGNER: (
        '按设计师的视角拆分：先定信息架构和关键流程，再拆页面状态、组件、'
        '可访问性与走查；关注体验细节和边界状态。'
    ),
    UserProfile.Role.OPS: (
        '按运营的视角拆分：先定渠道、内容节奏和漏斗指标，再拆冷启动、'
        '转化路径、留存动作和数据复盘；任务要能对应到可观测的数字。'
    ),
    UserProfile.Role.FOUNDER: (
        '按创始人/个体的视角拆分：先定结果、预算和时间，再判断“买还是做”，'
        '任务要写清成本、依赖和外包边界，避免技术黑话。'
    ),
    UserProfile.Role.STUDENT: (
        '按学习者的视角拆分：先定知识点和练习目标，再拆小步练习、'
        '可运行的最小作品和复盘；每个任务都要能在一次学习时段内完成。'
    ),
    UserProfile.Role.OTHER: (
        '先确认用户要完成的事情和判断标准，再按“最小可验证步骤”拆分，'
        '避免假设用户懂技术。'
    ),
}


LOCAL_USERNAME = 'workroom_local'


def local_user():
    from django.contrib.auth import get_user_model

    user, created = get_user_model().objects.get_or_create(
        username=LOCAL_USERNAME, defaults={'is_active': True}
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=['password'])
    return user


def current_profile(request) -> UserProfile | None:
    if request.user.is_authenticated:
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        return profile
    if not is_server():
        profile, _ = UserProfile.objects.get_or_create(user=local_user())
        return profile
    return None


def for_project(project: Project) -> UserProfile | None:
    owner = getattr(project, 'owner', None)
    if owner is not None:
        return UserProfile.objects.filter(user=owner).first()
    if not is_server():
        return UserProfile.objects.filter(user=local_user()).first()
    return None


def prompt_block(project: Project) -> str:
    profile = for_project(project)
    if profile is None:
        return ''
    parts = [f'项目所有者身份：{profile.get_role_display()}']
    if profile.domain:
        parts.append(f'领域：{profile.domain}')
    if profile.experience:
        parts.append(f'经验：{profile.experience}')
    if profile.stack:
        parts.append(f'常用技术/工具：{profile.stack}')
    if profile.goal:
        parts.append(f'当前目标：{profile.goal}')
    roles = [profile.role]
    for extra in profile.secondary_roles or []:
        if extra in _LENS and extra not in roles:
            roles.append(extra)
    lenses = [_LENS[item] for item in roles[:2]]
    parts.append('拆分视角：' + '；'.join(lenses))
    return '\n'.join(parts)


def lens(project: Project) -> str:
    profile = for_project(project)
    if profile is None:
        return ''
    return _LENS.get(profile.role, _LENS[UserProfile.Role.OTHER])
