/* v0.11 feature controls: prompt templates, platform profiles, ducking,
 * transitions, and approval-first YouTube publishing. */
(() => {
  const ready = () => {
    const $ = id => document.getElementById(id);
    const add = (parent, html) => { const wrap = document.createElement('div'); wrap.innerHTML = html.trim(); const node = wrap.firstElementChild; if (node) parent.appendChild(node); return node; };
    const audio = $('audioTab');
    if (audio && !$('musicDucking')) {
      add(audio, `<div class="field feature-controls"><label class="checkline"><input id="musicDucking" type="checkbox"> Duck music under speech</label><div class="two"><div class="field"><label for="duckingStrength">Ducking strength</label><input class="input" id="duckingStrength" type="number" min="0" max="1" step=".05" value=".65"></div><div class="field"><label for="transition">Clip transition</label><select class="select" id="transition"><option value="none">No transition</option><option value="fade">Fade</option><option value="slide">Slide</option><option value="zoom">Zoom</option></select></div></div><div class="field"><label for="transitionDuration">Transition duration (s)</label><input class="input" id="transitionDuration" type="number" min="0" max="2" step=".05" value=".25"></div><p class="setting-help">Transitions apply when several cut ranges are merged into one rendered clip.</p></div>`);
    }
    const exportTab = $('exportTab');
    if (exportTab && !$('platformPresetSelect')) {
      add(exportTab, `<div class="field feature-controls"><label for="platformPresetSelect">Platform validation preset</label><select class="select" id="platformPresetSelect"><option value="">Custom dimensions</option></select><p class="setting-help" id="platformPresetStatus" role="status" aria-live="polite">Presets validate aspect ratio, canvas, frame rate, and duration before rendering.</p></div>`);
      fetch('/api/export-presets', {cache: 'no-store'}).then(r => r.json()).then(data => {
        const select = $('platformPresetSelect'); if (!select) return;
        (data.presets || []).forEach(item => { const option = new Option(`${item.label} · ${item.width}×${item.height}`, item.key); option.title = item.description || ''; select.add(option); });
      }).catch(() => {});
      $('platformPresetSelect').addEventListener('change', event => {
        const value = event.target.value; if (!value) return;
        fetch('/api/export-presets', {cache: 'no-store'}).then(r => r.json()).then(data => {
          const preset = (data.presets || []).find(item => item.key === value); if (!preset) return;
          if ($('aspect')) $('aspect').value = preset.aspect_ratio;
          if ($('outputHeight')) $('outputHeight').value = String(preset.height);
          const status = $('platformPresetStatus'); if (status) status.textContent = `${preset.label}: ${preset.width}×${preset.height}, ${preset.aspect_ratio}, up to ${preset.max_duration_seconds}s.`;
        }).catch(() => {});
      });
    }
    const focus = $('focus');
    if (focus && !$('viralityPrompt')) {
      const block = add(focus.closest('.field')?.parentElement || focus.parentElement, `<div class="field feature-controls"><label for="viralityPrompt">Virality scoring prompt <span>optional, saved locally</span></label><div class="two"><input class="input" id="viralityPromptName" maxlength="60" placeholder="Template name" aria-label="Virality prompt template name"><select class="select" id="viralityPromptTemplate" aria-label="Saved virality prompt templates"><option value="">Saved templates</option></select></div><textarea class="textarea" id="viralityPrompt" rows="5" maxlength="12000" placeholder="Tell the scorer what your audience values (for example: prioritize practical takeaways and surprising data)."></textarea><div class="settings-actions"><button class="secondary" id="saveViralityPrompt" type="button">Save template</button><button class="ghost" id="deleteViralityPrompt" type="button">Delete selected</button><button class="ghost" id="resetViralityPrompt" type="button">Reset text</button></div><p class="setting-help" id="viralityPromptStatus" role="status" aria-live="polite">Templates stay in this browser; the selected text is sent with the next render.</p></div>`);
      const key = 'shorts-studio-virality-prompts';
      const read = () => { try { const value = JSON.parse(localStorage.getItem(key) || '[]'); return Array.isArray(value) ? value.filter(item => item && item.name && typeof item.prompt === 'string').slice(-20) : []; } catch (_) { return []; } };
      const render = () => { const select = $('viralityPromptTemplate'); if (!select) return; select.innerHTML = '<option value="">Saved templates</option>'; read().forEach(item => select.add(new Option(item.name, item.name))); };
      const write = values => { try { localStorage.setItem(key, JSON.stringify(values.slice(-20))); } catch (_) {} };
      render();
      $('viralityPromptTemplate').addEventListener('change', event => { const item = read().find(value => value.name === event.target.value); if (item) { $('viralityPrompt').value = item.prompt; $('viralityPromptName').value = item.name; } });
      $('saveViralityPrompt').addEventListener('click', () => { const name = $('viralityPromptName').value.trim(); const prompt = $('viralityPrompt').value.trim(); if (!name || !prompt) { $('viralityPromptStatus').textContent = 'Enter a template name and prompt first.'; return; } write([...read().filter(item => item.name.toLowerCase() !== name.toLowerCase()), {name, prompt}]); render(); $('viralityPromptTemplate').value = name; $('viralityPromptStatus').textContent = `Saved “${name}” locally.`; });
      $('deleteViralityPrompt').addEventListener('click', () => { const name = $('viralityPromptTemplate').value; if (!name) return; write(read().filter(item => item.name !== name)); render(); $('viralityPrompt').value = ''; $('viralityPromptName').value = ''; $('viralityPromptStatus').textContent = 'Template deleted.'; });
      $('resetViralityPrompt').addEventListener('click', () => { $('viralityPrompt').value = ''; $('viralityPromptStatus').textContent = 'Using the built-in virality criteria.'; });
    }
    if (exportTab && !$('youtubeApprovalControls')) {
      const block = add(exportTab, `<div class="field feature-controls" id="youtubeApprovalControls"><label>YouTube / Google account</label><div class="two"><select class="select" id="youtubePrivacy" aria-label="YouTube privacy"><option value="private">Private (recommended)</option><option value="unlisted">Unlisted</option><option value="public">Public (explicit approval)</option></select><input class="input" id="youtubePublishAt" type="datetime-local" aria-label="Schedule publish time"></div><label class="checkline"><input id="youtubeConfirm" type="checkbox"> I reviewed the title, description, clip, and privacy setting</label><label class="checkline"><input id="youtubeAutoPublish" type="checkbox"> Enable unattended YouTube publish (deployment opt-in required)</label><div class="settings-actions"><button class="secondary" id="youtubeOAuthButton" type="button">Sign in with Google</button><button class="ghost" id="youtubeDisconnectButton" type="button">Disconnect</button><button class="primary" id="youtubePublishButton" type="button">Approve upload</button></div><p class="setting-help" id="youtubePublishStatus" role="status" aria-live="polite">Google OAuth uses process-memory tokens. Uploads are resumable, approval-first, private by default, and never start without your confirmation.</p></div>`);
      const status = $('youtubePublishStatus');
      const setStatus = message => { if (status) status.textContent = String(message || ''); };
      const refreshYouTubeStatus = async () => {
        try {
          const response = await fetch('/api/v1/youtube/oauth/status', {cache: 'no-store'});
          const data = await response.json();
          if (!response.ok) throw Error(data.error || data.detail || 'Google sign-in status unavailable');
          const button = $('youtubeOAuthButton');
          if (button) button.textContent = data.authorized ? 'Google account connected' : 'Sign in with Google';
          if (data.authorized) setStatus(`Google account connected. Privacy default: ${data.privacy_default || 'private'}.`);
          return data;
        } catch (error) { setStatus(error.message); return null; }
      };
      $('youtubeOAuthButton').addEventListener('click', async () => {
        try {
          const response = await fetch('/api/v1/youtube/oauth/start'); const data = await response.json();
          if (!response.ok) throw Error(data.error || data.detail || 'YouTube OAuth is not configured');
          const opened = window.open(data.authorization_url, '_blank', 'noopener,noreferrer');
          if (!opened) window.location.href = data.authorization_url;
          setStatus('Authorize Shorts Studio in the Google consent window, then return here. This page will refresh the connection status.');
          let checks = 0; const timer = window.setInterval(async () => { checks += 1; const current = await refreshYouTubeStatus(); if (current?.authorized || checks >= 30) window.clearInterval(timer); }, 2000);
        } catch (error) { setStatus(error.message); }
      });
      $('youtubeDisconnectButton').addEventListener('click', async () => {
        try { const response = await fetch('/api/v1/youtube/oauth/disconnect', {method: 'POST'}); const data = await response.json(); if (!response.ok) throw Error(data.error || data.detail || 'Could not disconnect Google'); setStatus('Google account disconnected from this Shorts Studio process.'); $('youtubeOAuthButton').textContent = 'Sign in with Google'; } catch (error) { setStatus(error.message); }
      });
      $('youtubePublishButton').addEventListener('click', async () => {
        const job = window.ShortsStudioState?.state?.activeJobId;
        if (!job) { setStatus('Render a project before approving an upload.'); return; }
        if (!$('youtubeConfirm').checked) { setStatus('Check the review confirmation before uploading.'); return; }
        const publishAt = $('youtubePublishAt').value ? new Date($('youtubePublishAt').value).toISOString() : null;
        const privacy = $('youtubePrivacy').value;
        const payload = {platform: 'youtube_shorts', privacy_status: privacy, publish_at: publishAt, confirm: true, allow_public: privacy === 'public', auto_publish: Boolean($('youtubeAutoPublish').checked)};
        try { const response = await fetch(`/api/v1/jobs/${encodeURIComponent(job)}/youtube/publish`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)}); const data = await response.json(); if (!response.ok) throw Error(data.error || data.detail || 'YouTube upload failed'); setStatus(data.message || `Upload ${data.status}.`); } catch (error) { setStatus(error.message); }
      });
      refreshYouTubeStatus();
    }
    if (exportTab && !$('factoryControls')) {
      add(exportTab, `<div class="field feature-controls" id="factoryControls"><label>Autonomous Shorts Factory review</label><p class="setting-help">Queue factory jobs through <code>/api/v1/factory/jobs</code>. Each completed clip gets a human checkpoint before direct publishing.</p><div class="settings-actions"><button class="secondary" id="factoryRefreshButton" type="button">Refresh factory package</button><button class="primary" id="factoryApproveButton" type="button">Approve selected clip</button></div><p class="setting-help" id="factoryStatus" role="status" aria-live="polite">No factory package loaded for the current project.</p></div>`);
      const factoryMessage = message => { const node = $('factoryStatus'); if (node) node.textContent = String(message || ''); };
      const loadFactory = async () => { const job = window.ShortsStudioState?.state?.activeJobId; if (!job) { factoryMessage('Open a factory project before reviewing its package.'); return null; } try { const response = await fetch(`/api/v1/jobs/${encodeURIComponent(job)}/factory`, {cache: 'no-store'}); const data = await response.json(); if (!response.ok) throw Error(data.error || data.detail || 'Factory package unavailable'); const summary = data.approval_summary || {}; factoryMessage(`Factory ${data.status}: ${summary.approved || 0} approved, ${summary.pending || 0} pending, ${summary.rejected || 0} rejected.`); return data; } catch (error) { factoryMessage(error.message); return null; } };
      $('factoryRefreshButton').addEventListener('click', loadFactory);
      $('factoryApproveButton').addEventListener('click', async () => { const job = window.ShortsStudioState?.state?.activeJobId; const clip = Number(window.ShortsStudioState?.state?.selectedClip || 0); if (!job) { factoryMessage('Open a factory project before approving a clip.'); return; } try { const response = await fetch(`/api/v1/jobs/${encodeURIComponent(job)}/factory/approve`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({clip_indices: [clip], decision: 'approved'})}); const data = await response.json(); if (!response.ok) throw Error(data.error || data.detail || 'Factory approval failed'); factoryMessage(data.message || 'Factory approval recorded.'); } catch (error) { factoryMessage(error.message); } });
    }
    if (exportTab && !$('mergeControls')) {
      add(exportTab, `<div class="field feature-controls" id="mergeControls"><label for="mergeClipIndices">Merge separate highlights</label><div class="two"><input class="input" id="mergeClipIndices" inputmode="numeric" placeholder="Clip numbers, e.g. 1,3,4"><button class="secondary" id="mergeClipsButton" type="button">Render merged clip</button></div><p class="setting-help" id="mergeStatus" role="status" aria-live="polite">Choose two or more completed clips. Each source range remains explicit; transitions are applied at the joins.</p></div>`);
      $('mergeClipsButton').addEventListener('click', async () => {
        const studioState = window.ShortsStudioState?.state; const job = studioState?.activeJobId; if (!job) { $('mergeStatus').textContent = 'Render a project before merging clips.'; return; }
        const indices = $('mergeClipIndices').value.split(',').map(value => Number(value.trim()) - 1).filter(value => Number.isInteger(value) && value >= 0);
        if (indices.length < 2) { $('mergeStatus').textContent = 'Enter at least two clip numbers.'; return; }
        try { const response = await fetch(`/api/jobs/${encodeURIComponent(job)}/merge`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({clip_indices: indices, transition: $('transition')?.value || 'fade', transition_duration: Number($('transitionDuration')?.value || .25)})}); const data = await response.json(); if (!response.ok) throw Error(data.error || data.detail || 'Merge failed'); $('mergeStatus').textContent = data.message || 'Merged clip rendered. Open the workspace to preview it.'; } catch (error) { $('mergeStatus').textContent = error.message; }
      });
    }
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready, {once: true}); else ready();
})();
