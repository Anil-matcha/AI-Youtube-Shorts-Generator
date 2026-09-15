/* Fetch and job-monitoring boundary. SSE transparently falls back to polling. */
(() => {
  class ApiError extends Error {
    constructor(message, status = 0, data = null) {
      super(message);
      this.name = 'ApiError';
      this.status = status;
      this.data = data;
    }
  }

  async function json(url, options = {}) {
    const response = await fetch(url, options);
    const contentType = response.headers.get('content-type') || '';
    let data = null;
    if (contentType.includes('json')) {
      try { data = await response.json(); } catch (_) { data = null; }
    } else {
      try { data = await response.text(); } catch (_) { data = null; }
    }
    if (!response.ok) {
      const message = data && typeof data === 'object'
        ? (data.error || data.detail || data.message)
        : String(data || 'Request failed');
      throw new ApiError(message || `Request failed (${response.status})`, response.status, data);
    }
    return data;
  }

  function watchJob(id, handlers = {}, options = {}) {
    const interval = Math.max(400, Number(options.interval) || 1200);
    const terminal = new Set(['done', 'error', 'cancelled', 'interrupted']);
    let eventSource = null;
    let timer = null;
    let stopped = false;
    let busy = false;
    let failures = 0;

    const stop = () => {
      stopped = true;
      if (timer) window.clearTimeout(timer);
      timer = null;
      if (eventSource) eventSource.close();
      eventSource = null;
    };

    const emit = job => {
      if (stopped || !job) return;
      failures = 0;
      handlers.onUpdate?.(job);
      if (terminal.has(String(job.status || '').toLowerCase())) {
        handlers.onEnd?.(job);
        stop();
      }
    };

    const poll = async () => {
      if (stopped || busy) return;
      busy = true;
      try {
        emit(await json(`/api/jobs/${encodeURIComponent(id)}`));
      } catch (error) {
        failures += 1;
        handlers.onRetry?.(failures, error);
        if (failures >= 5) {
          stop();
          handlers.onError?.(error);
          return;
        }
      } finally {
        busy = false;
      }
      if (!stopped && !eventSource) timer = window.setTimeout(poll, interval);
    };

    const fallback = () => {
      if (eventSource) eventSource.close();
      eventSource = null;
      if (!stopped && !timer) timer = window.setTimeout(poll, 0);
    };

    try {
      eventSource = new EventSource(`/api/jobs/${encodeURIComponent(id)}/events`);
      eventSource.onmessage = event => {
        try { emit(JSON.parse(event.data)); } catch (_) { /* malformed event; polling remains available */ }
      };
      eventSource.onerror = fallback;
    } catch (_) {
      fallback();
    }
    poll();
    return {stop, get usingSse() { return Boolean(eventSource); }};
  }

  window.ShortsStudioAPI = {ApiError, json, fetchJson: json, watchJob};
})();
