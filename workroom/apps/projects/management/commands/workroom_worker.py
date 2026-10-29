"""Independent low-resource database worker; run under systemd/Compose."""

import time

from django.core.management.base import BaseCommand, CommandError

from apps.projects import queue
from apps.projects.permissions import is_server


class Command(BaseCommand):
    help = "运行持久任务 Worker（生产环境由 systemd/Compose 自动重启）。"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--poll", type=float, default=2)
        parser.add_argument("--worker-id", default="")

    def handle(self, *args, **options):
        if not is_server():
            raise CommandError("Worker 必须在 WORKROOM_MODE=server 下运行。")
        worker = options["worker_id"] or queue.default_worker_id()
        self.stdout.write(f"Worker {worker} 已启动；按 Ctrl+C 停止。")
        try:
            while True:
                worked = queue.run_once(worker)
                if options["once"]:
                    return
                if not worked:
                    time.sleep(max(0.2, options["poll"]))
        except KeyboardInterrupt:
            self.stdout.write("Worker 已停止，队列保留。")
