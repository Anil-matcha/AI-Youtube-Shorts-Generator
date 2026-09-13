    (() => {
      try {
        const saved = localStorage.getItem('shorts-studio-theme');
        const choice = saved === 'light' || saved === 'dark' || saved === 'system' ? saved : 'system';
        const theme = choice === 'system' && window.matchMedia
          ? (window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark')
          : choice === 'light' ? 'light' : 'dark';
        document.documentElement.dataset.theme = theme;
      } catch (_) {
        document.documentElement.dataset.theme = 'dark';
      }
    })();
