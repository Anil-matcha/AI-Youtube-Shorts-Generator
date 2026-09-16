"""Packaging regressions for the Windows portable build command."""

from __future__ import annotations

from scripts import build


def _collect_all_packages(command: list[str]) -> set[str]:
    return {command[index + 1] for index, value in enumerate(command[:-1]) if value == "--collect-all"}


def test_portable_build_collects_local_whisper_runtime() -> None:
    command = build._portable_command("python")

    local_runtime = {"faster_whisper", "ctranslate2", "yt_dlp", "cv2", "openai", "google.genai"}
    assert local_runtime.issubset(_collect_all_packages(command))
    assert local_runtime.issubset(set(build._REQUIRED_BUILD_IMPORTS))
