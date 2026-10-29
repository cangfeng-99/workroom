import io
import json
import sqlite3
import zipfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from django.db import connection
from django.test import override_settings
from django.utils import timezone

from apps.projects import local_backups as backups
from apps.projects.models import Delivery, Project, ReplyJob, Task, TaskClaim, WorkerHeartbeat

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def local_data(tmp_path):
    with override_settings(WORKROOM_MODE="local", DATA_DIR=tmp_path / "app"):
        workspace = tmp_path / "code"
        memory = workspace / ".workroom"
        memory.mkdir(parents=True)
        (memory / "MEMORY.md").write_text("长期记忆：必须本人确认。", encoding="utf-8")
        (workspace / "main.py").write_text('print("source untouched")', encoding="utf-8")
        project = Project.objects.create(
            name="备份项目",
            goal_title="从零到一",
            workspace_path=str(workspace),
            workspace_authorized_at=timezone.now(),
        )
        task = Task.objects.create(project=project, title="实现登录", acceptance="前后端验证")
        yield project, task, workspace


def edited_archive(path, changes):
    output = io.BytesIO()
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(output, "w") as dest:
        files = {name: source.read(name) for name in source.namelist()}
        files.update(changes)
        for name, value in files.items():
            dest.writestr(name, value)
    output.seek(0)
    return output


def test_complete_roundtrip_keeps_code_and_restores_memory_in_app_only(local_data):
    project, task, workspace = local_data
    # Delivery data is in the same consistent SQLite snapshot.
    Delivery.objects.create(
        task=task, summary="登录交付", body="核对", idempotency_key="backup-test"
    )
    archive = backups.export_backup()
    with zipfile.ZipFile(archive) as package:
        assert "database.sqlite3" in package.namelist()
        assert f"memories/{project.pk}/MEMORY.md" in package.namelist()
        assert not any(name.endswith("main.py") for name in package.namelist())
    with archive.open("rb") as stream:
        preview = backups.inspect_upload(stream)
    assert preview["counts"]["tasks"] == 1
    assert preview["counts"]["deliveries"] == 1
    assert preview["memory_files"] == 1
    Project.objects.filter(pk=project.pk).update(name="后来修改")
    Task.objects.filter(pk=task.pk).update(title="后来的任务")
    backups.schedule_restore(preview["token"])
    assert Project.objects.get(pk=project.pk).name == "后来修改"
    result = backups.apply_pending_restore()
    assert result["status"] == "success"
    project.refresh_from_db()
    task.refresh_from_db()
    assert project.name == "备份项目" and task.title == "实现登录"
    assert Delivery.objects.get(task=task).summary == "登录交付"
    recovered = Path(project.workspace_path)
    assert recovered.is_relative_to(Path(backups.data_dir()) / "recovered-workspaces")
    assert (recovered / ".workroom/MEMORY.md").read_text(encoding="utf-8").startswith("长期记忆")
    assert project.workspace_authorized_at is None
    assert (workspace / "main.py").read_text() == 'print("source untouched")'
    assert Path(result["safety_backup"]).is_file()
    with backups.export_backup().open("rb") as stream:
        assert backups.inspect_upload(stream)["memory_files"] == 1
    with Path(result["safety_backup"]).open("rb") as stream:
        before = backups.inspect_upload(stream)
    assert before["counts"]["tasks"] == 1
    assert backups.apply_pending_restore() is None


@pytest.mark.parametrize(
    "name",
    [
        "../outside.txt",
        "/abs.txt",
        "memories/1/../x",
        "memories/1/C:x",
        "memories/1/a\\x",
        "memories/1/CON",
        "memories/1/a.",
    ],
)
def test_unsafe_zip_paths_rejected_without_writes(local_data, name):
    archive = backups.export_backup()
    with pytest.raises(backups.BackupError):
        backups.inspect_upload(edited_archive(archive, {name: b"bad"}))
    assert not (Path(backups.data_dir()).parent / "outside.txt").exists()


def test_hash_tamper_unknown_format_and_duplicate_rejected(local_data):
    archive = backups.export_backup()
    with pytest.raises(backups.BackupError):
        backups.inspect_upload(edited_archive(archive, {"database.sqlite3": b"not sqlite"}))
    with zipfile.ZipFile(archive) as source:
        manifest = json.loads(source.read("manifest.json"))
    manifest["version"] = 999
    with pytest.raises(backups.BackupError):
        backups.inspect_upload(
            edited_archive(archive, {"manifest.json": json.dumps(manifest).encode()})
        )
    dup = edited_archive(archive, {})
    with zipfile.ZipFile(dup, "a") as out, pytest.warns(UserWarning):
        out.writestr("database.sqlite3", b"duplicate")
    dup.seek(0)
    with pytest.raises(backups.BackupError):
        backups.inspect_upload(dup)


def test_restore_failure_preserves_original_and_does_not_retry(local_data):
    project, _, _ = local_data
    archive = backups.export_backup()
    with archive.open("rb") as stream:
        token = backups.inspect_upload(stream)["token"]
    Project.objects.filter(pk=project.pk).update(name="必须保住")
    backups.schedule_restore(token)
    with patch.object(
        backups, "_replace_database", side_effect=sqlite3.OperationalError("simulated failure")
    ):
        result = backups.apply_pending_restore()
    assert result["status"] == "error"
    assert Project.objects.get(pk=project.pk).name == "必须保住"
    assert Path(result["safety_backup"]).exists()
    assert backups.apply_pending_restore() is None


@pytest.mark.parametrize("busy", ["job", "claim", "worker"])
def test_schedule_refuses_active_work(local_data, busy):
    project, task, _ = local_data
    archive = backups.export_backup()
    with archive.open("rb") as stream:
        token = backups.inspect_upload(stream)["token"]
    if busy == "job":
        ReplyJob.objects.create(project=project, prompt="never execute", status="queued")
    elif busy == "claim":
        TaskClaim.objects.create(task=task, expires_at=timezone.now() + timedelta(minutes=10))
    else:
        WorkerHeartbeat.objects.create(worker_id="busy", hostname="test")
    with pytest.raises(backups.BackupError, match="执行|Worker|任务|认领"):
        backups.schedule_restore(token)


def test_recheck_busy_on_startup_does_not_touch_data(local_data):
    project, _, _ = local_data
    archive = backups.export_backup()
    with archive.open("rb") as stream:
        token = backups.inspect_upload(stream)["token"]
    backups.schedule_restore(token)
    ReplyJob.objects.create(project=project, prompt="busy", status="running")
    assert backups.apply_pending_restore()["status"] == "error"
    assert ReplyJob.objects.get(project=project).status == "running"


def test_cancel_and_expired_token(local_data):
    archive = backups.export_backup()
    with archive.open("rb") as stream:
        token = backups.inspect_upload(stream)["token"]
    backups.schedule_restore(token)
    backups.cancel_restore()
    assert backups.apply_pending_restore() is None
    with patch.object(backups.time, "time", return_value=backups.time.time() + 90000):
        with pytest.raises(backups.BackupError, match="过期"):
            backups.preview(token)


def test_unapproved_memory_excluded_and_corrupt_file_rejected(local_data):
    project, _, _ = local_data
    project.workspace_authorized_at = None
    project.save(update_fields=["workspace_authorized_at"])
    archive = backups.export_backup()
    with archive.open("rb") as stream:
        assert backups.inspect_upload(stream)["memory_files"] == 0
    with pytest.raises(backups.BackupError):
        backups.inspect_upload(io.BytesIO(b"not zip"))


def test_mismatching_schema_is_rejected(local_data):
    archive = backups.export_backup()
    with connection.cursor() as cursor:
        cursor.execute("CREATE TABLE s135_schema_drift(id INTEGER)")
    try:
        with archive.open("rb") as stream, pytest.raises(backups.BackupError, match="版本|结构"):
            backups.inspect_upload(stream)
    finally:
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE s135_schema_drift")


def test_instance_lock_rejects_second_launcher(local_data):
    with backups.instance_lock(), pytest.raises(backups.BackupError, match="运行"):
        with backups.instance_lock():
            pytest.fail("second app must not start")


def test_upgrade_backup_only_for_existing_data_and_pending_migrations(local_data):
    with patch("django.db.migrations.executor.MigrationExecutor") as executor:
        executor.return_value.migration_plan.return_value = []
        assert backups.backup_before_migrate() is None
        executor.return_value.migration_plan.return_value = [("pending", False)]
        assert backups.backup_before_migrate().is_file()


def test_real_sqlite_backup_transaction_rolls_back_partial_copy(local_data, tmp_path):
    project, task, _ = local_data
    task.detail = "备份原内容" * 200000
    task.save(update_fields=["detail"])
    archive = backups.export_backup()
    source = tmp_path / "source.sqlite3"
    with zipfile.ZipFile(archive) as package:
        source.write_bytes(package.read("database.sqlite3"))
    Project.objects.filter(pk=project.pk).update(name="必须保留的新数据")

    def fail_partial(start, status, remaining, total):
        assert status != sqlite3.SQLITE_DONE and remaining > 0
        raise backups.BackupError("中断实际分页复制")

    with (
        patch.object(backups, "_backup_progress", side_effect=fail_partial),
        pytest.raises(backups.BackupError),
    ):
        backups._replace_database(source)
    assert Project.objects.get(pk=project.pk).name == "必须保留的新数据"
    assert Task.objects.get(pk=task.pk).detail == task.detail


def test_snapshot_jobs_and_tokens_are_not_resumed(local_data):
    from apps.projects.models import ToolToken

    project, task, _ = local_data
    job = ReplyJob.objects.create(project=project, prompt="never resume", status="queued")
    token = ToolToken.objects.create(project=project, name="old", token_hash="a" * 64)
    TaskClaim.objects.create(task=task, expires_at=timezone.now() - timedelta(days=1))
    archive = backups.export_backup()
    job.status = "cancelled"
    job.save(update_fields=["status"])
    with archive.open("rb") as stream:
        key = backups.inspect_upload(stream)["token"]
    backups.schedule_restore(key)
    assert backups.apply_pending_restore()["status"] == "success"
    job.refresh_from_db()
    token.refresh_from_db()
    assert job.status == "cancelled" and token.revoked_at is not None
    assert TaskClaim.objects.get(task=task).status == "released"


def test_inspected_archive_cannot_be_swapped_after_confirmation(local_data):
    archive = backups.export_backup()
    with archive.open("rb") as stream:
        token = backups.inspect_upload(stream)["token"]
    backups.schedule_restore(token)
    backups._import_path(token).write_bytes(b"tampered after confirm")
    assert backups.apply_pending_restore()["status"] == "error"
    assert Project.objects.get().name == "备份项目"


def test_symlink_archive_entry_rejected(local_data):
    archive = backups.export_backup()
    stream = edited_archive(archive, {})
    with zipfile.ZipFile(stream, "a") as package:
        link = zipfile.ZipInfo("memories/1/link")
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        package.writestr(link, "/outside")
    stream.seek(0)
    with pytest.raises(backups.BackupError, match="链接"):
        backups.inspect_upload(stream)


def test_archive_size_and_memory_file_limits(local_data):
    with patch.object(backups, "MAX_ARCHIVE", 10), pytest.raises(backups.BackupError):
        backups.inspect_upload(io.BytesIO(b"x" * 11))
    _, _, workspace = local_data
    with patch.object(backups, "MAX_MEMORY_FILE", 1), pytest.raises(backups.BackupError):
        backups.export_backup()
    assert (workspace / ".workroom/MEMORY.md").exists()


def test_temporary_import_cleanup_never_removes_scheduled_backup(local_data):
    archive = backups.export_backup()
    with archive.open("rb") as stream:
        first = backups.inspect_upload(stream)["token"]
    backups.schedule_restore(first)
    for _ in range(9):
        with archive.open("rb") as stream:
            backups.inspect_upload(stream)
    assert backups._import_path(first).exists()
    assert len(list((backups.data_dir() / "backup-imports").glob("*.zip"))) == 8
    assert archive.exists()
