"""Measure in-process SSE fan-out before considering a WebSocket transport.

This probe exercises the same ``job_events`` generator used by the browser,
but keeps the clients in one event loop so the result isolates application
fan-out and snapshot serialization from browser/network variability. It does
not claim to be a production load test; run a real reverse-proxy/load test
before changing the transport for a multi-process deployment.

Examples::

    venv\\Scripts\\python.exe scripts\\measure_sse_scaling.py
    venv\\Scripts\\python.exe scripts\\measure_sse_scaling.py \\
        --clients 1,10,50,250,500 --duration 2 --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import web.app as studio  # noqa: E402
from web.feature_routes import job_events  # noqa: E402


_TERMINAL_STATUSES = {"done", "error", "cancelled", "interrupted"}
_DEFAULT_CLIENTS = (1, 10, 50, 250)
_MAX_CLIENTS = 5_000


def parse_clients(value: str) -> List[int]:
    """Parse a comma-separated, positive client-count list."""

    clients: List[int] = []
    for raw in str(value).split(","):
        item = raw.strip()
        if not item:
            continue
        try:
            count = int(item)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid client count: {item!r}") from exc
        if count < 1 or count > _MAX_CLIENTS:
            raise argparse.ArgumentTypeError(f"client counts must be between 1 and {_MAX_CLIENTS}")
        if count not in clients:
            clients.append(count)
    if not clients:
        raise argparse.ArgumentTypeError("at least one client count is required")
    return clients


def _p95(values: Iterable[float]) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    return statistics.quantiles(ordered, n=100, method="inclusive")[94]


async def run_probe(client_count: int, duration: float, update_interval: float) -> Dict[str, Any]:
    """Run one in-process SSE fan-out probe and return JSON-safe metrics."""

    job_id = f"sse-benchmark-{uuid.uuid4().hex}"
    job: Dict[str, Any] = {
        "id": job_id,
        "status": "running",
        "stage": "transcribe",
        "message": "SSE scaling probe",
        "progress": 1,
        "logs": [],
        "request": {"url": "https://example.com/benchmark.mp4", "mode": "api"},
        "created_at": time.time(),
    }
    with studio._lock:
        studio._jobs[job_id] = job

    responses = []
    tasks: List[asyncio.Task[None]] = []
    event_counts = [0] * client_count
    first_events: List[float | None] = [None] * client_count
    start = time.perf_counter()
    cpu_start = time.process_time()

    async def consume(index: int, response: Any) -> None:
        async for _chunk in response.body_iterator:
            now = time.perf_counter()
            event_counts[index] += 1
            if first_events[index] is None:
                first_events[index] = now

    try:
        responses = [await job_events(job_id) for _ in range(client_count)]
        tasks = [asyncio.create_task(consume(index, response)) for index, response in enumerate(responses)]
        await asyncio.sleep(0)

        steps = max(1, math.ceil(duration / update_interval))
        for step in range(steps):
            await asyncio.sleep(update_interval)
            with studio._lock:
                job["progress"] = min(99, 1 + step * 98 // max(1, steps))
                job["message"] = f"SSE scaling step {step + 1}"

        with studio._lock:
            job.update(
                status="done",
                stage="done",
                progress=100,
                message="SSE scaling probe complete",
            )
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        with studio._lock:
            studio._jobs.pop(job_id, None)

    elapsed = time.perf_counter() - start
    cpu_seconds = time.process_time() - cpu_start
    first_latencies = [event - start for event in first_events if event is not None]
    received = sum(1 for count in event_counts if count > 0)
    total_events = sum(event_counts)
    return {
        "clients": client_count,
        "elapsed_seconds": round(elapsed, 4),
        "cpu_seconds": round(cpu_seconds, 4),
        "cpu_percent_of_one_core": round((cpu_seconds / elapsed) * 100, 2) if elapsed else 0.0,
        "events": total_events,
        "events_per_client": round(total_events / client_count, 2),
        "events_per_second": round(total_events / elapsed, 2) if elapsed else 0.0,
        "first_event_p95_ms": round((_p95(first_latencies) or 0.0) * 1000, 3),
        "clients_with_events": received,
        "all_clients_received": received == client_count,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--clients",
        type=parse_clients,
        default=list(_DEFAULT_CLIENTS),
        help="comma-separated client counts (default: 1,10,50,250; max: 5000)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=2.0,
        help="seconds during which the synthetic job changes (default: 2)",
    )
    parser.add_argument(
        "--update-interval",
        type=float,
        default=0.1,
        help="seconds between synthetic progress updates (default: 0.1)",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser


def main(argv: List[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.duration <= 0 or args.update_interval <= 0:
        _parser().error("--duration and --update-interval must be positive")

    results = [asyncio.run(run_probe(count, args.duration, args.update_interval)) for count in args.clients]
    report = {
        "benchmark": "in-process-sse-fanout",
        "duration_seconds": args.duration,
        "update_interval_seconds": args.update_interval,
        "results": results,
    }
    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print("SSE fan-out scaling probe (application/event-loop only)")
    print("clients  events/client  first-event p95  CPU%/core  all clients")
    for result in results:
        print(
            f"{result['clients']:>7}  {result['events_per_client']:>14.2f}  "
            f"{result['first_event_p95_ms']:>15.3f} ms  {result['cpu_percent_of_one_core']:>10.2f}  "
            f"{str(result['all_clients_received']):>11}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
