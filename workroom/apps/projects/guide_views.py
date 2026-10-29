import ipaddress
from io import BytesIO

from django.conf import settings
from django.db import DatabaseError
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

import guide_content
from desktop_support import DesktopError

from . import sample_projects


def _local(request):
    if settings.WORKROOM_MODE != "local":
        raise Http404
    try:
        if not ipaddress.ip_address(request.META.get("REMOTE_ADDR", "")).is_loopback:
            raise Http404
    except ValueError as exc:
        raise Http404 from exc


def _page(request, error="", status=200):
    return render(
        request,
        "projects/usage_guide.html",
        {
            "guide_intro": guide_content.INTRO,
            "guide_sections": guide_content.SECTIONS,
            "example_phase_count": len(sample_projects.PHASES),
            "example_leaf_count": len(sample_projects.LEAVES),
            "error": error,
        },
        status=status,
    )


@require_GET
def guide(request):
    _local(request)
    return _page(request)


@require_GET
def download(request):
    _local(request)
    return FileResponse(
        BytesIO(guide_content.render_markdown().encode("utf-8")),
        as_attachment=True,
        filename="WorkRoom使用指南.md",
        content_type="text/markdown; charset=utf-8",
    )


@require_POST
def example(request):
    _local(request)
    try:
        project, _ = sample_projects.open_example(
            request.user if request.user.is_authenticated else None
        )
    except DesktopError as exc:
        return _page(request, str(exc), status=409)
    except (DatabaseError, OSError):
        return _page(
            request,
            "本机数据暂时忙碌或无法保存，请检查空间和访问权限，稍后重试。原项目未被替换。",
            status=409,
        )
    return redirect(reverse("projects:space", args=[project.pk]) + "?tab=tasks")
