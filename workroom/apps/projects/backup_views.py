"""Local-only backup UI. No restore is performed inside an HTTP request."""

import ipaddress
from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from . import local_backups as backups
from .models import Delivery, Project, Task


@require_http_methods(["GET", "POST"])
def local_backups(request):
    if settings.WORKROOM_MODE != "local":
        raise Http404
    try:
        if not ipaddress.ip_address(request.META.get("REMOTE_ADDR", "")).is_loopback:
            raise Http404
    except ValueError as exc:
        raise Http404 from exc
    error = ""
    inspected = None
    status = 200
    try:
        if int(request.META.get("CONTENT_LENGTH") or 0) > backups.MAX_ARCHIVE + 1024 * 1024:
            raise backups.BackupError("文件超过 64 MB，请选择较小的 WorkRoom 备份。")
        if request.method == "POST":
            action = request.POST.get("action", "")
            if action == "export":
                archive = backups.export_backup()
                return FileResponse(
                    archive.open("rb"),
                    as_attachment=True,
                    filename=archive.name,
                    content_type="application/zip",
                )
            if action == "inspect":
                request.session.pop("backup_preview", None)
                upload = request.FILES.get("archive")
                if upload is None:
                    raise backups.BackupError("请先选择 WorkRoom 导出的 ZIP 文件。")
                inspected = backups.inspect_upload(upload)
                request.session["backup_preview"] = inspected["token"]
                return redirect("projects:local_backups")
            if action == "schedule":
                token = request.POST.get("token", "")
                if not token or token != request.session.get("backup_preview"):
                    raise backups.BackupError("检查记录已改变，请重新选择备份。")
                if request.POST.get("confirm_replace") != "yes":
                    raise backups.BackupError("请先核对备份内容，再勾选覆盖确认。")
                backups.schedule_restore(token)
                request.session.pop("backup_preview", None)
                return redirect("projects:local_backups")
            if action == "cancel":
                backups.cancel_restore()
                return redirect("projects:local_backups")
            raise backups.BackupError("请选择导出、检查或取消恢复。")
    except (backups.BackupError, RequestDataTooBig, OSError) as exc:
        error = (
            str(exc)
            if isinstance(exc, backups.BackupError)
            else "无法完成操作，请检查文件大小、磁盘空间和访问权限。原数据未更改。"
        )
        status = 400
    token = request.session.get("backup_preview")
    if token:
        try:
            inspected = backups.preview(token)
        except backups.BackupError as exc:
            error = error or str(exc)
            request.session.pop("backup_preview", None)
    state = backups.restore_state()
    if inspected:
        inspected["created_at_display"] = (
            datetime.fromisoformat(inspected["created_at"])
            .astimezone(ZoneInfo("Asia/Shanghai"))
            .strftime("%Y-%m-%d %H:%M:%S 北京时间")
        )
    return render(
        request,
        "projects/local_backups.html",
        {
            "error": error,
            "inspected": inspected,
            "restore_state": state,
            "counts": {
                "projects": Project.objects.count(),
                "tasks": Task.objects.count(),
                "deliveries": Delivery.objects.count(),
            },
            "backup_directory": str(backups.data_dir() / "backups"),
        },
        status=status,
    )
