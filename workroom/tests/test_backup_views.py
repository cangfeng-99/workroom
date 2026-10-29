import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings

from apps.projects import local_backups as backups
from apps.projects.models import Project

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def backup_ui(tmp_path, client):
    with override_settings(WORKROOM_MODE="local", DATA_DIR=tmp_path / "app"):
        Project.objects.create(name="个人项目", goal_title="先交付")
        yield client


def test_local_export_preview_confirmation_schedule_cancel(backup_ui):
    client = backup_ui
    page = client.get("/backups/")
    assert page.status_code == 200
    assert "备份与恢复" in client.get("/").content.decode()
    response = client.post("/backups/", {"action": "export"})
    assert response.status_code == 200
    assert response["Content-Type"] == "application/zip"
    body = b"".join(response.streaming_content)
    response.close()
    reply = client.post(
        "/backups/", {"action": "inspect", "archive": SimpleUploadedFile("backup.zip", body)}
    )
    assert reply.status_code == 302
    page = client.get("/backups/").content.decode()
    assert "备份检查通过" in page and "记忆文件" in page
    assert "北京时间" in page
    token = client.session["backup_preview"]
    assert client.post("/backups/", {"action": "schedule", "token": token}).status_code == 400
    assert not backups.restore_state().get("pending")
    assert (
        client.post(
            "/backups/", {"action": "schedule", "token": "0" * 32, "confirm_replace": "yes"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/backups/", {"action": "schedule", "token": token, "confirm_replace": "yes"}
        ).status_code
        == 302
    )
    assert "已安排下次启动恢复" in client.get("/backups/").content.decode()
    assert Project.objects.get().name == "个人项目"
    assert client.post("/backups/", {"action": "cancel"}).status_code == 302
    assert not backups.restore_state().get("pending")


def test_bad_upload_keeps_data_and_displays_error(backup_ui):
    response = backup_ui.post(
        "/backups/", {"action": "inspect", "archive": SimpleUploadedFile("wrong.zip", b"bad")}
    )
    assert response.status_code == 400
    assert "原数据未更改" in response.content.decode()
    assert Project.objects.get().name == "个人项目"
    assert backup_ui.post("/backups/", {"action": "inspect"}).status_code == 400


def test_csrf_required_and_server_does_not_expose_backup(backup_ui):
    assert backup_ui.get("/backups/", REMOTE_ADDR="203.0.113.7").status_code == 404
    csrf = Client(enforce_csrf_checks=True)
    assert csrf.post("/backups/", {"action": "export"}).status_code == 403
    user = get_user_model().objects.create_user(username="backup-server-user")
    backup_ui.force_login(user)
    with override_settings(WORKROOM_MODE="server"):
        assert backup_ui.get("/backups/").status_code == 404
        assert backup_ui.post("/backups/", {"action": "export"}).status_code == 404
        assert 'href="/backups/"' not in backup_ui.get("/").content.decode()


def test_upload_size_and_unknown_action_rejected(backup_ui):
    assert backup_ui.post("/backups/", {"action": "unknown"}).status_code == 400
    with override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=10):
        response = backup_ui.post("/backups/", {"action": "inspect", "oversize": "x" * 100})
        assert response.status_code == 400


def test_bad_new_file_does_not_leave_old_success_preview(backup_ui):
    archive = backups.export_backup()
    with archive.open("rb") as stream:
        data = stream.read()
    backup_ui.post(
        "/backups/", {"action": "inspect", "archive": SimpleUploadedFile("old.zip", data)}
    )
    assert backup_ui.session.get("backup_preview")
    reply = backup_ui.post(
        "/backups/", {"action": "inspect", "archive": SimpleUploadedFile("bad.zip", b"invalid")}
    )
    assert reply.status_code == 400
    assert not backup_ui.session.get("backup_preview")
    assert "备份检查通过" not in reply.content.decode()


def test_corrupt_pending_record_is_visible_and_can_be_cancelled(backup_ui):
    pending = backups.data_dir() / "pending-restore.json"
    pending.write_text("{broken", encoding="utf-8")
    page = backup_ui.get("/backups/").content.decode()
    assert "恢复记录损坏" in page and "取消这次恢复" in page
    assert backup_ui.post("/backups/", {"action": "cancel"}).status_code == 302
    assert not pending.exists()
