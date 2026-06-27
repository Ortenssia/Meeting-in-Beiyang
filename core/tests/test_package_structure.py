"""
挑战 3 - 包结构测试
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.services.social_runtime import SocialRuntime
from core.utils.protocol import Protocol


def test_core_package_is_primary():
    assert SocialRuntime.__module__.startswith("core.")
    assert Protocol.__module__.startswith("core.")
    assert Protocol.DEFAULT_TCP_PORT == 7779


def test_assets_contain_local_data_directories():
    root = Path(__file__).resolve().parents[2]
    assert (root / "assets" / "data").is_dir()
    assert (root / "assets" / "received_files").is_dir()
