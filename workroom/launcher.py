"""Desktop entry point.

    python launcher.py          # serve the web UI on 127.0.0.1:8000
    python launcher.py --mcp    # run the MCP stdio server (used by Codex/Cursor)

Packaged builds point MCP clients at ``WorkRoom.exe --mcp``; in development the
clients point at ``python mcp_server.py`` instead.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')


def main() -> None:
    if '--mcp' in sys.argv:
        from mcp_server import main as mcp_main

        mcp_main()
        return

    import django

    django.setup()
    from django.core.management import call_command

    call_command('migrate', interactive=False)

    try:
        from waitress import serve

        from config.wsgi import application

        serve(application, host='127.0.0.1', port=8000, threads=4)
    except ImportError:
        from django.core.management import execute_from_command_line

        execute_from_command_line(
            [sys.argv[0], 'runserver', '127.0.0.1:8000', '--noreload']
        )


if __name__ == '__main__':
    main()
