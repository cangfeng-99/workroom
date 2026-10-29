"""Generate private deployment secrets once; never print their values."""

import secrets
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "生成服务器 .env（不覆盖现有文件，不在终端显示密钥）。请在 local 模式运行。"

    def add_arguments(self, parser):
        parser.add_argument("domain")
        parser.add_argument("--output", default=".env")

    def handle(self, *args, **options):
        domain = options["domain"].strip()
        parsed = urlsplit("https://" + domain)
        if parsed.hostname != domain or any(x in domain for x in "/:@?#\r\n ") or not domain:
            raise CommandError("请输入不含协议、端口或路径的域名。")
        target = Path(options["output"]).resolve()
        values = Path(__file__).resolve().parents[4] / ".env.example"
        text = values.read_text(encoding="utf-8").replace("workroom.example.com", domain)
        text = text.replace(
            "REPLACE_WITH_RANDOM_SECRET_AT_LEAST_50_CHARACTERS", secrets.token_urlsafe(64)
        )
        text = text.replace("REPLACE_WITH_A_FERNET_KEY", Fernet.generate_key().decode())
        try:
            with target.open("x", encoding="utf-8") as handle:
                handle.write(text)
            target.chmod(0o600)
        except FileExistsError:
            raise CommandError("配置文件已存在，拒绝覆盖。") from None
        self.stdout.write(f"配置已生成：{target}。请单独保管，不要上传到仓库或聊天。")
