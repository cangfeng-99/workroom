"""Online SQLite backup using the database backup API (includes WAL)."""

import re
import sqlite3
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "在线备份数据库到数据目录 backups/，目标文件已存在时拒绝覆盖。"

    def add_arguments(self, parser):
        parser.add_argument("name", help="例如 before-upgrade.sqlite3")

    def handle(self, *args, **options):
        name = options["name"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\.sqlite3", name):
            raise CommandError("备份名必须是安全的 .sqlite3 文件名，不能带路径。")
        folder = Path(settings.DATA_DIR) / "backups"
        folder.mkdir(exist_ok=True)
        target = folder / name
        try:
            with target.open("xb"):
                pass
        except FileExistsError:
            raise CommandError("备份已存在，拒绝覆盖。") from None
        source = Path(settings.DATABASES["default"]["NAME"]).resolve()
        with (
            sqlite3.connect(source.as_uri() + "?mode=rw", uri=True) as db,
            sqlite3.connect(target) as out,
        ):
            db.backup(out)
        target.chmod(0o600)
        self.stdout.write(f"数据库已备份：{target}。模型加密密钥与服务器 .env 需另外保管。")
