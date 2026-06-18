import json
import os
import sys
import subprocess
import threading
import time
from pathlib import Path
from datetime import datetime, timedelta

import requests

from version import __version__, __app_name__, __repo_owner__, __repo_name__

UPDATE_CHECK_INTERVAL = timedelta(hours=6)
UPDATE_STATE_FILE = None


def _get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR = _get_base_dir()


def _state_path():
    global UPDATE_STATE_FILE
    if UPDATE_STATE_FILE is None:
        UPDATE_STATE_FILE = BASE_DIR / "config" / "update_state.json"
    return UPDATE_STATE_FILE


def _load_state():
    p = _state_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_check": None, "skipped_version": None}


def _save_state(state: dict):
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _parse_version(tag: str) -> str:
    return tag.lstrip("vV").strip()


def _should_check(state: dict) -> bool:
    last = state.get("last_check")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
        return datetime.now() - last_dt > UPDATE_CHECK_INTERVAL
    except Exception:
        return True


def _compare_versions(v1: str, v2: str) -> int:
    p1 = [int(x) for x in v1.split(".")]
    p2 = [int(x) for x in v2.split(".")]
    max_len = max(len(p1), len(p2))
    p1 += [0] * (max_len - len(p1))
    p2 += [0] * (max_len - len(p2))
    for a, b in zip(p1, p2):
        if a < b:
            return -1
        if a > b:
            return 1
    return 0


def check_for_updates(force: bool = False):
    state = _load_state()
    if not force and not _should_check(state):
        return None

    try:
        url = f"https://api.github.com/repos/{__repo_owner__}/{__repo_name__}/releases/latest"
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            state["last_check"] = datetime.now().isoformat()
            _save_state(state)
            return None

        data = resp.json()
        latest_tag = data.get("tag_name", "")
        latest_version = _parse_version(latest_tag)
        skipped = state.get("skipped_version")

        state["last_check"] = datetime.now().isoformat()
        _save_state(state)

        if skipped and _compare_versions(latest_version, skipped) <= 0:
            return None

        if _compare_versions(latest_version, __version__) > 0:
            asset = _find_asset(data)
            return {
                "version": latest_version,
                "tag": latest_tag,
                "download_url": asset["browser_download_url"] if asset else None,
                "asset_name": asset["name"] if asset else None,
                "release_url": data.get("html_url", ""),
                "body": data.get("body", ""),
                "published": data.get("published_at", ""),
            }
    except Exception as e:
        print(f"[Updater] check failed: {e}")

    return None


def _find_asset(release_data: dict):
    assets = release_data.get("assets", [])
    if not assets:
        return None
    preferred = [a for a in assets if a["name"].endswith(".exe") and "setup" in a["name"].lower()]
    if preferred:
        return preferred[0]
    exes = [a for a in assets if a["name"].endswith(".exe")]
    if exes:
        return exes[0]
    largest = max(assets, key=lambda a: a.get("size", 0))
    return largest


def download_update(update_info: dict, progress_callback=None):
    url = update_info.get("download_url")
    if not url:
        raise ValueError("No download URL available")

    temp_dir = BASE_DIR / "temp_update"
    temp_dir.mkdir(parents=True, exist_ok=True)
    local_path = temp_dir / (update_info.get("asset_name") or "Aegis-Update.exe")

    resp = requests.get(url, stream=True, timeout=120)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0))
    downloaded = 0

    with open(local_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
            downloaded += len(chunk)
            if progress_callback and total:
                progress_callback(downloaded / total)

    return local_path


def apply_update(update_exe_path: Path):
    runner = BASE_DIR / "update_runner.ps1"
    if not runner.exists():
        _create_runner_script(runner)

    current_exe = Path(sys.executable) if getattr(sys, "frozen", False) else None
    if not current_exe:
        raise RuntimeError("Update only works in frozen/bundled mode")

    ps_cmd = (
        f'powershell -ExecutionPolicy Bypass -File "{runner}" '
        f'-CurrentExe "{current_exe}" -UpdateExe "{update_exe_path}"'
    )
    subprocess.Popen(ps_cmd, shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
    sys.exit(0)


def _create_runner_script(path: Path):
    content = """param(
    [Parameter(Mandatory=$true)]
    [string]$CurrentExe,
    [Parameter(Mandatory=$true)]
    [string]$UpdateExe
)

Write-Host "Waiting for Aegis to exit..."
Start-Sleep -Seconds 3

$retry = 0
while ($retry -lt 30) {
    try {
        Move-Item -LiteralPath $UpdateExe -Destination $CurrentExe -Force
        Write-Host "Update applied successfully."
        Start-Process -FilePath $CurrentExe
        exit 0
    } catch {
        $retry++
        Start-Sleep -Seconds 1
    }
}

Write-Host "Failed to apply update after 30 retries."
exit 1
"""
    path.write_text(content, encoding="utf-8")


def skip_version(version_str: str):
    state = _load_state()
    state["skipped_version"] = version_str
    _save_state(state)
