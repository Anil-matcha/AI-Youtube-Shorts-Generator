"""Desktop launcher for Shorts Studio.

The packaged application prefers an embedded WebView2 window, so users do not
need to open a separate browser.  Set ``SHORTS_STUDIO_BROWSER=1`` to force the
fallback browser mode (useful on systems without WebView2).
"""

from __future__ import annotations

import argparse
import ctypes
from importlib import resources
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Optional


_instance_handle: Any = None


def _asset_path(name: str) -> Path:
    """Resolve an asset in source, a frozen bundle, or an installed package."""
    resource_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    bundled = resource_root / "assets" / name
    if bundled.is_file():
        return bundled
    try:
        traversable = resources.files("assets").joinpath(name)
        if traversable.is_file():
            return Path(traversable)
    except (ModuleNotFoundError, FileNotFoundError, TypeError, AttributeError):
        pass
    return bundled


def _ensure_stdio() -> None:
    """Give windowed PyInstaller builds file-like stdio for Uvicorn logging."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def _show_message(title: str, message: str) -> None:
    if os.name == "nt":
        try:
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
            return
        except Exception:
            pass
    print(f"{title}: {message}", file=sys.stderr, flush=True)


def _acquire_single_instance() -> bool:
    """Hold a user-scoped lock that is released automatically on exit."""
    global _instance_handle
    data_root = (
        Path(os.getenv("LOCALAPPDATA") or os.getenv("XDG_CACHE_HOME") or Path.home() / ".cache") / "ShortsStudio"
    )
    try:
        data_root.mkdir(parents=True, exist_ok=True)
        lock_path = data_root / "instance.lock"
        _instance_handle = lock_path.open("a+")
        if os.name == "nt":
            import msvcrt

            _instance_handle.seek(0)
            _instance_handle.write("1")
            _instance_handle.flush()
            msvcrt.locking(_instance_handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(_instance_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except (OSError, IOError):
        if _instance_handle:
            try:
                _instance_handle.close()
            except OSError:
                pass
            _instance_handle = None
        return False


def _free_port(preferred: int) -> int:
    """Use the preferred UI port, or a free loopback port if it is occupied."""
    try:
        preferred = int(preferred)
    except (TypeError, ValueError, OverflowError):
        preferred = 7860
    preferred = max(1024, min(65535, preferred))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_for_server(url: str, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=1.5) as response:
                if response.status == 200:
                    return True
        except (OSError, urllib.error.URLError):
            time.sleep(0.15)
    return False


def _make_tray(window: Any, server: Any) -> Optional[Any]:
    """Create an optional tray icon when pystray/Pillow are available."""
    try:
        import pystray  # type: ignore
        from PIL import Image, ImageDraw  # type: ignore
    except Exception:
        return None

    icon_path = _asset_path("shorts_studio_icon.ico")
    try:
        source = Image.open(icon_path).convert("RGBA")
        resample = getattr(Image, "Resampling", Image).LANCZOS
        source.thumbnail((64, 64), resample)
        image = Image.new("RGBA", (64, 64), (16, 22, 38, 255))
        image.alpha_composite(source, ((64 - source.width) // 2, (64 - source.height) // 2))
    except Exception:
        image = Image.new("RGBA", (64, 64), (16, 22, 38, 255))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((6, 6, 58, 58), radius=14, fill=(94, 231, 239, 255))
        draw.text((24, 17), "S", fill=(7, 16, 25, 255))

    def show(_icon: Any, _item: Any) -> None:
        try:
            window.show()
        except Exception:
            pass

    def quit_app(icon: Any, _item: Any) -> None:
        server.should_exit = True
        try:
            window.destroy()
        except Exception:
            pass
        icon.stop()

    icon = pystray.Icon(
        "Shorts Studio",
        image,
        "Shorts Studio",
        pystray.Menu(
            pystray.MenuItem("Show Shorts Studio", show, default=True),
            pystray.MenuItem("Quit", quit_app),
        ),
    )
    threading.Thread(target=icon.run, name="shorts-studio-tray", daemon=True).start()
    return icon


def main() -> None:
    _ensure_stdio()
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--port", type=int, default=None)
    args, _unknown = parser.parse_known_args()

    if args.browser:
        os.environ["SHORTS_STUDIO_BROWSER"] = "1"
    if args.port is not None:
        os.environ["SHORTS_PORT"] = str(args.port)

    if not _acquire_single_instance():
        _show_message(
            "Shorts Studio is already running", "Close the existing Shorts Studio window before starting another one."
        )
        return

    frozen = bool(getattr(sys, "frozen", False))
    resource_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    package_root = Path(sys.executable).resolve().parent if frozen else resource_root
    os.chdir(resource_root)
    os.environ["PATH"] = os.pathsep.join(
        part for part in (str(package_root), str(resource_root), os.environ.get("PATH", "")) if part
    )
    if str(resource_root) not in sys.path:
        sys.path.insert(0, str(resource_root))

    # A packaged app runs from PyInstaller's resource directory, so the
    # normal python-dotenv search would miss a user-created .env beside the
    # executable. Load that file explicitly before importing web.app.
    if frozen:
        try:
            from dotenv import load_dotenv

            load_dotenv(package_root / ".env", override=False)
        except Exception:
            pass

    # Program Files is not reliably writable by a normal user.  Keep generated
    # projects in the user's profile for installed/portable builds while still
    # loading an optional .env beside the executable.
    if frozen:
        user_data = Path(os.getenv("LOCALAPPDATA") or Path.home()) / "ShortsStudio"
        os.environ.setdefault("LOCAL_OUTPUT_DIR", str(user_data / "output"))
        os.environ.setdefault("SHORTS_STUDIO_DATA_DIR", str(user_data))

    import uvicorn

    preferred_port = os.getenv("SHORTS_PORT", "7860") or "7860"
    port = _free_port(preferred_port)
    url = f"http://127.0.0.1:{port}"
    config = uvicorn.Config("web.app:app", host="127.0.0.1", port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="shorts-studio-server", daemon=True)
    thread.start()
    if not _wait_for_server(url):
        server.should_exit = True
        _show_message(
            "Shorts Studio could not start",
            "The local editor server did not become ready. Check the diagnostics log and try again.",
        )
        return

    use_browser = os.getenv("SHORTS_STUDIO_BROWSER", "0").strip().lower() in {"1", "true", "yes", "on"}
    tray = None
    try:
        if not use_browser:
            try:
                import webview  # type: ignore

                window = webview.create_window(
                    "Shorts Studio",
                    url,
                    width=1480,
                    height=960,
                    min_size=(980, 700),
                    text_select=True,
                )

                def on_closed() -> None:
                    server.should_exit = True

                window.events.closed += on_closed
                tray = _make_tray(window, server)
                webview.start(debug=False)
            except Exception as exc:
                # A missing WebView2 runtime should not make the application
                # unusable; fall back to the user's browser with a clear hint.
                print(f"[desktop] embedded window unavailable: {exc}; opening browser", flush=True)
                webbrowser.open(url)
                thread.join()
        else:
            webbrowser.open(url)
            thread.join()
    finally:
        server.should_exit = True
        if tray is not None:
            try:
                tray.stop()
            except Exception:
                pass
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
