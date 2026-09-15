/* Editor request mapping, capability schema, range handling, and export presets. */
(() => {
  function createEditor(ctx) {
    const {state, $, finiteNumber, toast, fmtTime, capabilities} = ctx;
    const exportKey = ctx.exportPresetsKey || 'shorts-studio-export-presets';

    function readRequest() {
      const value = id => $(id)?.value ?? '';
      const checked = id => Boolean($(id)?.checked);
      const number = (id, fallback) => finiteNumber(value(id), fallback);
      const mode = value('mode');
      const local = mode === 'local';
      return {
        url: value('sourceInput').trim(), mode,
        num_clips: Math.min(12, Math.max(1, Math.round(number('numClips', 3)))),
        aspect_ratio: value('aspect'), download_format: value('format'),
        language: value('language').trim() || null,
        virality_prompt: value('viralityPrompt').trim() || null,
        caption_style: local ? value('captionStyle') : 'bold',
        caption_position: local ? value('captionPosition') : 'bottom',
        caption_font: local ? (value('captionFont').trim() || 'Arial') : 'Arial',
        caption_size: local ? Math.min(120, Math.max(0, Math.round(number('captionSize', 0)))) : 0,
        caption_color: local ? (value('captionColor') || null) : null,
        focus: value('focus'),
        background_music: local ? (value('music').trim() || null) : null,
        music_volume: local ? Math.min(1, Math.max(0, number('musicVolume', .18))) : .18,
        music_fade_in: local ? Math.min(30, Math.max(0, number('musicFadeIn', 0))) : 0,
        music_fade_out: local ? Math.min(30, Math.max(0, number('musicFadeOut', 0))) : 0,
        music_ducking: local && checked('musicDucking'),
        ducking_strength: local ? Math.min(1, Math.max(0, number('duckingStrength', .65))) : .65,
        watermark: local ? (value('watermark').trim() || null) : null,
        auto_reframe: local ? checked('autoReframe') : true,
        crop_position: local ? Math.min(1, Math.max(0, number('cropPosition', .5))) : .5,
        fit_mode: local ? value('fitMode') : 'crop', zoom: local ? Math.min(1.5, Math.max(.5, number('zoom', 1))) : 1,
        intro: local ? (value('intro').trim() || null) : null,
        outro: local ? (value('outro').trim() || null) : null,
        remove_silence: local && checked('removeSilence'), jump_cuts: local && checked('jumpCuts'),
        normalize_audio: local && checked('normalizeAudio'), denoise_audio: local && checked('denoiseAudio'),
        remove_filler_words: local && checked('fillerWords'), layout: local ? value('layout') : 'single',
        transition: local ? (value('transition') || 'none') : 'none',
        transition_duration: local ? Math.min(2, Math.max(0, number('transitionDuration', .25))) : .25,
        whisper_model: local ? (value('whisperModel') || null) : null,
        whisper_device: local ? (value('whisperDevice') || null) : null,
        output_height: local ? Math.min(4320, Math.max(0, Math.round(number('outputHeight', 1920)))) : 1920,
        save_folder: local ? (value('saveFolder').trim() || null) : null,
        llm_provider: local ? ($('settingsLlmProvider')?.value || state.settings.llmProvider || null) : null,
        llm_model: local ? ($('llmModel')?.value || null) : null,
        llm_temperature: local ? Math.min(1, Math.max(0, number('llmTemperature', .2))) : .2,
        export_preset: value('platformPresetSelect') || null,
        cuts: local ? state.cuts : []
      };
    }

    function applyRequest(req = {}) {
      const set = (id, key) => { if (req[key] !== undefined && req[key] !== null && $(id)) $(id).value = req[key]; };
      const check = (id, key) => { if (req[key] !== undefined && $(id)) $(id).checked = Boolean(req[key]); };
      [['sourceInput', 'url'], ['mode', 'mode'], ['numClips', 'num_clips'], ['aspect', 'aspect_ratio'],
        ['format', 'download_format'], ['language', 'language'], ['captionStyle', 'caption_style'],
        ['captionPosition', 'caption_position'], ['captionFont', 'caption_font'], ['captionSize', 'caption_size'],
        ['captionColor', 'caption_color'], ['focus', 'focus'], ['viralityPrompt', 'virality_prompt'], ['music', 'background_music'],
        ['musicVolume', 'music_volume'], ['musicFadeIn', 'music_fade_in'], ['musicFadeOut', 'music_fade_out'], ['duckingStrength', 'ducking_strength'], ['transitionDuration', 'transition_duration'],
        ['platformPresetSelect', 'export_preset'], ['transition', 'transition'],
        ['watermark', 'watermark'], ['cropPosition', 'crop_position'], ['fitMode', 'fit_mode'], ['zoom', 'zoom'],
        ['intro', 'intro'], ['outro', 'outro'], ['layout', 'layout'], ['whisperModel', 'whisper_model'],
        ['whisperDevice', 'whisper_device'], ['outputHeight', 'output_height'], ['saveFolder', 'save_folder'],
        ['settingsLlmProvider', 'llm_provider'], ['llmModel', 'llm_model'], ['llmTemperature', 'llm_temperature']]
        .forEach(([id, key]) => set(id, key));
      [['autoReframe', 'auto_reframe'], ['removeSilence', 'remove_silence'], ['jumpCuts', 'jump_cuts'],
        ['normalizeAudio', 'normalize_audio'], ['denoiseAudio', 'denoise_audio'], ['fillerWords', 'remove_filler_words'], ['musicDucking', 'music_ducking']]
        .forEach(([id, key]) => check(id, key));
      state.cuts = Array.isArray(req.cuts) ? req.cuts.map(cut => ({...cut})) : [];
      renderCuts();
      ctx.updateLabels?.();
      syncModeCapabilities();
    }

    function renderCuts() {
      const editor = $('cutsEditor');
      if (!editor) return;
      const clear = $('clearCutsButton');
      if (clear) clear.disabled = state.cuts.length === 0;
      editor.innerHTML = state.cuts.length
        ? state.cuts.map((cut, index) => `<div class="cut-row"><span>${fmtTime(cut.start_time)} - ${fmtTime(cut.end_time)}</span><button class="ghost" type="button" data-remove-cut="${index}" aria-label="Remove cut ${index + 1}">Remove</button></div>`).join('')
        : '<span class="dropzone-sub">No extra ranges. The selected start/end range will be used.</span>';
      editor.querySelectorAll('[data-remove-cut]').forEach(button => button.addEventListener('click', () => {
        state.cuts.splice(Number(button.dataset.removeCut), 1);
        renderCuts();
      }));
    }

    function syncModeCapabilities() {
      const api = $('mode')?.value === 'api';
      (capabilities?.localOnly || []).forEach(id => {
        const element = $(id);
        if (!element) return;
        element.disabled = api;
        element.title = api ? 'This setting is available in Local mode only.' : '';
      });
      const panel = document.querySelector('.editor-tools-panel');
      if (panel) panel.hidden = !state.activeJobId || !state.activeJob?.result || api;
      const hint = $('renderNote');
      if (hint && api) hint.textContent = 'API mode supports hosted download, transcription, ranking, and basic aspect/timestamp cropping. Switch to Local mode for captions, audio, branding, and precision edits.';
    }

    function loadExportPresets() {
      try {
        const raw = JSON.parse(localStorage.getItem(exportKey) || '[]');
        state.exportPresets = Array.isArray(raw) ? raw.filter(item => item && typeof item === 'object' && item.name) : [];
      } catch (_) { state.exportPresets = []; }
      const select = $('exportPresetSelect');
      if (select) select.innerHTML = '<option value="">Choose export preset</option>' + state.exportPresets.map(item => `<option value="${ctx.esc(item.name)}">${ctx.esc(item.name)}</option>`).join('');
      return state.exportPresets;
    }

    function saveExportPreset() {
      const name = $('exportPresetName')?.value.trim();
      if (!name) { toast('Enter a name for the export preset.', true); return; }
      const preset = {name, aspect_ratio: $('aspect')?.value || '9:16', output_height: $('outputHeight')?.value || '1920', format: $('format')?.value || '720', caption_style: $('captionStyle')?.value || 'bold', caption_position: $('captionPosition')?.value || 'bottom'};
      state.exportPresets = [...state.exportPresets.filter(item => item.name.toLowerCase() !== name.toLowerCase()), preset].slice(-20);
      localStorage.setItem(exportKey, JSON.stringify(state.exportPresets));
      loadExportPresets();
      if ($('exportPresetStatus')) $('exportPresetStatus').textContent = `Saved "${name}" for future exports.`;
      toast('Export preset saved.');
    }

    function applyExportPreset(name) {
      const preset = state.exportPresets.find(item => item.name === name);
      if (!preset) return;
      [['aspect', 'aspect_ratio'], ['outputHeight', 'output_height'], ['format', 'format'], ['captionStyle', 'caption_style'], ['captionPosition', 'caption_position']].forEach(([id, key]) => { if ($(id) && preset[key] !== undefined) $(id).value = preset[key]; });
      ctx.updateLabels?.();
      toast(`Export preset "${name}" applied.`);
    }

    loadExportPresets();
    return {readRequest, applyRequest, renderCuts, syncModeCapabilities, loadExportPresets, saveExportPreset, applyExportPreset};
  }

  window.ShortsStudioEditor = {create: createEditor};
})();
