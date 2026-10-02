/* Explicit, bounded local OCR and speech evidence for the active project. */
(() => {
  const $ = id => document.getElementById(id);
  const state = window.ShortsStudioState?.state;
  const api = (url, options = {}) => window.ShortsStudioAPI.json(url, options);
  const currentJob = () => String(state?.activeJobId || '');
  const endpoint = job => `/api/v1/jobs/${encodeURIComponent(job)}/story/analyze`;
  let models = [];
  let budgets = {max_duration_seconds: 120, max_frames: 8, timeout_seconds: 90};
  let loadedJob = '';
  let runningJob = '';
  let timer = null;
  let loadingModels = false;
  const pending = new Set();
  const setStatus = message => { if ($('storyEvidenceStatus')) $('storyEvidenceStatus').textContent = String(message || ''); };

  function updateButtons() {
    const running = currentJob() && (runningJob === currentJob() || pending.has(currentJob()));
    ['storyOcrEnabled', 'storyAudioEnabled'].forEach(id => {
      const control = $(id);
      if (control) control.disabled = Boolean(running) || !models.find(model => model.id === control.value)?.available;
    });
    const selected = ['storyOcrEnabled', 'storyAudioEnabled'].some(id => $(id)?.checked && !$(id).disabled);
    if ($('storyAnalyzeButton')) $('storyAnalyzeButton').disabled = !currentJob() || !selected || Boolean(running);
    if ($('storyCancelButton')) { $('storyCancelButton').hidden = !running; $('storyCancelButton').disabled = !running; }
    if ($('storyClearButton')) $('storyClearButton').disabled = !currentJob() || Boolean(running);
  }

  function showEvidence(evidence) {
    const node = $('storyEvidenceResults');
    if (!node) return;
    node.replaceChildren();
    const rows = [
      ...(Array.isArray(evidence?.ocr) ? evidence.ocr.map(item => ({...item, kind: 'On-screen text'})) : []),
      ...(Array.isArray(evidence?.audio) ? evidence.audio.map(item => ({...item, kind: 'Audio'})) : [])
    ];
    rows.slice(0, 100).forEach(item => {
      const row = document.createElement('div');
      row.className = 'insight-row';
      const body = document.createElement('div');
      const title = document.createElement('strong');
      title.textContent = String(item.text || item.label || item.kind);
      const detail = document.createElement('small');
      const start = Number(item.start_time ?? item.time ?? item.timestamp);
      const end = Number(item.end_time);
      const timing = Number.isFinite(start) ? `${start.toFixed(1)}s${Number.isFinite(end) && end > start ? `–${end.toFixed(1)}s` : ''}` : '';
      detail.textContent = [item.kind, timing, item.model].filter(Boolean).join(' · ');
      body.append(title, detail);
      row.append(body);
      node.append(row);
    });
    if (!rows.length) {
      const empty = document.createElement('div');
      empty.className = 'empty';
      empty.textContent = evidence ? 'No text or speech evidence found in this range.' : 'Analyze a source range to add searchable evidence.';
      node.append(empty);
    }
    const notices = Array.isArray(evidence?.notices) ? evidence.notices : [];
    notices.forEach(notice => {
      const paragraph = document.createElement('p');
      paragraph.className = 'setting-help';
      paragraph.textContent = String(typeof notice === 'string' ? notice : notice?.message || '');
      node.append(paragraph);
    });
  }

  async function refreshModels() {
    if (loadingModels) return;
    loadingModels = true;
    $('storyModelsRefresh').disabled = true;
    try {
      const data = await api('/api/v1/story/models', {cache: 'no-store'});
      models = Array.isArray(data.models) ? data.models : [];
      budgets = {...budgets, ...data.budgets};
      ['storyOcrEnabled', 'storyAudioEnabled'].forEach(id => {
        const control = $(id);
        const model = models.find(item => item.id === control.value);
        if (!model?.available) control.checked = false;
        const notice = $(`${id}Notice`);
        notice.textContent = model ? `${model.label || model.id}: ${model.available ? 'ready' : 'unavailable'}. ${model.notice || ''}` : 'This local model is unavailable.';
      });
      $('storyEvidenceDuration').max = String(budgets.max_duration_seconds);
      $('storyEvidenceFrames').max = String(budgets.max_frames);
      $('storyEvidenceBudget').textContent = `Analyze up to ${budgets.max_duration_seconds}s and ${budgets.max_frames} sampled frames per request. Time limit: ${budgets.timeout_seconds}s. Local models run only when you choose Analyze.`;
    } catch (error) { setStatus(error.message); }
    finally { loadingModels = false; $('storyModelsRefresh').disabled = false; updateButtons(); }
  }

  async function refreshEvidence(job = currentJob()) {
    if (!job) return;
    try {
      const data = await api(endpoint(job), {cache: 'no-store'});
      if (currentJob() !== job) return;
      runningJob = data.running ? job : '';
      showEvidence(data.evidence);
      if (data.running) {
        setStatus('Local analysis is running. You can cancel this request.');
        window.clearTimeout(timer);
        timer = window.setTimeout(() => refreshEvidence(job), 1500);
      } else if (!pending.has(job)) setStatus(data.evidence ? 'Evidence saved locally and available in Story search.' : 'Select one or both available models, then choose Analyze.');
    } catch (error) { if (currentJob() === job) setStatus(error.message); }
    finally { updateButtons(); }
  }

  function syncProject() {
    const job = currentJob();
    if (job === loadedJob) return;
    loadedJob = job;
    window.clearTimeout(timer);
    runningJob = '';
    showEvidence(null);
    setStatus(job ? 'Loading evidence for this project…' : 'Open a completed local project to analyze its source.');
    updateButtons();
    if (job) refreshEvidence(job);
  }

  async function analyze() {
    const job = currentJob();
    if (!job) { setStatus('Open a completed local project first.'); return; }
    const inputs = ['storyEvidenceStart', 'storyEvidenceDuration', 'storyEvidenceFrames', 'storyEvidenceLanguage'];
    if (inputs.some(id => !$(id).reportValidity())) return;
    const ocr = $('storyOcrEnabled').checked && !$('storyOcrEnabled').disabled;
    const audio = $('storyAudioEnabled').checked && !$('storyAudioEnabled').disabled;
    if (!ocr && !audio) { setStatus('Select an available local model first.'); return; }
    const body = {
      ocr_model: ocr ? 'tesseract' : null,
      audio_model: audio ? 'silero-vad' : null,
      language: $('storyEvidenceLanguage').value.trim() || 'eng',
      start_time: Number($('storyEvidenceStart').value),
      duration_seconds: Number($('storyEvidenceDuration').value),
      max_frames: Number($('storyEvidenceFrames').value)
    };
    pending.add(job);
    runningJob = job;
    setStatus('Analyzing the selected range locally…');
    updateButtons();
    try {
      const data = await api(endpoint(job), {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
      if (currentJob() === job) {
        showEvidence(data.evidence);
        setStatus('Evidence saved locally and available in Story search.');
      }
    } catch (error) { if (currentJob() === job) setStatus(error.message); }
    finally {
      pending.delete(job);
      if (runningJob === job) runningJob = '';
      updateButtons();
    }
  }

  async function cancelOrClear() {
    const job = currentJob();
    if (!job) return;
    try {
      const data = await api(endpoint(job), {method: 'DELETE'});
      if (currentJob() !== job) return;
      const cancelling = data.status === 'cancelling' || data.running || pending.has(job);
      setStatus(data.message || (cancelling ? 'Cancellation requested. Waiting for the local worker to stop…' : 'Stored evidence cleared.'));
      if (cancelling) {
        runningJob = job;
        window.clearTimeout(timer);
        timer = window.setTimeout(() => refreshEvidence(job), 1500);
      } else { runningJob = ''; showEvidence(null); }
      updateButtons();
    } catch (error) { if (currentJob() === job) setStatus(error.message); }
  }

  function mount() {
    const tab = $('audioTab');
    if (!tab || $('storyEvidenceControls')) return;
    const wrap = document.createElement('section');
    wrap.id = 'storyEvidenceControls';
    wrap.className = 'field feature-controls';
    wrap.innerHTML = `
      <h3>Local story evidence</h3>
      <p class="setting-help">Read on-screen text and detect speech activity in your source. Evidence stays with this project and becomes searchable.</p>
      <label class="checkline"><input id="storyOcrEnabled" value="tesseract" type="checkbox" disabled> Read on-screen text (OCR)</label>
      <p class="setting-help" id="storyOcrEnabledNotice">Checking local OCR availability…</p>
      <label class="checkline"><input id="storyAudioEnabled" value="silero-vad" type="checkbox" disabled> Detect speech activity</label>
      <p class="setting-help" id="storyAudioEnabledNotice">Checking local audio model availability…</p>
      <div class="two"><div class="field"><label for="storyEvidenceStart">Source start (s)</label><input class="input" id="storyEvidenceStart" type="number" min="0" max="86400" step=".1" value="0" required></div><div class="field"><label for="storyEvidenceDuration">Duration (s)</label><input class="input" id="storyEvidenceDuration" type="number" min="1" max="120" step=".1" value="60" required></div></div>
      <div class="two"><div class="field"><label for="storyEvidenceFrames">OCR frames</label><input class="input" id="storyEvidenceFrames" type="number" min="1" max="8" step="1" value="4" required></div><div class="field"><label for="storyEvidenceLanguage">OCR language</label><input class="input" id="storyEvidenceLanguage" minlength="3" maxlength="15" pattern="[a-z]{3}(?:\\+[a-z]{3}){0,3}" value="eng" placeholder="eng or eng+fra" required></div></div>
      <p class="setting-help" id="storyEvidenceBudget"></p>
      <div class="settings-actions"><button class="primary" id="storyAnalyzeButton" type="button" disabled>Analyze range</button><button class="secondary" id="storyCancelButton" type="button" hidden>Cancel analysis</button><button class="ghost" id="storyClearButton" type="button" disabled>Clear evidence</button><button class="ghost" id="storyModelsRefresh" type="button">Refresh models</button></div>
      <p class="setting-help" id="storyEvidenceStatus" role="status" aria-live="polite">Open a completed local project to analyze its source.</p>
      <div class="insight-list" id="storyEvidenceResults"></div>`;
    tab.append(wrap);
    ['storyOcrEnabled', 'storyAudioEnabled'].forEach(id => $(id).addEventListener('change', updateButtons));
    $('storyAnalyzeButton').addEventListener('click', analyze);
    $('storyCancelButton').addEventListener('click', cancelOrClear);
    $('storyClearButton').addEventListener('click', cancelOrClear);
    $('storyModelsRefresh').addEventListener('click', refreshModels);
    const observer = new MutationObserver(syncProject);
    ['jobIdBadge', 'jobBadge', 'clipGrid'].forEach(id => { if ($(id)) observer.observe($(id), {childList: true, attributes: true}); });
    document.addEventListener('shorts:jobs-changed', syncProject);
    document.querySelector('[data-tab="audioTab"]')?.addEventListener('click', () => { syncProject(); if (currentJob()) refreshEvidence(); });
    showEvidence(null);
    syncProject();
    refreshModels();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once: true});
  else mount();
})();
