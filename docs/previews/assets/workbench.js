(function () {
  'use strict';
  const $ = (selector) => document.querySelector(selector);
  const list = $('#project-list');
  const search = $('#project-search');
  const statusFilter = $('#status-filter');
  const count = $('#project-count');
  const empty = $('#empty-state');
  const navCount = $('#nav-count');
  const railAuth = $('#rail-auth');
  const motionToggle = $('#motion-toggle');
  const motionState = $('#motion-state');
  const detailDialog = $('#detail-dialog');
  const newDialog = $('#new-dialog');
  const newForm = $('#new-form');
  const newName = $('#new-name');
  const newDesc = $('#new-desc');
  const newFolder = $('#new-folder');
  const nameError = $('#new-name-error');
  const toastRegion = $('#toast-region');
  const root = document.documentElement;
  const motionMq = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };
  let reduceMotion = motionMq.matches;

  const mk = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  // Motion 14：duration 以秒为单位；stagger 用于列表错峰。
  function canAnimate() {
    return !reduceMotion && !motionMq.matches;
  }
  function animate(target, keyframes, options) {
    if (!canAnimate() || typeof Motion === 'undefined' || typeof Motion.animate !== 'function') return;
    try { Motion.animate(target, keyframes, options); } catch (error) { /* 保持内容可见 */ }
  }
  function animateCards(items) {
    if (!items.length || typeof Motion === 'undefined' || typeof Motion.stagger !== 'function') return;
    animate(items, { opacity: [0, 1], y: [6, 0] }, { duration: 0.28, delay: Motion.stagger(0.04), ease: 'easeOut' });
  }

  function syncMotion() {
    const effective = reduceMotion || motionMq.matches;
    root.classList.toggle('reduce-motion', effective);
    motionToggle.setAttribute('aria-checked', String(effective));
    motionState.textContent = effective ? '开' : '关';
  }
  motionToggle.addEventListener('click', () => {
    if (motionMq.matches) {
      showToast('系统已启用“减弱动效”，样稿会继续跳过动画。');
      syncMotion();
      return;
    }
    reduceMotion = !reduceMotion;
    syncMotion();
    showToast(reduceMotion ? '已减弱动效：跳过淡入与位移动画。' : '已恢复动效：使用短时淡入与位移。');
  });
  if (motionMq.addEventListener) motionMq.addEventListener('change', syncMotion);
  else if (motionMq.addListener) motionMq.addListener(syncMotion);

  function showToast(message) {
    const node = mk('div', 'demo-toast', message);
    toastRegion.append(node);
    animate(node, { opacity: [0, 1], y: [8, 0] }, { duration: 0.24, ease: 'easeOut' });
    while (toastRegion.children.length > 3) toastRegion.firstElementChild.remove();
    window.setTimeout(() => {
      node.classList.add('is-out');
      window.setTimeout(() => node.remove(), 220);
    }, 3600);
  }

  function applyFilters(shouldAnimate) {
    const query = search.value.trim().toLowerCase();
    const state = statusFilter.value;
    const items = Array.from(list.querySelectorAll('.project-item'));
    let shown = 0;
    items.forEach((item) => {
      const haystack = (item.dataset.name + ' ' + item.textContent).toLowerCase();
      const match = (!query || haystack.includes(query)) && (state === 'all' || item.dataset.status === state);
      item.hidden = !match;
      if (match) shown += 1;
    });
    empty.hidden = shown !== 0;
    count.textContent = query || state !== 'all' ? shown + ' / ' + items.length + ' 个示例项目' : items.length + ' 个示例项目';
    if (shouldAnimate) animateCards(items.filter((item) => !item.hidden));
  }

  function refreshSummary() {
    const items = Array.from(list.querySelectorAll('.project-item'));
    const authorized = items.filter((item) => item.dataset.status === 'authorized').length;
    navCount.textContent = String(items.length);
    railAuth.textContent = authorized + ' / ' + items.length;
    applyFilters(false);
  }

  function clearFilters() {
    search.value = '';
    statusFilter.value = 'all';
    applyFilters(true);
  }
  search.addEventListener('input', () => applyFilters(false));
  statusFilter.addEventListener('change', () => applyFilters(true));
  $('#clear-filters').addEventListener('click', clearFilters);
  $('#empty-reset').addEventListener('click', clearFilters);

  function openDetail(item) {
    const data = item.dataset;
    const authorized = data.status === 'authorized';
    const linked = data.folder !== '未关联示例文件夹';
    $('#detail-title').textContent = data.name;
    $('#detail-summary').textContent = data.summary;
    $('#detail-folder').textContent = data.folder;
    $('#detail-location').textContent = linked ? '项目工作区（示例）' : '未关联';
    $('#detail-updated').textContent = data.updated;
    $('#detail-members').textContent = data.members;
    const status = $('#detail-status');
    status.textContent = authorized ? '已授权，可读写' : '尚未授权';
    status.className = 'badge auth-badge ' + (authorized ? 'is-ok' : 'is-warn');
    $('#detail-auth-note').textContent = authorized
      ? '示例授权状态：已授权，可读写。正式版中该状态来自项目与本机文件夹的显式关联；本样稿不读取或写入任何文件。'
      : linked
        ? '示例授权状态：位置已关联，本次会话尚未授权该项目；保存的位置不等于文件访问权限。本样稿不访问文件。'
        : '示例授权状态：尚未授权。正式版需在项目中关联本机文件夹并显式授权后才能读写；本样稿不访问文件。';
    const tasks = (data.tasks || '').split('|').filter(Boolean);
    const taskList = $('#detail-tasks');
    taskList.replaceChildren();
    if (!tasks.length) {
      taskList.append(mk('li', 'task-empty', '暂无示例任务；任务与 AI 协作仍在规划中。'));
    } else {
      tasks.forEach((task) => {
        const row = mk('li');
        row.append(mk('span', '', task), mk('span', 'badge auth-badge is-warn', '规划中'));
        taskList.append(row);
      });
    }
    detailDialog.showModal();
  }

  list.addEventListener('click', (event) => {
    const button = event.target.closest('[data-action="detail"]');
    if (!button) return;
    const item = button.closest('.project-item');
    if (item) openDetail(item);
  });
  detailDialog.querySelectorAll('[data-close-detail]').forEach((button) => {
    button.addEventListener('click', () => detailDialog.close());
  });

  function buildProject(name, summary, authorized) {
    const folder = authorized ? 'D:\\Work\\demo-new' : '未关联示例文件夹';
    const item = list.querySelector('.project-item').cloneNode(true);
    Object.assign(item.dataset, { name, summary, folder, updated: '刚刚', members: '示例访客', tasks: '', status: authorized ? 'authorized' : 'pending' });
    item.querySelector('.project-icon').textContent = Array.from(name)[0] || '新';
    item.querySelector('h3').textContent = name;
    item.querySelector('.project-info > p').textContent = summary;
    item.querySelectorAll('.sample-tag').forEach((tag) => tag.remove());
    const badge = item.querySelector('.auth-badge');
    badge.textContent = authorized ? '已授权，可读写' : '尚未授权';
    badge.className = 'badge auth-badge ' + (authorized ? 'is-ok' : 'is-warn');
    item.querySelector('.title-line').append(mk('span', 'sample-tag', '刚创建 · 内存'));
    const meta = item.querySelectorAll('.meta span');
    meta[0].lastChild.textContent = folder;
    meta[1].textContent = '更新于 刚刚';
    item.querySelector('.project-side > span').textContent = authorized ? '关联位置：项目工作区' : '关联位置：未关联';
    return item;
  }

  function clearNameError() {
    nameError.hidden = true;
    nameError.textContent = '';
    newName.removeAttribute('aria-invalid');
  }
  newName.addEventListener('input', clearNameError);
  $('#open-new').addEventListener('click', () => {
    newDialog.showModal();
    newName.focus();
  });
  newDialog.querySelectorAll('[data-close-new]').forEach((button) => {
    button.addEventListener('click', () => newDialog.close());
  });
  newDialog.addEventListener('close', () => {
    newForm.reset();
    clearNameError();
  });
  newForm.addEventListener('submit', (event) => {
    event.preventDefault();
    const name = newName.value.trim();
    if (!name) {
      nameError.textContent = '请输入项目名称。';
      nameError.hidden = false;
      newName.setAttribute('aria-invalid', 'true');
      newName.focus();
      return;
    }
    const summary = newDesc.value.trim() || '新建的内存示例项目，尚未填写说明。';
    const authorized = newFolder.value === 'authorized';
    const item = buildProject(name, summary, authorized);
    if (authorized) {
      list.querySelectorAll('[data-status="authorized"]').forEach((previous) => {
        previous.dataset.status = 'pending';
        const badge = previous.querySelector('.auth-badge');
        badge.textContent = '尚未授权';
        badge.className = 'badge auth-badge is-warn';
      });
    }
    list.prepend(item);
    newDialog.close();
    search.value = '';
    statusFilter.value = 'all';
    refreshSummary();
    animateCards([item]);
    showToast('示例项目「' + name + '」已加入本页内存；刷新即恢复，不写入数据库或本机文件。');
  });

  [detailDialog, newDialog].forEach((dialog) => {
    dialog.addEventListener('click', (event) => {
      if (event.target === dialog) dialog.close();
    });
  });

  document.querySelectorAll('[data-plan]').forEach((button) => {
    button.addEventListener('click', () => {
      const message = button.dataset.kind === 'outside'
        ? '文件工作区已在现有产品中可用；本样稿不连接真实文件。'
        : '「' + button.dataset.plan + '」为规划中入口，本样稿暂未实现。';
      showToast(message);
    });
  });

  syncMotion();
  refreshSummary();
  animateCards(Array.from(list.querySelectorAll('.project-item')));
})();
