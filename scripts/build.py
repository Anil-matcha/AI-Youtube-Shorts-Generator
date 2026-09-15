"""Cross-platform build entry point for Shorts Studio.

``python scripts/build.py portable`` builds the PyInstaller bundle on Windows,
macOS, or Linux. The Windows Inno Setup installer is an optional second step;
other platforms receive a clear packaging message instead of a shell error.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List


ROOT = Path(__file__).resolve().parent.parent

# Running ``python scripts/build.py`` puts ``scripts/`` (not the repository
# root) on ``sys.path``.  Add the checkout explicitly so the installer target
# can read the single source-of-truth package version from a clean environment.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _run(command: Iterable[str], *, dry_run: bool = False) -> None:
    args = [str(item) for item in command]
    print("$ " + " ".join(args), flush=True)
    if not dry_run:
        subprocess.run(args, cwd=ROOT, check=True)


def _data_arg(source: str, target: str) -> List[str]:
    return ["--add-data", f"{ROOT / source}{os.pathsep}{target}"]


def build_portable(*, dry_run: bool = False) -> None:
    command: List[str] = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        "ShortsStudio",
        "--windowed",
        "--icon",
        str(ROOT / "assets" / "shorts_studio_icon.ico"),
    ]
    for source, target in (("web", "web"), ("shorts_generator", "shorts_generator"), ("assets", "assets")):
        command.extend(_data_arg(source, target))
    command.extend(
        [
            "--hidden-import",
            "web.app",
            "--collect-submodules",
            "shorts_generator",
            "--collect-all",
            "webview",
            "--collect-all",
            "pystray",
            "--collect-all",
            "PIL",
            "launcher.py",
        ]
    )
    _run(command, dry_run=dry_run)
    if dry_run:
        return
    bundle = ROOT / "dist" / "ShortsStudio"
    executable = bundle / ("ShortsStudio.exe" if os.name == "nt" else "ShortsStudio")
    if not executable.is_file():
        raise RuntimeError(f"PyInstaller did not create {executable}")
    shutil.copy2(ROOT / ".env.example", bundle / ".env.example")
    if os.name == "nt" and (ROOT / "unblock_and_start.bat").is_file():
        shutil.copy2(ROOT / "unblock_and_start.bat", bundle / "unblock_and_start.bat")
    print(f"Portable build ready: {bundle}")


def _get_version() -> str:
    init_path = ROOT / "shorts_generator" / "__init__.py"
    init_text = init_path.read_text(encoding="utf-8")
    for line in init_text.splitlines():
        if line.startswith("__version__"):
            _, value = line.split("=", 1)
            return value.strip().strip('"').strip("'")
    raise RuntimeError("Unable to determine version.")


def build_installer(*, dry_run: bool = False) -> None:
    if os.name != "nt":
        print("Inno Setup installer is Windows-only; skipping on this platform.")
        return
    iscc = shutil.which("ISCC.exe")
    if not iscc:
        for candidate in (
            Path(os.getenv("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
            Path(os.getenv("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
            Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        ):
            if candidate.is_file():
                iscc = str(candidate)
                break
    if not iscc:
        raise RuntimeError("Inno Setup 6 was not found; install it before building the Windows installer")
    version = _get_version()
    _run([iscc, f"/DMyAppVersion={version}", str(ROOT / "installer" / "ShortsStudio.iss")], dry_run=dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=("portable", "installer", "all"), nargs="?", default="portable")
    parser.add_argument("--dry-run", action="store_true", help="print commands without running them")
    args = parser.parse_args()
    if args.target in {"portable", "all"}:
        build_portable(dry_run=args.dry_run)
    if args.target in {"installer", "all"}:
        build_installer(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
