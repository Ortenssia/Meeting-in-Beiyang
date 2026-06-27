"""
挑战 3 - 包结构测试
"""
import ast
import inspect
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.backend.services.social_runtime import SocialRuntime
from core.backend.shared.protocol import Protocol
from core.config import get_app_paths
from core.frontend import theme as T
from core.frontend.app import BeiyangApp
from core.frontend.views.discover import DiscoverView
from core.frontend.views.friends import FriendsView
from core.frontend.views.chat import ChatView
from core.ops.logging_config import NOISY_FRAMEWORK_LOGGERS, configure_logging


def test_core_package_is_primary():
    assert SocialRuntime.__module__.startswith("core.")
    assert Protocol.__module__.startswith("core.")
    assert Protocol.DEFAULT_TCP_PORT == 7779


def test_application_boundaries_exist():
    root = Path(__file__).resolve().parents[1]
    assert (root / "frontend").is_dir()
    assert (root / "backend" / "services").is_dir()
    assert (root / "backend" / "shared").is_dir()
    assert (root / "ops").is_dir()
    assert (root / "config").is_dir()


def test_paths_are_resolved_from_config_layer():
    paths = get_app_paths(refresh=True)
    root = Path(__file__).resolve().parents[2]
    assert paths.project_root == root
    assert paths.assets_dir == root / "assets"
    assert paths.resolve_db_path("friends.db") == root / "assets" / "data" / "friends.db"
    assert paths.asset_src(str(root / "assets" / "avatars" / "avatar_boy.png")) == "avatars/avatar_boy.png"


def test_instance_paths_isolate_all_writable_data():
    paths = get_app_paths(refresh=True)
    alice = paths.for_instance("Alice")
    bob = paths.for_instance("Bob")

    assert alice.assets_dir == bob.assets_dir == paths.assets_dir
    assert alice.data_dir != bob.data_dir
    assert alice.received_files_dir != bob.received_files_dir
    assert alice.received_avatars_dir != bob.received_avatars_dir
    assert alice.resolve_db_path("friends.db").parent == alice.data_dir


def test_default_logging_suppresses_framework_control_noise():
    import logging

    configure_logging("INFO")

    for logger_name in NOISY_FRAMEWORK_LOGGERS:
        assert logging.getLogger(logger_name).getEffectiveLevel() >= logging.WARNING


def test_flet_application_does_not_import_kivy_compatibility():
    root = Path(__file__).resolve().parents[2]
    application_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (root / "core").rglob("*.py")
        if "tests" not in path.parts
    )

    assert "from kivy" not in application_source
    assert "jnius" not in application_source
    assert "KIVY_NO_ARGS" not in application_source
    assert not (root / "buildozer.spec").exists()


def test_frontend_only_uses_available_flet_icons():
    import flet as ft

    root = Path(__file__).resolve().parents[2]
    icon_pattern = re.compile(r"ft\.Icons\.([A-Z0-9_]+)")
    missing = []
    for path in (root / "core" / "frontend").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for icon_name in icon_pattern.findall(source):
            if not hasattr(ft.Icons, icon_name):
                missing.append(f"{path.relative_to(root)}:{icon_name}")

    assert missing == []


def test_frontend_flet_constructor_keywords_match_installed_api():
    import flet as ft

    root = Path(__file__).resolve().parents[2]
    unexpected = []
    for path in (root / "core" / "frontend").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if not isinstance(node.func.value, ast.Name) or node.func.value.id != "ft":
                continue
            constructor = getattr(ft, node.func.attr, None)
            if constructor is None or not callable(constructor):
                continue
            try:
                signature = inspect.signature(constructor)
            except (TypeError, ValueError):
                continue
            parameters = signature.parameters
            if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
                continue
            for keyword in node.keywords:
                if keyword.arg and keyword.arg not in parameters:
                    unexpected.append(
                        f"{path.relative_to(root)}:{node.lineno} "
                        f"ft.{node.func.attr} keyword {keyword.arg}"
                    )

    assert unexpected == []


class _DiscoverAppStub:
    page = None

    def get_discovered_people(self):
        return []

    def get_network_diagnostics(self):
        return {}

    def get_relationship_status(self, *_args):
        return "none"


def test_discover_view_avoids_nested_scrolling_and_expanding_empty_state():
    view = DiscoverView(_DiscoverAppStub())
    root = view.build()
    view.refresh_discovered()

    assert root.scroll is None
    assert view.list_col.scroll is not None
    assert view.list_col.controls[0].height == 180
    assert not view.list_col.controls[0].expand


def test_discovered_person_card_has_bounded_height():
    view = DiscoverView(_DiscoverAppStub())

    card = view._person_card(
        {"name": "Bob", "ip": "127.0.0.1", "tcp_port": 7780, "user_id": "bob"}
    )

    assert card.height == 76


class _FriendsAppStub:
    page = None

    def open_chat_with(self, _name):
        pass

    def has_unread_chat(self, _name):
        return False


def test_friend_card_popup_menu_uses_current_flet_api():
    view = FriendsView(_FriendsAppStub())

    card = view._friend_card({"name": "Bob", "ip": "127.0.0.1", "port": 7780})
    popup = card.content.content.controls[2]

    assert [item.content.value for item in popup.items if item.content] == [
        "发起聊天",
        "管理分类",
        "删除好友",
    ]


def test_avatar_circle_accepts_local_image_path(tmp_path):
    image_path = tmp_path / "avatar.png"
    image_path.write_bytes(b"not-a-real-png-but-valid-src-bytes")

    avatar = T.avatar_circle(str(image_path), T.AVATAR_SM)

    image = avatar.controls[0].content.content
    assert isinstance(image.src, bytes)


def test_avatar_circle_never_contains_null_controls():
    offline_avatar = T.avatar_circle("Alice", T.AVATAR_SM, online=False)
    online_avatar = T.avatar_circle("Bob", T.AVATAR_SM, online=True)
    unread_avatar = T.avatar_circle("Carol", T.AVATAR_SM, unread=True)

    assert len(offline_avatar.controls) == 1
    assert len(online_avatar.controls) == 2
    assert len(unread_avatar.controls) == 2
    assert all(control is not None for control in offline_avatar.controls)
    assert all(control is not None for control in online_avatar.controls)
    assert all(control is not None for control in unread_avatar.controls)


def test_app_unread_chat_state_marks_and_clears():
    app = BeiyangApp.__new__(BeiyangApp)
    app._unread_chats = set()

    app.mark_chat_unread("Bob")
    assert app.has_unread_chat("Bob") is True

    app.mark_chat_read("Bob")
    assert app.has_unread_chat("Bob") is False


def test_avatar_circle_falls_back_for_missing_absolute_image(tmp_path):
    missing_path = tmp_path / "missing.png"

    avatar = T.avatar_circle(str(missing_path), T.AVATAR_SM)

    content = avatar.controls[0].content.content
    assert content.value == str(missing_path)[0].upper()


def test_assets_contain_local_data_directories():
    root = Path(__file__).resolve().parents[2]
    assert (root / "assets" / "data").is_dir()
    assert (root / "assets" / "received_files").is_dir()


class _ChatAppStub:
    page = None
    message_service = None
    device_name = "Me"

    def __init__(self):
        self.sent_files = []

    def get_avatar_for_name(self, name):
        return name

    def get_receive_dir(self):
        return r"C:\Temp"

    def show_toast(self, _text):
        pass

    def send_file_to_friend(self, friend_name, file_path):
        self.sent_files.append((friend_name, file_path))
        return True


def test_chat_file_status_replaces_existing_bubble_in_place():
    import flet as ft

    view = ChatView(_ChatAppStub())
    view._msg_list = ft.Column()
    pending = view._append_bubble(
        "Me",
        view._file_message_content("正在发送文件", "large.bin", r"C:\Temp\large.bin"),
        "12:00:00",
        is_self=True,
    )

    view._replace_bubble(
        pending,
        "Me",
        view._file_message_content("文件发送失败", "large.bin", r"C:\Temp\large.bin"),
        "12:00:01",
        is_self=True,
    )

    assert len(view._msg_list.controls) == 1


def test_failed_file_bubble_retry_reuses_same_bubble(tmp_path):
    import time
    import flet as ft

    app = _ChatAppStub()
    view = ChatView(app)
    view.current_friend = "Bob"
    view._msg_list = ft.Column()
    file_path = tmp_path / "large.bin"
    file_path.write_bytes(b"payload")

    view._append_bubble(
        "Me",
        view._file_message_content("文件发送失败", "large.bin", str(file_path)),
        "12:00:00",
        is_self=True,
    )

    retry_button = None
    pending = list(view._msg_list.controls)
    while pending and retry_button is None:
        control = pending.pop()
        if isinstance(control, ft.IconButton) and control.tooltip == "重试/续传":
            retry_button = control
            break
        for attr in ("controls", "items"):
            pending.extend(getattr(control, attr, []) or [])
        content = getattr(control, "content", None)
        if content is not None:
            pending.append(content)

    assert retry_button is not None
    retry_button.on_click(None)
    time.sleep(0.1)

    assert app.sent_files == [("Bob", str(file_path))]
    assert len(view._msg_list.controls) == 1


def test_root_does_not_contain_python_application_code():
    root = Path(__file__).resolve().parents[2]
    assert not (root / "main.py").exists()
    assert (root / "core" / "main.py").is_file()
