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

# These imports are part of the desktop runtime, not optional build-time
# conveniences.  PyInstaller can otherwise continue after silently dropping
# modules that are unavailable in the interpreter used to run this script,
# producing an EXE that launches but fails when a local render reaches a
# dynamically imported dependency.
_REQUIRED_BUILD_IMPORTS = (
    "PyInstaller",
    "fastapi",
    "uvicorn",
    "pydantic",
    "dotenv",
    "webview",
    "pystray",
    "PIL",
    # Local mode imports these packages dynamically when a render starts.
    "faster_whisper",
    "ctranslate2",
    "yt_dlp",
    "cv2",
    "openai",
    "google.genai",
)

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


def _venv_python(venv: Path) -> Path:
    """Return the platform-specific Python executable inside ``venv``."""
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _build_interpreters() -> List[Path]:
    """List likely build interpreters, preferring an active/project venv."""
    candidates: List[Path] = []
    current = Path(sys.executable).resolve()
    if sys.prefix != sys.base_prefix or os.getenv("VIRTUAL_ENV"):
        candidates.append(current)
    for name in ("venv", ".venv"):
        candidates.append(_venv_python(ROOT / name))
    candidates.append(current)

    unique: List[Path] = []
    seen = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def _has_build_dependencies(python: Path) -> bool:
    probe = (
        "import importlib.util, sys; "
        "missing = [name for name in sys.argv[1:] if importlib.util.find_spec(name) is None]; "
        "print('missing: ' + ', '.join(missing) if missing else 'ok'); "
        "raise SystemExit(1 if missing else 0)"
    )
    result = subprocess.run(
        [str(python), "-c", probe, *_REQUIRED_BUILD_IMPORTS],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        detail = (result.stdout or result.stderr).strip()
        print(f"Skipping {python}: {detail or 'required build imports are unavailable'}")
    return result.returncode == 0


def _build_python(*, dry_run: bool = False) -> str:
    """Select an interpreter that can actually build the desktop bundle."""
    candidates = _build_interpreters()
    if dry_run:
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return str(Path(sys.executable).resolve())

    for candidate in candidates:
        if candidate.is_file() and _has_build_dependencies(candidate):
            return str(candidate)

    names = ", ".join(_REQUIRED_BUILD_IMPORTS)
    raise RuntimeError(
        "Portable build requires a Python environment containing "
        f"{names}. Run install_windows.bat (or install requirements-local.txt) "
        "and retry. No build was produced."
    )


def _first_file(candidates: Iterable[Path]) -> Path | None:
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _copy_windows_runtime_assets(bundle: Path, python: Path) -> None:
    """Keep the self-contained Windows bundle's media runtime assets."""
    if os.name != "nt":
        return

    ffmpeg = _first_file(
        [
            Path(shutil.which("ffmpeg.exe") or ""),
            Path(os.getenv("USERPROFILE", "")) / "scoop" / "apps" / "ffmpeg" / "current" / "bin" / "ffmpeg.exe",
            Path("C:/ffmpeg/bin/ffmpeg.exe"),
            Path(os.getenv("ChocolateyToolsLocation", "")) / "ffmpeg" / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe",
        ]
    )
    ffprobe = _first_file(
        [
            Path(shutil.which("ffprobe.exe") or ""),
            Path(os.getenv("USERPROFILE", "")) / "scoop" / "apps" / "ffmpeg" / "current" / "bin" / "ffprobe.exe",
            Path("C:/ffmpeg/bin/ffprobe.exe"),
            Path(os.getenv("ChocolateyToolsLocation", "")) / "ffmpeg" / "tools" / "ffmpeg" / "bin" / "ffprobe.exe",
        ]
    )
    winget_root = Path(os.getenv("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if winget_root.is_dir():
        if ffmpeg is None:
            ffmpeg = _first_file(winget_root.rglob("ffmpeg.exe"))
        if ffprobe is None:
            ffprobe = _first_file(winget_root.rglob("ffprobe.exe"))
    for source, name in ((ffmpeg, "ffmpeg.exe"), (ffprobe, "ffprobe.exe")):
        if source is not None:
            shutil.copy2(source, bundle / name)
            print(f"Bundled {name} from {source}")
        else:
            print(f"WARNING: {name} was not found; install FFmpeg or add it to PATH for local rendering.")

    cuda_root = Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "lib" / "ollama" / "cuda_v12"
    cublas = cuda_root / "cublas64_12.dll"
    if not cublas.is_file():
        cuda_roots = Path(os.getenv("ProgramFiles", "")) / "NVIDIA GPU Computing Toolkit"
        for candidate in sorted(cuda_roots.glob("CUDA/v12*/bin")):
            if (candidate / "cublas64_12.dll").is_file():
                cuda_root = candidate
                cublas = candidate / "cublas64_12.dll"
                break
    if cublas.is_file():
        for name in ("cublas64_12.dll", "cublasLt64_12.dll", "cudart64_12.dll"):
            source = cuda_root / name
            if source.is_file():
                shutil.copy2(source, bundle / name)
        print(f"Bundled CUDA 12 runtime files from {cuda_root}")
    else:
        print("WARNING: CUDA 12 runtime not found; CUDA mode will fall back to CPU.")

    python_root = python.resolve().parent.parent
    cudnn_candidates = (
        python_root / "Lib" / "site-packages" / "ctranslate2" / "cudnn64_9.dll",
        ROOT / "venv" / "Lib" / "site-packages" / "ctranslate2" / "cudnn64_9.dll",
    )
    cudnn = _first_file(cudnn_candidates)
    if cudnn is not None:
        shutil.copy2(cudnn, bundle / cudnn.name)


def _portable_command(python: str) -> List[str]:
    """Build the PyInstaller command for the self-contained desktop bundle."""
    command: List[str] = [
        python,
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
            "faster_whisper",
            "--collect-all",
            "ctranslate2",
            "--collect-all",
            "yt_dlp",
            "--collect-all",
            "cv2",
            "--collect-all",
            "openai",
            "--collect-all",
            "google.genai",
            "--collect-all",
            "webview",
            "--collect-all",
            "pystray",
            "--collect-all",
            "PIL",
            "launcher.py",
        ]
    )
    return command


def build_portable(*, dry_run: bool = False) -> None:
    python = _build_python(dry_run=dry_run)
    command = _portable_command(python)
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
    _copy_windows_runtime_assets(bundle, Path(python))
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
