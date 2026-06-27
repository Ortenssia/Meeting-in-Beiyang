"""Central path and platform configuration for the application.

UI, services, and operational entry points should import this module instead
of deriving project-relative paths on their own.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


DEFAULT_DB_NAME = "friends.db"
DEFAULT_RECEIVE_DIR_NAME = "received_files"
DEFAULT_AVATAR_CACHE_DIR_NAME = "received_avatars"
DEFAULT_INSTANCE_DIR_NAME = ".runtime"

def _candidate_roots() -> Iterable[Path]:
    env_root = os.environ.get("BEIYANG_PROJECT_ROOT")
    if env_root:
        yield Path(env_root)

    here = Path(__file__).resolve()
    yield here.parents[2]
    yield Path.cwd()


def _looks_like_project_root(path: Path) -> bool:
    return (
        (path / "core" / "frontend" / "app.py").is_file()
        and (path / "assets").is_dir()
    )


def _discover_project_root(explicit: Optional[str] = None) -> Path:
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if _looks_like_project_root(candidate):
            return candidate

    for candidate in _candidate_roots():
        try:
            current = candidate.expanduser().resolve()
        except Exception:
            current = candidate
        for parent in [current, *current.parents]:
            if _looks_like_project_root(parent):
                return parent

    return Path.cwd().resolve()


@dataclass(frozen=True)
class AppPaths:
    """Resolved filesystem and Flet asset paths for one app launch."""

    project_root: Path
    assets_dir: Path
    data_dir: Path
    received_files_dir: Path
    received_avatars_dir: Path

    @classmethod
    def discover(cls, project_root: Optional[str] = None) -> "AppPaths":
        root = _discover_project_root(project_root)
        assets_dir = root / "assets"

        data_override = os.environ.get("BEIYANG_DATA_DIR")
        if data_override:
            data_dir = Path(data_override).expanduser()
        else:
            data_dir = assets_dir / "data"

        receive_override = os.environ.get("BEIYANG_RECEIVED_DIR")
        if receive_override:
            received_files_dir = Path(receive_override).expanduser()
        else:
            received_files_dir = assets_dir / DEFAULT_RECEIVE_DIR_NAME

        avatar_override = os.environ.get("BEIYANG_AVATAR_DIR")
        if avatar_override:
            received_avatars_dir = Path(avatar_override).expanduser()
        else:
            received_avatars_dir = assets_dir / DEFAULT_AVATAR_CACHE_DIR_NAME

        return cls(
            project_root=root,
            assets_dir=assets_dir,
            data_dir=data_dir,
            received_files_dir=received_files_dir,
            received_avatars_dir=received_avatars_dir,
        )

    @property
    def font_asset(self) -> str:
        return "fonts/NotoSansSC.ttf"

    @property
    def default_avatar_assets(self) -> list[tuple[str, str]]:
        return [
            ("avatar_boy.png", "avatars/avatar_boy.png"),
            ("avatar_girl.png", "avatars/avatar_girl.png"),
            ("avatar_cat.png", "avatars/avatar_cat.png"),
            ("avatar_space.png", "avatars/avatar_space.png"),
        ]

    def ensure_writable_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.received_files_dir.mkdir(parents=True, exist_ok=True)
        self.received_avatars_dir.mkdir(parents=True, exist_ok=True)

    def for_instance(self, instance_name: str) -> "AppPaths":
        """Create isolated writable paths for a local app instance."""
        slug = re.sub(r"[^\w.-]+", "_", (instance_name or "").strip()).strip("._")
        if not slug:
            raise ValueError("instance name must contain at least one valid character")

        instance_root = self.project_root / DEFAULT_INSTANCE_DIR_NAME / slug
        return AppPaths(
            project_root=self.project_root,
            assets_dir=self.assets_dir,
            data_dir=instance_root / "data",
            received_files_dir=instance_root / DEFAULT_RECEIVE_DIR_NAME,
            received_avatars_dir=instance_root / DEFAULT_AVATAR_CACHE_DIR_NAME,
        )

    def resolve_db_path(self, db_path: Optional[str] = None) -> Path:
        path_text = (db_path or DEFAULT_DB_NAME).strip()
        path = Path(path_text)
        if not path.is_absolute() and len(path.parts) == 1:
            path = self.data_dir / path
        elif not path.is_absolute():
            path = self.project_root / path
        return path

    def resolve_receive_dir(self, receive_dir: Optional[str] = None) -> Path:
        if not receive_dir:
            return self.received_files_dir
        path = Path(receive_dir)
        if not path.is_absolute():
            path = self.project_root / path
        return path

    def resolve_avatar_cache_dir(self, avatar_dir: Optional[str] = None) -> Path:
        if not avatar_dir:
            return self.received_avatars_dir
        path = Path(avatar_dir)
        if not path.is_absolute():
            path = self.project_root / path
        return path

    def asset_src(self, path_or_asset: str) -> str:
        """Convert project asset paths to Flet asset-relative source strings."""
        value = (path_or_asset or "").replace("\\", "/").strip()
        if not value:
            return ""

        assets_prefix = self.assets_dir.as_posix().rstrip("/") + "/"
        if value.startswith(assets_prefix):
            return value[len(assets_prefix):]
        if value.startswith("assets/"):
            return value[len("assets/"):]
        return value


_APP_PATHS: Optional[AppPaths] = None


def get_app_paths(project_root: Optional[str] = None, refresh: bool = False) -> AppPaths:
    global _APP_PATHS
    if refresh or _APP_PATHS is None:
        _APP_PATHS = AppPaths.discover(project_root)
    return _APP_PATHS
