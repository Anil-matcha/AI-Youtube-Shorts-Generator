# SSE scaling decision for v0.10.2

Date: 2026-09-15

The v0.10.2 browser monitor keeps Server-Sent Events (SSE) and falls back to
polling when an `EventSource` connection is unavailable. Before introducing a
WebSocket or external pub/sub dependency, the application fan-out was measured
with the reproducible probe in
[`scripts/measure_sse_scaling.py`](../../scripts/measure_sse_scaling.py).

## Method

```powershell
venv\Scripts\python.exe scripts\measure_sse_scaling.py `
  --clients 1,10,50,250 `
  --duration 1.6 `
  --update-interval 0.1 `
  --json
```

The probe opens concurrent `job_events` streams, changes one synthetic job,
and closes the streams with a terminal snapshot. It measures application/event
loop fan-out only; it does not represent browser, reverse-proxy, network, or
multi-process behavior.

## Observed result

| Connected clients | Events/client | First-event p95 | CPU (% of one core) | All clients received events |
| ---: | ---: | ---: | ---: | :--- |
| 1 | 5.00 | 0.254 ms | 0.00 | Yes |
| 10 | 5.00 | 0.711 ms | 1.54 | Yes |
| 50 | 5.00 | 3.687 ms | 1.55 | Yes |
| 250 | 5.00 | 19.291 ms | 4.58 | Yes |

## Decision

SSE is sufficient for the current single-process creator workspace. The
250-client probe stayed below the v0.10.2 review thresholds of 100 ms first-
event p95, 25% of one CPU core, and zero clients without an event. No
WebSocket or pub/sub transport is justified in v0.10.2.

Re-run the probe with a production reverse proxy before a deployment change.
Reconsider WebSocket/pub-sub if a measured workload exceeds any threshold,
requires cross-process event fan-out, or introduces a sustained multi-tenant
connection count beyond this probe.
