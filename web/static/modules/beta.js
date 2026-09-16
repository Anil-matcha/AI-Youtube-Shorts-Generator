/* v1 beta workflows: direct publishing, A/B variants, and analytics feedback. */
(() => {
  const state = window.ShortsStudioState?.state;
  const $ = id => document.getElementById(id);

  const request = async (url, options = {}) => {
    const headers = {...(options.headers || {})};
    if (options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
    const response = await fetch(url, {...options, headers});
    let data = null;
    try { data = await response.json(); } catch (_) { data = {}; }
    if (!response.ok) throw Error(data?.error || data?.message || `Request failed (${response.status})`);
    return data;
  };

  const currentJob = () => String(state?.activeJobId || '');
  const endpoint = suffix => `/api/v1/jobs/${encodeURIComponent(currentJob())}${suffix}`;

  function mount() {
    const tab = $('exportTab');
    if (!tab || $('betaControls')) return;
    const wrap = document.createElement('div');
    wrap.className = 'field feature-controls';
    wrap.id = 'betaControls';
    wrap.innerHTML = `
      <label>v1 beta publishing and experiments</label>
      <div class="two">
        <select class="select" id="betaPlatform" aria-label="Beta publishing platform">
          <option value="tiktok">TikTok direct upload</option>
          <option value="instagram_reels">Instagram Reels direct upload</option>
        </select>
        <button class="secondary" id="betaConnectButton" type="button">Connect platform</button>
      </div>
      <div class="two">
        <input class="input" id="betaMediaUrl" maxlength="4096" placeholder="Public https media URL (Instagram only)" aria-label="Public media URL">
        <select class="select" id="betaVariantSelect" aria-label="A/B variant (optional)"><option value="">Base clip</option></select>
      </div>
      <label class="checkline"><input id="betaConfirm" type="checkbox"> I reviewed this clip and approve the private upload</label>
      <div class="settings-actions">
        <button class="primary" id="betaPublishButton" type="button">Approve direct upload</button>
        <button class="ghost" id="betaRefreshButton" type="button">Refresh insights</button>
      </div>
      <p class="setting-help" id="betaPublishStatus" role="status" aria-live="polite">Direct uploads use official APIs, require approval, and keep tokens in process memory.</p>
      <div class="two">
        <input class="input" id="betaVariantName" maxlength="80" placeholder="Variant name, e.g. Hook B" aria-label="A/B variant name">
        <input class="input" id="betaVariantHook" maxlength="500" placeholder="Optional alternate hook" aria-label="A/B variant hook">
      </div>
      <button class="secondary" id="betaCreateVariantButton" type="button">Create variant from selected clip</button>
      <div class="two">
        <input class="input" id="betaAnalyticsViews" type="number" min="0" max="2000000000" placeholder="Views" aria-label="Analytics views">
        <input class="input" id="betaAnalyticsLikes" type="number" min="0" max="2000000000" placeholder="Likes" aria-label="Analytics likes">
      </div>
      <div class="two">
        <input class="input" id="betaAnalyticsComments" type="number" min="0" max="2000000000" placeholder="Comments" aria-label="Analytics comments">
        <input class="input" id="betaAnalyticsCompletion" type="number" min="0" max="100" step="1" placeholder="Completion %" aria-label="Completion percentage">
      </div>
      <button class="ghost" id="betaRecordAnalyticsButton" type="button">Record analytics observation</button>
      <p class="setting-help" id="betaInsights" role="status" aria-live="polite">Create a variant or record platform metrics to see feedback.</p>`;
    tab.appendChild(wrap);

    const status = message => { const node = $('betaPublishStatus'); if (node) node.textContent = String(message || ''); };
    const insight = message => { const node = $('betaInsights'); if (node) node.textContent = String(message || ''); };
    const variantSelect = $('betaVariantSelect');
    const platform = $('betaPlatform');
    const media = $('betaMediaUrl');

    const refresh = async () => {
      if (!currentJob()) { status('Render a project before using beta publishing or experiments.'); return; }
      try {
        const [variants, analytics] = await Promise.all([
          request(endpoint('/variants')),
          request(endpoint('/analytics'))
        ]);
        if (variantSelect) {
          variantSelect.innerHTML = '<option value="">Base clip</option>';
          (variants.variants || []).forEach(item => {
            const option = new Option(`${item.name || item.id} (clip ${Number(item.clip_index || 0) + 1})`, item.id);
            variantSelect.add(option);
          });
        }
        const feedback = analytics.feedback || {};
        const recommendations = (feedback.recommendations || []).map(item => item.message).filter(Boolean);
        insight(recommendations.length ? recommendations.join(' ') : `Recorded observations: ${feedback.overall?.records || 0}.`);
      } catch (error) {
        insight(error.message);
      }
    };

    platform?.addEventListener('change', () => {
      const instagram = platform.value === 'instagram_reels';
      if (media) {
        media.disabled = !instagram;
        media.placeholder = instagram ? 'Public https media URL (required by Instagram)' : 'Public media URL (Instagram only)';
      }
      status(instagram ? 'Instagram Reels needs a public HTTPS media URL.' : 'TikTok accepts the selected local rendered clip.');
    });
    $('betaConnectButton')?.addEventListener('click', async () => {
      if (!currentJob()) { status('You can connect a platform before rendering, but select a project before publishing.'); }
      const key = platform?.value === 'instagram_reels' ? 'instagram' : 'tiktok';
      try {
        const data = await request(`/api/v1/${key}/oauth/start`);
        const opened = window.open(data.authorization_url, '_blank', 'noopener,noreferrer');
        if (!opened) window.location.href = data.authorization_url;
        status(`Authorize ${key === 'instagram' ? 'Instagram' : 'TikTok'} in the consent window, then return here.`);
      } catch (error) { status(error.message); }
    });
    $('betaPublishButton')?.addEventListener('click', async () => {
      if (!currentJob()) { status('Render a project before approving a direct upload.'); return; }
      if (!$('betaConfirm')?.checked) { status('Check the approval box after reviewing the clip and privacy setting.'); return; }
      const selected = variantSelect?.value || null;
      const payload = {
        platform: platform?.value || 'tiktok',
        clip_index: selected ? null : Number(state?.selectedClip || 0),
        variant_id: selected,
        media_url: media?.value.trim() || null,
        confirm: true,
        allow_public: false,
        privacy_status: 'private'
      };
      try {
        const data = await request(endpoint('/publish'), {method: 'POST', body: JSON.stringify(payload)});
        status(data.message || `${payload.platform} upload completed.`);
        await refresh();
      } catch (error) { status(error.message); }
    });
    $('betaCreateVariantButton')?.addEventListener('click', async () => {
      if (!currentJob()) { insight('Render a project before creating a variant.'); return; }
      const name = $('betaVariantName')?.value.trim();
      if (!name) { insight('Enter a variant name first.'); return; }
      try {
        await request(endpoint('/variants'), {
          method: 'POST',
          body: JSON.stringify({clip_index: Number(state?.selectedClip || 0), name, hook: $('betaVariantHook')?.value.trim() || null})
        });
        $('betaVariantName').value = '';
        $('betaVariantHook').value = '';
        insight('Variant created. Record platform metrics after publishing it.');
        await refresh();
      } catch (error) { insight(error.message); }
    });
    $('betaRecordAnalyticsButton')?.addEventListener('click', async () => {
      if (!currentJob()) { insight('Render a project before recording analytics.'); return; }
      const number = id => Math.max(0, Number($(id)?.value || 0));
      const completion = Math.min(100, number('betaAnalyticsCompletion')) / 100;
      try {
        await request(endpoint('/analytics'), {
          method: 'POST',
          body: JSON.stringify({
            platform: platform?.value || 'tiktok',
            variant_id: variantSelect?.value || null,
            views: number('betaAnalyticsViews'),
            likes: number('betaAnalyticsLikes'),
            comments: number('betaAnalyticsComments'),
            completion_rate: completion
          })
        });
        insight('Analytics observation recorded. Refreshing feedback...');
        await refresh();
      } catch (error) { insight(error.message); }
    });
    $('betaRefreshButton')?.addEventListener('click', refresh);
    platform?.dispatchEvent(new Event('change'));
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once: true});
  else mount();
})();
