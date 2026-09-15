"""Publishing adapter contracts are deterministic and credential-free."""

from __future__ import annotations

from web.publishing import PLATFORMS, build_publish_plan


def test_platform_plans_include_official_handoff_links_and_limits() -> None:
    item = {
        "title": "A" * 200,
        "description": "B" * 6000,
        "hashtags": "#Shorts",
        "thumbnail_text": "Hook",
        "start_time": 1.0,
        "end_time": 8.0,
        "clip_url": "/api/jobs/j/clip/0",
    }
    for key, spec in PLATFORMS.items():
        plan = build_publish_plan(key, [item])
        assert plan["upload_url"].startswith("https://")
        assert plan["requires_manual_upload"] is True
        assert plan["token_storage"] == "disabled"
        assert len(plan["items"][0]["title"]) <= spec.title_limit
        assert len(plan["items"][0]["description"]) <= spec.description_limit
