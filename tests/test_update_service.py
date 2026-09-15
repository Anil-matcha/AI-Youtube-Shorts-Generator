"""Release update policy tests (no GitHub or process restart required)."""

from __future__ import annotations

from pathlib import Path

from web.update_service import UpdateService


def _service(tmp_path: Path, state: dict) -> UpdateService:
    return UpdateService(
        repo="wiifhub/AI-Youtube-Shorts-Generator",
        current_version="0.10.0",
        data_root=tmp_path,
        state_setter=lambda **values: (state.update(values) or dict(state)),
        state_getter=lambda: dict(state),
    )


def test_release_policy_parses_versions_and_never_installs_source_checkout(tmp_path: Path) -> None:
    service = _service(tmp_path, {})
    assert service.version_tuple("v1.2") == (1, 2, 0)
    assert service.version_tuple("not-a-version") == (0, 0, 0)

    info = service.release_info(
        {
            "tag_name": "v0.11.0",
            "html_url": "https://github.com/wiifhub/AI-Youtube-Shorts-Generator/releases/tag/v0.11.0",
            "assets": [{"name": "ShortsStudio-v0.11.0-windows.zip", "browser_download_url": "https://github.com/a.zip"}],
        }
    )
    assert info["update_available"] is True
    assert info["can_install"] is False
    assert service.select_release_asset({"assets": []}) is None


def test_download_rejects_non_github_urls_and_records_safe_error(tmp_path: Path) -> None:
    state = {}
    service = _service(tmp_path, state)

    service.download_and_apply({"name": "update.zip", "url": "http://example.com/update.zip", "kind": "zip"}, "0.11.0")

    assert state["status"] == "error"
    assert "approved GitHub HTTPS host" in state["error"]


def test_release_digest_is_checked_before_install(tmp_path: Path, monkeypatch) -> None:
    state = {}
    service = _service(tmp_path, state)
    service.require_digest = True
    monkeypatch.setattr(
        "requests.get",
        lambda *args, **kwargs: type(
            "Response",
            (),
            {
                "headers": {"content-length": "4"},
                "raise_for_status": lambda self: None,
                "iter_content": lambda self, chunk_size: [b"data"],
                "__enter__": lambda self: self,
                "__exit__": lambda self, *exc: None,
            },
        )(),
    )
    service.download_and_apply(
        {"name": "update.zip", "url": "https://github.com/example/update.zip", "kind": "zip"},
        "0.11.0",
    )
    assert "release digest" in state["error"]
