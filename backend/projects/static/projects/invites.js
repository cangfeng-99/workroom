// T017: copy a still-valid invitation link. Success is only announced after
// the clipboard write resolves; otherwise the link is selected for Ctrl+C.
(function () {
  'use strict';

  var hint = document.querySelector('[data-copy-hint]');

  document.querySelectorAll('[data-copy-invite]').forEach(function (button) {
    button.addEventListener('click', function () {
      var input = document.getElementById(button.dataset.copyInvite);
      if (!input) return;
      var done = function () {
        button.textContent = '已复制';
        if (hint) hint.hidden = true;
      };
      var fallback = function () {
        button.textContent = '请手动复制';
        input.focus();
        input.select();
        if (hint) hint.hidden = false;
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(input.value).then(done, fallback);
      } else {
        fallback();
      }
    });
  });
})();
