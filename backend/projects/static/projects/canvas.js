/* T016B project canvas: dated task tree, split links, detail/team panel.
   All task text is written with textContent / DOM APIs; nothing from the
   server JSON or a form is concatenated into innerHTML. Without JavaScript
   the server-rendered outline list and the plain dialogs remain usable. */
(function () {
  'use strict';

  var board = document.querySelector('[data-board]');
  if (!board) {
    return;
  }

  var DAY = 86400000;
  var ROW_H = 112;
  var NODE_H = 88;
  var TOP_PAD = 18;
  var LEFT_PAD = 14;
  var BASE_DAY_W = 34;
  var MAX_STAGE_W = 26000;
  var TIMEOUT_MS = 8000;

  var dataEl = document.getElementById('canvas-data');
  var data = null;
  if (dataEl) {
    try {
      data = JSON.parse(dataEl.textContent);
    } catch (error) {
      data = null;
    }
  }

  var tasks = data && Array.isArray(data.tasks) ? data.tasks : [];
  var selectedRaw = board.getAttribute('data-selected') || '';
  var selectedId = /^\d+$/.test(selectedRaw) ? parseInt(selectedRaw, 10) : null;

  var canvas = board.querySelector('[data-canvas]');
  var scroll = board.querySelector('[data-canvas-scroll]');
  var stage = board.querySelector('[data-canvas-stage]');
  var ruler = board.querySelector('[data-ruler]');
  var canvasBody = board.querySelector('[data-canvas-body]');
  var svg = board.querySelector('[data-links]');
  var nodeLayer = board.querySelector('[data-nodes]');
  var outlineTree = board.querySelector('[data-outline-tree]');
  var outlineFallback = board.querySelector('[data-outline-fallback]');
  var searchInput = document.getElementById('board-search');
  var countEl = board.querySelector('[data-count]');
  var zoomLabel = board.querySelector('[data-zoom-label]');
  var zoomOut = board.querySelector('[data-zoom-out]');
  var zoomIn = board.querySelector('[data-zoom-in]');
  var resetButton = board.querySelector('[data-reset]');
  var collapseButton = board.querySelector('[data-collapse-all]');
  var viewButtons = Array.prototype.slice.call(board.querySelectorAll('[data-view-btn]'));

  var state = {
    zoom: 1,
    query: '',
    view: 'canvas',
    collapsed: {},
    range: null,
    dayW: BASE_DAY_W,
    rendered: false,
    animated: false,
    pendingSelect: selectedId !== null
  };

  /* ---- tiny DOM helpers ------------------------------------------- */
  function create(tag, className) {
    var node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    return node;
  }

  function each(list, callback) {
    Array.prototype.forEach.call(list, callback);
  }

  function clear(node) {
    while (node && node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  function pad2(value) {
    return value < 10 ? '0' + value : String(value);
  }

  function parseDay(value) {
    var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ''));
    if (!match) {
      return null;
    }
    return Date.UTC(parseInt(match[1], 10), parseInt(match[2], 10) - 1, parseInt(match[3], 10));
  }

  function isoDay(offset) {
    var date = new Date();
    date.setDate(date.getDate() + (offset || 0));
    return date.getFullYear() + '-' + pad2(date.getMonth() + 1) + '-' + pad2(date.getDate());
  }

  function shortDate(ms) {
    var date = new Date(ms);
    return pad2(date.getUTCMonth() + 1) + '-' + pad2(date.getUTCDate());
  }

  function todayUTC() {
    var now = new Date();
    return Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  }

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function isReduced() {
    if (document.documentElement.classList.contains('reduce-motion')) {
      return true;
    }
    return Boolean(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }

  function canAnimate() {
    return !isReduced()
      && typeof window.Motion !== 'undefined'
      && typeof window.Motion.animate === 'function';
  }

  /* ---- tree data --------------------------------------------------- */
  var byId = {};
  var children = {};
  var roots = [];
  var parentOf = {};

  tasks.forEach(function (task) {
    task._start = parseDay(task.start_date);
    task._end = parseDay(task.end_date);
    byId[task.id] = task;
  });

  tasks.forEach(function (task) {
    var parentId = task.parent_id;
    if (parentId !== null && parentId !== undefined && byId[parentId] && String(parentId) !== String(task.id)) {
      if (!children[parentId]) {
        children[parentId] = [];
      }
      children[parentId].push(task);
      parentOf[task.id] = byId[parentId];
    } else {
      roots.push(task);
    }
  });

  var collapsible = {};
  Object.keys(children).forEach(function (id) {
    if (children[id] && children[id].length) {
      collapsible[id] = true;
    }
  });

  function buildRows(ignoreCollapse) {
    var rows = [];
    var stack = [];
    var seen = {};
    var index;
    for (index = roots.length - 1; index >= 0; index -= 1) {
      stack.push({ task: roots[index], depth: 0 });
    }
    while (stack.length) {
      var item = stack.pop();
      var task = item.task;
      if (seen[task.id]) {
        continue;
      }
      seen[task.id] = true;
      rows.push(item);
      if (!ignoreCollapse && state.collapsed[task.id]) {
        continue;
      }
      var kids = children[task.id] || [];
      for (index = kids.length - 1; index >= 0; index -= 1) {
        stack.push({ task: kids[index], depth: item.depth + 1 });
      }
    }
    return rows;
  }

  function computeRange() {
    var min = null;
    var max = null;
    tasks.forEach(function (task) {
      if (task._start === null || task._end === null) {
        return;
      }
      if (min === null || task._start < min) {
        min = task._start;
      }
      if (max === null || task._end > max) {
        max = task._end;
      }
    });
    if (min === null || max === null) {
      return null;
    }
    min -= DAY * 2;
    max += DAY * 3;
    return {
      start: min,
      end: max,
      days: Math.round((max - min) / DAY) + 1
    };
  }

  function dayWidth(range, zoom) {
    var base = Math.min(BASE_DAY_W, Math.max(8, MAX_STAGE_W / range.days));
    return Math.max(5, base * zoom);
  }

  function matches(task, query) {
    if (!query) {
      return true;
    }
    var haystack = [
      task.title,
      task.description,
      task.assignee_name,
      task.status_label
    ].join(' ').toLowerCase();
    return haystack.indexOf(query) !== -1;
  }

  function taskCount(query) {
    var count = 0;
    tasks.forEach(function (task) {
      if (matches(task, query)) {
        count += 1;
      }
    });
    return count;
  }

  /* ---- canvas rendering ------------------------------------------- */
  function renderRuler(range, dayW) {
    clear(ruler);
    var cursor = range.start;
    var monthIndex = 0;
    while (cursor <= range.end) {
      var date = new Date(cursor);
      var year = date.getUTCFullYear();
      var month = date.getUTCMonth();
      var next = Date.UTC(year, month + 1, 1);
      var segmentEnd = Math.min(next, range.end + DAY);
      var left = ((cursor - range.start) / DAY) * dayW;
      var width = ((segmentEnd - cursor) / DAY) * dayW;

      var label = create('span', 'ruler-month');
      label.style.left = left + 'px';
      label.style.width = Math.max(width, 0) + 'px';
      label.textContent = (monthIndex === 0 || month === 0)
        ? year + '年' + (month + 1) + '月'
        : (month + 1) + '月';
      ruler.appendChild(label);

      monthIndex += 1;
      cursor = next;
    }

    var step = dayW >= 26 ? 1 : (dayW >= 15 ? 3 : 7);
    if (range.days / step > 90) {
      step = Math.ceil(range.days / 90);
    }
    for (var index = 0; index < range.days; index += step) {
      var day = new Date(range.start + index * DAY);
      var tick = create('span', 'ruler-day');
      tick.style.left = (index * dayW + dayW / 2) + 'px';
      tick.textContent = String(day.getUTCDate());
      ruler.appendChild(tick);
    }

    var today = todayUTC();
    if (today >= range.start && today <= range.end) {
      var marker = create('div', 'ruler-today');
      marker.style.left = (((today - range.start) / DAY) * dayW + dayW / 2) + 'px';
      ruler.appendChild(marker);
    }
  }

  function renderGrid(range, dayW) {
    each(canvasBody.querySelectorAll('.month-line, .today-line'), function (line) {
      line.parentNode.removeChild(line);
    });
    var cursor = range.start;
    while (cursor <= range.end) {
      var date = new Date(cursor);
      var next = Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 1);
      if (cursor !== range.start) {
        var line = create('div', 'month-line');
        line.style.left = (((cursor - range.start) / DAY) * dayW) + 'px';
        canvasBody.appendChild(line);
      }
      cursor = next;
    }
    var today = todayUTC();
    if (today >= range.start && today <= range.end) {
      var todayLine = create('div', 'today-line');
      todayLine.style.left = (((today - range.start) / DAY) * dayW + dayW / 2) + 'px';
      canvasBody.appendChild(todayLine);
    }
  }

  function renderNode(task, rowIndex, left, width, layoutMap) {
    var node = create('a', 'canvas-node status-' + task.status);
    node.href = '?task=' + task.id + '#board-side';
    node.style.left = left + 'px';
    node.style.top = (TOP_PAD + rowIndex * ROW_H) + 'px';
    node.style.width = width + 'px';
    node.setAttribute('data-node-id', String(task.id));

    var owner = task.assignee_name || '未分配';
    var status = task.status_label || task.status || '';
    var titleRow = create('span', 'node-title-row');
    var title = create('span', 'node-title');
    title.textContent = task.title;
    var badge = create('span', 'node-status');
    badge.textContent = status;
    titleRow.appendChild(title);
    titleRow.appendChild(badge);

    var desc = create('span', 'node-desc');
    desc.textContent = task.description ? task.description.replace(/\s+/g, ' ') : '（无内容）';

    var meta = create('span', 'node-meta');
    var ownerEl = create('span', 'node-owner');
    ownerEl.textContent = owner;
    var dates = create('span', 'node-dates');
    dates.textContent = shortDate(task._start) + ' → ' + shortDate(task._end);
    meta.appendChild(ownerEl);
    meta.appendChild(dates);

    node.appendChild(titleRow);
    node.appendChild(desc);
    node.appendChild(meta);

    var full = task.title + ' · ' + status + ' · 负责人 ' + owner
      + ' · ' + task.start_date + ' 至 ' + task.end_date + ' · 点按查看详情';
    node.setAttribute('title', full);
    node.setAttribute('aria-label', full);

    if (selectedId !== null && task.id === selectedId) {
      node.classList.add('is-selected');
    }
    if (state.query && !matches(task, state.query)) {
      node.classList.add('is-dim');
    } else if (state.query) {
      node.classList.add('is-match');
    }

    nodeLayer.appendChild(node);
    layoutMap[task.id] = { left: left, top: TOP_PAD + rowIndex * ROW_H, width: width };
    return node;
  }

  function renderToggle(task, left, top) {
    var kids = children[task.id] || [];
    if (!kids.length) {
      return;
    }
    var collapsed = Boolean(state.collapsed[task.id]);
    var button = create('button', 'node-toggle');
    button.type = 'button';
    button.style.left = (left - 8) + 'px';
    button.style.top = (top - 8) + 'px';
    button.textContent = collapsed ? '+' : '−';
    button.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    button.setAttribute(
      'aria-label',
      (collapsed ? '展开 ' : '折叠 ') + task.title + ' 的 ' + kids.length + ' 个子任务'
    );
    button.setAttribute('title', collapsed ? '展开子任务' : '折叠子任务');
    button.addEventListener('click', function (event) {
      event.preventDefault();
      event.stopPropagation();
      if (state.collapsed[task.id]) {
        delete state.collapsed[task.id];
      } else {
        state.collapsed[task.id] = true;
      }
      updateCollapseButton();
      renderCanvas(true);
    });
    nodeLayer.appendChild(button);
  }

  function renderLinks(rows, layoutMap) {
    clear(svg);
    var height = TOP_PAD * 2 + rows.length * ROW_H;
    svg.setAttribute('width', String(stage.offsetWidth || 0));
    svg.setAttribute('height', String(height));
    rows.forEach(function (row) {
      var parent = parentOf[row.task.id];
      if (!parent) {
        return;
      }
      var from = layoutMap[parent.id];
      var to = layoutMap[row.task.id];
      if (!from || !to) {
        return;
      }
      var sx = from.left + Math.min(from.width / 2, 52);
      var sy = from.top + NODE_H;
      var cx = to.left + Math.min(to.width / 2, 52);
      var cy = to.top;
      var mid = sy + Math.max(8, (cy - sy) / 2);
      var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('class', 'canvas-link');
      path.setAttribute('d', 'M ' + sx + ' ' + sy + ' V ' + mid + ' H ' + cx + ' V ' + cy);
      if (state.query && (!matches(row.task, state.query) || !matches(parent, state.query))) {
        path.setAttribute('opacity', '0.2');
      }
      svg.appendChild(path);

      var dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      dot.setAttribute('class', 'canvas-link-dot');
      dot.setAttribute('cx', String(cx));
      dot.setAttribute('cy', String(cy));
      dot.setAttribute('r', '2.5');
      svg.appendChild(dot);
    });
  }

  function enhanceNodes(nodes) {
    if (state.animated || !nodes.length || !canAnimate()) {
      return;
    }
    state.animated = true;
    try {
      var options = { duration: 0.18, ease: 'easeOut' };
      if (typeof window.Motion.stagger === 'function') {
        options.delay = window.Motion.stagger(0.008);
      }
      window.Motion.animate(nodes, { opacity: [0.2, 1] }, options);
    } catch (error) {
      /* Nodes are already visible; animation is optional. */
    }
  }

  function renderCanvas(preserveCenter) {
    if (!tasks.length || !canvas) {
      return;
    }
    var range = computeRange();
    if (!range) {
      return;
    }

    var oldStart = state.range ? state.range.start : null;
    var oldDayW = state.dayW;
    var centerMs = null;
    if (preserveCenter && oldStart !== null && scroll && scroll.clientWidth) {
      var centerPx = scroll.scrollLeft + scroll.clientWidth / 2 - LEFT_PAD;
      centerMs = oldStart + (centerPx / oldDayW) * DAY;
    }

    var dayW = dayWidth(range, state.zoom);
    state.range = range;
    state.dayW = dayW;

    var rows = buildRows(state.query.length > 0);
    var width = Math.max(
      scroll ? scroll.clientWidth : 0,
      LEFT_PAD * 2 + range.days * dayW
    );
    var height = TOP_PAD * 2 + rows.length * ROW_H;

    if (stage) {
      stage.style.width = Math.max(width, 320) + 'px';
    }
    if (canvasBody) {
      canvasBody.style.height = height + 'px';
      canvasBody.style.setProperty('--day-w', dayW + 'px');
    }

    renderRuler(range, dayW);
    renderGrid(range, dayW);
    clear(nodeLayer);

    var layoutMap = {};
    var nodes = [];
    rows.forEach(function (row, index) {
      var task = row.task;
      if (task._start === null || task._end === null) {
        return;
      }
      var spanDays = Math.max(1, Math.round((task._end - task._start) / DAY) + 1);
      var left = LEFT_PAD + ((task._start - range.start) / DAY) * dayW;
      var nodeWidth = Math.max(260, spanDays * dayW - 8);
      nodes.push(renderNode(task, index, left, nodeWidth, layoutMap));
      renderToggle(task, left, TOP_PAD + index * ROW_H);
    });
    renderLinks(rows, layoutMap);
    enhanceNodes(nodes);

    if (selectedId !== null && layoutMap[selectedId] && scroll && state.view === 'canvas' && state.pendingSelect) {
      var targetLeft = layoutMap[selectedId].left;
      scroll.scrollLeft = Math.max(0, targetLeft - 80);
      scroll.scrollTop = 0;
      state.pendingSelect = false;
    } else if (centerMs !== null && scroll) {
      var offset = LEFT_PAD + ((centerMs - range.start) / DAY) * dayW;
      scroll.scrollLeft = Math.max(0, offset - scroll.clientWidth / 2);
    }

    state.rendered = true;
    updateZoomLabel();
  }

  function renderOutline() {
    if (!outlineTree) {
      return;
    }
    clear(outlineTree);
    if (!tasks.length) {
      return;
    }
    var rows = buildRows(true);
    var shown = 0;
    rows.forEach(function (row) {
      var task = row.task;
      if (!matches(task, state.query)) {
        return;
      }
      shown += 1;
      var line = create('div', 'outline-node');
      line.style.paddingLeft = (row.depth * 16) + 'px';
      line.setAttribute('data-outline-id', String(task.id));

      var link = create('a', 'outline-title');
      link.href = '?task=' + task.id + '#board-side';
      link.textContent = task.title;
      line.appendChild(link);

      var chip = create('span', 'chip chip-' + task.status);
      chip.textContent = task.status_label || task.status;
      line.appendChild(chip);

      var owner = task.assignee_name || '未分配';
      var meta = create('span', 'outline-meta');
      meta.textContent = (row.depth ? '子任务' : '整体任务')
        + ' · ' + task.start_date + ' → ' + task.end_date
        + ' · ' + owner;
      line.appendChild(meta);

      outlineTree.appendChild(line);
    });

    if (!shown) {
      var empty = create('p', 'side-empty');
      empty.textContent = '没有匹配的任务。';
      outlineTree.appendChild(empty);
    }
  }

  function updateCount() {
    if (!countEl) {
      return;
    }
    if (state.query) {
      countEl.textContent = '匹配 ' + taskCount(state.query) + ' / ' + tasks.length + ' 个任务';
    } else {
      countEl.textContent = tasks.length + ' 个任务';
    }
  }

  function updateZoomLabel() {
    if (zoomLabel) {
      zoomLabel.textContent = Math.round(state.zoom * 100) + '%';
    }
    if (zoomOut) {
      zoomOut.disabled = !tasks.length || state.zoom <= 0.6;
    }
    if (zoomIn) {
      zoomIn.disabled = !tasks.length || state.zoom >= 2;
    }
  }

  function updateCollapseButton() {
    if (!collapseButton) {
      return;
    }
    var ids = Object.keys(collapsible);
    var allCollapsed = ids.length > 0 && ids.every(function (id) {
      return Boolean(state.collapsed[id]);
    });
    collapseButton.textContent = allCollapsed ? '展开全部' : '折叠全部';
    collapseButton.setAttribute('aria-pressed', allCollapsed ? 'true' : 'false');
  }

  function applyView() {
    if (!canvas) {
      return;
    }
    var hasTasks = tasks.length > 0;
    var showCanvas = hasTasks && state.view === 'canvas';
    canvas.hidden = !showCanvas;
    if (outlineTree) {
      outlineTree.hidden = !(hasTasks && state.view === 'list');
    }
    if (outlineFallback) {
      outlineFallback.hidden = true;
    }
    viewButtons.forEach(function (button) {
      button.setAttribute('aria-pressed', button.getAttribute('data-view-btn') === state.view ? 'true' : 'false');
    });
    if (showCanvas) {
      renderCanvas(false);
    }
  }

  function setView(view) {
    state.view = view;
    applyView();
  }

  /* ---- toolbar ----------------------------------------------------- */
  function setQuery(value) {
    state.query = value.trim().toLowerCase();
    updateCount();
    if (tasks.length && state.view === 'canvas') {
      renderCanvas(true);
    }
    if (tasks.length) {
      renderOutline();
    }
  }

  var searchTimer = null;

  if (searchInput) {
    searchInput.addEventListener('input', function () {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(function () {
        setQuery(searchInput.value || '');
      }, 90);
    });
    searchInput.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && searchInput.value) {
        searchInput.value = '';
        setQuery('');
      }
    });
  }

  each(board.querySelectorAll('[data-view-btn]'), function (button) {
    button.addEventListener('click', function () {
      setView(button.getAttribute('data-view-btn') === 'list' ? 'list' : 'canvas');
    });
  });

  if (zoomOut) {
    zoomOut.addEventListener('click', function () {
      state.zoom = clamp(Math.round((state.zoom - 0.2) * 10) / 10, 0.6, 2);
      state.view = 'canvas';
      applyView();
      updateZoomLabel();
    });
  }

  if (zoomIn) {
    zoomIn.addEventListener('click', function () {
      state.zoom = clamp(Math.round((state.zoom + 0.2) * 10) / 10, 0.6, 2);
      state.view = 'canvas';
      applyView();
      updateZoomLabel();
    });
  }

  if (collapseButton) {
    collapseButton.addEventListener('click', function () {
      var ids = Object.keys(collapsible);
      if (!ids.length) {
        return;
      }
      var allCollapsed = ids.every(function (id) {
        return Boolean(state.collapsed[id]);
      });
      state.collapsed = {};
      if (!allCollapsed) {
        ids.forEach(function (id) {
          state.collapsed[id] = true;
        });
      }
      updateCollapseButton();
      if (state.view === 'canvas') {
        renderCanvas(true);
      }
    });
  }

  if (resetButton) {
    resetButton.addEventListener('click', function () {
      state.zoom = 1;
      state.query = '';
      state.collapsed = {};
      if (searchInput) {
        searchInput.value = '';
      }
      updateCount();
      updateCollapseButton();
      state.view = window.matchMedia && window.matchMedia('(max-width: 767px)').matches ? 'list' : 'canvas';
      applyView();
      renderOutline();
      if (scroll) {
        scroll.scrollLeft = 0;
        scroll.scrollTop = 0;
      }
      updateZoomLabel();
    });
  }

  /* ---- dialogs ----------------------------------------------------- */
  var lastTrigger = null;

  function dialogSupported(dialog) {
    return Boolean(dialog && typeof dialog.showModal === 'function');
  }

  function openDialog(dialog, trigger) {
    if (!dialogSupported(dialog)) {
      return;
    }
    lastTrigger = trigger || null;
    if (!dialog.open) {
      dialog.showModal();
    }
    var first = dialog.querySelector('input:not([type="hidden"]), select, textarea');
    if (first) {
      first.focus();
    }
  }

  function closeDialog(dialog) {
    if (dialog && dialog.open) {
      dialog.close();
    }
  }

  function wireDialog(dialog) {
    if (!dialog) {
      return;
    }
    each(dialog.querySelectorAll('[data-close-dialog]'), function (button) {
      button.addEventListener('click', function () {
        closeDialog(dialog);
      });
    });
    dialog.addEventListener('click', function (event) {
      if (event.target === dialog) {
        closeDialog(dialog);
      }
    });
    dialog.addEventListener('close', function () {
      if (lastTrigger && document.contains(lastTrigger)) {
        try {
          lastTrigger.focus();
        } catch (error) {
          /* The trigger may belong to a replaced view. */
        }
      }
      lastTrigger = null;
    });
  }

  var taskDialog = document.getElementById('task-dialog');
  var memberDialog = document.getElementById('member-dialog');

  function prepareTaskDialog(parentId) {
    var start = document.getElementById('new-task-start');
    var end = document.getElementById('new-task-end');
    if (start && !start.value) {
      start.value = isoDay(0);
    }
    if (end && !end.value) {
      end.value = isoDay(2);
    }
    if (parentId) {
      var parent = document.getElementById('new-task-parent');
      if (parent) {
        parent.value = String(parentId);
      }
    }
  }

  each(board.querySelectorAll('[data-open-dialog]'), function (button) {
    button.addEventListener('click', function () {
      var id = button.getAttribute('data-open-dialog');
      var dialog = document.getElementById(id);
      if (id === 'task-dialog') {
        prepareTaskDialog(null);
      }
      openDialog(dialog, button);
    });
  });

  each(board.querySelectorAll('[data-new-child]'), function (link) {
    link.addEventListener('click', function (event) {
      event.preventDefault();
      prepareTaskDialog(link.getAttribute('data-new-child'));
      openDialog(taskDialog, link);
    });
  });

  wireDialog(taskDialog);
  wireDialog(memberDialog);
  wireDialog(document.getElementById('folder-picker'));

  var kindSelect = document.getElementById('member-kind');
  if (kindSelect && memberDialog) {
    var syncKind = function () {
      var isHuman = kindSelect.value !== 'ai';
      var humanFields = memberDialog.querySelector('[data-member-human]');
      var aiFields = memberDialog.querySelector('[data-member-ai]');
      if (humanFields) {
        humanFields.hidden = !isHuman;
      }
      if (aiFields) {
        aiFields.hidden = isHuman;
      }
    };
    kindSelect.addEventListener('change', syncKind);
    syncKind();
  }

  each(document.querySelectorAll('[data-open-on-load]'), function (dialog) {
    openDialog(dialog, null);
  });

  /* ---- side panel tabs -------------------------------------------- */
  var side = document.getElementById('board-side');
  var tabButtons = Array.prototype.slice.call(board.querySelectorAll('[data-tab]'));
  var panels = {
    detail: document.getElementById('panel-detail'),
    team: document.getElementById('panel-team')
  };

  function setTab(name) {
    var teamControl = document.querySelector('[data-team-toggle]');
    if (teamControl) {
      teamControl.setAttribute('aria-expanded', name === 'team' ? 'true' : 'false');
    }
    tabButtons.forEach(function (button) {
      var active = button.getAttribute('data-tab') === name;
      button.setAttribute('aria-selected', active ? 'true' : 'false');
      button.tabIndex = active ? 0 : -1;
    });
    Object.keys(panels).forEach(function (key) {
      if (panels[key]) {
        panels[key].hidden = key !== name;
      }
    });
  }

  tabButtons.forEach(function (button, index) {
    button.addEventListener('click', function () {
      setTab(button.getAttribute('data-tab'));
    });
    button.addEventListener('keydown', function (event) {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') {
        return;
      }
      event.preventDefault();
      var next = (index + (event.key === 'ArrowRight' ? 1 : -1) + tabButtons.length) % tabButtons.length;
      tabButtons[next].focus();
      setTab(tabButtons[next].getAttribute('data-tab'));
    });
  });

  var activeTab = tabButtons.filter(function (button) {
    return button.getAttribute('aria-selected') === 'true';
  })[0];
  if (activeTab) {
    setTab(activeTab.getAttribute('data-tab'));
  } else {
    setTab('team');
  }

  var teamToggle = document.querySelector('[data-team-toggle]');
  if (teamToggle) {
    teamToggle.addEventListener('click', function () {
      setTab('team');
      teamToggle.setAttribute('aria-expanded', 'true');
      if (side && window.matchMedia && window.matchMedia('(max-width: 900px)').matches) {
        side.scrollIntoView({ block: 'start' });
      }
    });
  }

  /* ---- folder picker ---------------------------------------------- */
  (function initPicker() {
    var dialog = document.getElementById('folder-picker');
    if (!dialog || typeof dialog.showModal !== 'function' || !window.fetch || !window.AbortController) {
      return;
    }

    var list = document.getElementById('picker-list');
    var statusEl = document.getElementById('picker-status');
    var currentEl = document.getElementById('picker-current');
    var pathInput = document.getElementById('picker-path');
    var upButton = document.getElementById('picker-up');
    var chooseButton = document.getElementById('picker-choose');
    var closeButton = document.getElementById('picker-close');
    var pathForm = document.getElementById('picker-path-form');
    var targetInput = document.getElementById('workspace-path');
    var note = board.querySelector('[data-picker-note]');
    var openButtons = board.querySelectorAll('[data-pick-folder]');

    if (!list || !statusEl || !currentEl || !pathInput || !chooseButton || !pathForm) {
      return;
    }

    var ERRORS = {
      authentication_required: '请先登录后再选择文件夹。',
      invalid_path: '路径无效：请输入本机绝对目录，不能是相对路径、UNC、设备路径或包含 .. 。',
      not_found: '找不到这个目录，可能已被移动或删除。',
      not_a_directory: '该路径不是文件夹。',
      unsafe_path: '出于安全考虑，链接、reparse 或不可访问的目录不能浏览。',
      unreadable: '无法读取这个目录的列表。'
    };

    var picker = {
      path: '',
      parent: '',
      busy: false,
      seq: 0,
      controller: null,
      trigger: null
    };

    function setStatus(text, isError) {
      statusEl.textContent = text || '';
      statusEl.classList.toggle('error', Boolean(isError));
    }

    function setBusy(busy) {
      picker.busy = busy;
      list.setAttribute('aria-busy', busy ? 'true' : 'false');
      pathInput.disabled = busy;
      pathForm.querySelector('button[type="submit"]').disabled = busy;
      upButton.disabled = busy || !picker.path;
      chooseButton.disabled = busy || !picker.path;
      if (busy) {
        setStatus('正在加载…', false);
      }
    }

    function showError(message, retryPath) {
      picker.path = '';
      picker.parent = '';
      clear(list);
      chooseButton.disabled = true;
      setStatus('', true);
      statusEl.appendChild(document.createTextNode(message + ' '));
      var retry = create('button', 'secondary');
      retry.type = 'button';
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

    function render(data_) {
      picker.path = data_.path || '';
      picker.parent = data_.parent || '';
      currentEl.textContent = picker.path || '驱动器';
      pathInput.value = picker.path;
      clear(list);

      var entries = (picker.path ? data_.directories : data_.drives) || [];
      entries.forEach(addEntry);
      if (!entries.length) {
        var empty = document.createElement('li');
        empty.className = 'picker-empty';
        empty.textContent = picker.path
          ? '此目录没有可进入的子文件夹。'
          : '没有找到可用的驱动器。';
        list.appendChild(empty);
      }

      if (upButton) {
        upButton.disabled = !picker.path;
      }
      if (!picker.path) {
        setStatus('请选择一个驱动器，或输入完整目录路径。', false);
      } else if (data_.truncated) {
        setStatus('文件夹较多，仅显示前 100 个；可输入路径直接打开其余目录。', false);
      } else {
        setStatus('', false);
      }
      chooseButton.disabled = !picker.path;
    }

    function load(path) {
      if (picker.busy) {
        return;
      }
      picker.seq += 1;
      var seq = picker.seq;
      var controller = new AbortController();
      picker.controller = controller;
      var timer = window.setTimeout(function () {
        controller.abort();
      }, TIMEOUT_MS);
      setBusy(true);

      var tokenInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
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
          }).then(function (payload) {
            if (!response.ok) {
              var error = new Error(payload.error || 'http_' + response.status);
              error.code = payload.error;
              throw error;
            }
            return payload;
          });
        })
        .then(function (payload) {
          if (seq !== picker.seq) {
            return;
          }
          render(payload);
        })
        .catch(function (error) {
          if (seq !== picker.seq) {
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
          if (seq === picker.seq) {
            picker.controller = null;
            picker.busy = false;
            setBusy(false);
          }
        });
    }

    function stopPending() {
      picker.seq += 1;
      if (picker.controller) {
        picker.controller.abort();
        picker.controller = null;
      }
      picker.busy = false;
      setBusy(false);
    }

    function open(trigger) {
      picker.trigger = trigger || null;
      if (!dialog.open) {
        dialog.showModal();
      }
      clear(list);
      var initial = targetInput ? targetInput.value.trim() : '';
      pathInput.value = initial;
      load(initial);
    }

    each(openButtons, function (button) {
      button.addEventListener('click', function () {
        open(button);
      });
    });

    dialog.addEventListener('close', stopPending);
    dialog.addEventListener('cancel', stopPending);

    if (closeButton) {
      closeButton.addEventListener('click', function () {
        dialog.close();
      });
    }

    if (upButton) {
      upButton.addEventListener('click', function () {
        if (picker.busy) {
          return;
        }
        load(picker.parent || '');
      });
    }

    pathForm.addEventListener('submit', function (event) {
      event.preventDefault();
      if (picker.busy) {
        return;
      }
      var value = pathInput.value.trim();
      load(value || '');
    });

    chooseButton.addEventListener('click', function () {
      if (!picker.path || picker.busy) {
        return;
      }
      if (targetInput) {
        targetInput.value = picker.path;
        targetInput.dispatchEvent(new Event('input', { bubbles: true }));
      }
      if (note) {
        note.textContent = '已填入路径。请点击“授权并设为工作空间”完成保存；选择文件夹本身不会授权。';
      }
      dialog.close();
      var submit = document.getElementById('workspace-submit');
      var panel = document.getElementById('board-workspace');
      if (panel && window.matchMedia && window.matchMedia('(max-width: 900px)').matches) {
        panel.scrollIntoView({ block: 'start' });
      }
      if (submit) {
        window.setTimeout(function () {
          submit.focus();
        }, 0);
      }
    });
  })();

  /* ---- initial state ---------------------------------------------- */
  if (!tasks.length) {
    [searchInput, zoomOut, zoomIn, resetButton, collapseButton].forEach(function (control) {
      if (control) {
        control.disabled = true;
      }
    });
    viewButtons.forEach(function (button) {
      button.disabled = true;
    });
    updateCount();
    return;
  }

  state.view = window.matchMedia && window.matchMedia('(max-width: 767px)').matches ? 'list' : 'canvas';
  updateCount();
  updateCollapseButton();
  updateZoomLabel();
  renderOutline();
  applyView();

  if (scroll) {
    scroll.addEventListener('keydown', function (event) {
      if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
        event.preventDefault();
        scroll.scrollLeft += event.key === 'ArrowRight' ? 80 : -80;
      }
    });
  }
})();
