"""Transparent, local-first creator style memory helpers.

The profile is deliberately a small JSON document instead of an opaque model.
Creators can inspect, edit, back up, and delete every learned preference.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from web.security import redact_text


PROFILE_VERSION = 1
_URL_IN_TEXT = re.compile(r"https?://[^\s<>\"']+")


def default_profile() -> Dict[str, Any]:
    return {
        "version": PROFILE_VERSION,
        "name": "My creator style",
        "notes": None,
        "preferences": {},
        "patterns": {"hooks": [], "titles": []},
        "examples": [],
        "source_jobs": [],
        "learned_at": None,
        "updated_at": None,
    }


def load_profile(path: Path) -> Dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return default_profile()
    if not isinstance(raw, dict):
        return default_profile()
    result = default_profile()
    result.update({key: value for key, value in raw.items() if key in result})
    result["version"] = PROFILE_VERSION
    result["preferences"] = raw.get("preferences") if isinstance(raw.get("preferences"), dict) else {}
    result["patterns"] = raw.get("patterns") if isinstance(raw.get("patterns"), dict) else {"hooks": [], "titles": []}
    result["examples"] = raw.get("examples") if isinstance(raw.get("examples"), list) else []
    result["source_jobs"] = raw.get("source_jobs") if isinstance(raw.get("source_jobs"), list) else []
    return _safe_profile(result)


def save_profile(path: Path, profile: Dict[str, Any]) -> Dict[str, Any]:
    safe = _safe_profile(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return safe


def learn_profile(
    jobs: Iterable[Dict[str, Any]],
    *,
    name: Optional[str] = None,
    include_unreviewed: bool = False,
) -> Dict[str, Any]:
    """Learn simple, explainable preferences from completed projects.

    Only request settings and approved clip metadata are copied.  Source URLs,
    credentials, media paths, and provider responses never enter the profile.
    """

    selected_jobs: List[Dict[str, Any]] = []
    for job in jobs:
        if not isinstance(job, dict) or str(job.get("status") or "") != "done":
            continue
        selected_jobs.append(job)

    profile = default_profile()
    profile["name"] = " ".join(str(name or "My creator style").split())[:80] or "My creator style"
    profile["source_jobs"] = [str(job.get("id") or "") for job in selected_jobs if job.get("id")][:50]
    caption_styles: Counter[str] = Counter()
    caption_positions: Counter[str] = Counter()
    aspects: Counter[str] = Counter()
    focuses: Counter[str] = Counter()
    fonts: Counter[str] = Counter()
    transitions: Counter[str] = Counter()
    colors: Counter[str] = Counter()
    auto_reframes: Counter[str] = Counter()
    music_ducking: Counter[str] = Counter()
    hooks: Counter[str] = Counter()
    titles: Counter[str] = Counter()
    examples: List[Dict[str, Any]] = []

    for job in selected_jobs:
        request = job.get("request") if isinstance(job.get("request"), dict) else {}
        for counter, key in (
            (caption_styles, "caption_style"),
            (caption_positions, "caption_position"),
            (aspects, "aspect_ratio"),
            (focuses, "focus"),
            (fonts, "caption_font"),
            (transitions, "transition"),
            (colors, "caption_color"),
        ):
            value = str(request.get(key) or "").strip()
            if value:
                counter[value] += 1
        for counter, key in ((auto_reframes, "auto_reframe"), (music_ducking, "music_ducking")):
            if isinstance(request.get(key), bool):
                counter[str(request[key]).lower()] += 1

        approvals: Dict[int, str] = {}
        factory = job.get("factory") if isinstance(job.get("factory"), dict) else {}
        for item in factory.get("approvals", []) if isinstance(factory.get("approvals"), list) else []:
            if not isinstance(item, dict):
                continue
            try:
                clip_index = int(item.get("clip_index"))
            except (TypeError, ValueError, OverflowError):
                continue
            decision = str(item.get("decision") or "").lower()
            if decision in {"approved", "rejected"}:
                approvals[clip_index] = decision

        shorts = job.get("raw_shorts") if isinstance(job.get("raw_shorts"), list) else []
        for index, short in enumerate(shorts):
            if not isinstance(short, dict):
                continue
            if approvals and not include_unreviewed and approvals.get(index) != "approved":
                continue
            hook = " ".join(str(short.get("hook_sentence") or "").split())[:500]
            title = " ".join(str(short.get("title") or "").split())[:150]
            if hook:
                hooks[hook] += 1
            if title:
                titles[title] += 1
            if len(examples) < 12 and (hook or title):
                examples.append(
                    {
                        "job_id": str(job.get("id") or ""),
                        "clip_index": index,
                        "title": title,
                        "hook": hook,
                        "score": short.get("score"),
                    }
                )

    def most_common(counter: Counter[str]) -> Optional[str]:
        return counter.most_common(1)[0][0] if counter else None

    profile["preferences"] = {
        key: value
        for key, value in {
            "caption_style": most_common(caption_styles),
            "caption_position": most_common(caption_positions),
            "aspect_ratio": most_common(aspects),
            "focus": most_common(focuses),
            "caption_font": most_common(fonts),
            "transition": most_common(transitions),
            "caption_color": most_common(colors),
            "auto_reframe": most_common(auto_reframes),
            "music_ducking": most_common(music_ducking),
        }.items()
        if value
    }
    profile["patterns"] = {
        "hooks": [item[0] for item in hooks.most_common(8)],
        "titles": [item[0] for item in titles.most_common(8)],
    }
    profile["examples"] = examples
    now = time.time()
    profile["learned_at"] = now
    profile["updated_at"] = now
    return _safe_profile(profile)


def _safe_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Bound profile text and remove accidental media/credential fields."""
    def clean(value: Any, limit: int) -> str:
        without_urls = _URL_IN_TEXT.sub("[url omitted]", str(value or ""))
        return redact_text(without_urls, max_length=limit)

    safe = default_profile()
    safe.update(profile)
    safe["version"] = PROFILE_VERSION
    safe["name"] = " ".join(clean(safe.get("name") or "My creator style", 80).split())
    safe["notes"] = " ".join(clean(safe.get("notes") or "", 1000).split()) or None
    preferences = safe.get("preferences") if isinstance(safe.get("preferences"), dict) else {}
    safe_preferences: Dict[str, Any] = {}
    allowed_keys = {"caption_style", "caption_position", "aspect_ratio", "focus", "caption_font", "transition", "caption_color", "hook_style"}
    for key, value in preferences.items():
        name = str(key)
        if name in {"auto_reframe", "music_ducking"}:
            if isinstance(value, bool):
                safe_preferences[name] = value
            elif str(value).strip().lower() in {"true", "false"}:
                safe_preferences[name] = str(value).strip().lower() == "true"
        elif name in allowed_keys and str(value).strip():
            safe_preferences[name] = clean(value, 240).strip()
    safe["preferences"] = safe_preferences
    patterns = safe.get("patterns") if isinstance(safe.get("patterns"), dict) else {}
    safe["patterns"] = {
        "hooks": [" ".join(clean(item, 500).split()) for item in patterns.get("hooks", []) if str(item).strip()][:8],
        "titles": [" ".join(clean(item, 150).split()) for item in patterns.get("titles", []) if str(item).strip()][:8],
    }
    examples: List[Dict[str, Any]] = []
    for item in safe.get("examples", []):
        if not isinstance(item, dict) or not (item.get("title") or item.get("hook")):
            continue
        try:
            clip_index = max(0, int(item.get("clip_index") or 0))
        except (TypeError, ValueError, OverflowError):
            clip_index = 0
        examples.append(
            {
                "job_id": str(item.get("job_id") or "")[:64],
                "clip_index": clip_index,
                "title": " ".join(clean(item.get("title") or "", 150).split()),
                "hook": " ".join(clean(item.get("hook") or "", 500).split()),
                "score": item.get("score"),
            }
        )
        if len(examples) >= 12:
            break
    safe["examples"] = examples
    safe["source_jobs"] = [str(item)[:64] for item in safe.get("source_jobs", []) if str(item).strip()][:50]
    return safe
