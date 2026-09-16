/* DOM, feedback, accessibility, and loading-state primitives. */
(() => {
  const dom = id => document.getElementById(id);
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
  const finiteNumber = (value, fallback = 0) => {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  };
  const fmtTime = value => {
    const number = Math.max(0, finiteNumber(value));
    return `${Math.floor(number / 60)}:${String(Math.floor(number % 60)).padStart(2, '0')}`;
  };
  const fmtDate = value => {
    const number = finiteNumber(value, NaN);
    if (!Number.isFinite(number) || number <= 0) return '';
    const date = new Date(number * 1000);
    return Number.isNaN(date.getTime()) ? '' : date.toLocaleString([], {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'
    });
  };

  let toastTimer = null;
  const persistentErrors = new Map();

  function ensureNotificationCenter() {
    let center = dom('notificationCenter');
    if (center) return center;
    center = document.createElement('aside');
    center.id = 'notificationCenter';
    center.className = 'notification-center';
    center.setAttribute('aria-label', 'Persistent notifications');
    center.setAttribute('aria-live', 'polite');
    document.body.appendChild(center);
    return center;
  }

  function dismissNotification(key) {
    const entry = persistentErrors.get(key);
    if (entry) entry.remove();
    persistentErrors.delete(key);
  }

  function rememberError(message) {
    const key = String(message || 'Something went wrong');
    if (persistentErrors.has(key)) return;
    const center = ensureNotificationCenter();
    const entry = document.createElement('div');
    entry.className = 'notification notification-error';
    entry.setAttribute('role', 'alert');
    const text = document.createElement('span');
    text.textContent = key;
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'notification-dismiss';
    close.setAttribute('aria-label', 'Dismiss notification');
    close.textContent = '×';
    close.addEventListener('click', () => dismissNotification(key));
    entry.append(text, close);
    center.appendChild(entry);
    persistentErrors.set(key, entry);
  }

  function toast(message, bad = false, options = {}) {
    const element = dom('toast');
    if (!element) return;
    const text = String(message || '');
    element.textContent = text;
    element.style.borderColor = bad ? 'var(--danger-border)' : 'var(--info-line)';
    element.classList.toggle('toast-error', Boolean(bad));
    element.classList.add('show');
    if (bad && options.persist !== false) rememberError(text);
    if (toastTimer) clearTimeout(toastTimer);
    if (!options.persist && !bad) {
      toastTimer = setTimeout(() => element.classList.remove('show'), 3500);
    } else if (!bad) {
      toastTimer = setTimeout(() => element.classList.remove('show'), 3500);
    }
  }

  function skeletonMarkup(kind = 'card') {
    return `<div class="skeleton skeleton-${escapeHtml(kind)}" aria-hidden="true"><span></span><span></span><span></span></div>`;
  }

  function showSkeletons(container, count = 3, kind = 'card') {
    if (!container) return;
    container.setAttribute('aria-busy', 'true');
    container.innerHTML = Array.from({length: Math.max(1, count)}, () => skeletonMarkup(kind)).join('');
  }

  function clearBusy(container) {
    if (container) container.removeAttribute('aria-busy');
  }

  function progressPercent(job) {
    const status = String(job?.status || '').toLowerCase();
    if (status === 'done') return 100;
    if (status === 'error' || status === 'cancelled') return Math.max(0, finiteNumber(job?.progress));
    return Math.min(99, Math.max(0, finiteNumber(job?.progress)));
  }

  function renderProgress(container, job, label = '') {
    if (!container) return;
    const value = progressPercent(job);
    const message = label || job?.message || job?.stage || 'Waiting for work';
    container.innerHTML = `<div class="progress-head"><span>${escapeHtml(message)}</span><strong>${Math.round(value)}%</strong></div><div class="progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(value)}" aria-label="Job progress"><span style="width:${value}%"></span></div>`;
  }

  function announce(message) {
    const live = dom('liveRegion') || (() => {
      const node = document.createElement('div');
      node.id = 'liveRegion';
      node.className = 'sr-only';
      node.setAttribute('aria-live', 'polite');
      document.body.appendChild(node);
      return node;
    })();
    live.textContent = String(message || '');
  }

  function setView(name) {
    document.querySelectorAll('.view').forEach(view => view.classList.toggle('active', view.id === `${name}View`));
    document.querySelectorAll('.nav button').forEach(button => {
      const active = button.dataset.view === name;
      button.classList.toggle('active', active);
      if (active) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });
    const navButton = [...document.querySelectorAll('.nav button')].find(button => button.dataset.view === name);
    const title = navButton?.querySelector('span:last-child');
    if (dom('crumbTitle') && title) dom('crumbTitle').textContent = title.textContent;
  }

  window.ShortsStudioUI = {
    $: dom, dom, escapeHtml, esc: escapeHtml, finiteNumber, fmtTime, fmtDate,
    toast, showSkeletons, clearBusy, progressPercent, renderProgress, announce,
    setView, dismissNotification
  };
})();
