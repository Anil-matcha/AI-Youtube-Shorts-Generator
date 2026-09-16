/* Shared, serialisable client state and capability metadata. */
(() => {
  const state = {
    jobs: [],
    activeJobId: null,
    activeJob: null,
    result: null,
    selectedClip: 0,
    poll: null,
    eventSource: null,
    pollBusy: false,
    pollFailures: 0,
    uploading: false,
    dragged: false,
    setup: null,
    showArchived: false,
    lastDeleted: null,
    update: null,
    updatePoll: null,
    updateBusy: false,
    logs: [],
    logsLoading: false,
    logsDebounce: null,
    settings: {},
    credentials: {muapi: '', openai: '', gemini: ''},
    cuts: [],
    auth: {enabled: false, authenticated: true},
    presets: [],
    batchJobs: [],
    batchActive: false,
    batchMonitors: {},
    editHistory: [],
    redoHistory: [],
    exportPresets: []
  };

  const defaults = {
    theme: 'system',
    accent: 'cyan',
    reducedMotion: false,
    autoUpdateCheck: false,
    mode: 'local',
    outputHeight: '1920',
    captionStyle: 'bold',
    aspect: '9:16',
    autoReframe: true,
    saveFolder: '',
    llmProvider: 'openai'
  };

  const formFields = [
    'sourceInput', 'mode', 'numClips', 'aspect', 'format', 'saveFolder',
    'captionStyle', 'captionPosition', 'captionFont', 'captionSize',
    'captionColor', 'focus', 'viralityPrompt', 'music', 'musicVolume', 'musicFadeIn',
    'musicFadeOut', 'musicDucking', 'duckingStrength', 'transition', 'transitionDuration', 'watermark', 'intro', 'outro', 'language',
    'whisperModel', 'whisperDevice', 'outputHeight', 'removeSilence',
    'jumpCuts', 'normalizeAudio', 'denoiseAudio', 'fillerWords',
    'autoReframe', 'cropPosition', 'fitMode', 'zoom', 'layout'
  ];

  const capabilityGroups = Object.freeze({
    localOnly: [
      'captionStyle', 'captionPosition', 'captionFont', 'captionSize',
      'captionColor', 'removeSilence', 'jumpCuts', 'normalizeAudio',
      'denoiseAudio', 'fillerWords', 'music', 'musicVolume', 'musicFadeIn',
      'musicFadeOut', 'musicDucking', 'duckingStrength', 'transition', 'transitionDuration', 'watermark', 'intro', 'outro', 'layout', 'whisperModel',
      'whisperDevice', 'outputHeight', 'saveFolder', 'autoReframe',
      'cropPosition', 'fitMode', 'zoom', 'llmModel', 'llmTemperature'
    ]
  });

  window.ShortsStudioState = {
    UI_APP_VERSION: '1.0.0',
    THEME_KEY: 'shorts-studio-theme',
    ACCENT_KEY: 'shorts-studio-accent',
    ACCENT_CHOICES: Object.freeze(['cyan', 'indigo', 'sunset', 'emerald', 'berry']),
    SETTINGS_KEY: 'shorts-studio-settings',
    EXPORT_PRESETS_KEY: 'shorts-studio-export-presets',
    state,
    DEFAULT_SETTINGS: Object.freeze(defaults),
    FORM_FIELDS: Object.freeze(formFields),
    CAPABILITIES: capabilityGroups
  };
})();
