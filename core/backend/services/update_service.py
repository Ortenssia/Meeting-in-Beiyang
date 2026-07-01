"""Application update manifest fetching and version comparison."""

from __future__ import annotations

import json
import os
import platform
import re
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


DEFAULT_UPDATE_MANIFEST_URL = "https://raw.githubusercontent.com/Ortenssia/Meeting-in-Beiyang/main/docs/latest.json"
UPDATE_URL_ENV = "BEIYANG_UPDATE_URL"


@dataclass(frozen=True)
class UpdateAsset:
    url: str
    sha256: str = ""
    size: str = ""


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    has_update: bool
    notes: str = ""
    asset: Optional[UpdateAsset] = None
    manifest_url: str = ""


class UpdateCheckError(RuntimeError):
    """Raised when update metadata cannot be loaded or parsed."""


def current_app_version(project_root: Optional[Path] = None) -> str:
    """Return the local app version from pyproject.toml."""
    root = project_root or Path(__file__).resolve().parents[3]
    pyproject = root / "pyproject.toml"
    try:
        with pyproject.open("rb") as handle:
            data = tomllib.load(handle)
        return str(data.get("project", {}).get("version") or "0.0.0")
    except Exception:
        return "0.0.0"


def default_manifest_url() -> str:
    """Return the configured default update manifest URL."""
    return os.environ.get(UPDATE_URL_ENV, DEFAULT_UPDATE_MANIFEST_URL).strip()


def platform_key() -> str:
    """Return the update asset key for the current runtime platform."""
    system = platform.system().lower()
    if _is_android():
        return "android"
    if system == "windows":
        return "windows"
    if system == "darwin":
        return "macos"
    return "linux"


def check_for_updates(
    manifest_url: str,
    *,
    current_version: Optional[str] = None,
    target_platform: Optional[str] = None,
    timeout: float = 10.0,
) -> UpdateInfo:
    """Fetch latest.json and compare it with the local app version."""
    url = (manifest_url or "").strip()
    if not url:
        raise UpdateCheckError("尚未配置更新地址")

    manifest = _fetch_json(url, timeout=timeout)
    latest_version = str(manifest.get("version") or "").strip()
    if not latest_version:
        raise UpdateCheckError("更新清单缺少 version 字段")

    local_version = current_version or current_app_version()
    key = target_platform or platform_key()
    asset_data = manifest.get(key) or {}
    asset = None
    if isinstance(asset_data, dict) and asset_data.get("url"):
        asset = UpdateAsset(
            url=str(asset_data.get("url") or ""),
            sha256=str(asset_data.get("sha256") or ""),
            size=str(asset_data.get("size") or ""),
        )

    return UpdateInfo(
        current_version=local_version,
        latest_version=latest_version,
        has_update=compare_versions(latest_version, local_version) > 0,
        notes=str(manifest.get("notes") or ""),
        asset=asset,
        manifest_url=url,
    )


def compare_versions(left: str, right: str) -> int:
    """Compare semantic-ish version strings.

    Returns 1 if left is newer, -1 if right is newer, 0 if equal.
    """
    left_parts = _version_parts(left)
    right_parts = _version_parts(right)
    max_len = max(len(left_parts), len(right_parts))
    left_parts.extend([0] * (max_len - len(left_parts)))
    right_parts.extend([0] * (max_len - len(right_parts)))
    if left_parts > right_parts:
        return 1
    if left_parts < right_parts:
        return -1
    return 0


def _fetch_json(url: str, *, timeout: float) -> dict[str, Any]:
    try:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "meeting-in-beiyang-update-checker",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(1024 * 1024)
    except urllib.error.URLError as exc:
        raise UpdateCheckError(f"无法连接更新地址: {exc}") from exc
    except Exception as exc:
        raise UpdateCheckError(f"检查更新失败: {exc}") from exc

    try:
        data = json.loads(payload.decode("utf-8"))
    except Exception as exc:
        raise UpdateCheckError("更新清单不是有效 JSON") from exc
    if not isinstance(data, dict):
        raise UpdateCheckError("更新清单格式不正确")
    return data


def _version_parts(version: str) -> list[int]:
    text = (version or "").strip().lstrip("vV")
    return [int(part) for part in re.findall(r"\d+", text)] or [0]


def _is_android() -> bool:
    if hasattr(os, "getandroidapplication"):
        return True
    if "ANDROID_ARGUMENT" in os.environ or "ANDROID_APP_PATH" in os.environ:
        return True
    if os.environ.get("PYTHONHOME", "").startswith("/data/data/"):
        return True
    return False
