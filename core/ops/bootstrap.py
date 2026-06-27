"""Launch-time bootstrap helpers.

This module is the operational boundary for resolving the project root and
preparing import paths. Frontend and backend modules should not repeat this
startup logic.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from core.config import get_app_paths


def prepare_runtime(project_root: str | None = None) -> Path:
    paths = get_app_paths(project_root, refresh=True)
    root = paths.project_root
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    if root.exists():
        os.chdir(root)
    paths.ensure_writable_dirs()
    return root
