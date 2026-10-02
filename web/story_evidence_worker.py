"""Isolated VAD inference so request cancellation/deadlines can stop ONNX."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Optional, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web.story_evidence import MAX_OUTPUT_BYTES, speech_evidence


def main(arguments: Optional[Sequence[str]] = None) -> int:
    args = list(arguments if arguments is not None else sys.argv[1:])
    if len(args) != 3:
        return 2
    try:
        start = float(args[1])
        if not math.isfinite(start) or not 0 <= start <= 86400:
            return 2
        with Path(args[0]).open("rb") as stream:
            payload = stream.read(MAX_OUTPUT_BYTES + 1)
        output = speech_evidence(payload, start)
        Path(args[2]).write_text(json.dumps(output, allow_nan=False), encoding="utf-8")
        return 0
    except (ImportError, OSError, RuntimeError, ValueError):
        # No dependency traceback, credentials or host paths reach the UI.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
