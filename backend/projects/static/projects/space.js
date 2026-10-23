/* Project space helpers: instruction templates and the in-page folder picker.
   Everything is optional; without JavaScript the forms still submit. */
(function () {
  'use strict';

  var TEMPLATES = {
    delivery: '协作约定：\n- 改动前先说明目标与影响范围；\n- 小步提交，每步运行相关检查；\n- 评审时附上验证命令与结果；\n- 未接入的 AI、连接器与自动执行不写入完成状态。',
    content: '内容约定：\n- 先列提纲，再补素材与来源；\n- 区分事实、推断与待确认项；\n- 交付前统一术语、日期与链接；\n- 不复制未授权的品牌、图片或私有文字。',
    learning: '学习约定：\n- 每次只推进一个可验证的小目标；\n- 记录问题、证据与下一步；\n- 每周回看已完成与未完成项；\n- 不把计划当成已完成的进度。'
  };

  function connectTemplates() {
    var buttons = document.querySelectorAll('[data-template]');
    var field = document.getElementById('id_instructions');
    if (!buttons.length || !field) {
      return;
    }
    var selected = new URLSearchParams(window.location.search).get('template');
    if (!field.value && Object.prototype.hasOwnProperty.call(TEMPLATES, selected)) {
      field.value = TEMPLATES[selected];
    }
    Array.prototype.forEach.call(buttons, function (button) {
      button.addEventListener('click', function () {
        var text = TEMPLATES[button.getAttribute('data-template')];
        if (!text) {
          return;
        }
        field.value = text;
        field.dispatchEvent(new Event('input', { bubbles: true }));
        field.focus();
      });
    });
  }

  function connectPicker() {
    var dialog = document.getElementById('folder-picker');
    var pathInput = document.getElementById('id_setup_path');
    if (!dialog || !pathInput || typeof dialog.showModal !== 'function'
      || !window.fetch || !window.AbortController) {
      return;
    }

    var list = document.getElementById('picker-list');
    var statusEl = document.getElementById('picker-status');
    var currentEl = document.getElementById('picker-current');
    var typedPath = document.getElementById('picker-path');
    var upButton = document.getElementById('picker-up');
    var chooseButton = document.getElementById('picker-choose');
    var closeButton = document.getElementById('picker-close');
    var pathForm = document.getElementById('picker-path-form');
    var openButtons = document.querySelectorAll('[data-pick-folder]');
    var TIMEOUT_MS = 8000;

    var ERRORS = {
      authentication_required: '请先登录后再选择文件夹。',
      invalid_path: '路径无效：请输入本机绝对目录，不能是相对路径、UNC、设备路径或包含 .. 。',
      not_found: '找不到这个目录，可能已被移动或删除。',
      not_a_directory: '该路径不是文件夹。',
      unsafe_path: '出于安全考虑，链接、reparse 或不可访问的目录不能浏览。',
      unreadable: '无法读取这个目录的列表。'
    };

    var state = {
      path: '',
      parent: '',
      busy: false,
      seq: 0,
      controller: null
    };

    function setStatus(text, isError) {
      statusEl.textContent = text || '';
      statusEl.classList.toggle('error', Boolean(isError));
    }

    function setBusy(busy) {
      state.busy = busy;
      list.setAttribute('aria-busy', busy ? 'true' : 'false');
      chooseButton.disabled = busy || !state.path;
      if (busy) {
        setStatus('正在加载…', false);
      }
    }

    function showError(message, retryPath) {
      state.path = '';
      state.parent = '';
      list.textContent = '';
      chooseButton.disabled = true;
      setStatus('', true);
      statusEl.appendChild(document.createTextNode(message + ' '));
      var retry = document.createElement('button');
      retry.type = 'button';
      retry.className = 'secondary';
      retry.textContent = '重试';
      retry.addEventListener('click', function () {
        load(retryPath);
      });
      statusEl.appendChild(retry);
    }

    function addEntry(entry) {
      var item = document.createElement('li');
      var button = document.createElement('button');
      button.type = 'button';
      button.textContent = entry.name;
      button.title = entry.path;
      button.addEventListener('click', function () {
        load(entry.path);
      });
      item.appendChild(button);
      list.appendChild(item);
    }

    function render(data) {
      state.path = data.path || '';
      state.parent = data.parent || '';
      currentEl.textContent = state.path || '驱动器';
      typedPath.value = state.path;
      list.textContent = '';

      var entries = (state.path ? data.directories : data.drives) || [];
      entries.forEach(addEntry);
      if (!entries.length) {
        var empty = document.createElement('li');
        empty.className = 'picker-empty';
        empty.textContent = state.path
          ? '此目录没有可进入的子文件夹。'
          : '没有找到可用的驱动器。';
        list.appendChild(empty);
      }

      upButton.disabled = !state.path;
      if (!state.path) {
        setStatus('请选择一个驱动器，或输入完整目录路径。', false);
      } else if (data.truncated) {
        setStatus('文件夹较多，仅显示前 100 个；可输入路径直接打开其余目录。', false);
      } else {
        setStatus('', false);
      }
      chooseButton.disabled = !state.path;
    }

    function load(path) {
      if (state.busy) {
        return;
      }
      state.seq += 1;
      var seq = state.seq;
      var controller = new AbortController();
      state.controller = controller;
      var timer = window.setTimeout(function () {
        controller.abort();
      }, TIMEOUT_MS);
      setBusy(true);

      var tokenInput = dialog.querySelector('input[name="csrfmiddlewaretoken"]')
        || document.querySelector('input[name="csrfmiddlewaretoken"]');
      var body = new URLSearchParams();
      body.set('path', path);

      fetch('/workspace/folders/', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'X-CSRFToken': tokenInput ? tokenInput.value : ''
        },
        body: body,
        signal: controller.signal
      })
        .then(function (response) {
          return response.json().catch(function () {
            return {};
          }).then(function (data) {
            if (!response.ok) {
              var error = new Error(data.error || 'http_' + response.status);
              error.code = data.error;
              throw error;
            }
            return data;
          });
        })
        .then(function (data) {
          if (seq !== state.seq) {
            return;
          }
          render(data);
        })
        .catch(function (error) {
          if (seq !== state.seq) {
            return;
          }
          if (error && error.name === 'AbortError') {
            showError('加载超时（8 秒），请重试。', path);
            return;
          }
          var code = error && error.code;
          showError(ERRORS[code] || '无法加载目录，请重试。', path);
        })
        .finally(function () {
          window.clearTimeout(timer);
          if (seq === state.seq) {
            state.controller = null;
            state.busy = false;
            setBusy(false);
          }
        });
    }

    function stopPending() {
      state.seq += 1;
      if (state.controller) {
        state.controller.abort();
        state.controller = null;
      }
      state.busy = false;
      setBusy(false);
    }

    function openPicker() {
      if (!dialog.open) {
        dialog.showModal();
      }
      typedPath.value = '';
      list.textContent = '';
      load('');
    }

    Array.prototype.forEach.call(openButtons, function (button) {
      button.addEventListener('click', openPicker);
    });

    dialog.addEventListener('close', stopPending);
    dialog.addEventListener('cancel', stopPending);

    closeButton.addEventListener('click', function () {
      dialog.close();
    });

    upButton.addEventListener('click', function () {
      if (state.busy) {
        return;
      }
      load(state.parent || '');
    });

    pathForm.addEventListener('submit', function (event) {
      event.preventDefault();
      if (state.busy) {
        return;
      }
      var value = typedPath.value.trim();
      if (!value) {
        load('');
        return;
      }
      load(value);
    });

    chooseButton.addEventListener('click', function () {
      if (!state.path || state.busy) {
        return;
      }
      pathInput.value = state.path;
      pathInput.dispatchEvent(new Event('input', { bubbles: true }));
      dialog.close();
      pathInput.focus();
    });
  }

  function connectMembers() {
    var rows = document.querySelector('[data-member-rows]');
    var add = document.querySelector('[data-add-member]');
    var template = document.getElementById('empty-member-row');
    var total = document.querySelector('[name="members-TOTAL_FORMS"]');
    var count = document.querySelector('[data-member-count]');
    if (!rows || !add || !template || !total) return;
    function refresh() {
      var items = rows.querySelectorAll('.member-row');
      Array.prototype.forEach.call(items, function (row, index) {
        Array.prototype.forEach.call(row.querySelectorAll('[name], [id], [for]'), function (element) {
          ['name', 'id', 'for'].forEach(function (attribute) {
            var value = element.getAttribute(attribute);
            if (value) element.setAttribute(attribute, value.replace(/members-(?:\d+|__prefix__)-/g, 'members-' + index + '-'));
          });
        });
        row.querySelector('[data-remove-member]').hidden = false;
      });
      total.value = String(items.length);
      add.disabled = items.length >= 10;
      if (count) count.textContent = items.length + ' / 10 个成员位置';
    }
    add.hidden = false;
    add.addEventListener('click', function () {
      if (rows.querySelectorAll('.member-row').length >= 10) return;
      rows.appendChild(template.content.cloneNode(true));
      refresh();
      rows.lastElementChild.querySelector('select').focus();
    });
    rows.addEventListener('click', function (event) {
      var remove = event.target.closest('[data-remove-member]');
      if (!remove || !rows.contains(remove)) return;
      remove.closest('.member-row').remove();
      refresh();
      add.focus();
    });
    refresh();
  }

  function init() {
    connectTemplates();
    connectPicker();
    connectMembers();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
