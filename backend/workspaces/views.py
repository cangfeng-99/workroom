"""Folder workspace page: authorize a real folder, browse, edit, save.

The authorized root lives in the server-side session together with a random
``grant_id``. Every list/read/create/save re-checks that session, and writes
must repeat the current ``grant_id`` so a page rendered before a root switch
cannot write into the newly authorized folder. ``GET`` never writes and never
opens the native dialog. The legacy demo key is never read.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from workspaces.forms import GrantForm, NewFileForm, SaveForm
from workspaces.grants import (
    LEGACY_SESSION_KEY,
    clear_grant,
    get_grant,
    set_grant,
)
from workspaces.picker import PickerError, browse
from workspaces.services import Workspace, WorkspaceError

UNKNOWN_ACTION = '无法识别的操作，请刷新页面后重试。'
NEED_GRANT = '请先授权一个本机文件夹，然后再操作文件。'
STALE_GRANT = '授权已变更或页面已过期，本次操作未写入任何文件。请刷新页面后重试。'
FORM_INVALID = '请检查填写内容（文件名不能为空，内容可为空）。'

_ERROR_TEXT = {
    'invalid_root': '该路径不是可用的本机文件夹（需为已存在的普通目录，不能是链接、UNC 或设备路径）。',
    'workspace_not_initialized': '已授权的文件夹当前不可用，请重新授权。',
    'invalid_name': '路径或文件名无效：不能包含 .. 、反斜杠、冒号、控制字符，也不能以空格或点结尾。',
    'unsupported_type': '该类型不是可编辑文本；仅支持常见文本和代码文件。',
    'not_found': '找不到这个文件或目录，可能已被移动或删除。',
    'not_a_file': '该名称不是普通文件。',
    'not_a_directory': '该名称不是目录。',
    'unsafe_path': '出于安全考虑，链接、reparse、隐藏或多硬链文件不能访问。',
    'file_too_large': '文件超过 64 KiB，无法读取或保存。',
    'content_too_large': '内容超过 64 KiB，请缩短后重试。',
    'invalid_content': '内容必须是文本。',
    'invalid_encoding': '文件不是 UTF-8 文本，无法显示。',
    'binary_content': '文件包含二进制内容（NUL 字节），不是可编辑文本。',
    'invalid_revision': '缺少读取时的版本信息，请重新读取文件后再保存。',
    'conflict': '文件在读取后已被外部修改，保存已取消；你的编辑仍保留在下方，请重新读取后再保存。',
    'already_exists': '同名文件已存在，新建不会覆盖它，请换一个文件名。',
    'create_failed': '新建文件失败，请稍后重试；未覆盖任何已有文件。',
    'save_failed': '保存失败，原文件未被替换，你的编辑仍保留在下方。',
    'read_failed': '读取失败，请稍后重试。',
}

_PICK_NOTICE = (
    '请点击“选择文件夹…”打开页面内目录选择器；也可以直接输入完整路径后授权。'
    '此操作没有授权任何文件夹。'
)


def _workspace(grant: dict[str, str]) -> Workspace:
    return Workspace(Path(grant['root']))


def _message(exc: WorkspaceError) -> str:
    return _ERROR_TEXT.get(exc.code, '操作失败，请稍后重试。')


def _parent(directory: str) -> str:
    return directory.rsplit('/', 1)[0] if '/' in directory else ''


def _render(
    request,
    *,
    grant: dict[str, str] | None,
    error: str = '',
    notice: str = '',
    entries: list[dict[str, object]] | None = None,
    current_dir: str = '',
    save_form: SaveForm | None = None,
    new_form: NewFileForm | None = None,
    grant_path: str = '',
    status: int = 200,
):
    grant_id = grant['grant_id'] if grant else ''
    if grant and entries is None:
        entries = _entries(grant, current_dir)
    return render(
        request,
        'workspaces/workspace.html',
        {
            'granted': bool(grant),
            'root_path': grant['root'] if grant else '',
            'grant_id': grant_id,
            'root_display': grant['root'] if grant else '',
            'entries': entries or [],
            'current_dir': current_dir,
            'parent_dir': _parent(current_dir),
            'save_form': save_form,
            'new_form': new_form
            or NewFileForm(initial={'grant_id': grant_id, 'directory': current_dir}),
            'grant_form': GrantForm(initial={'path': grant_path}),
            'grant_path': grant_path,
            'error': error,
            'notice': notice,
        },
        status=status,
    )


@never_cache
@login_required
@require_http_methods(['GET', 'POST'])
def workspace_page(request):
    grant = get_grant(request)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'grant':
            return _grant_folder(request)
        if action == 'pick':
            # Legacy form target kept only for stale pages: answer immediately,
            # never start an OS dialog, never grant or change the session.
            return _render(request, grant=grant, notice=_PICK_NOTICE)
        if not grant:
            return _render(request, grant=None, error=NEED_GRANT, status=403)
        if action == 'revoke':
            clear_grant(request)
            return redirect('workspaces:workspace')
        if action == 'save':
            return _save_file(request, grant)
        if action == 'create':
            return _create_file(request, grant)
        return _render(request, grant=grant, error=UNKNOWN_ACTION, status=400)

    return _read_page(request, grant)


def _grant_folder(request):
    form = GrantForm(request.POST)
    if not form.is_valid():
        return _render(
            request, grant=get_grant(request), error=FORM_INVALID, grant_path=request.POST.get('path', ''),
            status=400,
        )
    path = form.cleaned_data['path']
    try:
        Workspace(Path(path)).validate_root()
    except WorkspaceError as exc:
        return _render(
            request, grant=get_grant(request), error=_message(exc), grant_path=path, status=400
        )
    except (TypeError, ValueError):
        return _render(
            request, grant=get_grant(request), error=_message(WorkspaceError('invalid_root')),
            grant_path=path, status=400,
        )
    # Authorization itself never creates folders or welcome files.
    request.session.pop(LEGACY_SESSION_KEY, None)
    request.session.cycle_key()
    set_grant(request, str(Path(path)), uuid.uuid4().hex)
    return redirect('workspaces:workspace')


@never_cache
@require_POST
def folder_list(request):
    """Return folder names/paths for the page dialog; never reads file contents."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'authentication_required'}, status=401)
    try:
        data = browse(request.POST.get('path', ''))
    except PickerError as exc:
        return JsonResponse({'error': exc.code}, status=400)
    return JsonResponse(data)


def _read_page(request, grant):
    if not grant:
        return _render(request, grant=None)

    workspace = _workspace(grant)
    current_dir = request.GET.get('dir', '')
    selected = request.GET.get('file', '')
    error = ''
    notice = ''
    entries: list[dict[str, object]] = []
    save_form = None

    try:
        entries = workspace.list_directory(current_dir)
    except WorkspaceError as exc:
        error = _message(exc)
        current_dir = ''

    if selected:
        try:
            content, revision = workspace.read_document(selected)
        except WorkspaceError as exc:
            error = _message(exc)
        else:
            save_form = SaveForm(
                initial={
                    'grant_id': grant['grant_id'],
                    'path': selected,
                    'revision': revision,
                    'content': content,
                }
            )
            notice = f'已读取：{selected}'

    return _render(
        request,
        grant=grant,
        error=error,
        notice=notice,
        entries=entries,
        current_dir=current_dir,
        save_form=save_form,
    )


def _save_file(request, grant):
    form = SaveForm(request.POST)
    directory = request.POST.get('directory', '')
    if not form.is_valid():
        return _render(
            request,
            grant=grant,
            error=FORM_INVALID,
            entries=_entries(grant, directory),
            current_dir=directory,
            save_form=form,
            status=400,
        )
    if form.cleaned_data['grant_id'] != grant['grant_id']:
        return _render(
            request,
            grant=grant,
            error=STALE_GRANT,
            entries=_entries(grant, directory),
            current_dir=directory,
            save_form=form,
            status=403,
        )
    path = form.cleaned_data['path']
    try:
        _workspace(grant).save_text(path, form.cleaned_data['content'], form.cleaned_data['revision'])
    except WorkspaceError as exc:
        return _render(
            request,
            grant=grant,
            error=_message(exc),
            entries=_entries(grant, directory),
            current_dir=directory,
            save_form=form,
            status=400,
        )
    messages.success(request, f'已保存：{path}')
    if '/' in path:
        directory = path.rsplit('/', 1)[0]
        return redirect(f'/workspace/?dir={quote(directory)}&file={quote(path)}')
    return redirect(f'/workspace/?file={quote(path)}')


def _create_file(request, grant):
    form = NewFileForm(request.POST)
    directory = request.POST.get('directory', '')
    if not form.is_valid():
        return _render(
            request,
            grant=grant,
            error=FORM_INVALID,
            entries=_entries(grant, directory),
            current_dir=directory,
            new_form=form,
            status=400,
        )
    if form.cleaned_data['grant_id'] != grant['grant_id']:
        return _render(
            request,
            grant=grant,
            error=STALE_GRANT,
            entries=_entries(grant, directory),
            current_dir=directory,
            new_form=form,
            status=403,
        )
    directory = form.cleaned_data['directory']
    name = form.cleaned_data['name']
    path = f'{directory}/{name}' if directory else name
    try:
        _workspace(grant).create_text(path, form.cleaned_data['content'])
    except WorkspaceError as exc:
        return _render(
            request,
            grant=grant,
            error=_message(exc),
            entries=_entries(grant, directory),
            current_dir=directory,
            new_form=form,
            status=400,
        )
    messages.success(request, f'已创建：{path}')
    return redirect(f'/workspace/?dir={quote(directory)}' if directory else '/workspace/')


def _entries(grant, directory: str) -> list[dict[str, object]]:
    try:
        return _workspace(grant).list_directory(directory)
    except WorkspaceError:
        return []
