"""Safe, testable release-update primitives for Shorts Studio.

The FastAPI module should only expose update routes; download, digest, and
portable-install details live here so they can be tested without importing the
entire application.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse


class UpdateService:
    def __init__(
        self,
        *,
        repo: str,
        current_version: str,
        data_root: Path,
        state_setter: Callable[..., Dict[str, Any]],
        state_getter: Callable[[], Dict[str, Any]],
        max_bytes: int = 4 * 1024 * 1024 * 1024,
        require_digest: bool = False,
    ) -> None:
        self.repo = repo
        self.current_version = current_version
        self.data_root = data_root
        self.set_state = state_setter
        self.get_state = state_getter
        self.max_bytes = max(1, int(max_bytes))
        self.require_digest = bool(require_digest)

    @staticmethod
    def version_tuple(value: Any) -> tuple[int, int, int]:
        match = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(value or ""))
        if not match:
            return (0, 0, 0)
        return tuple(int(part or 0) for part in match.groups())  # type: ignore[return-value]

    def github_release(self) -> Dict[str, Any]:
        import requests

        response = requests.get(
            f"https://api.github.com/repos/{self.repo}/releases/latest",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "ShortsStudio-Updater"},
            timeout=(8, 30),
        )
        response.raise_for_status()
        release = response.json()
        if not isinstance(release, dict):
            raise RuntimeError("GitHub returned an invalid release response")
        return release

    @staticmethod
    def package_root() -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent.parent

    def package_root_writable(self) -> bool:
        if not getattr(sys, "frozen", False):
            return False
        root = self.package_root()
        probe = root / f".shorts-studio-update-{uuid.uuid4().hex}.tmp"
        try:
            probe.write_text("ok", encoding="ascii")
            probe.unlink(missing_ok=True)
            return True
        except OSError:
            try:
                probe.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    def update_dir(self) -> Path:
        return self.data_root / "updates"

    def select_release_asset(self, release: Dict[str, Any]) -> Optional[Dict[str, str]]:
        raw_assets = release.get("assets")
        assets = raw_assets if isinstance(raw_assets, list) else []
        candidates: list[Dict[str, str]] = []
        for raw in assets:
            if not isinstance(raw, dict):
                continue
            name = Path(str(raw.get("name") or "")).name
            url = str(raw.get("browser_download_url") or "").strip()
            if not name or not url:
                continue
            lower = name.lower()
            candidate = {"name": name, "url": url, "digest": str(raw.get("digest") or "")}
            if lower.endswith(".zip") and "window" in lower:
                candidate["kind"] = "zip"
                candidates.append(candidate)
            elif lower.endswith(".exe") and ("setup" in lower or "installer" in lower):
                candidate["kind"] = "installer"
                candidates.append(candidate)
        if not candidates:
            return None
        if self.package_root_writable():
            return next((asset for asset in candidates if asset["kind"] == "zip"), candidates[0])
        if getattr(sys, "frozen", False):
            return next((asset for asset in candidates if asset["kind"] == "installer"), candidates[0])
        return None

    def release_info(self, release: Dict[str, Any]) -> Dict[str, Any]:
        tag = str(release.get("tag_name") or "").strip()
        if not tag or self.version_tuple(tag) == (0, 0, 0):
            raise RuntimeError("GitHub release did not include a usable version tag")
        latest = tag.lstrip("vV")
        asset = self.select_release_asset(release)
        return {
            "available": True,
            "update_available": self.version_tuple(latest) > self.version_tuple(self.current_version),
            "current_version": self.current_version,
            "latest_version": latest,
            "tag": tag,
            "url": str(release.get("html_url") or f"https://github.com/{self.repo}/releases/tag/{tag}"),
            "name": str(release.get("name") or f"Shorts Studio {tag}"),
            "published_at": release.get("published_at"),
            "asset": asset,
            "can_install": bool(asset and self.version_tuple(latest) > self.version_tuple(self.current_version)),
            "frozen": bool(getattr(sys, "frozen", False)),
        }

    @staticmethod
    def _ps_quote(value: Any) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    def _write_zip_updater(self, zip_path: Path) -> Path:
        update_root = zip_path.parent
        script = update_root / f"apply-{uuid.uuid4().hex}.ps1"
        pid = os.getpid()
        install_root = self.package_root()
        script_text = f"""$ErrorActionPreference = 'Stop'
$pidToWait = {pid}
$zip = {self._ps_quote(zip_path)}
$install = {self._ps_quote(install_root)}
$stage = Join-Path ([IO.Path]::GetTempPath()) ('ShortsStudio-update-' + [guid]::NewGuid().ToString('N'))
try {{
  while (Get-Process -Id $pidToWait -ErrorAction SilentlyContinue) {{ Start-Sleep -Milliseconds 500 }}
  New-Item -ItemType Directory -Path $stage -Force | Out-Null
  Expand-Archive -LiteralPath $zip -DestinationPath $stage -Force
  $payload = Join-Path $stage 'ShortsStudio'
  if (-not (Test-Path -LiteralPath $payload)) {{ throw 'The downloaded update did not contain a ShortsStudio folder.' }}
  & robocopy $payload $install /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NJH /NJS | Out-Null
  if ($LASTEXITCODE -gt 7) {{ throw "Update copy failed with robocopy exit code $LASTEXITCODE." }}
  Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
  Start-Process -FilePath (Join-Path $install 'ShortsStudio.exe') -WorkingDirectory $install
}} catch {{
  Add-Content -LiteralPath (Join-Path $stage 'update-error.txt') -Value $_.Exception.Message -ErrorAction SilentlyContinue
}} finally {{
  Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
}}
"""
        script.write_text(script_text, encoding="utf-8")
        return script

    def launch(self, asset: Dict[str, str], downloaded: Path) -> None:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if asset.get("kind") == "zip":
            script = self._write_zip_updater(downloaded)
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", str(script)],
                cwd=str(downloaded.parent),
                creationflags=flags,
            )
        else:
            subprocess.Popen(
                [str(downloaded), "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"],
                cwd=str(downloaded.parent),
                creationflags=flags,
            )

    def download_and_apply(self, asset: Dict[str, str], latest: str) -> None:
        import requests

        partial: Optional[Path] = None
        try:
            parsed_url = urlparse(str(asset.get("url") or ""))
            if parsed_url.scheme != "https" or parsed_url.hostname not in {
                "github.com",
                "objects.githubusercontent.com",
                "release-assets.githubusercontent.com",
            }:
                raise RuntimeError("update asset URL is not an approved GitHub HTTPS host")
            target_dir = self.update_dir()
            target_dir.mkdir(parents=True, exist_ok=True)
            filename = Path(asset["name"]).name
            target = target_dir / filename
            partial = target.with_name(target.name + ".part")
            self.set_state(status="downloading", latest_version=latest, asset_name=filename, progress=0, total=0, message=f"Downloading {filename}", error=None)
            with requests.get(asset["url"], headers={"Accept": "application/octet-stream", "User-Agent": "ShortsStudio-Updater"}, stream=True, timeout=(15, 120)) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length") or 0)
                if total > self.max_bytes:
                    raise RuntimeError("update asset exceeds the configured size limit")
                downloaded_bytes = 0
                digest = hashlib.sha256()
                self.set_state(total=total)
                with partial.open("wb") as output:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        output.write(chunk)
                        digest.update(chunk)
                        downloaded_bytes += len(chunk)
                        if downloaded_bytes > self.max_bytes:
                            raise RuntimeError("update asset exceeds the configured size limit")
                        self.set_state(progress=downloaded_bytes, total=total)
            expected = str(asset.get("digest") or "").strip().lower()
            # GitHub's release API normally returns ``sha256:<hex>``. Accept
            # a bare SHA-256 as well because mirrors and older release
            # metadata sometimes expose only the hexadecimal digest.
            if re.fullmatch(r"[0-9a-f]{64}", expected):
                expected = "sha256:" + expected
            if expected and expected != "sha256:" + digest.hexdigest():
                raise RuntimeError("downloaded update failed the GitHub SHA-256 digest check")
            if self.require_digest and not expected:
                raise RuntimeError("this installation requires a release digest, but GitHub did not provide one")
            os.replace(partial, target)
            self.set_state(status="restarting", progress=target.stat().st_size, total=target.stat().st_size, path=str(target), message="Update downloaded. Restarting Shorts Studio…", error=None)
            self.launch(asset, target)
            threading.Thread(target=lambda: (time.sleep(0.35), os._exit(0)), name="shorts-studio-update-exit", daemon=True).start()
        except Exception as exc:
            if partial is not None:
                try:
                    partial.unlink(missing_ok=True)
                except OSError:
                    pass
            self.set_state(status="error", message="Update failed", error=str(exc))
