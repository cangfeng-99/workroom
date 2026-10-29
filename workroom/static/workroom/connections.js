(function () {
  'use strict';
  var list = document.querySelector('[data-connection-list]');
  if (!list) { return; }
  var feedback = document.querySelector('[data-connect-feedback]');
  var scope = document.querySelector('[data-connection-scope]');
  var deadline = 0;
  var pollTimer;
  function show(message, error) {
    feedback.textContent = message;
    feedback.hidden = false;
    feedback.classList.toggle('is-error', Boolean(error));
  }
  function poll() {
    if (Date.now() > deadline) { return; }
    if (document.hidden) { pollTimer = window.setTimeout(poll, 5000); return; }
    fetch(list.dataset.statusUrl, {cache: 'no-store', credentials: 'same-origin'})
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (data) {
        if (!data) { return; }
        data.instances.forEach(function (instance) {
          var row = list.querySelector('[data-member="' + instance.id + '"]');
          if (row && instance.last_connected_at) {
            var state = row.querySelector('[data-connection-state]');
            state.textContent = '凭据已验证';
            state.classList.add('is-connected');
            state.classList.remove('is-pending');
          }
        });
      }).catch(function () {}).finally(function () { pollTimer = window.setTimeout(poll, 5000); });
  }
  function startPolling() {
    deadline = Date.now() + 120000;
    window.clearTimeout(pollTimer);
    poll();
  }
  document.querySelectorAll('[data-open-advanced]').forEach(function (link) {
    link.addEventListener('click', function () { document.getElementById('advanced-connection').open = true; });
  });
  document.querySelectorAll('[data-quick-connect]').forEach(function (form) {
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      var button = form.querySelector('button');
      var row = form.closest('[data-provider]');
      var state = row.querySelector('[data-connection-state]');
      if (button.disabled) { return; }
      var idle = button.textContent;
      var body = new FormData(form);
      body.set('scope', scope ? scope.value : 'read');
      button.disabled = true;
      button.textContent = '正在保存…';
      form.setAttribute('aria-busy', 'true');
      var controller = new AbortController();
      var timer = window.setTimeout(function () { controller.abort(); }, 15000);
      fetch(form.action, {method: 'POST', body: body, credentials: 'same-origin', headers: {'Accept':'application/json'}, signal: controller.signal})
        .then(function (response) {
          if (!response.ok) {
            return response.json().catch(function () { return {error: '连接未完成，请刷新页面后重试。'}; }).then(function (data) { throw new Error(data.error || '连接未完成，请重试。'); });
          }
          var disposition = response.headers.get('Content-Disposition') || '';
          if (response.headers.get('X-WorkRoom-Member')) { row.dataset.member = response.headers.get('X-WorkRoom-Member'); }
          if (disposition.indexOf('attachment') >= 0) {
            return response.blob().then(function (blob) {
              var file = /filename="([a-zA-Z0-9.-]+)"/.exec(disposition);
              var url = URL.createObjectURL(blob);
              var link = document.createElement('a');
              link.href = url;
              link.download = file ? file[1] : 'Connect-WorkRoom';
              document.body.appendChild(link);
              link.click();
              link.remove();
              window.setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
              state.textContent = '待运行助手';
              show('连接助手已下载。在运行AI工具的电脑上打开它，完成后重新加载工具的MCP连接。助手需要Python 3.11及以上。');
              startPolling();
            });
          }
          return response.json().then(function (data) {
            row.dataset.member = data.member;
            state.classList.remove('is-connected');
            state.classList.add('is-pending');
            state.textContent = data.install_url ? '待客户端确认' : '待工具加载';
            show(data.message || '连接配置已准备。');
            if (data.install_url && data.install_url.indexOf('cursor://anysphere.cursor-deeplink/mcp/install?') === 0) {
              var retry = document.createElement('a');
              retry.href = data.install_url;
              retry.textContent = '打开Cursor';
              feedback.appendChild(retry);
              retry.click();
            }
            button.dataset.idleLabel = data.install_url ? '重新打开Cursor' : '更新本机配置';
            startPolling();
          });
        }).catch(function (error) {
          show(error.name === 'AbortError' ? '暂未确认连接结果，请检查工具状态后重试。' : error.message, true);
        }).finally(function () {
          window.clearTimeout(timer);
          button.disabled = false;
          button.textContent = button.dataset.idleLabel || idle;
          form.removeAttribute('aria-busy');
        });
    });
  });
  if (list.querySelector('[data-member]')) { startPolling(); }
}());
