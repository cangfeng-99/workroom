from pathlib import Path
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

import guide_content
from apps.projects import sample_projects
from apps.projects.models import AuditLog, LibraryEntry, Member, Project, ReplyJob, Task
from apps.projects.task_explanations import explanation, validate_prerequisites
from desktop_support import operation_lock

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def local_example(settings, tmp_path):
    settings.WORKROOM_MODE = "local"
    settings.DATA_DIR = tmp_path / "app"
    return settings.DATA_DIR


def test_guide_get_is_read_only_and_has_no_seed_side_effect(local_example, client):
    assert client.get("/guide/").status_code == 200
    assert Project.objects.count() == Task.objects.count() == ReplyJob.objects.count() == 0
    assert get_user_model().objects.count() == 0
    body = client.get("/guide/").content.decode()
    assert "使用指南" in body and "打开练习项目" in body
    assert "只读" in body and "不会自动派发" in body


def test_download_and_html_share_the_same_sections(local_example, client):
    reply = client.get("/guide/download/")
    assert reply.status_code == 200 and "attachment" in reply["Content-Disposition"]
    text = b"".join(reply.streaming_content).decode("utf-8")
    reply.close()
    assert text == guide_content.render_markdown()
    assert (Path(__file__).resolve().parents[1] / "docs/USER_GUIDE.md").read_text(
        encoding="utf-8"
    ) == text
    html = client.get("/guide/").content.decode()
    for section in guide_content.SECTIONS:
        assert section["title"] in text and section["title"] in html


def test_sample_has_real_dependencies_complete_instructions_and_no_fake_work(local_example):
    project, created = sample_projects.open_example()
    assert created and project.owner_id
    assert project.tasks.count() == 15
    assert project.tasks.filter(parent__isnull=False).first().title == "写清楚第一版要交付什么"
    assert project.tasks.filter(status="todo").count() == 15
    assert project.tasks.filter(start_date__isnull=False).count() == 0
    assert not project.workspace_path and project.workspace_authorized_at is None
    assert not project.members.exclude(kind="human").exists()
    assert not project.members.exclude(key_ciphertext="").exists()
    assert not ReplyJob.objects.exists()
    assert project.tasks.filter(deliveries__isnull=False).count() == 0
    for task in project.tasks.all():
        assert task.detail and task.acceptance and task.guide["steps"] and task.guide["outcomes"]
        assert task.guide["frontend"] and task.guide["backend"]
        validate_prerequisites(task, task.prerequisites.all())
        assert not task.prerequisites.exclude(project=project).exists()
    dependent = project.tasks.get(title="做出登录页面和退出入口")
    assert explanation(dependent)["primary"]["kind"] == "prerequisite"
    code_task = project.tasks.get(title="设计用户与待办数据")
    assert not code_task.execution_spec["baseline"]
    assert list(code_task.prerequisites.values_list("title", flat=True)) == [
        "准备 Django 项目和检查入口"
    ]
    assert any(b["kind"] == "package" for b in explanation(code_task)["blockers"])


def test_reopen_preserves_user_edits_even_after_rename(local_example):
    original, _ = sample_projects.open_example()
    original.name = "我修改后的项目"
    original.goal_title = "保留我的目标"
    original.save(update_fields=["name", "goal_title"])
    task = original.tasks.filter(parent__isnull=False).first()
    task.detail = "不能重置我的内容"
    task.save(update_fields=["detail"])
    reopened, created = sample_projects.open_example()
    assert not created and reopened.pk == original.pk
    assert reopened.name == original.name and reopened.goal_title == original.goal_title
    task.refresh_from_db()
    assert task.detail == "不能重置我的内容" and reopened.tasks.count() == 15


def test_normal_same_name_project_is_never_overwritten(local_example):
    existing = Project.objects.create(name=sample_projects.NAME, goal_title="真正工作")
    example, _ = sample_projects.open_example()
    existing.refresh_from_db()
    assert example.pk != existing.pk and existing.goal_title == "真正工作"
    assert existing.tasks.count() == 0


def test_sample_is_scoped_to_owner(local_example):
    first = get_user_model().objects.create_user(username="first")
    second = get_user_model().objects.create_user(username="second")
    a, _ = sample_projects.open_example(first)
    b, _ = sample_projects.open_example(second)
    assert a.pk != b.pk and a.owner_id == first.pk and b.owner_id == second.pk
    assert a.tasks.count() == b.tasks.count() == 15


def test_failed_creation_rolls_back_everything_including_first_local_owner(local_example):
    with patch.object(Task.objects, "create", side_effect=RuntimeError("simulated task failure")):
        with pytest.raises(RuntimeError):
            sample_projects.open_example()
    assert (
        not Project.objects.exists() and not Member.objects.exists() and not Task.objects.exists()
    )
    assert not LibraryEntry.objects.exists() and not AuditLog.objects.exists()
    assert not get_user_model().objects.exists()


def test_creation_releases_gate_after_failure(local_example):
    with patch.object(Task.objects, "create", side_effect=RuntimeError("fail")):
        with pytest.raises(RuntimeError):
            sample_projects.open_example()
    assert sample_projects.open_example()[1]


def test_delete_then_only_explicit_post_recreates_sample(local_example, client):
    reply = client.post("/examples/starter/")
    assert reply.status_code == 302
    first = Project.objects.get()
    assert client.post(f"/p/{first.pk}/delete/").status_code == 302
    assert client.get("/guide/").status_code == 200 and not Project.objects.exists()
    assert client.post("/examples/starter/").status_code == 302
    assert Project.objects.get().pk != first.pk and Task.objects.count() == 15


def test_sample_endpoint_is_post_only_and_csrf_protected(local_example, client):
    assert client.get("/examples/starter/").status_code == 405
    assert Client(enforce_csrf_checks=True).post("/examples/starter/").status_code == 403
    assert not Project.objects.exists()


@pytest.mark.parametrize("route", ["/guide/", "/guide/download/", "/examples/starter/"])
def test_server_rejects_single_user_guide_and_sample(local_example, client, settings, route):
    user = get_user_model().objects.create_user(username="server-owner")
    client.force_login(user)
    settings.WORKROOM_MODE = "server"
    reply = client.post(route) if "examples" in route else client.get(route)
    assert reply.status_code == 404 and not Project.objects.exists()


@pytest.mark.parametrize("route", ["/guide/", "/guide/download/", "/examples/starter/"])
def test_non_loopback_rejected(local_example, client, route):
    reply = (
        client.post(route, REMOTE_ADDR="203.0.113.7")
        if "examples" in route
        else client.get(route, REMOTE_ADDR="203.0.113.7")
    )
    assert reply.status_code == 404 and not Project.objects.exists()


def test_busy_data_gate_has_clear_error_and_no_partial_example(local_example, client):
    with operation_lock(local_example):
        reply = client.post("/examples/starter/")
    assert reply.status_code == 409
    assert "稍后重试" in reply.content.decode() and not Project.objects.exists()


def test_home_and_workspace_link_to_guide(local_example, client):
    assert 'href="/guide/' in client.get("/").content.decode()
    reply = client.post("/examples/starter/")
    assert reply.status_code == 302
    project = Project.objects.get()
    # rail 会带 ?from=<pk>，让指南页能返回工作区
    assert 'href="/guide/' in client.get(f"/p/{project.pk}/").content.decode()
