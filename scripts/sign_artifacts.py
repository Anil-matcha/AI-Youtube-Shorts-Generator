"""Sign release artifacts when platform credentials are available.

The script is intentionally conservative: it never creates a placeholder
signature. Windows uses Authenticode through ``signtool`` and macOS uses
``codesign`` with optional ``notarytool`` submission. Without the relevant
certificate/identity it writes an unsigned report and exits successfully
unless ``--required`` was supplied by a release job.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


def _run(command: Iterable[str]) -> None:
    subprocess.run([str(item) for item in command], check=True)


def _find_signtool() -> str | None:
    direct = shutil.which("signtool.exe") or shutil.which("signtool")
    if direct:
        return direct
    roots = [
        Path(os.getenv("ProgramFiles(x86)", "")) / "Windows Kits" / "10" / "bin",
        Path(os.getenv("ProgramFiles", "")) / "Windows Kits" / "10" / "bin",
    ]
    candidates = []
    for root in roots:
        if root.is_dir():
            candidates.extend(root.glob("**/x64/signtool.exe"))
    return str(sorted(candidates, reverse=True)[0]) if candidates else None


def _windows_sign(paths: list[Path]) -> dict[str, Any]:
    certificate = os.getenv("WINDOWS_CODESIGN_CERT", "").strip()
    if not certificate:
        return {"status": "unsigned", "reason": "WINDOWS_CODESIGN_CERT is not configured", "artifacts": []}
    cert_path = Path(certificate).expanduser().resolve()
    tool = _find_signtool()
    if not tool:
        return {"status": "unsigned", "reason": "signtool was not found", "artifacts": []}
    if not cert_path.is_file():
        return {"status": "failed", "reason": "configured signing certificate does not exist", "artifacts": []}
    password = os.getenv("WINDOWS_CODESIGN_PASSWORD", "")
    timestamp = os.getenv("WINDOWS_CODESIGN_TIMESTAMP", "http://timestamp.digicert.com").strip()
    signed: list[str] = []
    for path in paths:
        if path.suffix.lower() not in {".exe", ".msi", ".dll"}:
            continue
        command = [tool, "sign", "/fd", "SHA256", "/f", str(cert_path), "/tr", timestamp, "/td", "SHA256"]
        if password:
            command.extend(["/p", password])
        command.append(str(path))
        _run(command)
        signed.append(str(path))
    return {"status": "signed", "method": "Authenticode", "artifacts": signed}


def _macos_sign(paths: list[Path], notarize: bool) -> dict[str, Any]:
    identity = os.getenv("MACOS_SIGN_IDENTITY", "").strip()
    if not identity:
        return {"status": "unsigned", "reason": "MACOS_SIGN_IDENTITY is not configured", "artifacts": []}
    codesign = shutil.which("codesign")
    if not codesign:
        return {"status": "unsigned", "reason": "codesign was not found", "artifacts": []}
    signed: list[str] = []
    for path in paths:
        if path.suffix.lower() not in {".app", ".dmg", ".pkg"} and not path.is_dir():
            continue
        _run([codesign, "--force", "--deep", "--options", "runtime", "--timestamp", "--sign", identity, str(path)])
        signed.append(str(path))
    result: dict[str, Any] = {"status": "signed", "method": "codesign", "artifacts": signed}
    if notarize and signed:
        notarytool = shutil.which("notarytool") or (shutil.which("xcrun") and "xcrun")
        apple_id = os.getenv("APPLE_ID", "").strip()
        team_id = os.getenv("APPLE_TEAM_ID", "").strip()
        password = os.getenv("APPLE_APP_PASSWORD", "")
        if not notarytool or not apple_id or not team_id or not password:
            result.update(status="signed_not_notarized", reason="Apple notarization credentials/tool are not configured")
        else:
            # xcrun is used when notarytool is exposed through Apple's CLI.
            command = [notarytool, "notarytool", "submit"] if Path(notarytool).name == "xcrun" else [notarytool, "submit"]
            command += [signed[0], "--apple-id", apple_id, "--team-id", team_id, "--password", password, "--wait"]
            _run(command)
            result["notarized"] = True
    return result


def sign(paths: list[Path], *, notarize: bool = False) -> dict[str, Any]:
    system = platform.system().lower()
    if system == "windows":
        return _windows_sign(paths)
    if system == "darwin":
        return _macos_sign(paths, notarize)
    return {"status": "not_applicable", "reason": f"platform {system} has no configured signing backend", "artifacts": []}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="EXE/installer or macOS app artifacts to sign")
    parser.add_argument("--report", type=Path, default=Path("release") / "signing-report.json")
    parser.add_argument("--notarize", action="store_true", help="submit the first signed macOS artifact to Apple")
    parser.add_argument("--required", action="store_true", help="fail when a configured signing operation is unavailable")
    args = parser.parse_args()
    paths = [path.expanduser().resolve() for path in args.paths]
    missing = [str(path) for path in paths if not path.exists()]
    result: dict[str, Any] = {"platform": platform.system(), "artifacts_requested": [str(path) for path in paths]}
    if missing:
        result.update(status="failed", reason="artifact does not exist", missing=missing)
    else:
        try:
            result.update(sign(paths, notarize=args.notarize))
        except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
            result.update(status="failed", reason=str(exc))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    if args.required and result.get("status") not in {"signed", "notarized"}:
        return 1
    return 0 if result.get("status") != "failed" or not args.required else 1


if __name__ == "__main__":
    raise SystemExit(main())
