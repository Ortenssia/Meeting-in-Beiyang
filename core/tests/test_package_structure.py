"""
挑战 3 - 包结构测试
"""
import ast
import inspect
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.backend.services.social_runtime import SocialRuntime
from core.backend.services.network_policy import CAMPUS_NETWORK_POLICY
from core.backend.shared.protocol import Protocol
from core.config import get_app_paths
from core.frontend import theme as T
from core.frontend.app import BeiyangApp
from core.frontend.views.discover import DiscoverView
from core.frontend.views.friends import FriendsView
from core.frontend.views.chat import ChatView
from core.frontend.views.profile import TagInput
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


def test_file_offer_callback_is_ui_thread_safe():
    source = inspect.getsource(BeiyangApp._main)

    assert "on_file_offer_received" in source
    assert "_on_file_offer_received" in source
    assert "self._safe" in source


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

    def has_friend_profile_update(self, _name):
        return False

    def get_profile_update_mode(self):
        return "auto"


def test_friend_card_popup_menu_uses_current_flet_api():
    view = FriendsView(_FriendsAppStub())

    card = view._friend_card({"name": "Bob", "ip": "127.0.0.1", "port": 7780})
    popup = card.content.content.controls[2]

    assert [item.content.value for item in popup.items if item.content] == [
        "发起聊天",
        "管理分类",
        "删除好友",
    ]


def test_profile_tag_input_adds_current_text_before_save():
    tags = TagInput("输入兴趣")

    tags.input.value = "编程，篮球"
    assert tags.get_tags() == ["编程", "篮球"]
    assert tags.input.value == ""

    class Event:
        pass

    event = Event()
    event.control = tags.input
    tags.input.value = "编程, 摄影"
    tags._on_input_change(event)
    tags.input.value = ""
    assert tags.get_tags() == ["编程", "篮球", "摄影"]


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
        self.cancelled_files = []
        self.deleted_messages = []
        self.shown_views = []

    def get_avatar_for_name(self, name):
        return name

    def get_receive_dir(self):
        return r"C:\Temp"

    def show_toast(self, _text):
        pass

    def cancel_file_transfer(self, file_id):
        self.cancelled_files.append(file_id)

    def delete_chat_message(self, msg_id, *, is_group=False):
        self.deleted_messages.append((msg_id, is_group))
        return True

    def send_file_to_friend(self, friend_name, file_path, file_id=""):
        self.sent_files.append((friend_name, file_path))
        return True

    def show_view(self, key):
        self.shown_views.append(key)


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


def test_android_outgoing_file_is_staged_in_private_storage(tmp_path):
    source = tmp_path / "picked" / "photo.jpg"
    source.parent.mkdir()
    source.write_bytes(b"android-picker-content")
    data_dir = tmp_path / "app-data"

    app = _ChatAppStub()
    app.page = SimpleNamespace(platform="android", width=360)
    app.paths = SimpleNamespace(data_dir=data_dir)
    view = ChatView(app)

    staged = Path(view._stage_android_outgoing_file(str(source)))

    assert staged.parent == data_dir / "outgoing_files"
    assert staged.name.endswith("_photo.jpg")
    assert staged.read_bytes() == source.read_bytes()


def test_file_transfer_chunk_size_remains_256_kib():
    assert CAMPUS_NETWORK_POLICY.file_chunk_size == 256 * 1024


def test_active_file_bubble_has_determinate_progress_and_pause_button():
    import flet as ft

    view = ChatView(_ChatAppStub())
    view._msg_list = ft.Column()
    view._append_bubble(
        "Me",
        view._file_message_content(
            "正在发送文件",
            "large.bin",
            r"C:\Temp\large.bin",
            "transfer-1",
        ),
        "12:00:00",
        is_self=True,
    )

    pending = list(view._msg_list.controls)
    pause_button = None
    progress_bar = None
    while pending:
        control = pending.pop()
        if isinstance(control, ft.IconButton) and control.tooltip == "暂停传输":
            pause_button = control
        if isinstance(control, ft.ProgressBar):
            progress_bar = control
        for attr in ("controls", "items"):
            pending.extend(getattr(control, attr, []) or [])
        content = getattr(control, "content", None)
        if content is not None:
            pending.append(content)

    assert pause_button is not None
    assert progress_bar is not None
    assert progress_bar.value == 0.0


def test_delete_active_file_bubble_cancels_and_removes_row():
    import flet as ft

    app = _ChatAppStub()
    view = ChatView(app)
    view._msg_list = ft.Column()

    row = view._append_bubble(
        "Me",
        view._file_message_content(
            "正在发送文件",
            "large.bin",
            r"C:\Temp\large.bin",
            "transfer-delete",
        ),
        "12:00:00",
        is_self=True,
        msg_id="transfer-delete",
    )

    assert "transfer-delete" in view._transfer_widgets

    view._delete_message_row(
        row,
        msg_id="transfer-delete",
        file_id="transfer-delete",
    )

    assert view._msg_list.controls == []
    assert app.cancelled_files == ["transfer-delete"]
    assert app.deleted_messages == [("transfer-delete", False)]
    assert "transfer-delete" in view._closed_file_transfers
    assert view._transfer_widgets == {}


def test_delete_text_bubble_removes_persisted_message():
    import flet as ft

    app = _ChatAppStub()
    view = ChatView(app)
    view._msg_list = ft.Column()

    row = view._append_bubble(
        "Me",
        "hello",
        "12:00:00",
        is_self=True,
        msg_id="chat-delete",
    )

    view._delete_message_row(row, msg_id="chat-delete")

    assert view._msg_list.controls == []
    assert app.deleted_messages == [("chat-delete", False)]


def test_incoming_text_bubble_keeps_msg_id_for_delete_menu():
    import flet as ft

    app = _ChatAppStub()
    view = ChatView(app)
    view.current_friend = "Alice"
    view._msg_list = ft.Column()

    view.on_new_message(
        "Alice",
        "hello from alice",
        "2026-06-29 00:30:00",
        msg_id="incoming-delete",
    )

    def item_has_label(item, label):
        nested = [getattr(item, "content", None)]
        while nested:
            control = nested.pop()
            if control is None:
                continue
            if isinstance(control, ft.Text) and control.value == label:
                return True
            for attr in ("controls", "items"):
                nested.extend(getattr(control, attr, []) or [])
            content = getattr(control, "content", None)
            if content is not None:
                nested.append(content)
        return False

    delete_item = None
    pending = list(view._msg_list.controls)
    while pending and delete_item is None:
        control = pending.pop()
        if isinstance(control, ft.PopupMenuItem) and item_has_label(control, "删除此条"):
            delete_item = control
            break
        for attr in ("controls", "items"):
            pending.extend(getattr(control, attr, []) or [])
        content = getattr(control, "content", None)
        if content is not None:
            pending.append(content)

    assert delete_item is not None
    delete_item.on_click(None)
    assert view._msg_list.controls == []
    assert app.deleted_messages == [("incoming-delete", False)]


def test_waiting_accept_file_status_renders_as_file_bubble():
    import flet as ft

    view = ChatView(_ChatAppStub())
    view._msg_list = ft.Column()
    view._append_bubble(
        "Me",
        view._file_message_content(
            "等待对方接受",
            "photo.png",
            r"C:\Temp\photo.png",
            "transfer-waiting",
        ),
        "12:00:00",
        is_self=True,
    )

    assert len(view._msg_list.controls) == 1
    row = view._msg_list.controls[0]
    pending = [row]
    labels = []
    while pending:
        control = pending.pop()
        if isinstance(control, ft.Text):
            labels.append(control.value)
        for attr in ("controls", "items"):
            pending.extend(getattr(control, attr, []) or [])
        content = getattr(control, "content", None)
        if content is not None:
            pending.append(content)

    assert "photo.png" in labels
    assert all('"filename"' not in str(value) for value in labels)


def test_delete_file_offer_declines_and_removes_row():
    import flet as ft

    class _MessageService:
        def __init__(self):
            self.declined = []

        def decline_file_offer(self, file_id):
            self.declined.append(file_id)
            return True

    app = _ChatAppStub()
    app.message_service = _MessageService()
    view = ChatView(app)
    view.current_friend = "Alice"
    view._msg_list = ft.Column()

    view.add_file_offer("Alice", "photo.png", 1024, "offer-delete")
    row = view._msg_list.controls[0]

    view._delete_message_row(row, msg_id="offer-delete", file_id="offer-delete")

    assert view._msg_list.controls == []
    assert app.message_service.declined == ["offer-delete"]
    assert "offer-delete" not in view._pending_file_offers
    assert "offer-delete" in view._closed_file_transfers


def test_waiting_accept_sender_status_updates_same_bubble():
    import flet as ft

    view = ChatView(_ChatAppStub())
    view._msg_list = ft.Column()
    view._append_bubble(
        "Me",
        view._file_message_content(
            "等待对方接受",
            "photo.png",
            r"C:\Temp\photo.png",
            "transfer-waiting",
        ),
        "12:00:00",
        is_self=True,
    )

    view.on_file_status_changed("transfer-waiting", "文件")

    assert len(view._msg_list.controls) == 1
    assert view._transfer_widgets == {}


def test_accepting_file_offer_reuses_offer_bubble_for_progress():
    import threading
    import flet as ft

    class _TransferState:
        def active_file_id_for(self, _filename):
            return ""

    class _MessageService:
        def __init__(self):
            self._file_lock = threading.Lock()
            self.file_transfer = _TransferState()
            self.accepted = []

        def accept_file_offer(self, file_id):
            self.accepted.append(file_id)
            return True

    app = _ChatAppStub()
    app.message_service = _MessageService()
    view = ChatView(app)
    view.current_friend = "Alice"
    view._msg_list = ft.Column()

    view.add_file_offer("Alice", "photo.png", 1024, "transfer-offer")

    accept_button = None
    pending = list(view._msg_list.controls)
    while pending and accept_button is None:
        control = pending.pop()
        if isinstance(control, ft.IconButton) and control.tooltip == "接收文件":
            accept_button = control
            break
        for attr in ("controls", "items"):
            pending.extend(getattr(control, attr, []) or [])
        content = getattr(control, "content", None)
        if content is not None:
            pending.append(content)

    assert accept_button is not None
    accept_button.on_click(None)
    view.on_file_progress("transfer-offer", "Alice", "photo.png", 512, 1024, False)

    assert app.message_service.accepted == ["transfer-offer"]
    assert len(view._msg_list.controls) == 1
    assert "transfer-offer" in view._transfer_widgets


def test_late_progress_after_final_status_does_not_recreate_bubble():
    import flet as ft

    view = ChatView(_ChatAppStub())
    view.current_friend = "Alice"
    view._msg_list = ft.Column()

    view.on_file_progress("transfer-late", "Alice", "photo.png", 512, 1024, False)
    done_content = view._file_message_content(
        "文件",
        "photo.png",
        r"C:\Temp\photo.png",
        "transfer-late",
    )
    view.on_new_message("Alice", done_content, "2026-06-28 12:00:00")
    view.on_file_progress("transfer-late", "Alice", "photo.png", 0, 1024, False)

    assert len(view._msg_list.controls) == 1
    assert view._transfer_widgets == {}


def test_duplicate_final_file_message_is_ignored_after_close():
    import flet as ft

    view = ChatView(_ChatAppStub())
    view.current_friend = "Alice"
    view._msg_list = ft.Column()

    view.on_file_progress("transfer-final", "Alice", "photo.png", 1024, 1024, False)
    done_content = view._file_message_content(
        "文件",
        "photo.png",
        r"C:\Temp\photo.png",
        "transfer-final",
    )
    view.on_new_message("Alice", done_content, "2026-06-28 12:00:00")
    view.on_new_message("Alice", done_content, "2026-06-28 12:00:01")

    assert len(view._msg_list.controls) == 1
    assert view._transfer_widgets == {}


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


def test_incoming_retry_completion_replaces_stale_progress_bubble():
    import flet as ft

    view = ChatView(_ChatAppStub())
    view.current_friend = "Alice"
    view._msg_list = ft.Column()

    view.on_file_progress("old-transfer", "Alice", "driver.exe", 100, 1000, False)
    view.on_file_progress("new-transfer", "Alice", "driver.exe", 520, 1000, False)

    done_content = view._file_message_content(
        "文件",
        "driver.exe",
        r"C:\Temp\driver.exe",
        "new-transfer",
    )
    view.on_new_message("Alice", done_content, "2026-06-28 12:00:00")

    assert len(view._msg_list.controls) == 1
    assert view._transfer_widgets == {}


def test_file_progress_is_retained_without_visible_chat_widget():
    view = ChatView(_ChatAppStub())

    view.on_file_progress(
        "background-transfer",
        "Alice",
        "photo.png",
        512,
        1024,
        True,
    )

    state = view._transfer_states["background-transfer"]
    assert state["completed"] == 512
    assert state["total"] == 1024
    assert state["peer_name"] == "Alice"
    assert state["final"] is False


def test_back_to_chat_list_keeps_transfer_state_but_drops_stale_widgets():
    import flet as ft

    app = _ChatAppStub()
    view = ChatView(app)
    view.current_friend = "Alice"
    view._msg_list = ft.Column()
    view._transfer_states["transfer-1"] = {"peer_name": "Alice", "final": False}
    view._transfer_widgets["transfer-1"] = {"row": ft.Row()}

    view._back_to_list(None)

    assert view.current_friend == ""
    assert view._msg_list is None
    assert view._transfer_widgets == {}
    assert "transfer-1" in view._transfer_states
    assert app.shown_views == ["chat"]


def test_android_file_bubble_fits_viewport_and_omits_self_avatar():
    import flet as ft

    class MobilePage:
        width = 360
        platform = "android"

        def update(self):
            pass

    app = _ChatAppStub()
    app.page = MobilePage()
    view = ChatView(app)
    view.page = app.page
    view._msg_list = ft.Column()
    view._scroll_bottom = lambda: None

    row = view._append_bubble(
        "Me",
        view._file_message_content(
            "正在发送文件",
            "large-photo-with-long-name.png",
            r"C:\Temp\large-photo.png",
            "mobile-transfer",
        ),
        "12:00:00",
        is_self=True,
    )

    assert len(row.controls) == 2
    bubble_gesture = row.controls[-1]
    assert bubble_gesture.content.width <= 268


def test_root_does_not_contain_python_application_code():
    root = Path(__file__).resolve().parents[2]
    assert not (root / "main.py").exists()
    assert (root / "core" / "main.py").is_file()
