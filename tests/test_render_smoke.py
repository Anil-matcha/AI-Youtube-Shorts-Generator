"""Small real-FFmpeg render smoke, skipped on hosts without FFmpeg."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
def test_real_ffmpeg_subclip_render(tmp_path: Path) -> None:
    from shorts_generator.local.clipper import _cut_subclip

    source = tmp_path / "source.mp4"
    output = tmp_path / "short.mp4"
    subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x568:r=24",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    _cut_subclip(str(source), 0, 0.8, str(output))
    assert output.is_file() and output.stat().st_size > 0
