"""Shared test isolation for the FastAPI smoke suite."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


_TEST_DATA_ROOT = Path(tempfile.mkdtemp(prefix="shorts-studio-tests-"))
os.environ["LOCAL_OUTPUT_DIR"] = str(_TEST_DATA_ROOT / "output")
os.environ["SHORTS_STUDIO_DATA_DIR"] = str(_TEST_DATA_ROOT)
os.environ["SHORTS_AUTO_RESUME"] = "false"
