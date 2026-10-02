/* Human review and explicit dispatch of provider-side publishing schedules. */
(() => {
  const $ = id => document.getElementById(id);
  const state = window.ShortsStudioState?.state;
  const api = (url, options = {}) => window.ShortsStudioAPI.json(url, options);
  const pending = new Set();
  let entries = [];
  let capabilities = {};
  let loadedJob = '';
  let refreshing = false;
  const currentJob = () => String(state?.activeJobId || '');
  const setStatus = message => { if ($('scheduleReviewStatus')) $('scheduleReviewStatus').textContent = String(message || ''); };
  const jsonOptions = body => ({method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});

  function text(tag, value, className = '') {
    const node = document.createElement(tag);
    node.textContent = String(value || '');
    node.className = className;
    return node;
  }

  function action(parent, label, scheduleId, callback, className = 'secondary') {
    const button = text('button', label, className);
    button.type = 'button';
    button.disabled = pending.has(scheduleId);
    button.addEventListener('click', callback);
    parent.append(button);
    return button;
  }

  function showEntries() {
    const node = $('scheduleReviewList');
    if (!node) return;
    node.replaceChildren();
    const values = entries.filter(entry => String(entry.job_id || '') === currentJob());
    if (!currentJob() || !values.length) {
      node.append(text('div', currentJob() ? 'No schedule intents for this project. Choose a future time above, then Queue private review.' : 'Open a completed project to review its schedule.', 'empty'));
      return;
    }
    values.slice(0, 200).forEach(entry => {
      const card = document.createElement('article');
      card.className = 'field';
      const request = entry.request || {};
      const platform = request.platform || 'youtube_shorts';
      const provider = capabilities.platforms?.[platform] || {};
      const publishDate = new Date(entry.publish_at);
      const timing = Number.isFinite(publishDate.getTime()) ? publishDate.toLocaleString() : String(entry.publish_at || 'Time unavailable');
      card.append(text('strong', `${platform === 'youtube_shorts' ? 'YouTube Shorts' : platform} · clip ${Number(entry.clip_index || 0) + 1}`));
      card.append(text('p', `${timing} (${Intl.DateTimeFormat().resolvedOptions().timeZone}) · ${String(entry.status || '').replaceAll('_', ' ')}`, 'setting-help'));
      if (request.title) card.append(text('p', request.title, 'setting-help'));
      if (request.description) card.append(text('p', request.description, 'setting-help'));
      if (entry.note) card.append(text('p', entry.note, 'setting-help'));
      if (entry.policy?.status) card.append(text('p', `Policy preflight: ${entry.policy.status}. Review the clip and its metadata before approving.`, 'setting-help'));
      const actions = document.createElement('div');
      actions.className = 'settings-actions';
      if (entry.status === 'pending_review') {
        action(actions, 'Approve review', entry.id, () => decide(entry.id, 'approved'));
        action(actions, 'Reject', entry.id, () => decide(entry.id, 'rejected'), 'ghost');
      }
      if (['approved_pending_publish', 'retryable_failed'].includes(entry.status) && provider.provider_scheduling) {
        card.append(text('p', `YouTube will make this video public at ${timing}. Dispatch uploads it now as a private video with that future publication time.`, 'setting-help'));
        const approval = document.createElement('label');
        approval.className = 'checkline';
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.disabled = !provider.authorized || pending.has(entry.id);
        approval.append(checkbox, document.createTextNode(' I approve this upload and its future public publication on YouTube'));
        card.append(approval);
        const button = action(actions, 'Dispatch to YouTube', entry.id, () => dispatch(entry.id, checkbox), 'primary');
        button.disabled = true;
        checkbox.addEventListener('change', () => { button.disabled = !checkbox.checked || !provider.authorized || pending.has(entry.id); });
        if (!provider.authorized) card.append(text('p', 'Connect your Google account above, then refresh the schedule to dispatch.', 'setting-help'));
      } else if (['pending_review', 'approved_pending_publish', 'retryable_failed'].includes(entry.status) && !provider.provider_scheduling) {
        card.append(text('p', 'This platform supports review intents only. Provider-side scheduling is unavailable.', 'setting-help'));
      }
      if (['pending_review', 'approved_pending_publish', 'retryable_failed'].includes(entry.status)) {
        action(actions, 'Cancel local intent', entry.id, () => cancel(entry.id), 'ghost');
      }
      if (['provider_scheduled', 'provider_dispatching', 'provider_unknown'].includes(entry.status)) {
        card.append(text('p', entry.status === 'provider_unknown'
          ? 'The upload result is unknown. Check YouTube Studio before any retry. Enter the uploaded video ID below to verify and reconcile this schedule.'
          : 'This schedule belongs to YouTube. Change or cancel its publication in YouTube Studio; removing a local intent cannot cancel a provider schedule.', 'setting-help'));
        const link = text('a', 'Open YouTube Studio', 'secondary');
        link.href = 'https://studio.youtube.com/';
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        actions.append(link);
      }
      if (entry.status === 'provider_scheduled') {
        card.append(text('p', 'Refresh checks the connected YouTube account without changing the video or its publication time.', 'setting-help'));
        const button = action(actions, 'Refresh provider status', entry.id, () => refreshProvider(entry.id));
        button.disabled = !provider.authorized || pending.has(entry.id);
        if (!provider.authorized) card.append(text('p', 'Connect your Google account above, then refresh the schedule to check its provider status.', 'setting-help'));
      }
      if (entry.status === 'provider_unknown') {
        const field = document.createElement('label');
        field.className = 'field';
        field.append(document.createTextNode('Uploaded YouTube video ID'));
        const input = document.createElement('input');
        input.className = 'input';
        input.maxLength = 11;
        input.pattern = '[A-Za-z0-9_-]{11}';
        input.required = true;
        input.placeholder = '11-character video ID';
        field.append(input);
        card.append(field);
        action(actions, 'Verify uploaded video', entry.id, () => reconcile(entry.id, input));
      }
      card.append(actions);
      node.append(card);
    });
  }

  async function refresh(report = true) {
    if (refreshing) return;
    refreshing = true;
    $('scheduleReviewRefresh').disabled = true;
    try {
      const [listed, supported] = await Promise.all([
        api('/api/v1/scheduler', {cache: 'no-store'}),
        api('/api/v1/scheduler/capabilities', {cache: 'no-store'})
      ]);
      entries = Array.isArray(listed.entries) ? listed.entries : [];
      capabilities = supported || {};
      loadedJob = currentJob();
      showEntries();
      if (report) setStatus(supported.notice || 'Review approval records your decision. Dispatch requires a separate confirmation and uploads to YouTube.');
    } catch (error) { setStatus(error.message); }
    finally { refreshing = false; $('scheduleReviewRefresh').disabled = false; }
  }

  async function mutate(scheduleId, suffix, options, success) {
    if (pending.has(scheduleId)) return;
    const job = currentJob();
    pending.add(scheduleId);
    showEntries();
    setStatus(suffix === '/dispatch' ? 'Uploading the approved clip and requesting its YouTube publication time…' : suffix === '/refresh' ? 'Checking this video through the connected YouTube account…' : 'Updating schedule…');
    try {
      const data = await api(`/api/v1/scheduler/${encodeURIComponent(scheduleId)}${suffix}`, options);
      if (currentJob() === job) setStatus(typeof success === 'function' ? success(data) : success);
    } catch (error) { if (currentJob() === job) setStatus(error.message); }
    finally { pending.delete(scheduleId); await refresh(false); }
  }

  function decide(id, decision) {
    return mutate(id, '/decision', jsonOptions({decision}), decision === 'approved' ? 'Review approved. Nothing uploads until you explicitly dispatch.' : 'Schedule review rejected.');
  }

  function dispatch(id, checkbox) {
    if (!checkbox.checked) { setStatus('Confirm the future public publication before dispatching.'); return; }
    if (!capabilities.platforms?.youtube_shorts?.authorized) { setStatus('Connect your Google account and refresh the schedule first.'); return; }
    return mutate(id, '/dispatch', jsonOptions({confirm: true, acknowledge_public_publish: true}), 'YouTube accepted the schedule. Manage or cancel its publication in YouTube Studio.');
  }

  function cancel(id) {
    return mutate(id, '', {method: 'DELETE'}, 'Local review intent cancelled.');
  }

  function reconcile(id, input) {
    if (!input.reportValidity()) return;
    return mutate(id, '/reconcile', jsonOptions({confirm: true, video_id: input.value.trim()}), 'YouTube video verified and schedule reconciled.');
  }

  function refreshProvider(id) {
    if (!capabilities.platforms?.youtube_shorts?.authorized) { setStatus('Connect your Google account and refresh the schedule first.'); return; }
    const messages = {
      provider_scheduled: 'YouTube confirms that this private video still has its scheduled publication time.',
      provider_published: 'YouTube confirms that this video is now public.',
      provider_unscheduled: 'YouTube confirms that this private video no longer has a scheduled publication time.',
      provider_rejected: 'YouTube reports that this upload failed or was rejected.',
      provider_removed: 'YouTube confirms that this video was deleted.'
    };
    return mutate(id, '/refresh', jsonOptions({confirm: true}), data => messages[data.status || data.entry?.status] || 'YouTube provider status checked.');
  }

  function syncProject() {
    if (loadedJob === currentJob()) return;
    loadedJob = currentJob();
    showEntries();
    if (currentJob()) refresh(false);
  }

  function mount() {
    const tab = $('exportTab');
    if (!tab || $('scheduleReviewControls')) return;
    const wrap = document.createElement('section');
    wrap.id = 'scheduleReviewControls';
    wrap.className = 'field feature-controls';
    wrap.innerHTML = `<h3>Scheduled publishing review</h3><p class="setting-help">Queue a private review intent using the controls above. Approve it after checking the clip, then choose whether to dispatch it to the supported provider.</p><button class="secondary" id="scheduleReviewRefresh" type="button">Refresh schedule</button><p class="setting-help" id="scheduleReviewStatus" role="status" aria-live="polite">YouTube dispatch requires a connected account and explicit approval of future public publication.</p><div id="scheduleReviewList"></div>`;
    tab.append(wrap);
    $('scheduleReviewRefresh').addEventListener('click', () => refresh());
    document.querySelector('[data-tab="exportTab"]')?.addEventListener('click', () => refresh());
    const observer = new MutationObserver(syncProject);
    ['jobIdBadge', 'jobBadge', 'clipGrid'].forEach(id => { if ($(id)) observer.observe($(id), {childList: true, attributes: true}); });
    document.addEventListener('shorts:jobs-changed', syncProject);
    showEntries();
    syncProject();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once: true});
  else mount();
})();
