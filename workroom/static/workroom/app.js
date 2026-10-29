(function () {
  'use strict';

  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var sharedProject = document.querySelector('[data-snapshot-url]');
  if (sharedProject) {
    var revision = null;
    var updateButton = document.querySelector('[data-project-update]');
    var snapshotBusy = false;
    function checkProject() {
      if (document.hidden || snapshotBusy) { return; }
      snapshotBusy = true;
      fetch(sharedProject.getAttribute('data-snapshot-url'), {cache:'no-store'})
        .then(function(response){ return response.ok ? response.json() : null; })
        .then(function(data){
          if (!data) { return; }
          if (revision && revision !== data.version && updateButton) { updateButton.hidden = false; }
          revision = data.version;
        }).catch(function(){})
        .finally(function(){ snapshotBusy = false; });
    }
    if (updateButton) { updateButton.addEventListener('click', function(){ window.location.reload(); }); }
    checkProject();
    window.setInterval(checkProject, 10000);
  }

  // 聚光跟随：卡片和节点的 hover 高光跟着鼠标走
  if (!reduceMotion) {
    Array.prototype.forEach.call(
      document.querySelectorAll('.card, .node'),
      function (el) {
        el.addEventListener('pointermove', function (event) {
          var rect = el.getBoundingClientRect();
          el.style.setProperty('--mx', (event.clientX - rect.left) + 'px');
          el.style.setProperty('--my', (event.clientY - rect.top) + 'px');
        });
      }
    );
  }

  // 进度数字从 0 走到目标值
  Array.prototype.forEach.call(
    document.querySelectorAll('[data-count]'),
    function (el) {
      var target = parseInt(el.getAttribute('data-count'), 10);
      if (isNaN(target) || reduceMotion) {
        return;
      }
      var suffix = el.textContent.replace(/^\d+/, '');
      var duration = 720;
      var started = null;

      function frame(now) {
        if (started === null) {
          started = now;
        }
        var p = Math.min((now - started) / duration, 1);
        var eased = 1 - Math.pow(1 - p, 3);
        el.textContent = Math.round(target * eased) + suffix;
        if (p < 1) {
          window.requestAnimationFrame(frame);
        }
      }

      el.textContent = '0' + suffix;
      window.requestAnimationFrame(frame);
    }
  );

  Array.prototype.forEach.call(
    document.querySelectorAll('[data-ai-picker]'),
    function (picker) {
      var label = picker.querySelector('[data-ai-label]');

      function syncLabel() {
        var checked = picker.querySelector('input[name="ai"]:checked');
        if (!checked || !label) {
          return;
        }
        var text = checked.parentElement.querySelector('.ai-option-text');
        if (text) {
          label.textContent = text.textContent.trim();
        }
      }

      picker.addEventListener('change', function () {
        syncLabel();
        var checked = picker.querySelector('input[name="ai"]:checked');
        if (checked) {
          var cookieName = picker.getAttribute('data-ai-cookie');
          if (cookieName) {
            document.cookie =
              cookieName +
              '=' +
              encodeURIComponent(checked.value) +
              '; path=/; max-age=' +
              90 * 24 * 3600 +
              '; samesite=lax';
          }
          var next = new URL(window.location.href);
          next.searchParams.set('ai', checked.value);
          window.history.replaceState({}, '', next);
        }
        picker.open = false;
      });

      document.addEventListener('click', function (event) {
        if (picker.open && !picker.contains(event.target)) {
          picker.open = false;
        }
      });

      syncLabel();
    }
  );

  Array.prototype.forEach.call(
    document.querySelectorAll('form[data-confirm]'),
    function (form) {
      form.addEventListener('submit', function (event) {
        if (!window.confirm(form.getAttribute('data-confirm'))) {
          event.preventDefault();
        }
      });
    }
  );

  var chatForm = document.querySelector('.chat-form');
  if (chatForm) {
    chatForm.addEventListener('submit', function () {
      var button = chatForm.querySelector('button[type="submit"]');
      if (button) {
        button.disabled = true;
      }
    });
  }

  Array.prototype.forEach.call(
    document.querySelectorAll('[data-copy]'),
    function (button) {
      button.addEventListener('click', function () {
        var box = document.querySelector('[data-copy-target]');
        if (!box) {
          return;
        }
        var text = box.textContent;
        var done = function () {
          var old = button.textContent;
          button.textContent = '已复制';
          window.setTimeout(function () {
            button.textContent = old;
          }, 1500);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(done, done);
        } else {
          done();
        }
      });
    }
  );

  if (window.location.hash === '#new') {
    var newBox = document.querySelector('.new-project');
    if (newBox) {
      newBox.open = true;
      newBox.scrollIntoView({ block: 'center' });
    }
  }

  var agentToggle = document.querySelector('[data-agent-toggle]');
  var agentInput = document.querySelector('[data-agent-input]');
  var planToggle = document.querySelector('[data-plan-toggle]');
  var messageInput = document.querySelector('.chat-form textarea[name="message"]');
  if (agentInput) {
    var agentCookie = agentToggle
      ? agentToggle.getAttribute('data-agent-cookie')
      : 'agent_mode';
    var agentOn =
      ('; ' + document.cookie).indexOf('; ' + agentCookie + '=1') !== -1;
    var planOn = false;
    var kickoffToggle = document.querySelector('[data-kickoff-toggle]');
    var kickoffOn = false;

    var paintAgent = function () {
      if (agentToggle) {
        agentToggle.classList.toggle('is-on', agentOn);
        agentToggle.setAttribute('aria-pressed', agentOn ? 'true' : 'false');
      }
      if (planToggle) {
        planToggle.classList.toggle('is-on', planOn);
        planToggle.setAttribute('aria-pressed', planOn ? 'true' : 'false');
      }
      if (kickoffToggle) {
        kickoffToggle.classList.toggle('is-on', kickoffOn);
        kickoffToggle.setAttribute('aria-pressed', kickoffOn ? 'true' : 'false');
      }
      agentInput.value = agentOn
        ? 'agent'
        : planOn
          ? 'plan'
          : kickoffOn
            ? 'kickoff'
            : 'chat';
      if (messageInput) {
        messageInput.placeholder = agentOn
          ? '说目标，Agent 会先读项目再给计划…'
          : planOn
            ? '说清要做什么，AI 拆成任务树草案…'
            : kickoffOn
              ? '说清要做的项目，多个 AI 开立项会讨论…'
              : '说需求；输入 @ 或点「@成员」叫外部工具…';
      }
    };

    if (agentToggle) {
      agentToggle.addEventListener('click', function () {
        agentOn = !agentOn;
        if (agentOn) {
          planOn = false;
          kickoffOn = false;
        }
        document.cookie =
          agentCookie +
          '=' +
          (agentOn ? '1' : '0') +
          '; path=/; max-age=' +
          90 * 24 * 3600 +
          '; samesite=lax';
        paintAgent();
      });
    }

    if (planToggle) {
      planToggle.addEventListener('click', function () {
        planOn = !planOn;
        if (planOn) {
          agentOn = false;
          kickoffOn = false;
          document.cookie =
            agentCookie + '=0; path=/; max-age=' + 90 * 24 * 3600 + '; samesite=lax';
        }
        paintAgent();
      });
    }

    if (kickoffToggle) {
      kickoffToggle.addEventListener('click', function () {
        kickoffOn = !kickoffOn;
        if (kickoffOn) {
          agentOn = false;
          planOn = false;
          document.cookie =
            agentCookie + '=0; path=/; max-age=' + 90 * 24 * 3600 + '; samesite=lax';
        }
        paintAgent();
      });
    }

    paintAgent();
  }

  // 模糊输入提示：命中两项以上才提示确认提示词。
  var fuzzyBox = document.querySelector('[data-fuzzy-hint]');
  var fuzzyForm = document.querySelector('.chat-form');
  var fuzzyText = document.querySelector('.chat-form textarea[name="message"]');
  var fuzzyMode = document.querySelector('[data-mode-input]') || document.querySelector('select[name="mode"]');
  var fuzzyDismissBtn = document.querySelector('[data-fuzzy-dismiss]');
  var fuzzyAcceptBtn = document.querySelector('[data-fuzzy-accept]');
  var fuzzyIgnored = '';

  function fuzzyScore(value) {
    var text = (value || '').trim();
    if (!text) {
      return 0;
    }
    var verbs = /(做|改|加|删|实现|设计|写|拆|优化|检查|修|部署|画|整理|接入|迁移|重构|测试|发布|换成|替换)/;
    var score = 0;
    if (!verbs.test(text)) {
      score += 2;
    }
    if (/(它|这个|那个|这里|那里|这块|这些)/.test(text) && text.length < 30) {
      score += 1;
    }
    if (verbs.test(text) && text.length < 10) {
      score += 1;
    }
    return score;
  }

  function refreshFuzzy() {
    if (!fuzzyBox || !fuzzyText) {
      return;
    }
    if (fuzzyMode && fuzzyMode.value !== 'chat') {
      fuzzyBox.hidden = true;
      return;
    }
    var text = fuzzyText.value;
    if (!text.trim() || text === fuzzyIgnored) {
      fuzzyBox.hidden = true;
      return;
    }
    fuzzyBox.hidden = fuzzyScore(text) < 2;
  }

  if (fuzzyText && fuzzyBox) {
    fuzzyText.addEventListener('input', refreshFuzzy);
    if (fuzzyMode) {
      fuzzyMode.addEventListener('change', refreshFuzzy);
    }
    if (fuzzyDismissBtn) {
      fuzzyDismissBtn.addEventListener('click', function () {
        fuzzyIgnored = fuzzyText.value;
        fuzzyBox.hidden = true;
        fuzzyText.focus();
      });
    }
    if (fuzzyAcceptBtn) {
      fuzzyAcceptBtn.addEventListener('click', function () {
        if (fuzzyMode) {
          fuzzyMode.value = 'prompt';
        }
        fuzzyBox.hidden = true;
        fuzzyText.focus();
      });
    }
    if (fuzzyForm) {
      fuzzyForm.addEventListener('submit', function (event) {
        if (fuzzyMode && fuzzyMode.value !== 'chat') {
          return;
        }
        if (fuzzyScore(fuzzyText.value) >= 2 && fuzzyText.value !== fuzzyIgnored) {
          event.preventDefault();
          fuzzyBox.hidden = false;
          fuzzyText.focus();
        }
      });
    }
  }


  // 模式下拉：自定义样式 + 记住上次选择
  document.querySelectorAll('[data-mode-picker]').forEach(function (picker) {
    var input = picker.querySelector('[data-mode-input]');
    var trigger = picker.querySelector('[data-mode-trigger]');
    var label = picker.querySelector('[data-mode-label]');
    var menu = picker.querySelector('[data-mode-menu]');
    var options = Array.prototype.slice.call(menu.querySelectorAll('li'));
    var key = 'workroom_mode_' + (picker.getAttribute('data-project') || '0');

    function paint(value, persist) {
      var match = options.filter(function (item) {
        return item.getAttribute('data-value') === value;
      })[0] || options[0];
      options.forEach(function (item) {
        item.classList.toggle('is-on', item === match);
      });
      input.value = match.getAttribute('data-value');
      label.textContent = match.textContent;
      if (persist) {
        try {
          localStorage.setItem(key, input.value);
        } catch (err) {}
      }
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }

    var saved = '';
    try {
      saved = localStorage.getItem(key) || '';
    } catch (err) {}
    paint(saved || input.value, false);

    trigger.addEventListener('click', function (event) {
      event.stopPropagation();
      menu.hidden = !menu.hidden;
      trigger.setAttribute('aria-expanded', menu.hidden ? 'false' : 'true');
    });
    options.forEach(function (option) {
      option.addEventListener('click', function () {
        paint(option.getAttribute('data-value'), true);
        menu.hidden = true;
        trigger.setAttribute('aria-expanded', 'false');
        trigger.focus();
      });
    });
    document.addEventListener('click', function () {
      menu.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
    });
  });


  // 选择工作区：本地模式下打开系统文件夹选择器
  document.querySelectorAll('[data-path-pick]').forEach(function (button) {
    button.addEventListener('click', function () {
      var input = document.getElementById('workspace-path');
      var tokenInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
      if (!input || !tokenInput) {
        return;
      }
      button.disabled = true;
      fetch(button.getAttribute('data-url'), {
        method: 'POST',
        headers: { 'X-CSRFToken': tokenInput.value }
      })
        .then(function (response) { return response.json(); })
        .then(function (data) {
          if (data.path) {
            input.value = data.path;
          } else if (data.error) {
            window.alert('打不开文件夹选择器：' + data.error);
          }
        })
        .catch(function () {
          window.alert('打不开文件夹选择器，请手动填路径。');
        })
        .finally(function () {
          button.disabled = false;
        });
    });
  });

  // @ 提及：只把成员名插入光标处，不发请求，也不唤醒外部工具。
  var mentionInput = document.querySelector('[data-mention-input]');
  var mentionMenu = document.querySelector('[data-mention-menu]');
  var mentionList = document.querySelector('[data-mention-list]');
  var mentionEmpty = document.querySelector('[data-mention-empty]');
  var mentionData = document.getElementById('mention-candidates');
  var mentionItems = [];
  var mentionMatches = [];
  var mentionIndex = 0;
  var mentionComposing = false;
  if (mentionData) {
    try {
      mentionItems = JSON.parse(mentionData.textContent) || [];
    } catch (error) {
      mentionItems = [];
    }
  }

  function mentionToken() {
    if (!mentionInput) {
      return null;
    }
    if (mentionInput.selectionStart !== mentionInput.selectionEnd) {
      return null;
    }
    var caret = mentionInput.selectionStart;
    var before = mentionInput.value.slice(0, caret);
    var match = before.match(/@([^\s@]*)$/);
    if (!match) {
      return null;
    }
    var start = caret - match[1].length - 1;
    if (start > 0 && /[A-Za-z0-9._%+\-]/.test(before.charAt(start - 1))) {
      return null;
    }
    return { start: start, query: match[1] };
  }

  function closeMentions() {
    if (!mentionMenu) {
      return;
    }
    mentionMenu.hidden = true;
    mentionInput.setAttribute('aria-expanded', 'false');
    mentionInput.removeAttribute('aria-activedescendant');
    mentionMatches = [];
    mentionIndex = 0;
  }

  function paintMentions() {
    if (!mentionList) {
      return;
    }
    Array.prototype.forEach.call(mentionList.children, function (node, index) {
      node.setAttribute('aria-selected', index === mentionIndex ? 'true' : 'false');
      if (index === mentionIndex) {
        node.scrollIntoView({ block: 'nearest' });
      }
    });
    var active = mentionList.children[mentionIndex];
    if (active) {
      mentionInput.setAttribute('aria-activedescendant', active.id);
    } else {
      mentionInput.removeAttribute('aria-activedescendant');
    }
  }

  function renderMentions(query) {
    if (!mentionList || !mentionMenu) {
      return;
    }
    var needle = query.toLowerCase();
    mentionMatches = mentionItems.filter(function (item) {
      var haystack = [item.name, item.role, item.kindLabel, item.detail]
        .join(' ')
        .toLowerCase();
      return !needle || haystack.indexOf(needle) !== -1;
    });
    mentionIndex = 0;
    mentionList.textContent = '';
    mentionMatches.forEach(function (item, index) {
      var option = document.createElement('li');
      option.className = 'mention-option';
      option.id = 'mention-option-' + index;
      option.setAttribute('role', 'option');
      option.setAttribute('aria-selected', index === 0 ? 'true' : 'false');
      option.setAttribute('data-mention-index', String(index));

      var avatar = document.createElement('span');
      avatar.className = 'mention-avatar mention-avatar-' + item.kind;
      avatar.textContent = item.initial || '';

      var body = document.createElement('span');
      body.className = 'mention-body';
      var name = document.createElement('span');
      name.className = 'mention-name';
      name.textContent = '@' + item.name;
      var meta = document.createElement('span');
      meta.className = 'mention-meta';
      meta.textContent = item.kindLabel + (item.detail ? ' · ' + item.detail : '');
      body.appendChild(name);
      body.appendChild(meta);

      option.appendChild(avatar);
      option.appendChild(body);
      mentionList.appendChild(option);
    });
    if (mentionEmpty) {
      mentionEmpty.hidden = mentionMatches.length > 0;
    }
    mentionMenu.hidden = false;
    mentionInput.setAttribute('aria-expanded', 'true');
    paintMentions();
  }

  function refreshMentions() {
    if (!mentionInput || !mentionMenu || mentionComposing) {
      return;
    }
    var token = mentionToken();
    if (!token) {
      closeMentions();
      return;
    }
    renderMentions(token.query);
  }

  function insertMention(item) {
    if (!mentionInput || !item) {
      return;
    }
    var token = mentionToken();
    if (!token) {
      return;
    }
    var caret = mentionInput.selectionStart;
    var value = mentionInput.value;
    var text = '@' + item.name;
    mentionInput.value =
      value.slice(0, token.start) + text + ' ' + value.slice(caret);
    var next = token.start + text.length + 1;
    mentionInput.focus();
    mentionInput.setSelectionRange(next, next);
    closeMentions();
  }

  var mentionButton = document.querySelector('[data-mention-button]');
  if (mentionButton && mentionInput) {
    mentionButton.addEventListener('click', function (event) {
      event.preventDefault();
      event.stopPropagation();
      var start = mentionInput.selectionStart || mentionInput.value.length;
      var end = mentionInput.selectionEnd || start;
      mentionInput.value =
        mentionInput.value.slice(0, start) + '@' + mentionInput.value.slice(end);
      mentionInput.focus();
      mentionInput.setSelectionRange(start + 1, start + 1);
      renderMentions('');
      mentionMenu.removeAttribute('hidden');
      mentionInput.setAttribute('aria-expanded', 'true');
      mentionInput.dispatchEvent(new Event('input', { bubbles: true }));
    });
  }

  if (mentionInput && mentionMenu) {
    mentionInput.addEventListener('compositionstart', function () {
      mentionComposing = true;
      closeMentions();
    });
    mentionInput.addEventListener('compositionend', function () {
      mentionComposing = false;
      window.setTimeout(refreshMentions, 0);
    });
    mentionInput.addEventListener('input', function () {
      if (!mentionComposing) {
        refreshMentions();
      }
    });
    mentionInput.addEventListener('keydown', function (event) {
      if (event.isComposing || event.keyCode === 229) {
        return;
      }
      if (mentionMenu.hidden) {
        return;
      }
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        if (!mentionMatches.length) {
          return;
        }
        event.preventDefault();
        var step = event.key === 'ArrowDown' ? 1 : -1;
        mentionIndex =
          (mentionIndex + step + mentionMatches.length) % mentionMatches.length;
        paintMentions();
      } else if (event.key === 'Enter') {
        event.preventDefault();
        if (event.stopImmediatePropagation) {
          event.stopImmediatePropagation();
        }
        if (mentionMatches.length) {
          insertMention(mentionMatches[mentionIndex]);
        }
      } else if (event.key === 'Escape') {
        event.preventDefault();
        closeMentions();
      }
    });
    mentionList.addEventListener('mousedown', function (event) {
      event.preventDefault();
    });
    mentionList.addEventListener('click', function (event) {
      var option = event.target.closest('[data-mention-index]');
      if (!option) {
        return;
      }
      insertMention(mentionMatches[Number(option.getAttribute('data-mention-index'))]);
    });
    document.addEventListener('click', function (event) {
      if (
        !mentionMenu.hidden &&
        event.target !== mentionInput &&
        !mentionMenu.contains(event.target)
      ) {
        closeMentions();
      }
    });
  }

  if (messageInput) {
    if (planToggle && !agentToggle && agentInput) {
      planToggle.addEventListener('click', function () {
        var selected = planToggle.getAttribute('aria-pressed') !== 'true';
        planToggle.setAttribute('aria-pressed', selected ? 'true' : 'false');
        planToggle.classList.toggle('is-on', selected);
        agentInput.value = selected ? 'plan' : 'chat';
      });
    }
    messageInput.addEventListener('keydown', function (event) {
      if (event.defaultPrevented || event.isComposing || event.keyCode === 229) {
        return;
      }
      if (mentionMenu && !mentionMenu.hidden) {
        return;
      }
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        if (chatForm) {
          chatForm.requestSubmit();
        }
      }
    });
  }

  var pending = document.querySelectorAll('[data-job]');
  var jobsHost = document.querySelector('[data-jobs-url]');
  if (pending.length && jobsHost) {
    var jobsUrl = jobsHost.getAttribute('data-jobs-url');

    function paint(job) {
      var node = document.querySelector('[data-job="' + job.id + '"]');
      if (!node) {
        return;
      }
      var answer = node.querySelector('[data-job-answer]');
      var reasonBox = node.querySelector('[data-job-reasoning]');
      var reasonText = node.querySelector('[data-job-reasoning-text]');
      var meta = node.querySelector('[data-job-meta]');

      if (answer) {
        answer.textContent =
          job.answer ||
          (job.phase === 'thinking'
            ? '正在思考…'
            : job.phase === 'planning'
              ? '正在拆解任务…'
              : job.phase === 'proposal' ||
                  job.phase === 'review' ||
                  job.phase === 'decision'
                ? '正在组织讨论…'
                : '正在连接模型…');
      }
      if (reasonBox && reasonText && job.reasoning) {
        reasonBox.hidden = false;
        reasonBox.open = true;
        if (reasonText.getAttribute('data-raw') !== job.reasoning) {
          reasonText.setAttribute('data-raw', job.reasoning);
          var escaped = job.reasoning
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
          escaped = escaped.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
          var lines = escaped.split(String.fromCharCode(10));
          for (var lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
            lines[lineIndex] = lines[lineIndex].replace(/^\s*[-*]\s+/, '• ');
          }
          reasonText.innerHTML = lines.join('<br>');
        }
      }
      if (meta) {
        var phase =
          job.phase === 'answering'
            ? '正在回答'
            : job.phase === 'thinking'
              ? '思考中'
              : job.phase === 'planning'
                ? '正在拆任务'
                : job.phase === 'proposal'
                  ? '提议中'
                  : job.phase === 'review'
                    ? '评审中'
                    : job.phase === 'decision'
                      ? '决策中'
                      : '连接中';
        meta.textContent =
          phase +
          ' · ' +
          job.elapsed +
          ' 秒 · ' +
          (job.answer ? job.answer.length + ' 字' : '等待首个字');
      }
    }

    function followBottom() {
      var box = document.querySelector('.chat-log');
      return box && box.scrollHeight - box.scrollTop - box.clientHeight < 90;
    }

    var pollInFlight = false;
    var timer = window.setInterval(function () {
      if (document.hidden || pollInFlight) { return; }
      pollInFlight = true;
      fetch(jobsUrl, {
        headers: { 'Accept': 'application/json' },
        cache: 'no-store'
      })
        .then(function (response) { return response.json(); })
        .then(function (data) {
          var follow = followBottom();
          (data.jobs || []).forEach(paint);
          if (follow) {
            var box = document.querySelector('.chat-log');
            if (box) {
              box.scrollTop = box.scrollHeight;
            }
          }
          if (!(data.jobs || []).length) {
            window.clearInterval(timer);
            var unsent = document.querySelector('.chat-form textarea[name="message"]');
            if (unsent && unsent.value.trim()) {
              var refreshHint = document.querySelector('[data-project-update]');
              if (refreshHint) { refreshHint.hidden = false; }
              return;
            }
            window.location.reload();
          }
        })
        .catch(function () {})
        .finally(function () { pollInFlight = false; });
    }, Number(jobsHost.getAttribute('data-poll-ms')) || 700);
  }

  var log = document.querySelector('.chat-log');
  if (log) {
    log.scrollTop = log.scrollHeight;
  }

  Array.prototype.forEach.call(
    document.querySelectorAll('select[data-auto-submit]'),
    function (select) {
      select.addEventListener('change', function () {
        if (select.form) {
          select.form.submit();
        }
      });
    }
  );

  var add = document.querySelector('.add');
  if (add) {
    add.addEventListener('toggle', function () {
      if (!add.open) {
        return;
      }
      var field = add.querySelector('input[name="title"]');
      if (field) {
        field.focus();
      }
    });
  }

  var canvas = document.querySelector('.tree-canvas');
  var zoomBox = document.querySelector('[data-zoom-controls]');
  if (canvas && zoomBox) {
    var zoomKey = zoomBox.getAttribute('data-zoom-key') || 'tree-zoom';
    var zoomLabel = zoomBox.querySelector('[data-zoom-label]');
    var storedZoom = '1';
    try {
      storedZoom = window.localStorage.getItem(zoomKey) || '1';
    } catch (error) {
      /* A privacy policy or embedded browser can disable storage reads. */
    }
    var zoom = parseFloat(storedZoom);
    if (!isFinite(zoom) || zoom <= 0) {
      zoom = 1;
    }

    var applyZoom = function (value, persist) {
      zoom = Math.min(1.8, Math.max(0.25, value));
      canvas.style.zoom = zoom;
      if (zoomLabel) {
        zoomLabel.textContent = Math.round(zoom * 100) + '%';
      }
      if (persist) {
        try {
          window.localStorage.setItem(zoomKey, String(zoom));
        } catch (error) {
          /* storage may be unavailable */
        }
      }
    };

    var fitZoom = function () {
      var box = document.querySelector('.tree-scroll');
      if (!box) {
        return zoom;
      }
      var size = Math.min(
        (box.clientWidth - 36) / canvas.offsetWidth,
        (box.clientHeight - 36) / canvas.offsetHeight,
        1
      );
      return size;
    };

    var zoomIn = zoomBox.querySelector('[data-zoom-in]');
    var zoomOut = zoomBox.querySelector('[data-zoom-out]');
    var zoomFit = zoomBox.querySelector('[data-zoom-fit]');
    if (zoomIn) {
      zoomIn.addEventListener('click', function () {
        applyZoom(zoom + 0.1, true);
      });
    }
    if (zoomOut) {
      zoomOut.addEventListener('click', function () {
        applyZoom(zoom - 0.1, true);
      });
    }
    if (zoomFit) {
      zoomFit.addEventListener('click', function () {
        applyZoom(fitZoom(), true);
      });
    }
    applyZoom(zoom, false);
  }

  // 只读详情：打开时把焦点放进正文，关闭后回到原来那行/节点。
  var taskReader = document.querySelector('[data-task-reader]');
  var libraryReader = document.querySelector('[data-library-reader]');
  var readerSettingsToggle = document.querySelector('[data-reader-settings-toggle]');
  var readingWorkspace = document.querySelector('.workspace-reading');
  function closeReaderSettings() {
    if (readingWorkspace && readerSettingsToggle) {
      readingWorkspace.classList.remove('is-reader-settings-open');
      readerSettingsToggle.setAttribute('aria-expanded', 'false');
    }
  }
  if (readerSettingsToggle && readingWorkspace) {
    readerSettingsToggle.addEventListener('click', function () {
      var open = readingWorkspace.classList.toggle('is-reader-settings-open');
      readerSettingsToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }
  var params = new URLSearchParams(window.location.search);
  var focusTask = params.get('focus');
  var focusEntry = params.get('focusEntry');
  if (focusTask && /^\d+$/.test(focusTask)) {
    var focusNode = document.querySelector('.node[data-task-id="' + focusTask + '"]') ||
      document.querySelector('[data-task-open][data-task-id="' + focusTask + '"]');
    if (focusNode) {
      focusNode.focus();
    }
  } else if (focusEntry && /^\d+$/.test(focusEntry)) {
    var focusRow = document.querySelector('[data-entry-id="' + focusEntry + '"]');
    if (focusRow) {
      focusRow.focus();
    }
  } else if (taskReader || libraryReader) {
    (taskReader || libraryReader).focus({ preventScroll: true });
  }
  if (taskReader || libraryReader) {
    document.addEventListener('keydown', function (event) {
      if (event.key !== 'Escape') {
        return;
      }
      if (readingWorkspace && readingWorkspace.classList.contains('is-reader-settings-open')) {
        event.preventDefault();
        closeReaderSettings();
        readerSettingsToggle.focus();
        return;
      }
      var close = document.querySelector('[data-task-close], [data-library-close]');
      if (close) {
        event.preventDefault();
        close.click();
      }
    });
  }

  var tree = document.querySelector('.tree-scroll');
  if (!tree) {
    return;
  }

  var selected = document.querySelector('.node.is-selected');
  if (!selected && focusTask) {
    selected = focusNode;
  }
  var goal = document.querySelector('.node-goal');

  function centre(node) {
    if (!node) {
      return;
    }
    var nodeBox = node.getBoundingClientRect();
    var treeBox = tree.getBoundingClientRect();
    tree.scrollLeft += nodeBox.left + nodeBox.width / 2 - treeBox.left - tree.clientWidth / 2;
    tree.scrollTop += nodeBox.top + nodeBox.height / 2 - treeBox.top - tree.clientHeight / 2;
  }

  if (selected) {
    centre(selected);
  } else {
    tree.scrollLeft = 0;
    tree.scrollTop = 0;
  }
})();
document.querySelectorAll('[data-copy-target]').forEach((button) => {
  button.addEventListener('click', async () => {
    const target = document.getElementById(button.dataset.copyTarget);
    if (!target) return;
    try {
      await navigator.clipboard.writeText(target.textContent);
      button.textContent = '已复制';
    } catch {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(target);
      selection.removeAllRanges();
      selection.addRange(range);
      button.textContent = '已选中，请复制';
    }
  });
});
