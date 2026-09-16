"""Process-level cancellation regression tests."""

from __future__ import annotations

import sys
import threading

import pytest

from shorts_generator.config import runtime_job_control
from shorts_generator.local.clipper import _run_command


def test_ffmpeg_command_is_terminated_when_job_is_cancelled() -> None:
    cancelled = threading.Event()
    timer = threading.Timer(0.25, cancelled.set)
    timer.start()
    try:
        with runtime_job_control(cancel_check=cancelled.is_set):
            with pytest.raises(RuntimeError, match="Job cancelled"):
                _run_command([sys.executable, "-c", "import time; time.sleep(30)"])
    finally:
        timer.cancel()
