"""Exercise the actual local Django connection and result publisher, file DB."""
import json
import os
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import django


def main():
    ROOT = Path(__file__).resolve().parents[2]
    DATA = Path(sys.argv[1]).resolve()
    assert DATA.is_relative_to((ROOT / '.tools').resolve())
    os.environ.update(DJANGO_SETTINGS_MODULE='config.settings', WORKROOM_MODE='local', WORKROOM_DATA_DIR=str(DATA), WORKROOM_DB_PATH=str(DATA / 'concurrency.sqlite3'))
    sys.path.insert(0, str(ROOT / 'workroom'))
    django.setup()
    from django.core.management import call_command
    from django.db import connections

    from apps.projects import queue, views
    from apps.projects.models import ChatMessage, Project, ReplyJob

    call_command('migrate', interactive=False, verbosity=0)
    project = Project.objects.create(name='Isolated concurrent publisher')
    job = ReplyJob.objects.create(project=project, status='running')
    read = threading.Event()
    writing = threading.Event()
    written = threading.Event()
    errors = []
    original = queue.ensure_active


    def pause_after_read(job_id):
        original(job_id)
        read.set()
        assert writing.wait(3), 'concurrent writer did not start'
        # Hold the read/write-upgrade window open, not a model/network transaction.
        written.wait(.3)


    def publish():
        try:
            views._job_message(job, project=project, role='assistant', content='committed result', payload={})
        except Exception as exc:
            errors.append(type(exc).__name__ + ': ' + str(exc))
        finally:
            connections.close_all()


    def concurrent_write():
        try:
            assert read.wait(3), 'publisher did not read'
            writing.set()
            ReplyJob.objects.filter(pk=job.pk).update(partial_answer='concurrent committed update')
            written.set()
        except Exception as exc:
            errors.append(type(exc).__name__ + ': ' + str(exc))
        finally:
            connections.close_all()


    with patch.object(views.job_queue, 'ensure_active', side_effect=pause_after_read):
        publisher = threading.Thread(target=publish)
        writer = threading.Thread(target=concurrent_write)
        publisher.start()
        writer.start()
        publisher.join(10)
        writer.join(10)
        assert not publisher.is_alive() and not writer.is_alive(), 'threads did not finish'
    saved = ChatMessage.objects.filter(project=project, content='committed result').exists()
    updated = ReplyJob.objects.get(pk=job.pk).partial_answer == 'concurrent committed update'
    connections.close_all()
    if errors or not saved or not updated:
        print(json.dumps(dict(errors=errors, publication_saved=saved, concurrent_update_saved=updated)))
        raise SystemExit(1)
    print('publication and concurrent update both committed')


if __name__ == '__main__':
    main()
