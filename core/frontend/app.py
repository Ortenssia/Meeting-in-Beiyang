"""
Beiyang Social — Flet UI main app controller.

Owns the SocialRuntime lifecycle, wires runtime callbacks into UI refreshes,
and hosts the custom FloatingNavigationBar + per-screen views.
"""
import threading
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

import flet as ft

from core.config import AppPaths, get_app_paths
from core.backend.services.social_runtime import RuntimeConfig, SocialRuntime
from core.backend.shared.helpers import Helpers
from core.backend.shared.protocol import Protocol

from . import theme as T
from .views.discover import DiscoverView
from .views.friends import FriendsView
from .views.chat import ChatView
from .views.moments import MomentsView
from .views.profile import ProfileView


class FloatingNavBar(ft.Container):
    """A premium floating bottom navigation bar with smooth gradients and active indicator glows."""

    def __init__(self, tabs, on_change):
        self.tabs = tabs
        self.on_change = on_change
        self._selected_index = 0

        super().__init__(
            bgcolor=ft.Colors.with_opacity(0.92, ft.Colors.SURFACE_CONTAINER_HIGH),
            border_radius=28,
            padding=T.pad_symmetric(horizontal=12, vertical=10),
            margin=T.pad_only(left=18, right=18, bottom=18),
            border=T.border_all(1, ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE)),
            shadow=T.SHADOW_CARD,
        )
        self.controls_row = ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_AROUND,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.content = self.controls_row
        self._build_tabs()

    def _build_tabs(self):
        self.controls_row.controls.clear()
        for idx, (label, key, icon) in enumerate(self.tabs):
            is_selected = (idx == self._selected_index)

            icon_color = ft.Colors.WHITE if is_selected else ft.Colors.ON_SURFACE_VARIANT
            text_color = ft.Colors.WHITE if is_selected else ft.Colors.ON_SURFACE_VARIANT

            # Action item
            tab_item = ft.GestureDetector(
                mouse_cursor=ft.MouseCursor.CLICK,
                on_tap=lambda _e, i=idx: self._handle_tap(i),
                content=ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(icon, color=icon_color, size=20),
                            ft.Text(
                                label,
                                size=T.FS_BODY,
                                color=text_color,
                                weight=ft.FontWeight.BOLD if is_selected else ft.FontWeight.W_500,
                                visible=is_selected  # Show text only when selected (sleek slide-out look)
                            )
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=6,
                    ),
                    padding=T.pad_symmetric(horizontal=16, vertical=8),
                    border_radius=20,
                    gradient=T.GRADIENT_PRIMARY if is_selected else None,
                    animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT_QUAD),
                    shadow=T.SHADOW_GLOW if is_selected else None,
                )
            )
            self.controls_row.controls.append(tab_item)

    @property
    def selected_index(self):
        return self._selected_index

    @selected_index.setter
    def selected_index(self, value):
        if self._selected_index != value:
            self._selected_index = value
            self._build_tabs()

    def _handle_tap(self, idx):
        self.selected_index = idx
        if self.on_change:
            class NavEvent:
                def __init__(self, control):
                    self.control = control
            self.on_change(NavEvent(self))


class BeiyangApp:
    """Flet application controller."""

    def __init__(self, tcp_port=Protocol.DEFAULT_TCP_PORT,
                 udp_port=Protocol.DEFAULT_UDP_PORT,
                 db_path=None,
                 name_override="",
                 app_paths: Optional[AppPaths] = None):
        self.tcp_port = tcp_port
        self.udp_port = udp_port
        self.paths = app_paths or get_app_paths()
        self.db_path = str(self.paths.resolve_db_path(db_path))
        self.name_override = (name_override or "").strip()
        self.device_name = name_override or Helpers.get_hostname()

        self.runtime: Optional[SocialRuntime] = None
        self.friend_db = None
        self.connection_manager = None
        self.udp_service = None
        self.message_service = None
        self.social_service = None

        self.page: Optional[ft.Page] = None
        self.nav: Optional[FloatingNavBar] = None
        self.views: dict = {}
        self._unread_chats = set()
        self._open_profile_dlg: Optional[ft.AlertDialog] = None
        self._open_profile_dlg_name: str = ""

        # Initialize a hidden Tkinter root once for fast file dialogs
        try:
            import tkinter as tk
            self.tk_root = tk.Tk()
            self.tk_root.withdraw()
        except Exception:
            self.tk_root = None

    # -- bootstrap ---------------------------------------------------------

    def run(self):
        self.paths.ensure_writable_dirs()
        ft.app(target=self._main, assets_dir=str(self.paths.assets_dir))

    def _main(self, page: ft.Page):
        self.page = page
        self._init_services()
        self._build_shell(page)
        self.runtime.start()

        # bind runtime callbacks
        self.runtime.on_discovery_changed = lambda: self._safe(self._on_discovery)
        self.runtime.on_online_changed = lambda: self._safe(self._on_online)
        self.runtime.on_friends_changed = lambda: self._safe(self._on_friends)
        self.runtime.on_message_received = lambda n, c, t, mid="": self._safe(
            lambda: self._on_message(n, c, t, mid))
        self.runtime.on_friend_request = self._on_friend_request
        self.runtime.on_friend_accepted = lambda n, ip: self._safe(self._on_online)
        self.runtime.on_friend_deleted = lambda n: self._safe(lambda: self._on_friend_deleted(n))
        self.runtime.on_error = lambda msg: print(f"[BeiyangSocial] error: {msg}")
        self.runtime.on_group_message_received = lambda gid, s, c, ts: self._safe(
            lambda: self._on_group_message(gid, s, c, ts))
        self.runtime.on_moments_changed = lambda: self._safe(self._on_moments_changed)
        self.runtime.on_notifications_changed = lambda: self._safe(self._on_notifications_changed)
        self.message_service.on_friend_profile_update_available = (
            lambda name: self._safe(lambda: self._on_profile_update_available(name))
        )
        self.message_service.on_friend_profile_updated = (
            lambda name: self._safe(lambda: self._on_profile_updated(name))
        )
        self.message_service.on_file_received = (
            lambda name, path, ts: self._safe(
                lambda: self._on_file_received(name, path, ts)
            )
        )
        self.message_service.on_file_progress = (
            lambda fid, peer, name, done, total, sending, confirmed=0: self._safe(
                lambda: self.views["chat"].on_file_progress(
                    fid, peer, name, done, total, sending, confirmed=confirmed
                )
            )
        )
        self.message_service.on_file_offer_received = (
            lambda name, filename, size, fid: self._safe(
                lambda: self._on_file_offer_received(name, filename, size, fid)
            )
        )
        self.message_service.on_file_status_changed = (
            lambda fid, status: self._safe(
                lambda: self.views["chat"].on_file_status_changed(fid, status)
            )
        )

        # initial status fetch
        self._update_status_indicators()

        # apply active theme & background image on startup
        self.update_theme_and_background()

        # initial content
        self.show_view("chat")

    def _init_services(self):
        self.runtime = SocialRuntime(
            RuntimeConfig(
                tcp_port=self.tcp_port,
                udp_port=self.udp_port,
                db_path=self.db_path,
                name_override=self.name_override,
                avatar_dir=str(self.paths.received_avatars_dir),
                paths=self.paths,
            )
        ).initialize()
        self.friend_db = self.runtime.friend_db
        self.connection_manager = self.runtime.connection_manager
        self.udp_service = self.runtime.udp_service
        self.message_service = self.runtime.message_service
        self.social_service = self.runtime.social_service
        self.device_name = self.runtime.device_name

    def _build_shell(self, page: ft.Page):
        page.title = "相识北洋"
        page.theme_mode = ft.ThemeMode.SYSTEM

        # FilePicker is a Service in Flet 0.85+, not a visual overlay control.
        self.profile_file_picker = ft.FilePicker()
        self.chat_file_picker = ft.FilePicker()
        self.receive_dir_picker = ft.FilePicker()
        self.moment_image_picker = ft.FilePicker()
        page.services.append(self.profile_file_picker)
        page.services.append(self.chat_file_picker)
        page.services.append(self.receive_dir_picker)
        page.services.append(self.moment_image_picker)

        # Register local custom Noto Sans SC font from assets
        page.fonts = {
            "Noto Sans SC": self.paths.font_asset
        }

        # Premium Deep Purple seed theme with custom Noto Sans SC font
        page.theme = ft.Theme(
            color_scheme_seed=ft.Colors.DEEP_PURPLE,
            visual_density=ft.VisualDensity.COMFORTABLE,
            font_family="Noto Sans SC",
        )

        # Safe-area aware padding: on Android/iOS reserve space for the
        # system status bar so it doesn't overlap app content.
        is_mobile = str(page.platform).lower() in (
            "android",
            "ios",
            "pageplatform.android",
            "pageplatform.ios",
        )
        if is_mobile:
            page.padding = ft.Padding.only(top=40, left=0, right=0, bottom=0)
        else:
            page.padding = 0
            # Window size only meaningful on desktop; skip on mobile.
            page.window_width = 460
            page.window_height = 820
            page.window_min_width = 380
            page.window_min_height = 640

        # Set window icon (desktop only — .ico is Windows-specific)
        if not is_mobile:
            icon_path = self.paths.assets_dir / "app_icon.ico"
            if icon_path.exists():
                page.window.icon = str(icon_path.resolve())

        # Initialize network diagnostic status indicators
        self.udp_status_dot = ft.Container(
            width=8, height=8, border_radius=4,
            bgcolor=ft.Colors.RED_400,
            tooltip="UDP 广播: 关闭",
            shadow=ft.BoxShadow(blur_radius=4, color=ft.Colors.with_opacity(0.3, ft.Colors.RED_500))
        )
        self.tcp_status_dot = ft.Container(
            width=8, height=8, border_radius=4,
            bgcolor=ft.Colors.RED_400,
            tooltip="TCP 监听: 关闭",
            shadow=ft.BoxShadow(blur_radius=4, color=ft.Colors.with_opacity(0.3, ft.Colors.RED_500))
        )

        # Sleek App Header Bar
        self.top_header = ft.Container(
            content=ft.Row(
                [
                    ft.Row(
                        [
                            ft.Text("相识", size=18, weight=ft.FontWeight.W_900, color=ft.Colors.DEEP_PURPLE_400),
                            ft.Text("北洋", size=18, weight=ft.FontWeight.W_900),
                        ],
                        spacing=0,
                    ),
                    ft.Row(
                        [
                            ft.Row(
                                [
                                    self.udp_status_dot,
                                    ft.Text("UDP广播", size=10, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE_VARIANT),
                                ],
                                spacing=4,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            ft.Row(
                                [
                                    self.tcp_status_dot,
                                    ft.Text("TCP连线", size=10, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE_VARIANT),
                                ],
                                spacing=4,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                        ],
                        spacing=10,
                    )
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=T.pad_symmetric(horizontal=T.SP_LG, vertical=T.SP_MD),
            border=ft.Border(bottom=ft.BorderSide(1, ft.Colors.with_opacity(0.06, ft.Colors.ON_SURFACE))),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        )

        self.views = {
            "discover": DiscoverView(self),
            "friends": FriendsView(self),
            "chat": ChatView(self),
            "moments": MomentsView(self),
            "profile": ProfileView(self),
        }

        # Use our custom floating bottom dock
        self.nav = FloatingNavBar(
            tabs=T.TABS,
            on_change=self._on_nav_change,
        )

        self._stack = ft.Stack(expand=True)
        self.root_bg = ft.Image(
            src="placeholder",
            fit=ft.BoxFit.COVER,
            opacity=0.08,
            expand=True,
            visible=False,
        )
        self.root_container = ft.Container(
            content=ft.Column(
                [
                    self.top_header,
                    ft.Container(
                        content=self._stack,
                        expand=True,
                        padding=T.pad_only(
                            left=8 if is_mobile else T.SP_LG,
                            right=8 if is_mobile else T.SP_LG,
                            top=8 if is_mobile else T.SP_LG,
                        ),
                    ),
                    self.nav,
                ],
                spacing=0,
                expand=True,
            ),
            expand=True,
        )
        page.add(
            ft.Stack(
                [
                    self.root_bg,
                    self.root_container,
                ],
                expand=True,
            )
        )

    # -- navigation --------------------------------------------------------

    def _on_nav_change(self, e):
        idx = e.control.selected_index
        self.show_view(T.TABS[idx][1])

    def show_view(self, key: str, **kwargs):
        if key not in self.views:
            return

        # chat window mode hides both top header and bottom nav bar for maximum immersion
        if key == "chat" and kwargs.get("friend") and self.nav:
            self.nav.visible = False
            self.top_header.visible = False
        else:
            if self.nav:
                self.nav.visible = True
            if hasattr(self, "top_header") and self.top_header:
                self.top_header.visible = True

        # update selected index
        if self.nav and key in [k for _, k, _ in T.TABS]:
            self.nav.selected_index = [k for _, k, _ in T.TABS].index(key)

        view = self.views[key]
        if key == "chat" and kwargs.get("friend"):
            is_group = kwargs.get("is_group", False)
            group_id = kwargs.get("group_id", "")
            view.open_chat(kwargs["friend"], is_group=is_group, group_id=group_id)

        self._stack.controls = [view.build()]
        self.page.update()

        if key != "chat" or not kwargs.get("friend"):
            self._safe(view.on_enter)

    # -- runtime callback handlers (all UI-side, run on Flet thread) -------

    def _safe(self, fn):
        """Run a UI update on the Flet thread; swallow + log exceptions."""
        def _run():
            try:
                fn()
                if self.page:
                    self.page.update()
            except Exception as exc:  # never let a refresh crash the app
                print(f"[BeiyangApp] callback error: {exc}")
        try:
            if self.page:
                self.page.run_thread(_run) if hasattr(self.page, "run_thread") else _run()
        except Exception:
            _run()

    def _update_status_indicators(self):
        """Update TCP/UDP top bar indicator lights based on health details."""
        if not self.runtime or not hasattr(self, "udp_status_dot"):
            return
        diag = self.runtime.get_network_diagnostics() or {}
        udp_running = diag.get("udp_running", False)
        tcp_running = diag.get("tcp_running", False)

        self.udp_status_dot.bgcolor = ft.Colors.GREEN_400 if udp_running else ft.Colors.RED_400
        self.udp_status_dot.tooltip = f"UDP广播: {'运行中' if udp_running else '已停止'} (端口 {diag.get('udp_port', '-')})"
        self.udp_status_dot.shadow = ft.BoxShadow(
            blur_radius=4,
            color=ft.Colors.with_opacity(0.4, ft.Colors.GREEN_500 if udp_running else ft.Colors.RED_500)
        )

        self.tcp_status_dot.bgcolor = ft.Colors.GREEN_400 if tcp_running else ft.Colors.RED_400
        self.tcp_status_dot.tooltip = f"TCP监听: {'运行中' if tcp_running else '已停止'} (端口 {diag.get('tcp_port', '-')})"
        self.tcp_status_dot.shadow = ft.BoxShadow(
            blur_radius=4,
            color=ft.Colors.with_opacity(0.4, ft.Colors.GREEN_500 if tcp_running else ft.Colors.RED_500)
        )

    def _on_discovery(self):
        self._update_status_indicators()
        self.views["discover"].refresh_discovered()
        self.views["discover"].refresh_diagnostics()

    def _on_online(self):
        self._update_status_indicators()
        self.views["discover"].refresh_online()
        self.views["friends"].refresh()
        if self.views["chat"].current_friend:
            self.views["chat"].refresh_header()

    def _on_friends(self):
        self.views["friends"].refresh()
        if self.views["chat"].current_friend:
            self.views["chat"].refresh_header()

    def _on_message(self, name, content, timestamp, msg_id=""):
        chat_view = self.views.get("chat")
        is_open = bool(
            chat_view
            and chat_view.current_friend == name
            and not chat_view.is_group
        )
        if is_open:
            self.mark_chat_read(name)
        else:
            self.mark_chat_unread(name)
        self.views["chat"].on_new_message(name, content, timestamp, msg_id=msg_id)
        self.views["friends"].refresh()

    def _on_group_message(self, group_id, sender, content, timestamp):
        if "chat" in self.views:
            self.views["chat"].on_new_group_message(group_id, sender, content, timestamp)

    def _on_moments_changed(self):
        if "moments" in self.views:
            self.views["moments"].on_moments_changed()

    def _on_notifications_changed(self):
        if "chat" in self.views:
            try:
                self.views["chat"].refresh_notifications()
            except Exception:
                pass

    def _on_file_offer_received(self, from_name, filename, size, file_id):
        """Forward file offer to the chat view so it appears inline."""
        if not self.page:
            return
        chat = self.views.get("chat")
        if chat:
            chat.add_file_offer(from_name, filename, size, file_id)
        # Also show a brief toast so the user notices even outside chat.
        self.show_toast(f"📁 {from_name} 发来文件: {filename}")

    def _on_file_received(self, name, path, timestamp):
        # Avatar and card-background transfers also arrive through the file
        # channel. Once the DB has been updated by MessageService, refresh
        # avatar/card consumers.
        if "friends" in self.views:
            self.views["friends"].refresh()
        chat = self.views.get("chat")
        if chat and chat.current_friend:
            chat.refresh_header()
        if self._open_profile_dlg and self._open_profile_dlg_name == name:
            try:
                self._open_profile_dlg.open = False
                self.page.update()
                self.page.overlay.remove(self._open_profile_dlg)
            except Exception:
                pass
            self._open_profile_dlg = None
            self._open_profile_dlg_name = ""
            self.show_friend_profile(name)
        try:
            received_path = Path(path).resolve()
            avatar_root = self.paths.received_avatars_dir.resolve()
            is_profile_media = received_path == avatar_root or avatar_root in received_path.parents
        except Exception:
            is_profile_media = False
        if not is_profile_media:
            self.show_toast(f"文件接收成功：{Path(path).name}\n保存位置：{path}")
        if self.page:
            self.page.update()

    def _on_profile_update_available(self, name):
        mode = (self.friend_db.get_app_setting("profile_update_mode", "auto") or "auto")
        if mode == "manual":
            if name:
                self.show_toast(f"{name} 的资料有更新（手动模式）")
            if "friends" in self.views:
                self.views["friends"].refresh()
            return

        # Auto mode — pull immediately.
        if name:
            self.show_toast(f"{name} 的资料有更新，正在自动同步...")
            self.request_friend_profile_update(name, silent=True)
        if "friends" in self.views:
            self.views["friends"].refresh()

    def _on_profile_updated(self, name):
        if name:
            self.show_toast(f"{name} 的资料已更新")
        self._on_friends()
        chat = self.views.get("chat")
        if chat:
            chat.refresh_header()
        # If a profile dialog is open for this friend, refresh it in-place
        if self._open_profile_dlg and self._open_profile_dlg_name == name:
            try:
                self._open_profile_dlg.open = False
                self.page.update()
                self.page.overlay.remove(self._open_profile_dlg)
            except Exception:
                pass
            self._open_profile_dlg = None
            self._open_profile_dlg_name = ""
            self.show_friend_profile(name)
        if self.page:
            self.page.update()

    def _on_friend_request(self, profile, is_match, from_ip=None):
        profile = dict(profile or {})
        sender_name = profile.get("name", "未知用户")
        self.show_toast(f"👤 收到来自「{sender_name}」的好友申请，请前往「系统通知」查看和处理。")
        self._on_notifications_changed()

    def _on_friend_deleted(self, friend_name):
        self.show_toast(f"ℹ️ 好友「{friend_name}」已将您从好友列表中删除。")
        self._on_friends()
        self._on_online()

    # -- UI-facing API ------------------------------------------------------

    def get_local_device_info(self):
        return {"name": self.device_name, "ip": Helpers.get_default_ip()}

    def set_tcp_port(self, port):
        self.tcp_port = port
        if self.runtime:
            self.runtime.set_tcp_port(port)

    def get_receive_dir(self):
        if self.runtime:
            return self.runtime.get_receive_dir()
        return str(self.paths.received_files_dir)

    def set_receive_dir(self, receive_dir):
        if self.runtime:
            resolved = self.runtime.set_receive_dir(receive_dir)
            self.show_toast(f"接收文件保存目录已更新: {resolved}")
            return resolved
        return ""

    def get_my_profile(self):
        p = self.friend_db.get_my_profile()
        p["ip"] = Helpers.get_default_ip()
        if self.device_name and not p.get("name"):
            p["name"] = self.device_name
        return p

    def get_avatar_for_name(self, name):
        if not name:
            return ""
        if name == self.device_name and self.friend_db:
            profile = self.friend_db.get_my_profile()
            return self.paths.asset_src(profile.get("avatar", "")) or name
        if self.friend_db:
            friend = self.friend_db.get_friend(name)
            if friend and friend.get("avatar"):
                return self.paths.asset_src(friend.get("avatar", ""))
        return name

    def save_profile(self, profile):
        if self.runtime:
            ok = self.runtime.save_profile(profile)
            self.device_name = self.runtime.device_name
            if ok:
                self.update_theme_and_background()
                if self.message_service:
                    self.friend_db.set_app_setting("my_profile_updated_at", str(time.time()))
                    threading.Thread(
                        target=self.message_service.broadcast_profile_update_notice,
                        daemon=True,
                    ).start()
                    self._on_friends()
            return ok
        return False

    def update_theme_and_background(self):
        if not self.page or not self.friend_db:
            return

        # 1. Update Theme Color
        theme_color = self.friend_db.get_app_setting("theme_color", "DEEP_PURPLE")
        import core.frontend.theme as T
        import os
        if theme_color in T.THEME_COLORS:
            color_details = T.THEME_COLORS[theme_color]
            self.page.theme = ft.Theme(
                color_scheme_seed=color_details["seed"],
                visual_density=ft.VisualDensity.COMFORTABLE,
                font_family="Noto Sans SC",
            )
            T.GRADIENT_PRIMARY.colors = color_details["gradient"]

        # 2. Update Background Image
        profile = self.friend_db.get_my_profile()
        bg_path = profile.get("background", "").strip()
        if bg_path and os.path.exists(bg_path):
            try:
                import base64
                with open(bg_path, "rb") as f:
                    bg_bytes = f.read()
                self.root_bg.src_base64 = base64.b64encode(bg_bytes).decode()
                self.root_bg.visible = True
            except Exception as e:
                print(f"[BeiyangApp] failed to load global background: {e}")
                self.root_bg.visible = False
        else:
            self.root_bg.visible = False

        self.page.update()

    def has_friend_profile_update(self, name):
        return bool(
            self.message_service
            and self.message_service.has_pending_profile_update(name)
        )

    def get_profile_update_mode(self) -> str:
        if self.friend_db:
            mode = self.friend_db.get_app_setting("profile_update_mode", "auto")
            return mode if mode in ("auto", "manual") else "auto"
        return "auto"

    def request_friend_profile_update(self, name, silent=False):
        if self.message_service:
            ok = self.message_service.request_friend_profile(name)
            if not silent:
                self.show_toast("已请求更新资料" if ok else "请求更新失败，对方可能不在线")
            return ok
        return False

    def scan_for_people(self):
        if self.runtime:
            self.runtime.scan_for_people()

    def probe_peer(self, ip, port=Protocol.DEFAULT_TCP_PORT, display_name=""):
        if self.runtime:
            return self.runtime.probe_peer(ip, port, display_name)
        return {"ip": ip, "tcp_port": port, "tcp_connected": False}

    def get_discovered_people(self):
        return self.runtime.get_discovered_people() if self.runtime else []

    def get_network_diagnostics(self):
        return self.runtime.get_network_diagnostics() if self.runtime else {}

    def send_friend_request(self, name, ip, port=Protocol.DEFAULT_TCP_PORT, user_id=""):
        if self.is_existing_friend(name, ip, port, user_id):
            return False
        if self.message_service:
            return self.message_service.send_friend_request(name, ip, port, user_id)
        return False

    def is_existing_friend(self, name="", ip="", port=0, user_id=""):
        if not self.friend_db:
            return False
        return self.friend_db.get_relationship_status(
            user_id=user_id, name=name, ip=ip, port=port,
        ) in ("pending_sent", "pending_received", "accepted")

    def get_relationship_status(self, name="", ip="", port=0, user_id=""):
        if not self.friend_db:
            return "none"
        return self.friend_db.get_relationship_status(
            user_id=user_id, name=name, ip=ip, port=port,
        )

    def get_all_friends(self):
        return self.runtime.get_all_friends() if self.runtime else []

    def get_online_friends(self):
        return self.runtime.get_online_friends() if self.runtime else []

    def delete_friend(self, name):
        friend = self.friend_db.get_friend(name)
        if friend:
            ip = friend.get("ip")
            port = friend.get("port")

            # 发送 FRIEND_DELETE 消息通知对方删除自己
            if self.message_service:
                try:
                    self.message_service.send_friend_delete(name)
                except Exception:
                    pass
                time.sleep(0.2)  # 给操作系统足够的时间发送 TCP 缓存，避免被接下来的主动断连中断

            if ip and self.connection_manager:
                endpoint = f"{ip}:{port}" if port else ip
                self.connection_manager.disconnect_friend(endpoint)
            self.friend_db.remove_friend(name)
            self._on_friends()
            self._on_online()

    def set_friend_category(self, name, category):
        if self.friend_db:
            self.friend_db.set_friend_category(name, category)
            self._on_friends()

    def get_system_notifications(self):
        return self.friend_db.get_system_notifications() if self.friend_db else []

    def clear_system_notifications(self):
        if self.friend_db:
            self.friend_db.clear_system_notifications()
            self._on_notifications_changed()

    def mark_all_notifications_read(self):
        if self.friend_db:
            self.friend_db.mark_all_notifications_read()
            self._on_notifications_changed()

    def mark_notification_read(self, notif_id):
        if self.friend_db:
            self.friend_db.mark_notification_read(notif_id)
            self._on_notifications_changed()

    def open_chat_with(self, name, is_group=False, group_id=""):
        if not is_group:
            self.mark_chat_read(name)
        self.show_view("chat", friend=name, is_group=is_group, group_id=group_id)
        if "friends" in self.views:
            self.views["friends"].refresh()

    def mark_chat_unread(self, name):
        if name:
            self._unread_chats.add(name)

    def mark_chat_read(self, name):
        if name:
            self._unread_chats.discard(name)

    def has_unread_chat(self, name):
        return bool(name and name in self._unread_chats)

    def send_chat_message(self, friend_name, text, msg_id=""):
        if self.message_service:
            return self.message_service.send_message(friend_name, text, msg_id=msg_id)
        return False

    def send_file_to_friend(self, friend_name, file_path, file_id=""):
        if self.message_service:
            return self.message_service.send_file(
                friend_name, file_path, file_id=file_id
            )
        return False

    def pause_file_transfer(self, file_id):
        return bool(
            self.message_service
            and self.message_service.pause_file_transfer(file_id)
        )

    def resume_file_transfer(self, file_id):
        return bool(
            self.message_service
            and self.message_service.resume_file_transfer(file_id)
        )

    def cancel_file_transfer(self, file_id):
        if self.message_service:
            self.message_service.cancel_file_transfer(file_id)

    def get_chat_history(self, friend_name):
        if self.friend_db:
            return self.friend_db.get_chat_history(friend_name, limit=100)
        return []

    def clear_chat_history(self, friend_name):
        if self.friend_db:
            self.friend_db.clear_chat_history(friend_name)
            self.views["chat"].reload_current()

    def delete_chat_message(self, msg_id, *, is_group=False):
        if not self.friend_db or not msg_id:
            return False
        if is_group:
            return self.friend_db.delete_group_chat_message(msg_id)
        return self.friend_db.delete_chat_message(msg_id)

    def get_chat_list(self):
        try:
            chat_list = self.runtime.get_chat_list() if self.runtime else []
            for entry in chat_list:
                name = entry.get("name", "")
                if self.has_unread_chat(name):
                    entry["unread"] = max(int(entry.get("unread", 0) or 0), 1)
            return chat_list
        except Exception as e:
            print(f"获取聊天列表失败: {e}")
            return []

    def get_runtime_health(self):
        return self.runtime.get_health() if self.runtime else {}

    def clear_pending_messages(self, friend_name):
        if self.friend_db:
            self.friend_db.clear_pending_messages(friend_name)

    def get_pending_message_count(self, for_friend=None):
        if self.social_service:
            return self.social_service.get_pending_message_count(for_friend or "")
        return 0

    # -- worker helper for views ------------------------------------------

    def run_async(self, fn):
        """Run a blocking call off the UI thread, then refresh page."""
        def _worker():
            try:
                fn()
            except Exception as exc:
                print(f"[BeiyangApp] worker error: {exc}")
            finally:
                if self.page:
                    try:
                        self.page.update()
                    except Exception:
                        pass
        threading.Thread(target=_worker, daemon=True).start()

    def stop(self):
        if self.runtime:
            self.runtime.stop()

    def show_toast(self, text):
        if self.page:
            self.page.snack_bar = ft.SnackBar(ft.Text(text), action="确定")
            self.page.snack_bar.open = True
            self.page.update()

    def _on_update_profile_click(self, e, dlg, name, update_btn, update_status, actions_row):
        """Handle 'update profile' button click — keep dialog open, show progress."""
        update_btn.disabled = True
        update_btn.text = "更新中..."
        update_btn.icon = ft.Icons.HOURGLASS_EMPTY_ROUNDED
        update_status.value = "⏳ 正在请求更新..."
        update_status.color = ft.Colors.AMBER_400
        self.page.update()
        # Send the sync request; _on_profile_updated callback will refresh the dialog
        ok = self.request_friend_profile_update(name, silent=True)
        if not ok:
            update_status.value = "❌ 请求失败，对方可能不在线"
            update_status.color = ft.Colors.RED_400
            update_btn.text = "重试"
            update_btn.icon = ft.Icons.REFRESH_ROUNDED
            update_btn.disabled = False
            self.page.update()

    def show_friend_profile(self, name):
        if not self.page or not self.friend_db:
            return

        my_profile = self.friend_db.get_my_profile()
        is_me = (name == self.device_name or name == my_profile.get("name", ""))

        if is_me:
            profile = my_profile
            category = "自己"
        else:
            profile = self.friend_db.get_friend(name)
            if not profile:
                return
            category = profile.get("category", "朋友") or "朋友"

        user_id = profile.get("user_id", "无")
        ip = profile.get("ip", "127.0.0.1") if not is_me else "本机"
        port = profile.get("port", "") if not is_me else ""
        bio = profile.get("bio", "这个用户很懒，什么都没写。")
        tags = profile.get("tags", [])
        has_update = (not is_me) and self.has_friend_profile_update(name)
        if has_update and self.get_profile_update_mode() == "auto":
            threading.Thread(
                target=lambda: self.request_friend_profile_update(name, silent=True),
                daemon=True,
            ).start()

        import json
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = []

        tags_chips = []
        for tag in tags:
            tags_chips.append(
                ft.Container(
                    content=ft.Text(tag, size=10, color=ft.Colors.DEEP_PURPLE_400, weight=ft.FontWeight.BOLD),
                    bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.DEEP_PURPLE_400),
                    padding=T.pad_symmetric(horizontal=8, vertical=3),
                    border_radius=6,
                )
            )

        # Build the "loading" state for the update button
        update_status = ft.Text("", size=11, color=ft.Colors.GREEN_400, weight=ft.FontWeight.BOLD)
        update_btn = ft.ElevatedButton(
            "更新资料",
            icon=ft.Icons.REFRESH_ROUNDED,
            on_click=lambda e: self._on_update_profile_click(e, dlg, name, update_btn, update_status, actions_row),
            bgcolor=ft.Colors.DEEP_PURPLE_500,
            color=ft.Colors.WHITE,
        )

        def close_dlg(e):
            dlg.open = False
            self._open_profile_dlg = None
            self._open_profile_dlg_name = ""
            self.page.update()
            try:
                self.page.overlay.remove(dlg)
            except Exception:
                pass

        space_btn = ft.ElevatedButton(
            "个人空间",
            on_click=lambda _e: (close_dlg(None), self.show_personal_moments(name)),
            bgcolor=ft.Colors.DEEP_PURPLE_500,
            color=ft.Colors.WHITE,
        )

        actions_row = ft.Row(
            [
                space_btn,
                *([update_btn] if has_update else []),
                ft.TextButton("关闭", on_click=close_dlg),
            ],
            alignment=ft.MainAxisAlignment.END,
            spacing=8,
        )

        card_bg_path = profile.get("card_bg", "").strip()
        cover_container = ft.Container(
            height=100,
            border_radius=8,
            gradient=T.GRADIENT_PRIMARY,
        )
        if card_bg_path and os.path.exists(card_bg_path):
            cover_container.gradient = None
            cover_container.image = ft.DecorationImage(src=card_bg_path, fit=ft.BoxFit.COVER)

        profile_header = ft.Container(
            content=ft.Stack(
                [
                    cover_container,
                    ft.Container(
                        content=T.avatar_circle(self.get_avatar_for_name(name), 58),
                        top=72,
                        left=16,
                    ),
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Text(
                                    name,
                                    size=T.FS_TITLE,
                                    weight=ft.FontWeight.BOLD,
                                    max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                                ft.Text(
                                    f"分类/关系: {category}",
                                    size=T.FS_CAPTION,
                                    color=ft.Colors.ON_SURFACE_VARIANT,
                                    max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                            ],
                            spacing=2,
                            tight=True,
                        ),
                        top=108,
                        left=88,
                        right=8,
                    ),
                ],
                height=150,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            border_radius=8,
            border=T.border_all(1, ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE)),
        )

        dlg = ft.AlertDialog(
            content=ft.Column(
                [
                    profile_header,
                    ft.Divider(height=16, thickness=1, color=ft.Colors.with_opacity(0.06, ft.Colors.ON_SURFACE)),
                    T.section_title("基本信息"),
                    ft.Row(
                        [
                            ft.Text("用户ID: ", size=T.FS_CAPTION, weight=ft.FontWeight.BOLD),
                            ft.Text(user_id, size=T.FS_CAPTION, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True),
                        ],
                    ),
                    ft.Row(
                        [
                            ft.Text("连接地址: ", size=T.FS_CAPTION, weight=ft.FontWeight.BOLD),
                            ft.Text(f"{ip}:{port}" if port else ip, size=T.FS_CAPTION, color=ft.Colors.ON_SURFACE_VARIANT),
                        ],
                    ),
                    ft.Container(height=4),
                    T.section_title("个性签名"),
                    ft.Text(bio, size=T.FS_BODY, color=ft.Colors.ON_SURFACE),
                    ft.Container(height=4),
                    T.section_title("兴趣标签"),
                    ft.Row(tags_chips, wrap=True) if tags_chips else ft.Text("暂无标签", size=T.FS_CAPTION, color=ft.Colors.ON_SURFACE_VARIANT),
                    update_status,
                ],
                spacing=T.SP_SM,
                tight=True,
                width=300,
            ),
            actions=[actions_row],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.overlay.append(dlg)
        dlg.open = True
        # Track this dialog for potential refresh
        self._open_profile_dlg = dlg
        self._open_profile_dlg_name = name
        self.page.update()

    def create_group(self, group_name: str, members: List[str]) -> str:
        if self.message_service:
            return self.message_service.create_group(group_name, members)
        return ""

    def update_group_info(self, group_id: str, group_name: str, members: List[str], owner: str = "", only_owner_manage: int = 0):
        if self.message_service and self.friend_db:
            self.friend_db.save_group(group_id, group_name, members, owner=owner, only_owner_manage=only_owner_manage)
            payload = {
                "type": self.message_service.GROUP_CREATE,
                "group_id": group_id,
                "group_name": group_name,
                "members": members,
                "owner": owner,
                "only_owner_manage": only_owner_manage,
            }
            my_name = self.device_name
            for m in members:
                if m != my_name:
                    self.message_service._send_data_to_friend(m, payload)

    def send_group_chat_message(self, group_id: str, content: str, msg_id: str = "") -> bool:
        if self.message_service:
            return self.message_service.send_group_chat_message(
                group_id,
                content,
                msg_id=msg_id,
            )
        return False

    def get_group_chat_history(self, group_id: str) -> List[Dict[str, Any]]:
        if self.friend_db:
            return self.friend_db.get_group_chat_history(group_id, limit=100)
        return []

    def get_all_groups(self) -> List[Dict[str, Any]]:
        if self.friend_db:
            return self.friend_db.get_all_groups()
        return []

    def publish_moment(self, content: str, media_path: str = "") -> bool:
        if self.message_service:
            return self.message_service.publish_moment(content, media_path)
        return False

    def get_moments(self) -> List[Dict[str, Any]]:
        if self.friend_db:
            return self.friend_db.get_moments(limit=50)
        return []

    def delete_moment(self, post_id: str) -> bool:
        if self.message_service:
            return self.message_service.publish_moment_delete(post_id)
        elif self.friend_db:
            ok = self.friend_db.delete_moment(post_id)
            if ok:
                self._on_moments_changed()
            return ok
        return False

    def get_moment_comments(self, post_id: str) -> List[Dict[str, Any]]:
        if self.friend_db:
            return self.friend_db.get_moment_comments(post_id)
        return []

    def delete_moment_comment(self, comment_id: str) -> bool:
        if self.friend_db:
            ok = self.friend_db.delete_moment_comment(comment_id)
            if ok:
                self._on_moments_changed()
            return ok
        return False

    def publish_moment_comment(self, post_id: str, content: str) -> bool:
        if self.message_service:
            return self.message_service.publish_moment_comment(post_id, content)
        return False

    def sync_moments(self):
        if self.message_service and self.connection_manager:
            for f in self.connection_manager.get_online_friends():
                self.message_service.sync_moments_with_friend(f["name"])

    def show_personal_moments(self, name: str):
        if not self.page:
            return

        my_profile = self.friend_db.get_my_profile() if self.friend_db else None
        is_me = (name == self.device_name or (my_profile and name == my_profile.get("name", "")))
        if is_me:
            profile = my_profile or {}
        else:
            profile = self.friend_db.get_friend(name) if self.friend_db else {}

        card_bg_path = profile.get("card_bg", "").strip()
        cover_container = ft.Container(
            height=120,
            border_radius=10,
            gradient=T.GRADIENT_PRIMARY,
        )
        if card_bg_path and os.path.exists(card_bg_path):
            cover_container.gradient = None
            cover_container.image = ft.DecorationImage(src=card_bg_path, fit=ft.BoxFit.COVER)

        personal_feed = ft.Column(spacing=T.SP_SM, scroll=ft.ScrollMode.AUTO, height=400)

        def refresh_personal_feed():
            personal_feed.controls.clear()
            all_m = self.get_moments() or []
            user_m = [m for m in all_m if m.get("author") == name]

            if not user_m:
                personal_feed.controls.append(
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Icon(ft.Icons.AUTO_AWESOME_ROUNDED, size=40, color=ft.Colors.ON_SURFACE_VARIANT, opacity=0.4),
                                ft.Text("该空间暂无动态~", color=ft.Colors.ON_SURFACE_VARIANT, size=T.FS_CAPTION),
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=4,
                        ),
                        alignment=ft.alignment.Alignment.CENTER,
                        padding=20,
                    )
                )
            else:
                for m in user_m:
                    if "moments" in self.views:
                        personal_feed.controls.append(self.views["moments"]._build_moment_card(m))
            try:
                personal_feed.update()
            except Exception:
                pass

        self._open_personal_space_name = name
        self._refresh_personal_space_feed = refresh_personal_feed

        refresh_personal_feed()

        def close_space(_e):
            self._open_personal_space_name = ""
            self._refresh_personal_space_feed = None
            dlg.open = False
            self.page.update()
            try:
                self.page.overlay.remove(dlg)
            except Exception:
                pass

        dlg = ft.AlertDialog(
            title=ft.Row(
                [
                    T.avatar_circle(self.get_avatar_for_name(name), 30),
                    ft.Text(f"「{name}」的个人空间", weight=ft.FontWeight.BOLD, size=16),
                ],
                spacing=8,
            ),
            content=ft.Column(
                [
                    cover_container,
                    ft.Text("空间动态列表：", size=T.FS_CAPTION, color=ft.Colors.ON_SURFACE_VARIANT),
                    personal_feed,
                ],
                spacing=T.SP_SM,
                tight=True,
                width=360,
            ),
            actions=[
                ft.TextButton("返回", on_click=close_space)
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()
