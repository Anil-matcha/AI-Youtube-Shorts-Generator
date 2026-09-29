/* v2 performance loop, transparent style memory, and local model controls. */
(() => {
  const $ = id => document.getElementById(id);
  const esc = window.ShortsStudioUI?.esc || (value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char])));
  const api = (url, options = {}) => window.ShortsStudioAPI?.json
    ? window.ShortsStudioAPI.json(url, options)
    : fetch(url, options).then(async response => {
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw Error(data.error || data.detail || `Request failed (${response.status})`);
      return data;
    });
  const number = value => new Intl.NumberFormat(undefined, {notation: Number(value) >= 10000 ? 'compact' : 'standard', maximumFractionDigits: 1}).format(Number(value) || 0);
  const percent = value => `${Math.round((Number(value) || 0) * 100)}%`;
  const setText = (id, value) => { const node = $(id); if (node) node.textContent = String(value ?? ''); };
  let modelRefreshTimer = null;

  function renderRecommendations(items) {
    const node = $('performanceRecommendations');
    if (!node) return;
    const values = Array.isArray(items) ? items.filter(item => item && item.message) : [];
    node.innerHTML = values.length
      ? values.map(item => `<div class="insight-row"><span class="badge">${esc(item.code || 'signal')}</span><span>${esc(item.message)}</span></div>`).join('')
      : '<div class="empty">Record analytics to see recommendations.</div>';
  }

  function renderVariants(items) {
    const node = $('performanceVariants');
    if (!node) return;
    const values = Array.isArray(items) ? items.slice(0, 8) : [];
    node.innerHTML = values.length
      ? values.map(item => `<div class="insight-row"><div><strong>${esc(item.name || item.variant_id || 'Base clip')}</strong><small>${esc(item.project_name || 'Project')} · ${esc(item.platform || 'all platforms')}</small></div><span>${percent(item.completion_rate)} completion<br><small>${number(item.views)} views</small></span></div>`).join('')
      : '<div class="empty">No variant data yet.</div>';
  }

  function renderPublishing(data) {
    const node = $('performancePublishing');
    if (!node) return;
    const values = Array.isArray(data?.recent) ? data.recent.slice(0, 8) : [];
    node.innerHTML = values.length
      ? values.map(item => `<div class="insight-row"><div><strong>${esc(item.project_name || 'Project')}</strong><small>${esc(item.platform || 'platform')} · ${esc(item.privacy_status || 'private')}</small></div><span class="badge ${String(item.status || '').toLowerCase() === 'uploaded' ? 'done' : ''}">${esc(item.status || 'uploaded')}</span></div>`).join('')
      : '<div class="empty">Nothing published yet.</div>';
  }

  function renderStyle(profile) {
    const node = $('styleProfileSummary');
    if (!node) return;
    const preferences = profile?.preferences && typeof profile.preferences === 'object' ? profile.preferences : {};
    const entries = Object.entries(preferences).filter(([, value]) => value);
    const patterns = Array.isArray(profile?.patterns?.hooks) ? profile.patterns.hooks : [];
    node.innerHTML = entries.length || patterns.length
      ? `<div class="insight-row"><div><strong>${esc(profile?.name || 'My creator style')}</strong><small>${profile?.learned_at ? `Learned from ${number((profile.source_jobs || []).length)} project(s)` : 'Creator-authored profile'}</small></div></div><div class="style-chip-list">${entries.map(([key, value]) => `<span class="badge">${esc(key.replaceAll('_', ' '))}: ${esc(value)}</span>`).join('')}</div>${patterns.length ? `<p class="setting-help">Common hooks: ${esc(patterns.slice(0, 3).join(' · '))}</p>` : ''}`
      : '<div class="empty">No style profile learned yet.</div>';
    const notes = $('styleProfileNotes');
    if (notes && document.activeElement !== notes) notes.value = profile?.notes || '';
  }

  function renderModels(models) {
    const node = $('localModelList');
    if (!node) return;
    const values = Array.isArray(models) ? models : [];
    node.innerHTML = values.map(item => {
      const state = item.state || {};
      const busy = state.status === 'downloading';
      const installed = Boolean(item.installed) || state.status === 'ready';
      const action = installed ? `<button class="ghost" type="button" data-model-delete="${esc(item.name)}">Remove</button>` : `<button class="secondary" type="button" data-model-download="${esc(item.name)}" ${busy ? 'disabled' : ''}>${busy ? 'Downloading…' : 'Download'}</button>`;
      return `<article class="project-card model-card"><div class="project-info"><strong>${esc(item.label || item.name)}</strong><div class="project-meta"><span>${esc(item.name)} · about ${esc(item.size_gb)} GB</span><span class="badge ${installed ? 'done' : busy ? 'run' : ''}">${esc(state.status || (installed ? 'ready' : 'not installed'))}</span></div><p class="setting-help">${esc(item.description || '')}</p>${busy ? `<div class="mini-progress"><span style="width:${Math.max(0, Math.min(100, Number(state.progress) || 0))}%"></span></div>` : ''}<div class="project-card-actions">${action}</div>${state.error ? `<p class="setting-help">${esc(state.error)}</p>` : ''}</div></article>`;
    }).join('') || '<div class="empty">No model catalog available.</div>';
    node.querySelectorAll('[data-model-download]').forEach(button => button.addEventListener('click', async () => {
      button.disabled = true;
      try { await api(`/api/local/models/${encodeURIComponent(button.dataset.modelDownload)}/download`, {method: 'POST'}); await refreshModels(); }
      catch (error) { setText('styleProfileStatus', error.message); }
      finally { button.disabled = false; }
    }));
    node.querySelectorAll('[data-model-delete]').forEach(button => button.addEventListener('click', async () => {
      const name = button.dataset.modelDelete;
      if (!confirm(`Remove the cached Whisper model ${name}? It can be downloaded again later.`)) return;
      button.disabled = true;
      try { await api(`/api/local/models/${encodeURIComponent(name)}?confirm=true`, {method: 'DELETE'}); await refreshModels(); }
      catch (error) { setText('styleProfileStatus', error.message); }
      finally { button.disabled = false; }
    }));
  }

  async function refreshModels() {
    const data = await api('/api/local/models', {cache: 'no-store'});
    renderModels(data.models);
    if (modelRefreshTimer) window.clearTimeout(modelRefreshTimer);
    if ((data.models || []).some(item => item?.state?.status === 'downloading')) {
      modelRefreshTimer = window.setTimeout(() => refreshModels().catch(() => {}), 2500);
    }
    return data;
  }

  async function refresh() {
    const platform = $('performancePlatform')?.value || '';
    const query = platform ? `?platform=${encodeURIComponent(platform)}` : '';
    try {
      const data = await api(`/api/analytics/dashboard${query}`, {cache: 'no-store'});
      const overall = data.performance?.overall || {};
      setText('performanceViews', number(overall.views));
      setText('performanceCompletion', percent(overall.completion_rate));
      setText('performanceEngagement', percent(overall.engagement_rate));
      setText('performancePublished', number(data.publishing?.total));
      setText('performanceRecordCount', `${number(overall.records)} observation${Number(overall.records) === 1 ? '' : 's'}`);
      renderRecommendations(data.performance?.feedback?.recommendations);
      renderVariants(data.performance?.top_variants);
      renderPublishing(data.publishing);
      renderStyle(data.style_profile);
      renderModels(data.models);
      return data;
    } catch (error) {
      setText('performanceRecommendations', error.message);
      setText('performanceRecordCount', 'Unavailable');
      throw error;
    }
  }

  async function learnStyle() {
    const button = $('styleLearnButton');
    if (button) button.disabled = true;
    try {
      const data = await api('/api/style-profile/learn', {method: 'POST', body: JSON.stringify({name: 'My creator style', include_unreviewed: false}), headers: {'Content-Type': 'application/json'}});
      renderStyle(data.profile);
      setText('styleProfileStatus', 'Learned from completed projects and approved factory clips.');
    } catch (error) { setText('styleProfileStatus', error.message); }
    finally { if (button) button.disabled = false; }
  }

  async function saveStyle() {
    const notes = $('styleProfileNotes')?.value || '';
    try {
      const data = await api('/api/style-profile', {method: 'PUT', body: JSON.stringify({notes}), headers: {'Content-Type': 'application/json'}});
      renderStyle(data.profile);
      setText('styleProfileStatus', 'Style notes saved locally.');
    } catch (error) { setText('styleProfileStatus', error.message); }
  }

  async function applyStyle() {
    try {
      const data = await api('/api/style-profile', {cache: 'no-store'});
      const preferences = data.profile?.preferences && typeof data.profile.preferences === 'object' ? data.profile.preferences : {};
      const fields = {caption_style: 'captionStyle', caption_position: 'captionPosition', aspect_ratio: 'aspect', focus: 'focus', caption_font: 'captionFont', caption_color: 'captionColor', transition: 'transition'};
      Object.entries(fields).forEach(([source, target]) => {
        const value = preferences[source];
        const node = $(target);
        if (value && node) { node.value = value; node.dispatchEvent(new Event('change', {bubbles: true})); }
      });
      if (Object.prototype.hasOwnProperty.call(preferences, 'auto_reframe') && $('autoReframe')) {
        $('autoReframe').checked = Boolean(preferences.auto_reframe);
        $('autoReframe').dispatchEvent(new Event('change', {bubbles: true}));
      }
      if (Object.prototype.hasOwnProperty.call(preferences, 'music_ducking') && $('musicDucking')) {
        $('musicDucking').checked = Boolean(preferences.music_ducking);
        $('musicDucking').dispatchEvent(new Event('change', {bubbles: true}));
      }
      window.ShortsStudioApp?.setView?.('workspace');
      setText('styleProfileStatus', Object.keys(preferences).length ? 'Style preferences applied to the workspace form.' : 'Learn a profile first.');
    } catch (error) { setText('styleProfileStatus', error.message); }
  }

  async function resetStyle() {
    if (!confirm('Delete the transparent creator style profile? Completed projects will not be changed.')) return;
    try { const data = await api('/api/style-profile', {method: 'DELETE'}); renderStyle(data.profile); setText('styleProfileStatus', 'Style memory reset.'); }
    catch (error) { setText('styleProfileStatus', error.message); }
  }

  async function importAnalytics() {
    const input = $('analyticsImportInput');
    const status = $('analyticsImportStatus');
    try {
      const parsed = JSON.parse(input?.value || '');
      const records = Array.isArray(parsed) ? parsed : parsed?.records;
      if (!Array.isArray(records) || !records.length) throw Error('Paste a JSON array with at least one observation.');
      const data = await api('/api/analytics/import', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({records})});
      if (status) status.textContent = `Imported ${data.imported || records.length} observation(s).`;
      if (input) input.value = '';
      await refresh();
    } catch (error) { if (status) status.textContent = error.message; }
  }

  function mount() {
    $('performanceRefresh')?.addEventListener('click', () => refresh().catch(error => setText('performanceRecommendations', error.message)));
    $('performancePlatform')?.addEventListener('change', () => refresh().catch(error => setText('performanceRecommendations', error.message)));
    $('modelRefreshButton')?.addEventListener('click', () => refreshModels().catch(error => setText('styleProfileStatus', error.message)));
    $('styleLearnButton')?.addEventListener('click', learnStyle);
    $('styleApplyButton')?.addEventListener('click', applyStyle);
    $('styleSaveButton')?.addEventListener('click', saveStyle);
    $('styleResetButton')?.addEventListener('click', resetStyle);
    $('analyticsImportButton')?.addEventListener('click', importAnalytics);
    window.ShortsStudioDashboard = {refresh, refreshModels};
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once: true});
  else mount();
})();
