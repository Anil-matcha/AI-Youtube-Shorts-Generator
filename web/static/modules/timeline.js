/* Transcript timeline and waveform rendering. */
(() => {
  function createTimeline(ctx) {
    const {$, state, esc, finiteNumber, fmtTime, toast} = ctx;
    async function renderWaveform(jobId) {
      try {
        const data = await ctx.api.json(`/api/jobs/${encodeURIComponent(jobId)}/waveform`);
        if (!Array.isArray(data.peaks) || !data.peaks.length) {
          if ($('waveformTrack')) $('waveformTrack').innerHTML = '<span class="dropzone-sub">No audio waveform available.</span>';
          return;
        }
        $('waveformTrack').innerHTML = data.peaks.map(peak => `<i class="waveform-bar" style="height:${Math.max(4, Math.round(Math.min(1, Math.max(0, finiteNumber(peak))) * 100))}%"></i>`).join('');
      } catch (_) {
        if ($('waveformTrack')) $('waveformTrack').innerHTML = '';
      }
    }

    async function renderTimeline(jobId) {
      try {
        const data = await ctx.api.json(`/api/jobs/${encodeURIComponent(jobId)}/timeline`);
        const duration = Math.max(0, finiteNumber(data.duration));
        const segments = Array.isArray(data.segments) ? data.segments.filter(segment => segment && typeof segment === 'object') : [];
        $('timelineBadge').textContent = `${segments.length} transcript segments`;
        $('timelineEnd').textContent = fmtTime(duration);
        $('timelineTrack').innerHTML = segments.length ? segments.map((segment, index) => {
          const start = Math.max(0, finiteNumber(segment.start));
          const end = Math.max(start, finiteNumber(segment.end, start));
          const left = duration ? Math.min(100, Math.max(0, start / duration * 100)) : 0;
          const width = duration ? Math.max(1, (end - start) / duration * 100) : 4;
          return `<button class="timeline-segment" data-segment="${index}" style="left:${left}%;width:${Math.min(100 - left, width)}%" title="${esc(segment.text || '')}">${esc(segment.text || '')}</button>`;
        }).join('') : '<div class="empty" style="border:0;padding:18px">No transcript segments.</div>';
        $('transcriptList').innerHTML = segments.length ? segments.map((segment, index) => `<button class="transcript-row" data-segment="${index}"><time>${fmtTime(segment.start)}</time><span>${esc(segment.text || '')}</span></button>`).join('') : '<div class="empty" style="padding:15px">No transcript segments.</div>';
        document.querySelectorAll('[data-segment]').forEach(button => button.addEventListener('click', () => {
          const segment = segments[Number(button.dataset.segment)];
          if (!segment) return;
          $('startTime').value = Math.max(0, finiteNumber(segment.start)).toFixed(1);
          $('endTime').value = Math.max(.1, finiteNumber(segment.end, .1)).toFixed(1);
          ctx.updateCaptionOverlay?.();
          toast(`Selected transcript segment at ${fmtTime(segment.start)}.`);
        }));
        renderWaveform(jobId);
      } catch (error) {
        toast(error.message || 'Timeline unavailable', true);
      }
    }
    return {renderTimeline, renderWaveform};
  }
  window.ShortsStudioTimeline = {create: createTimeline};
})();
