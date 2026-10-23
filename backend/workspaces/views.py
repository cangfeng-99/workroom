"""Browser page for the fixed local demo workspace.

The root always comes from ``settings.WORKSPACE_ROOT``; the browser can only
choose a file name. Authorization lives in the server-side session and is
checked on every read, list, and write.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from workspaces.forms import NewFileForm
from workspaces.services import Workspace, WorkspaceError

SESSION_KEY = 'workspace_grant_root'
UNKNOWN_ACTION = '无法识别的操作，请刷新页面后重试。'
NEED_GRANT = '请先授权本机演示工作区，然后再操作文件。'
FORM_INVALID = '请填写文件名（内容可以为空）。'

_ERROR_TEXT = {
    'invalid_root': '工作区目录不可用，请联系维护者。',
    'workspace_not_initialized': '工作区尚未初始化，请先授权。',
    'invalid_name': '文件名无效，只能使用当前目录下的 .txt 或 .md 文件名。',
    'unsupported_type': '只支持 .txt 和 .md 文件。',
    'not_found': '找不到这个文件，可能已被移动或删除。',
    'not_a_file': '该名称不是普通文件。',
    'unsafe_path': '出于安全考虑，链接文件或特殊路径不能访问。',
    'file_too_large': '文件超过 64 KiB，无法读取。',
    'content_too_large': '内容超过 64 KiB，请缩短后重试。',
    'invalid_content': '内容必须是文本。',
    'invalid_encoding': '文件不是 UTF-8 文本，无法显示。',
    'already_exists': '同名文件已存在，请换一个文件名。',
    'create_failed': '创建文件失败，请稍后重试。',
    'read_failed': '读取文件失败，请稍后重试。',
}


def _root() -> Path:
    return Path(settings.WORKSPACE_ROOT)


def _is_granted(request) -> bool:
    return request.session.get(SESSION_KEY) == str(_root())


def _display_root() -> str:
    root = _root()
    try:
        return root.relative_to(settings.PROJECT_ROOT).as_posix()
    except ValueError:
        return root.name


def _message(exc: WorkspaceError) -> str:
    return _ERROR_TEXT.get(exc.code, '操作失败，请稍后重试。')


def _render(
    request,
    *,
    granted: bool,
    error: str = '',
    notice: str = '',
    files: list[str] | None = None,
    selected: str = '',
    content: str = '',
    form: NewFileForm | None = None,
    status: int = 200,
):
    return render(
        request,
        'workspaces/workspace.html',
        {
            'granted': granted,
            'root_display': _display_root(),
            'files': files or [],
            'selected': selected,
            'content': content,
            'form': form or NewFileForm(),
            'error': error,
            'notice': notice,
        },
        status=status,
    )


@never_cache
@require_http_methods(['GET', 'POST'])
def workspace_page(request):
    granted = _is_granted(request)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'grant':
            try:
                Workspace(_root()).initialize_demo()
            except WorkspaceError as exc:
                return _render(request, granted=granted, error=_message(exc), status=400)
            request.session[SESSION_KEY] = str(_root())
            return redirect('workspaces:workspace')
        if not granted:
            return _render(request, granted=False, error=NEED_GRANT, status=403)
        if action == 'revoke':
            request.session.pop(SESSION_KEY, None)
            return redirect('workspaces:workspace')
        if action == 'create':
            form = NewFileForm(request.POST)
            if not form.is_valid():
                return _failed_create(request, FORM_INVALID, form)
            try:
                Workspace(_root()).create_text(form.cleaned_data['name'], form.cleaned_data['content'])
            except WorkspaceError as exc:
                return _failed_create(request, _message(exc), form)
            messages.success(request, f'已创建：{form.cleaned_data["name"]}')
            return redirect('workspaces:workspace')
        return _failed_create(request, UNKNOWN_ACTION, None)

    if not granted:
        return _render(request, granted=False)

    files, error = _safe_list()
    selected = request.GET.get('file', '')
    content = ''
    notice = ''
    if selected:
        try:
            content = Workspace(_root()).read_text(selected)
            notice = f'已读取：{selected}'
        except WorkspaceError as exc:
            error = _message(exc)
            selected = ''
    return _render(
        request,
        granted=True,
        error=error,
        notice=notice,
        files=files,
        selected=selected,
        content=content,
    )


def _failed_create(request, error: str, form: NewFileForm | None):
    files, list_error = _safe_list()
    return _render(
        request,
        granted=True,
        error=error or list_error,
        files=files,
        form=form,
        status=400,
    )


def _safe_list() -> tuple[list[str], str]:
    try:
        return Workspace(_root()).list_files(), ''
    except WorkspaceError as exc:
        return [], _message(exc)
