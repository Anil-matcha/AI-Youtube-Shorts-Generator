/* Bounded channel/playlist discovery and batch queue controls. */
(() => {
  const $ = id => document.getElementById(id);
  const state = window.ShortsStudioState?.state;
  const esc = window.ShortsStudioUI?.esc || (value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char])));
  const api = (url, options = {}) => window.ShortsStudioAPI?.json
    ? window.ShortsStudioAPI.json(url, options)
    : fetch(url, options).then(async response => {
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw Error(data.error || data.detail || `Request failed (${response.status})`);
      return data;
    });

  function headers() {
    const credentials = state?.credentials || {};
    const result = {'Content-Type': 'application/json'};
    if (credentials.muapi) result['X-MuAPI-Key'] = credentials.muapi;
    if (credentials.openai) result['X-OpenAI-Key'] = credentials.openai;
    if (credentials.gemini) result['X-Gemini-Key'] = credentials.gemini;
    return result;
  }

  function payload() {
    return {
      source: $('channelBatchSource')?.value.trim() || '',
      max_items: Math.max(1, Math.min(50, Number($('channelBatchLimit')?.value || 10))),
      mode: $('mode')?.value || 'local',
      num_clips: Math.max(1, Math.min(12, Number($('numClips')?.value || 3))),
      aspect_ratio: $('aspect')?.value || '9:16',
      download_format: $('format')?.value || '720',
      language: $('language')?.value || null,
      factory_mode: Boolean($('channelBatchFactory')?.checked),
      name_prefix: $('channelBatchPrefix')?.value.trim() || null
    };
  }

  function showEntries(entries) {
    const node = $('channelBatchPreview');
    if (!node) return;
    node.innerHTML = (entries || []).map((item, index) => `<div class="insight-row"><span class="badge">${index + 1}</span><div><strong>${esc(item.title || 'Untitled video')}</strong><small>${esc(item.url)}</small></div></div>`).join('') || '<div class="empty">Preview videos to inspect the bounded queue.</div>';
  }

  async function preview() {
    const status = $('channelBatchStatus');
    const button = $('channelPreviewButton');
    const body = payload();
    if (!body.source) { if (status) status.textContent = 'Enter a YouTube channel or playlist URL first.'; return null; }
    if (button) button.disabled = true;
    if (status) status.textContent = 'Inspecting the channel without downloading media…';
    try {
      const data = await api('/api/channel/preview', {method: 'POST', headers: headers(), body: JSON.stringify(body)});
      showEntries(data.entries);
      if (status) status.textContent = `${data.count} video(s) ready to queue. Preview does not download source media.`;
      return data;
    } catch (error) { if (status) status.textContent = error.message; return null; }
    finally { if (button) button.disabled = false; }
  }

  async function queue() {
    const status = $('channelBatchStatus');
    const button = $('channelQueueButton');
    const body = payload();
    if (!body.source) { if (status) status.textContent = 'Enter and preview a YouTube channel or playlist first.'; return; }
    if (!confirm(`Resolve and queue up to ${body.max_items} videos as separate Shorts Studio projects?`)) return;
    if (button) button.disabled = true;
    if (status) status.textContent = 'Resolving videos and queueing projects…';
    try {
      const data = await api('/api/channel/batch', {method: 'POST', headers: headers(), body: JSON.stringify(body)});
      if (state) { state.batchJobs = Array.isArray(data.jobs) ? data.jobs : []; state.batchActive = state.batchJobs.length > 1; }
      if (status) status.textContent = `Queued ${data.count || 0} project(s). Open the workspace queue to monitor progress.`;
      document.dispatchEvent(new CustomEvent('shorts:jobs-changed'));
    } catch (error) { if (status) status.textContent = error.message; }
    finally { if (button) button.disabled = false; }
  }

  function mount() {
    $('channelPreviewButton')?.addEventListener('click', preview);
    $('channelQueueButton')?.addEventListener('click', queue);
    $('channelBatchSource')?.addEventListener('change', () => showEntries([]));
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once: true});
  else mount();
})();
