"""Explicit offline restore from an application-owned backup directory."""

import re
import sqlite3
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from apps.projects.queue import worker_online


class Command(BaseCommand):
    help = "停止 web/worker 后恢复备份；要求 --offline-confirm，恢复前再备份当前库。"

    def add_arguments(self, parser):
        parser.add_argument("name")
        parser.add_argument("--offline-confirm", action="store_true")

    def handle(self, *args, **options):
        from datetime import datetime

        if not options["offline_confirm"]:
            raise CommandError("请先停止 web 和 worker，再加 --offline-confirm。")
        if worker_online():
            raise CommandError("仍有近期 Worker 心跳；停止 Worker 并等心跳过期后再恢复。")
        name = options["name"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\.sqlite3", name):
            raise CommandError("只能恢复 backups/ 内的 .sqlite3 备份。")
        base = Path(settings.DATA_DIR).resolve()
        source = (base / "backups" / name).resolve()
        target = Path(settings.DATABASES["default"]["NAME"]).resolve()
        if (
            not source.is_relative_to(base / "backups")
            or not target.is_relative_to(base)
            or not source.is_file()
        ):
            raise CommandError("备份不存在或目标不在当前应用数据目录。")
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise CommandError("备份完整性校验失败。")
            tables = {
                row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if not {"projects_project", "django_migrations"} <= tables:
                raise CommandError("这不是 WorkRoom 数据库。")
            call_command(
                "workroom_backup",
                "before-restore-" + datetime.now().strftime("%Y%m%d%H%M%S") + ".sqlite3",
            )
            with sqlite3.connect(target) as destination:
                db.backup(destination)
        self.stdout.write("恢复完成。请使用匹配版本的程序及原加密密钥启动并检查。")
