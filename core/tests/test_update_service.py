import json

from core.backend.services.update_service import (
    check_for_updates,
    compare_versions,
    current_app_version,
)


def test_compare_versions_handles_v_prefix_and_missing_segments():
    assert compare_versions("v1.2.1", "1.2.0") == 1
    assert compare_versions("1.2", "1.2.0") == 0
    assert compare_versions("1.1.9", "1.2.0") == -1


def test_check_for_updates_selects_platform_asset(tmp_path):
    manifest = {
        "version": "1.0.1",
        "notes": "修复 Android 图标",
        "android": {
            "url": "https://example.invalid/app.apk",
            "sha256": "abc123",
        },
        "windows": {
            "url": "https://example.invalid/app.exe",
        },
    }
    manifest_path = tmp_path / "latest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    info = check_for_updates(
        manifest_path.as_uri(),
        current_version="1.0.0",
        target_platform="android",
    )

    assert info.has_update is True
    assert info.latest_version == "1.0.1"
    assert info.asset.url.endswith("app.apk")
    assert info.asset.sha256 == "abc123"


def test_current_app_version_reads_pyproject():
    assert current_app_version() == "1.8.95"
