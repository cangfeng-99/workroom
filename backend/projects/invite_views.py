"""Owner invitation management and the public one-time join page (T017).

An invitation only adds a human collaboration row. It never grants file
access, an owner role, or any change to an existing member's role.
"""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from projects import invitations as invite_codes
from projects.invite_forms import InviteCreateForm
from projects.models import Project, ProjectInvitation, ProjectMember

MAX_LISTED = 50
GONE = '该邀请链接已失效：可能已过期、已被撤销，或已被其他人使用。'
ALREADY = '你已经是该项目成员，此邀请不会被再次使用。'
JOINED = '已加入项目：{name}'
FAILED = '加入失败，请稍后重试或联系项目所有者。'


def _owned(request, pk: int) -> Project:
    return get_object_or_404(Project, pk=pk, owner=request.user)


def _entries(request, project: Project) -> dict:
    now = timezone.now()
    invitations = list(project.invitations.select_related('used_by')[:MAX_LISTED])
    entries = []
    for invitation in invitations:
        state = invite_codes.state(invitation, now)
        entries.append({
            'invitation': invitation,
            'state': state,
            'label': invite_codes.STATE_LABELS[state],
            'url': invite_codes.build_url(request, invitation) if state == invite_codes.VALID else '',
        })
    return {'project': project, 'invitations': invitations, 'entries': entries}


@never_cache
@login_required
@require_GET
def invitation_list(request, pk: int):
    project = _owned(request, pk)
    return render(
        request,
        'projects/invitations.html',
        {**_entries(request, project), 'form': InviteCreateForm()},
    )


@never_cache
@login_required
@require_POST
def invitation_create(request, pk: int):
    project = _owned(request, pk)
    form = InviteCreateForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            'projects/invitations.html',
            {
                **_entries(request, project),
                'form': form,
                'error': '请检查分工角色与有效期。',
            },
            status=400,
        )
    ProjectInvitation.objects.create(
        project=project,
        created_by=request.user,
        role=form.cleaned_data['role'],
        expires_at=timezone.now() + timedelta(days=form.cleaned_data['days']),
    )
    messages.success(request, '已生成一次性邀请链接，可复制后发给受邀成员。')
    return redirect('projects:invitation_list', pk=project.pk)


@never_cache
@login_required
@require_POST
def invitation_revoke(request, pk: int, invite_pk):
    project = _owned(request, pk)
    invitation = get_object_or_404(ProjectInvitation, pk=invite_pk, project=project)
    if invitation.used_at is not None:
        messages.info(request, '该邀请已被使用，无法撤销。')
    elif invitation.revoked_at is not None:
        messages.info(request, '该邀请已撤销。')
    else:
        invitation.revoked_at = timezone.now()
        invitation.save(update_fields=['revoked_at'])
        messages.success(request, '已撤销该邀请链接。')
    return redirect('projects:invitation_list', pk=project.pk)


def _page(request, invitation: ProjectInvitation, mode: str, *, status: int = 200,
          error: str = ''):
    project = invitation.project
    next_path = request.path
    return render(
        request,
        'projects/invitation_join.html',
        {
            'invitation': invitation,
            'project': project,
            'mode': mode,
            'next': next_path,
            'error': error,
            'board_url': reverse('projects:board', args=[project.pk]),
            'login_url': f"{reverse('accounts:login')}?{urlencode({'next': next_path})}",
            'signup_url': f"{reverse('accounts:signup')}?{urlencode({'next': next_path})}",
        },
        status=status,
    )


@never_cache
@require_http_methods(['GET', 'POST'])
def invitation_join(request, token: str):
    invitation = invite_codes.parse_token(token)
    if invitation is None:
        raise Http404('invalid invitation')
    now = timezone.now()
    project = invitation.project
    current = invite_codes.state(invitation, now)
    user = request.user

    if current == invite_codes.USED:
        if user.is_authenticated and invitation.used_by_id == user.pk:
            return _page(request, invitation, 'already')
        return _page(request, invitation, 'gone', status=410, error=GONE)
    if current != invite_codes.VALID:
        return _page(request, invitation, 'gone', status=410, error=GONE)

    if not user.is_authenticated:
        if request.method == 'POST':
            # Never join an anonymous request; send the visitor to login first
            # and come back to this exact confirmation page.
            return redirect(
                f"{reverse('accounts:login')}?{urlencode({'next': request.path})}"
            )
        return _page(request, invitation, 'anonymous')

    member = ProjectMember.objects.filter(
        project=project, kind=ProjectMember.Kind.HUMAN, user=user
    ).first()
    if member is not None or project.owner_id == user.pk:
        return _page(request, invitation, 'already')

    if request.method == 'GET':
        return _page(request, invitation, 'confirm')

    try:
        result, _member = invite_codes.consume(invitation, user, now)
    except IntegrityError:
        return _page(request, invitation, 'failure', status=400, error=FAILED)

    if result == invite_codes.JOINED:
        messages.success(request, JOINED.format(name=project.name))
        return redirect('projects:board', pk=project.pk)
    if result == invite_codes.ALREADY_MEMBER:
        return _page(request, invitation, 'already')
    return _page(request, invitation, 'gone', status=410, error=GONE)
