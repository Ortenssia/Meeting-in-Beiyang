"""Chat view: chat list + chat window with bubbles and file transfer."""
import os
import time
import threading
import subprocess
import uuid

import flet as ft

from core.backend.shared.file_message import (
    decode_file_message,
    encode_file_message,
    is_file_message_content,
)

from .. import theme as T


class ChatView:
    def __init__(self, app):
        self.app = app
        self.page = app.page
        self._lock = threading.Lock()
        self.current_friend = ""
        self.is_group = False
        self.current_group_id = ""
        self._list_root = None
        self._window_root = None
        self._msg_list = None
        self._input = None
        self._header_avatar = None
        self._header_name = None
        self._header_status = None
        self._scroll_generation = 0
        self._transfer_widgets = {}
        self._transfer_states = {}
        self._transfer_watchdogs = set()
        self._closed_file_transfers = set()
        self._pending_file_offers: dict = {}  # file_id → {from_name, filename, size, widget}
        self._notifications_col = None
        self.file_picker = getattr(app, "chat_file_picker", None) or ft.FilePicker()
        self.compress_checkbox = ft.Checkbox(
            label="压缩",
            value=False,
            fill_color=ft.Colors.DEEP_PURPLE_400,
            scale=0.9,
        )

    def _is_mobile_ui(self):
        platform_name = str(getattr(self.page, "platform", "")).lower()
        width = float(getattr(self.page, "width", 0) or 0)
        return platform_name in ("android", "ios", "pageplatform.android", "pageplatform.ios") or (0 < width < 600)

    def _file_bubble_width(self):
        width = float(getattr(self.page, "width", 0) or 0)
        if self._is_mobile_ui() and width:
            return max(220, min(300, width - 92))
        return 320

    # -- build -------------------------------------------------------------

    def build(self):
        if self.current_friend:
            return self._build_window()
        return self._build_tabs()

    def _build_tabs(self):
        tab_bar = ft.TabBar(
            tabs=[
                ft.Tab(label="会话列表", icon=ft.Icons.CHAT_ROUNDED),
                ft.Tab(label="系统通知", icon=ft.Icons.NOTIFICATIONS_ROUNDED),
                ft.Tab(label="雷达发现", icon=ft.Icons.RADAR_ROUNDED),
            ]
        )
        self._tab_bar = tab_bar

        self._list_col = ft.Column(spacing=T.SP_SM, expand=True, scroll=ft.ScrollMode.AUTO)
        self._list_root = ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("最近会话", size=T.FS_TITLE, weight=ft.FontWeight.BOLD),
                        ft.IconButton(
                            icon=ft.Icons.GROUP_ADD_ROUNDED,
                            icon_color=ft.Colors.DEEP_PURPLE_400,
                            tooltip="发起群聊",
                            on_click=self._on_create_group,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                self._list_col,
            ],
            spacing=T.SP_SM,
            expand=True,
        )

        discover_view = self.app.views.get("discover")

        tab_view = ft.TabBarView(
            expand=True,
            controls=[
                self._list_root,
                self._build_notifications_view(),
                discover_view.build(),
            ]
        )

        def on_tab_change(_e):
            if self.tabs.selected_index == 1:
                self.app.mark_all_notifications_read()

        self.tabs = ft.Tabs(
            length=3,
            expand=True,
            on_change=on_tab_change,
            content=ft.Column(
                controls=[
                    tab_bar,
                    tab_view,
                ],
                expand=True,
            )
        )
        self._render_list()
        self._render_notifications()
        return self.tabs

    def _build_window(self):
        mobile_ui = self._is_mobile_ui()
        self.compress_checkbox.label = None if mobile_ui else "压缩"
        self.compress_checkbox.tooltip = "发送前压缩" if mobile_ui else None
        # Clear any obsolete widget references from pending file offers, since
        # the message list is being rebuilt.
        for offer in self._pending_file_offers.values():
            if isinstance(offer, dict):
                offer.pop("widget", None)

        if self.is_group:
            group = self.app.friend_db.get_group(self.current_group_id)
            member_count = len(group.get("members", [])) if group else 0
            self._header_avatar = ft.GestureDetector(
                mouse_cursor=ft.MouseCursor.CLICK,
                on_tap=lambda _: self.show_group_settings(self.current_group_id),
                content=T.avatar_circle("group", T.AVATAR_MD)
            )
            self._header_name = ft.Text(self.current_friend, size=T.FS_TITLE, weight=ft.FontWeight.BOLD)
            self._header_status = ft.Text(
                f"{member_count} 个成员",
                size=T.FS_CAPTION,
                color=ft.Colors.ON_SURFACE_VARIANT,
                weight=ft.FontWeight.NORMAL
            )
        else:
            online = self.current_friend in [
                f.get("name") for f in self.app.get_online_friends()
            ]
            self._header_avatar = ft.GestureDetector(
                mouse_cursor=ft.MouseCursor.CLICK,
                on_tap=lambda _: self.app.show_friend_profile(self.current_friend) if hasattr(self.app, "show_friend_profile") else None,
                content=T.avatar_circle(
                    self.app.get_avatar_for_name(self.current_friend),
                    T.AVATAR_MD,
                    online=online,
                )
            )
            self._header_name = ft.Text(self.current_friend, size=T.FS_TITLE, weight=ft.FontWeight.BOLD)
            self._header_status = ft.Text(
                "在线" if online else "离线",
                size=T.FS_CAPTION,
                color=ft.Colors.GREEN_400 if online else ft.Colors.ON_SURFACE_VARIANT,
                weight=ft.FontWeight.BOLD if online else ft.FontWeight.NORMAL
            )

        self._msg_list = ft.Column(
            spacing=T.SP_MD,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )

        self._input = ft.TextField(
            hint_text="输入消息…",
            expand=True,
            autofocus=True,
            border_radius=22,
            border_color=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            content_padding=T.pad_symmetric(horizontal=16, vertical=10),
            on_submit=self._on_send,
        )

        attach_btn = ft.IconButton(
            icon=ft.Icons.ADD_ROUNDED,
            icon_color=ft.Colors.DEEP_PURPLE_400,
            icon_size=24,
            on_click=self._pick_file,
            tooltip="发送文件",
        )

        send_btn = ft.IconButton(
            icon=ft.Icons.SEND_ROUNDED,
            icon_color=ft.Colors.WHITE,
            icon_size=18,
            bgcolor=ft.Colors.DEEP_PURPLE_500,
            on_click=self._on_send,
            style=ft.ButtonStyle(
                shape=ft.CircleBorder(),
                padding=T.pad_all(12),
            ),
            tooltip="发送消息",
        )

        # Header bar for the chat window
        chat_header = ft.Container(
            content=ft.Row(
                [
                    ft.IconButton(
                        icon=ft.Icons.ARROW_BACK_IOS_NEW_ROUNDED,
                        icon_size=16,
                        on_click=self._back_to_list,
                        tooltip="返回消息列表"
                    ),
                    self._header_avatar,
                    ft.Column(
                        [
                            self._header_name,
                            self._header_status,
                        ],
                        spacing=1,
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                    ft.Container(expand=True),
                    # Direct action button: Clear history
                    ft.IconButton(
                        icon=ft.Icons.DELETE_SWEEP_ROUNDED,
                        icon_color=ft.Colors.ON_SURFACE_VARIANT,
                        on_click=lambda _e: self._confirm_clear(),
                        tooltip="清空聊天记录"
                    )
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=T.pad_symmetric(horizontal=T.SP_SM, vertical=T.SP_SM),
            border=ft.Border(bottom=ft.BorderSide(1, ft.Colors.with_opacity(0.06, ft.Colors.ON_SURFACE))),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            margin=T.pad_only(left=-T.SP_LG, right=-T.SP_LG, top=-T.SP_LG),  # Overlap shell padding
        )

        composer_controls = [attach_btn, self.compress_checkbox, self._input, send_btn]
        self._window_root = ft.Column(
            [
                chat_header,
                ft.Container(
                    content=self._msg_list,
                    padding=T.pad_symmetric(vertical=10),
                    expand=True,
                ),
                ft.Container(
                    content=ft.Row(
                        composer_controls,
                        spacing=4 if mobile_ui else T.SP_SM,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=T.pad_only(bottom=T.SP_SM),
                ),
            ],
            spacing=0, expand=True,
        )
        self._load_history()
        return self._window_root

    # -- lifecycle ---------------------------------------------------------

    def on_enter(self):
        if not self.current_friend:
            self._render_list()
            self._render_notifications()

    def _build_notifications_view(self):
        self._notifications_col = ft.Column(spacing=T.SP_SM, expand=True, scroll=ft.ScrollMode.AUTO)

        view_root = ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("系统通知", size=T.FS_TITLE, weight=ft.FontWeight.BOLD),
                        ft.Row(
                            [
                                ft.TextButton(
                                    "全部已读",
                                    icon=ft.Icons.DONE_ALL_ROUNDED,
                                    icon_color=ft.Colors.DEEP_PURPLE_400,
                                    on_click=self._on_mark_all_read,
                                    style=ft.ButtonStyle(
                                        padding=T.pad_symmetric(horizontal=8, vertical=4)
                                    )
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.DELETE_SWEEP_ROUNDED,
                                    icon_color=ft.Colors.RED_400,
                                    tooltip="清空通知",
                                    on_click=self._on_clear_notifications,
                                ),
                            ],
                            spacing=0,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                self._notifications_col,
            ],
            spacing=T.SP_SM,
            expand=True,
        )
        return view_root

    def _render_notifications(self):
        if not hasattr(self, "_notifications_col") or self._notifications_col is None:
            return

        with self._lock:
            self._notifications_col.controls.clear()
            notifications = self.app.get_system_notifications()

            # Update tab label and icon based on unread count
            unread_count = sum(1 for n in notifications if n.get("is_read", 0) == 0)
            if hasattr(self, "_tab_bar") and self._tab_bar:
                if unread_count > 0:
                    self._tab_bar.tabs[1].label = f"系统通知 ({unread_count})"
                    self._tab_bar.tabs[1].icon = ft.Icons.NOTIFICATION_IMPORTANT_ROUNDED
                else:
                    self._tab_bar.tabs[1].label = "系统通知"
                    self._tab_bar.tabs[1].icon = ft.Icons.NOTIFICATIONS_ROUNDED

            if not notifications:
                self._notifications_col.controls.append(
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Icon(ft.Icons.NOTIFICATIONS_NONE_ROUNDED, size=48, color=ft.Colors.ON_SURFACE_VARIANT, opacity=0.5),
                                ft.Text("暂无系统通知", size=T.FS_BODY, color=ft.Colors.ON_SURFACE_VARIANT, weight=ft.FontWeight.W_500),
                            ],
                            alignment=ft.MainAxisAlignment.CENTER,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=T.SP_SM,
                        ),
                        alignment=ft.alignment.Alignment.CENTER,
                        expand=True,
                        padding=T.SP_2XL,
                    )
                )
            else:
                for notif in notifications:
                    is_read = notif.get("is_read", 0) == 1
                    category = notif.get("category", "info")

                    icon = ft.Icons.INFO_ROUNDED
                    icon_color = ft.Colors.BLUE_400
                    if category == "success":
                        icon = ft.Icons.CHECK_CIRCLE_ROUNDED
                        icon_color = ft.Colors.GREEN_400
                    elif category == "warning":
                        icon = ft.Icons.WARNING_ROUNDED
                        icon_color = ft.Colors.ORANGE_400
                    elif category == "error":
                        icon = ft.Icons.ERROR_ROUNDED
                        icon_color = ft.Colors.RED_400
                    elif category == "friend_request":
                        icon = ft.Icons.PERSON_ADD_ROUNDED
                        icon_color = ft.Colors.DEEP_PURPLE_400
                    elif category == "file_offer":
                        icon = ft.Icons.FOLDER_ZIP_ROUNDED
                        icon_color = ft.Colors.BLUE_400

                    # Interactive buttons for pending friend requests / file offers
                    action_row = ft.Container()
                    if category == "friend_request":
                        import re
                        match = re.search(r"「([^」]+)」", notif.get("content", ""))
                        sender_name = match.group(1) if match else ""

                        is_pending = False
                        req = None
                        if sender_name:
                            req = self.app.friend_db.get_friend_request(name=sender_name)
                            if req and req.get("status") == "pending":
                                is_pending = True

                        if is_pending:
                            def make_accept_cb(s_name, req_info, n_id):
                                def on_accept_click(e):
                                    self.app.friend_db.add_friend(
                                        name=s_name, ip=req_info["ip"], port=req_info["port"],
                                        tags=req_info.get("tags", []), bio=req_info.get("bio", ""), category="朋友",
                                        user_id=req_info.get("user_id", ""), status="accepted",
                                    )
                                    self.app.friend_db.set_friend_request_status(
                                        "accepted", user_id=req_info.get("user_id", ""),
                                        name=s_name, ip=req_info["ip"], port=req_info["port"],
                                    )
                                    import threading
                                    threading.Thread(
                                        target=self.app.message_service.send_friend_accept,
                                        args=(s_name, req_info["ip"]), daemon=True,
                                    ).start()
                                    self.app.mark_notification_read(n_id)
                                    self.app.views["friends"].refresh()
                                    if "discover" in self.app.views:
                                        self.app.views["discover"].refresh_online()
                                    self._render_notifications()
                                return on_accept_click

                            def make_ignore_cb(req_info, n_id):
                                def on_ignore_click(e):
                                    self.app.friend_db.set_friend_request_status(
                                        "rejected", user_id=req_info.get("user_id", ""),
                                        name=req_info["name"], ip=req_info["ip"], port=req_info["port"],
                                    )
                                    self.app.mark_notification_read(n_id)
                                    self._render_notifications()
                                return on_ignore_click

                            action_row = ft.Container(
                                content=ft.Row(
                                    [
                                        ft.ElevatedButton(
                                            "同意并添加",
                                            icon=ft.Icons.CHECK_ROUNDED,
                                            on_click=make_accept_cb(sender_name, req, notif["id"]),
                                            bgcolor=ft.Colors.DEEP_PURPLE_400,
                                            color=ft.Colors.WHITE,
                                            style=ft.ButtonStyle(
                                                padding=T.pad_symmetric(horizontal=12, vertical=6)
                                            ),
                                            height=32,
                                        ),
                                        ft.OutlinedButton(
                                            "忽略",
                                            icon=ft.Icons.CLOSE_ROUNDED,
                                            on_click=make_ignore_cb(req, notif["id"]),
                                            style=ft.ButtonStyle(
                                                padding=T.pad_symmetric(horizontal=12, vertical=6)
                                            ),
                                            height=32,
                                        ),
                                    ],
                                    spacing=T.SP_SM,
                                ),
                                margin=ft.Margin.only(top=T.SP_SM)
                            )
                        else:
                            status_text = "已同意"
                            text_color = ft.Colors.GREEN_400
                            if req and req.get("status") == "rejected":
                                status_text = "已忽略"
                                text_color = ft.Colors.ON_SURFACE_VARIANT

                            action_row = ft.Container(
                                content=ft.Text(status_text, size=12, color=text_color, weight=ft.FontWeight.BOLD),
                                margin=ft.Margin.only(top=T.SP_XS)
                            )
                    elif category == "file_offer":
                        import re
                        match = re.search(r"\[文件ID:([^\]]+)\]", notif.get("content", ""))
                        file_id = match.group(1) if match else ""

                        is_pending = False
                        if file_id and self.app.message_service:
                            is_pending = file_id in self.app.message_service._pending_file_offers

                        if is_pending:
                            def make_file_accept_cb(f_id, n_id):
                                def on_file_accept_click(e):
                                    self.app.message_service.accept_file_offer(f_id)
                                    self.app.mark_notification_read(n_id)
                                    self._pending_file_offers.pop(f_id, None)
                                    self._render_notifications()
                                    if self.current_friend:
                                        self.reload_current()
                                return on_file_accept_click

                            def make_file_decline_cb(f_id, n_id):
                                def on_file_decline_click(e):
                                    self.app.message_service.decline_file_offer(f_id)
                                    self.app.mark_notification_read(n_id)
                                    self._pending_file_offers.pop(f_id, None)
                                    self._render_notifications()
                                    if self.current_friend:
                                        self.reload_current()
                                return on_file_decline_click

                            action_row = ft.Container(
                                content=ft.Row(
                                    [
                                        ft.ElevatedButton(
                                            "同意并接收",
                                            icon=ft.Icons.CHECK_ROUNDED,
                                            on_click=make_file_accept_cb(file_id, notif["id"]),
                                            bgcolor=ft.Colors.DEEP_PURPLE_400,
                                            color=ft.Colors.WHITE,
                                            style=ft.ButtonStyle(
                                                padding=T.pad_symmetric(horizontal=12, vertical=6)
                                            ),
                                            height=32,
                                        ),
                                        ft.OutlinedButton(
                                            "拒绝",
                                            icon=ft.Icons.CLOSE_ROUNDED,
                                            on_click=make_file_decline_cb(file_id, notif["id"]),
                                            style=ft.ButtonStyle(
                                                padding=T.pad_symmetric(horizontal=12, vertical=6)
                                            ),
                                            height=32,
                                        ),
                                    ],
                                    spacing=T.SP_SM,
                                ),
                                margin=ft.Margin.only(top=T.SP_SM)
                            )
                        else:
                            status_text = "已处理"
                            text_color = ft.Colors.ON_SURFACE_VARIANT
                            if self.app.message_service:
                                with self.app.message_service._file_lock:
                                    state = self.app.message_service._incoming_files.get(file_id)
                                if state:
                                    if state.get("error"):
                                        status_text = "传输失败"
                                        text_color = ft.Colors.RED_400
                                    elif state.get("completed", False):
                                        status_text = "已完成"
                                        text_color = ft.Colors.GREEN_400
                                    elif state.get("pending_accept") is False:
                                        status_text = "已同意"
                                        text_color = ft.Colors.GREEN_400
                                    else:
                                        status_text = "正在接收"
                                        text_color = ft.Colors.BLUE_400
                                else:
                                    if file_id in self._closed_file_transfers:
                                        status_text = "已拒绝"
                                        text_color = ft.Colors.RED_400

                            action_row = ft.Container(
                                content=ft.Text(status_text, size=12, color=text_color, weight=ft.FontWeight.BOLD),
                                margin=ft.Margin.only(top=T.SP_XS)
                            )

                    card = ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(icon, color=icon_color, size=24),
                                ft.Column(
                                    [
                                        ft.Row(
                                            [
                                                ft.Text(notif.get("title", ""), size=T.FS_BODY, weight=ft.FontWeight.BOLD),
                                                ft.Text(
                                                    notif.get("timestamp", "")[-8:] if len(notif.get("timestamp", "")) >= 8 else "",
                                                    size=T.FS_CAPTION,
                                                    color=ft.Colors.ON_SURFACE_VARIANT
                                                ),
                                            ],
                                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                        ),
                                        ft.Text(
                                            notif.get("content", ""),
                                            size=T.FS_BODY,
                                            color=ft.Colors.ON_SURFACE if not is_read else ft.Colors.ON_SURFACE_VARIANT,
                                            weight=ft.FontWeight.NORMAL if is_read else ft.FontWeight.W_500,
                                        ),
                                        action_row,
                                    ],
                                    spacing=T.SP_XS,
                                    expand=True,
                                )
                            ],
                            alignment=ft.MainAxisAlignment.START,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        padding=T.SP_MD,
                        border_radius=T.R_SM,
                        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH if is_read else ft.Colors.with_opacity(0.08, ft.Colors.DEEP_PURPLE),
                        border=T.border_all(1, ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE)),
                    )
                    self._notifications_col.controls.append(card)

            if self.page:
                self.page.update()

    def _on_mark_all_read(self, e):
        self.app.mark_all_notifications_read()

    def _on_clear_notifications(self, e):
        self.app.clear_system_notifications()

    def refresh_notifications(self):
        self._render_notifications()

    def open_chat(self, friend_name, is_group=False, group_id=""):
        self.current_friend = friend_name
        self.is_group = is_group
        self.current_group_id = group_id

    def reload_current(self):
        if self.current_friend:
            self._msg_list.controls.clear()
            self._load_history()
            if self.page:
                self.page.update()

    def refresh_header(self):
        """Update the chat-window header (avatar + online status).

        Returns early when nothing actually changed — rebuilding the avatar
        widget tree would otherwise cause a visible flicker even though the
        underlying image file is already on local disk.
        """
        with self._lock:
            if not self.current_friend or not self._header_avatar:
                return

            if self.is_group:
                group = self.app.friend_db.get_group(self.current_group_id)
                member_count = len(group.get("members", [])) if group else 0
                new_status = f"{member_count} 个成员"
                if (getattr(self, "_last_group_members", 0) == member_count
                        and self._header_status.value == new_status):
                    return  # nothing changed
                self._last_group_members = member_count
                self._header_avatar.content = T.avatar_circle("group", T.AVATAR_MD)
                self._header_status.value = new_status
                self._header_status.color = ft.Colors.ON_SURFACE_VARIANT
                self._header_status.weight = ft.FontWeight.NORMAL
            else:
                online = self.current_friend in [
                    f.get("name") for f in self.app.get_online_friends()
                ]
                avatar_src = self.app.get_avatar_for_name(self.current_friend)
                new_status = "在线" if online else "离线"
                new_color = ft.Colors.GREEN_400 if online else ft.Colors.ON_SURFACE_VARIANT
                new_weight = ft.FontWeight.BOLD if online else ft.FontWeight.NORMAL

                # Skip the entire rebuild when nothing changed — same avatar
                # source AND same online status.  This is the key flicker fix.
                if (getattr(self, "_last_avatar_src", "") == avatar_src
                        and getattr(self, "_last_online", None) == online
                        and self._header_status.value == new_status):
                    return

                self._last_avatar_src = avatar_src
                self._last_online = online
                self._header_avatar.content = T.avatar_circle(
                    avatar_src, T.AVATAR_MD, online=online,
                )
                self._header_status.value = new_status
                self._header_status.color = new_color
                self._header_status.weight = new_weight

            if self.page:
                self.page.update()

    # -- chat list ---------------------------------------------------------

    def _render_list(self):
        with self._lock:
            if self._list_root is None:
                return
            col = self._list_root.controls[1]
            col.controls.clear()
            chat_list = self.app.get_chat_list() or []
            for entry in chat_list:
                col.controls.append(self._list_item(entry))
            if not chat_list:
                col.controls.append(
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Icon(ft.Icons.CHAT_BUBBLE_OUTLINE_ROUNDED, size=40, color=ft.Colors.ON_SURFACE_VARIANT, opacity=0.4),
                                ft.Text(
                                    "暂无聊天记录\n去「发现」认识新朋友",
                                    text_align=ft.TextAlign.CENTER,
                                    size=T.FS_BODY,
                                    color=ft.Colors.ON_SURFACE_VARIANT,
                                    weight=ft.FontWeight.W_500
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.CENTER,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=T.SP_SM,
                        ),
                        padding=T.SP_2XL,
                        alignment=ft.alignment.Alignment.CENTER,
                        expand=True,
                    )
                )
            if self.page:
                self.page.update()

    def _list_item(self, entry):
        name = entry.get("name", "未知")
        online = entry.get("online", False)
        unread = entry.get("unread", 0)
        unread_badge = (
            ft.Container(
                content=ft.Text(str(unread), size=10, color=ft.Colors.WHITE,
                                weight=ft.FontWeight.BOLD),
                bgcolor=ft.Colors.PINK_500, border_radius=999,
                padding=T.pad_symmetric(horizontal=6, vertical=2),
                shadow=ft.BoxShadow(blur_radius=4, color=ft.Colors.with_opacity(0.3, ft.Colors.PINK_600)),
            )
            if unread > 0 else None
        )

        last_msg = entry.get("last_message", "")
        # Clean file tag descriptions for clean preview
        if last_msg.startswith("[") and "]" in last_msg:
            parts = last_msg.split("]", 1)
            file_info = (
                self._file_info_from_content(last_msg)
                if is_file_message_content(last_msg)
                else None
            )
            preview = file_info["filename"] if file_info else parts[1].strip()
            last_msg = f"📂 {parts[0][1:]}: {preview}"

        is_group = entry.get("is_group", False)
        group_id = entry.get("group_id", "")

        return ft.GestureDetector(
            mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=lambda _e, n=name, ig=is_group, gid=group_id: self.app.open_chat_with(n, is_group=ig, group_id=gid),
            content=ft.Container(
                content=ft.Row(
                    [
                        T.avatar_circle(
                            entry.get("avatar") or name,
                            T.AVATAR_MD,
                            online=online,
                            unread=unread > 0,
                        ),
                        ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Text(name, size=T.FS_TEXT, weight=ft.FontWeight.BOLD),
                                        ft.Container(expand=True),
                                        ft.Text(entry.get("time", ""), size=T.FS_CAPTION,
                                                 color=ft.Colors.ON_SURFACE_VARIANT, weight=ft.FontWeight.W_500),
                                    ],
                                ),
                                ft.Row(
                                    [
                                        ft.Text(last_msg, size=T.FS_CAPTION,
                                                color=ft.Colors.ON_SURFACE_VARIANT,
                                                max_lines=1, expand=True, overflow=ft.TextOverflow.ELLIPSIS),
                                    ] + ([unread_badge] if unread_badge else []),
                                ),
                            ],
                            spacing=2, expand=True,
                        ),
                    ],
                ),
                padding=T.SP_MD,
                height=76,
                border_radius=T.R_MD,
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
                border=T.border_all(1, ft.Colors.with_opacity(0.06, ft.Colors.ON_SURFACE)),
                shadow=T.SHADOW_CARD,
            )
        )

    # -- chat window -------------------------------------------------------

    def _load_history(self):
        my_name = self.app.device_name
        if self.is_group:
            history = self.app.get_group_chat_history(self.current_group_id) or []
            for msg in history:
                sender = msg.get("sender", "")
                is_self = (sender == my_name)
                content = msg.get("content", "")
                ts = msg.get("timestamp", "")
                if len(ts) >= 19:
                    ts = ts[11:19]
                self._append_bubble(
                    sender,
                    content,
                    ts,
                    is_self=is_self,
                    msg_id=msg.get("msg_id", ""),
                )
        else:
            history = self.app.get_chat_history(self.current_friend) or []
            for msg in history:
                direction = msg.get("direction", "")
                is_self = (direction == "send")
                from_name = my_name if is_self else self.current_friend
                content = msg.get("content", "")
                ts = msg.get("timestamp", "")
                if len(ts) >= 19:
                    ts = ts[11:19]
                self._append_bubble(
                    from_name,
                    content,
                    ts,
                    is_self=is_self,
                    msg_id=msg.get("msg_id", ""),
                )
        # Render any pending file offers for this friend at the bottom.
        if not self.is_group:
            self._render_file_offers_for(self.current_friend)
            self._render_active_transfers_for(self.current_friend)
        self._scroll_bottom()

    def _append_bubble(self, from_name, content, timestamp, is_self=False, msg_id=""):
        bubble_content = None

        # Check if the message is a file transfer representation
        is_file_msg = False
        file_status = ""
        filename = ""
        transfer_id = ""
        file_id = ""
        row = None

        def delete_current(_e=None):
            self._delete_message_row(row, msg_id=msg_id, file_id=file_id)

        if is_file_message_content(content):
            idx = content.find("]")
            tag = content[1:idx]
            file_info = self._file_info_from_content(content)
            is_file_msg = True
            filename = file_info["filename"]
            file_path = file_info["path"]
            transfer_id = file_info["transfer_id"]
            file_status = tag

        if is_file_msg:
            file_card_width = self._file_bubble_width()
            file_text_width = max(100, file_card_width - (112 if self._is_mobile_ui() else 140))
            # Resolve file_id for active cancel action
            file_id = transfer_id
            if self.app.message_service:
                with self.app.message_service._file_lock:
                    file_id = file_id or self.app.message_service.file_transfer.active_file_id_for(filename)

            # Styled File Card Redesign
            icon_color = ft.Colors.WHITE if is_self else ft.Colors.DEEP_PURPLE_400
            status_text = file_status
            detail_text = ""
            pb_val = 0.0
            pb_color = ft.Colors.WHITE if is_self else ft.Colors.BLUE_400

            if "正在" in file_status:
                pb_val = 0.0
                status_text = "📁 " + file_status + " · 0% · --/s"
            elif "失败" in file_status or "拒绝" in file_status or "取消" in file_status:
                pb_val = 1.0
                pb_color = ft.Colors.RED_400
                icon_color = ft.Colors.RED_400
                status_text = "❌ " + file_status
            elif "等待" in file_status:
                pb_val = 1.0
                pb_color = ft.Colors.ORANGE_400
                icon_color = ft.Colors.ORANGE_400
                status_text = "⏳ " + file_status
            else:
                pb_val = 1.0
                pb_color = ft.Colors.GREEN_400 if not is_self else ft.Colors.WHITE
                icon_color = ft.Colors.GREEN_400 if not is_self else ft.Colors.WHITE
                status_text = "✅ " + file_status

            cached_state = self._transfer_states.get(file_id, {})
            if cached_state and not cached_state.get("final"):
                completed = int(cached_state.get("completed", 0) or 0)
                total = int(cached_state.get("total", 0) or 0)
                pb_val = min(1.0, completed / total) if total else 0.0
                percent = pb_val * 100
                direction = "发送" if cached_state.get("sending") else "接收"
                status_text = f"{direction}中 · {percent:.0f}%"
                detail_text = f"{self._format_bytes(completed)} / {self._format_bytes(total)}" if total else "等待对端/网络"

            def open_file():
                def worker():
                    if os.path.exists(file_path):
                        try:
                            self._open_file_with_os(file_path)
                        except Exception as e:
                            self.show_toast(f"打开文件失败: {e}")
                    else:
                        self.show_toast("文件不存在或未在此电脑接收")
                import threading
                threading.Thread(target=worker, daemon=True).start()

            def open_folder():
                def worker():
                    folder_path = os.path.dirname(file_path) or self.app.get_receive_dir()
                    if os.path.exists(file_path):
                        try:
                            self._open_folder_with_os(file_path, folder_path)
                        except Exception:
                            try:
                                self._open_file_with_os(folder_path)
                            except Exception as e:
                                self.show_toast(f"打开文件夹失败: {e}")
                    else:
                        if os.path.exists(folder_path):
                            try:
                                self._open_file_with_os(folder_path)
                            except Exception as e:
                                self.show_toast(f"打开文件夹失败: {e}")
                        else:
                            self.show_toast("接收文件夹不存在")
                import threading
                threading.Thread(target=worker, daemon=True).start()

            def copy_path():
                # set_clipboard must run on the UI thread
                try:
                    if self.page:
                        self.page.set_clipboard(file_path)
                        self.show_toast("文件路径已复制")
                except Exception:
                    pass

            def decompress_zip():
                def worker():
                    import zipfile
                    if os.path.exists(file_path):
                        try:
                            dest_dir = os.path.dirname(file_path)
                            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                                zip_ref.extractall(dest_dir)
                            self.show_toast("解压缩成功！🎉")
                        except Exception as e:
                            self.show_toast(f"解压失败: {e}")
                    else:
                        self.show_toast("文件不存在或未下载完成")
                import threading
                threading.Thread(target=worker, daemon=True).start()

            def retry_file():
                if not is_self:
                    return
                if not file_path or not os.path.exists(file_path):
                    self.show_toast("原文件不存在，无法续传")
                    return
                target_friend = self.current_friend
                retry_id = str(uuid.uuid4())
                pending_content = self._file_message_content(
                    "正在发送文件", filename, file_path, retry_id
                )
                retry_row = self._replace_bubble(
                    row,
                    self.app.device_name,
                    pending_content,
                    time.strftime("%H:%M:%S", time.localtime()),
                    is_self=True,
                )
                if self.page:
                    self.page.update()

                def worker():
                    ok = False
                    if target_friend and not self.is_group:
                        ok = self.app.send_file_to_friend(
                            target_friend, file_path, retry_id
                        )
                    status = "文件" if ok else "文件发送失败"
                    done_content = self._file_message_content(
                        status, filename, file_path, retry_id
                    )
                    self._replace_bubble(
                        retry_row,
                        self.app.device_name,
                        done_content,
                        time.strftime("%H:%M:%S", time.localtime()),
                        is_self=True,
                    )
                    self._transfer_widgets.pop(retry_id, None)
                    if self.page:
                        self.page.update()

                threading.Thread(target=worker, daemon=True).start()

            # File Type Icon resolution
            ext = os.path.splitext(filename)[1].lower()
            if ext in (".zip", ".rar", ".7z", ".tar", ".gz"):
                file_icon = ft.Icons.FOLDER_ZIP_ROUNDED
                icon_bg = ft.Colors.AMBER_500
            elif ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
                file_icon = ft.Icons.IMAGE_ROUNDED
                icon_bg = ft.Colors.BLUE_500
            elif ext in (".mp4", ".avi", ".mkv", ".mov", ".flv"):
                file_icon = ft.Icons.VIDEO_LIBRARY_ROUNDED
                icon_bg = ft.Colors.RED_500
            elif ext in (".mp3", ".wav", ".flac", ".ogg", ".m4a"):
                file_icon = ft.Icons.AUDIO_FILE_ROUNDED
                icon_bg = ft.Colors.TEAL_500
            elif ext in (".txt", ".md", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"):
                file_icon = ft.Icons.ARTICLE_ROUNDED
                icon_bg = ft.Colors.BLUE_GREY_500
            else:
                file_icon = ft.Icons.INSERT_DRIVE_FILE_ROUNDED
                icon_bg = ft.Colors.DEEP_PURPLE_500

            icon_container = ft.Container(
                content=ft.Icon(file_icon, color=ft.Colors.WHITE, size=22),
                bgcolor=icon_bg,
                width=40,
                height=40,
                border_radius=8,
                alignment=ft.alignment.Alignment.CENTER,
            )

            status_label = ft.Text(
                status_text,
                size=11,
                color=icon_color,
                overflow=ft.TextOverflow.ELLIPSIS,
                max_lines=1,
                width=file_text_width,
            )
            detail_label = ft.Text(
                detail_text,
                size=10,
                color=ft.Colors.ON_SURFACE_VARIANT,
                overflow=ft.TextOverflow.ELLIPSIS,
                max_lines=1,
                width=file_text_width,
            )
            progress_bar = ft.ProgressBar(
                value=pb_val,
                color=pb_color,
                bgcolor=ft.Colors.with_opacity(0.1, ft.Colors.ON_SURFACE),
                height=3,
            )

            def toggle_pause():
                widget = self._transfer_widgets.get(file_id)
                if not widget:
                    return
                if widget.get("paused"):
                    if self.app.resume_file_transfer(file_id):
                        widget["paused"] = False
                        widget["last_time"] = time.monotonic()
                        widget["pause_button"].icon = ft.Icons.PAUSE_ROUNDED
                        widget["pause_button"].tooltip = "暂停传输"
                else:
                    if self.app.pause_file_transfer(file_id):
                        widget["paused"] = True
                        widget["pause_button"].icon = ft.Icons.PLAY_ARROW_ROUNDED
                        widget["pause_button"].tooltip = "继续传输"
                        widget["status"].value = (
                            f"⏸ 已暂停 · {widget.get('percent', 0):.0f}% · --/s"
                        )
                if self.page:
                    self.page.update()

            pause_button = ft.IconButton(
                icon=ft.Icons.PAUSE_ROUNDED,
                icon_color=ft.Colors.ON_SURFACE_VARIANT,
                icon_size=16,
                tooltip="暂停传输",
                on_click=lambda _: toggle_pause(),
                visible=not self._is_mobile_ui(),
            )

            top_row = ft.Row(
                [
                    icon_container,
                    ft.Column(
                        [
                            ft.Text(
                                filename,
                                size=13,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.ON_SURFACE,
                                overflow=ft.TextOverflow.ELLIPSIS,
                                max_lines=1,
                                width=file_text_width,
                            ),
                            status_label,
                            detail_label,
                        ],
                        spacing=1,
                        expand=True,
                    ),
                    ft.Row(
                        [
                            pause_button if ("正在" in file_status and file_id and is_self) else ft.Container(),
                            ft.IconButton(
                                icon=ft.Icons.CANCEL_OUTLINED,
                                icon_color=ft.Colors.RED_400,
                                icon_size=16,
                                tooltip="取消",
                                on_click=lambda _, fid=file_id: self.app.cancel_file_transfer(fid) if fid else None,
                                visible=not self._is_mobile_ui(),
                            ) if ("正在" in file_status and file_id) else ft.Container(),
                            ft.IconButton(
                                icon=ft.Icons.REFRESH_ROUNDED,
                                icon_color=ft.Colors.DEEP_PURPLE_400,
                                icon_size=16,
                                tooltip="重试/续传",
                                on_click=lambda _e: retry_file(),
                            ) if ("失败" in file_status and is_self) else ft.Container(),
                            ft.PopupMenuButton(
                                items=[
                                    ft.PopupMenuItem(
                                        content=ft.Row([
                                            ft.Icon(ft.Icons.CANCEL_OUTLINED, size=14, color=ft.Colors.RED_400),
                                            ft.Text("取消传输", size=12),
                                        ], spacing=6),
                                        on_click=lambda _, fid=file_id: self.app.cancel_file_transfer(fid) if fid else None,
                                        visible=bool("正在" in file_status and file_id),
                                    ),
                                    ft.PopupMenuItem(
                                        content=ft.Row([
                                            ft.Icon(ft.Icons.OPEN_IN_NEW_ROUNDED, size=14, color=ft.Colors.DEEP_PURPLE_400),
                                            ft.Text("打开文件", size=12),
                                        ], spacing=6),
                                        on_click=lambda _: open_file()
                                    ),
                                    ft.PopupMenuItem(
                                        content=ft.Row([
                                            ft.Icon(ft.Icons.FOLDER_OPEN_ROUNDED, size=14, color=ft.Colors.DEEP_PURPLE_400),
                                            ft.Text("打开文件夹", size=12),
                                        ], spacing=6),
                                        on_click=lambda _: open_folder()
                                    ),
                                    ft.PopupMenuItem(
                                        content=ft.Row([
                                            ft.Icon(ft.Icons.COPY_ALL_ROUNDED, size=14, color=ft.Colors.DEEP_PURPLE_400),
                                            ft.Text("复制路径", size=12),
                                        ], spacing=6),
                                        on_click=lambda _: copy_path()
                                    ),
                                    ft.PopupMenuItem(
                                        content=ft.Row([
                                            ft.Icon(ft.Icons.UNARCHIVE_ROUNDED, size=14, color=ft.Colors.DEEP_PURPLE_400),
                                            ft.Text("解压 ZIP", size=12),
                                        ], spacing=6),
                                        on_click=lambda _: decompress_zip()
                                    ) if filename.lower().endswith(".zip") else ft.PopupMenuItem(visible=False),
                                    ft.PopupMenuItem(
                                        content=ft.Row([
                                            ft.Icon(ft.Icons.DELETE_ROUNDED, size=14, color=ft.Colors.RED_400),
                                            ft.Text("删除此条", size=12),
                                        ], spacing=6),
                                        on_click=delete_current,
                                    ),
                                ],
                                icon=ft.Icons.MORE_VERT_ROUNDED,
                                icon_color=ft.Colors.ON_SURFACE_VARIANT,
                                icon_size=16,
                            )
                        ],
                        spacing=0,
                        alignment=ft.MainAxisAlignment.END,
                    )
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )

            bubble_content = ft.Column(
                [
                    top_row,
                    ft.Container(
                        content=progress_bar,
                        margin=ft.Margin.only(top=6),
                    ) if "正在" in file_status else ft.Container()
                ],
                spacing=0,
                tight=True,
            )
        else:
            # Check if Python Code (Challenge 1: Code Sharing)
            is_code = False
            code_content = content
            if content.startswith("```python"):
                is_code = True
                code_content = content[9:].strip()
                if code_content.endswith("```"):
                    code_content = code_content[:-3].strip()
            elif "def " in content or "import " in content or "class " in content or "print(" in content:
                is_code = True

            if is_code:
                # Code bubble
                def copy_code():
                    if self.page:
                        self.page.set_clipboard(code_content)
                        self.show_toast("代码已复制到剪贴板 📋")

                bubble_content = ft.Column(
                    [
                        ft.Container(
                            content=ft.Column(
                                [
                                    ft.Row(
                                        [
                                            ft.Text("Python 代码 🐍", size=12, color=ft.Colors.DEEP_PURPLE_200, weight=ft.FontWeight.BOLD),
                                            ft.IconButton(
                                                icon=ft.Icons.COPY_ALL_ROUNDED,
                                                icon_size=16,
                                                icon_color=ft.Colors.DEEP_PURPLE_200,
                                                tooltip="复制代码",
                                                on_click=lambda _: copy_code()
                                            )
                                        ],
                                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                        height=24,
                                    ),
                                    ft.Divider(height=1, color=ft.Colors.with_opacity(0.1, ft.Colors.ON_SURFACE)),
                                    ft.Text(
                                        code_content,
                                        font_family="monospace",
                                        size=13,
                                        color=ft.Colors.ON_SURFACE,
                                        selectable=True,
                                    ),
                                ],
                                spacing=5,
                            ),
                            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
                            padding=10,
                            border_radius=8,
                            border=T.border_all(1, ft.Colors.with_opacity(0.1, ft.Colors.ON_SURFACE)),
                            width=300,
                        ),
                        ft.Text(
                            timestamp,
                            size=T.FS_CAPTION,
                            color=ft.Colors.with_opacity(0.7, ft.Colors.WHITE) if is_self else ft.Colors.ON_SURFACE_VARIANT,
                            text_align=ft.TextAlign.RIGHT,
                        ),
                    ],
                    spacing=T.SP_XS,
                )
            else:
                # Standard Text Message
                bubble_content = ft.Column(
                    [
                        ft.Text(
                            content,
                            size=T.FS_TEXT,
                            color=ft.Colors.WHITE if is_self else ft.Colors.ON_SURFACE,
                            selectable=True,
                            weight=ft.FontWeight.W_500
                        ),
                        ft.Text(
                            timestamp,
                            size=T.FS_CAPTION,
                            color=ft.Colors.with_opacity(0.7, ft.Colors.WHITE) if is_self else ft.Colors.ON_SURFACE_VARIANT,
                            text_align=ft.TextAlign.RIGHT,
                        ),
                    ],
                    spacing=4,
                )

        if is_file_msg:
            bubble_bg = ft.Colors.SURFACE_CONTAINER_LOW
            bubble_border = T.border_all(1, ft.Colors.with_opacity(0.15, ft.Colors.DEEP_PURPLE_400 if is_self else ft.Colors.ON_SURFACE))
        else:
            bubble_bg = None if is_self else ft.Colors.SURFACE_CONTAINER_HIGH
            bubble_border = T.border_all(1, ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE)) if not is_self else None

        bubble = ft.Container(
            content=bubble_content,
            width=file_card_width if is_file_msg else None,
            gradient=T.GRADIENT_PRIMARY if is_self and not is_file_msg else None,
            bgcolor=bubble_bg,
            border_radius=T.radius_only(
                top_left=16, top_right=16,
                bottom_right=4 if is_self else 16,
                bottom_left=16 if is_self else 4,
            ),
            padding=T.pad_symmetric(horizontal=12, vertical=12),
            shadow=ft.BoxShadow(blur_radius=8, color=ft.Colors.with_opacity(0.04, ft.Colors.BLACK), offset=ft.Offset(0, 2)),
            border=bubble_border,
        )
        if is_file_msg:
            bubble = ft.GestureDetector(
                mouse_cursor=ft.MouseCursor.CLICK,
                on_double_tap=lambda _: open_file(),
                content=bubble,
            )

        avatar = ft.GestureDetector(
            mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=lambda _: self.app.show_friend_profile(from_name) if hasattr(self.app, "show_friend_profile") else None,
            content=T.avatar_circle(self.app.get_avatar_for_name(from_name), T.AVATAR_SM)
        )
        row_menu = None
        if not is_file_msg:
            row_menu = ft.PopupMenuButton(
                items=[
                    ft.PopupMenuItem(
                        content=ft.Row([
                            ft.Icon(
                                ft.Icons.DELETE_ROUNDED,
                                size=14,
                                color=ft.Colors.RED_400,
                            ),
                            ft.Text("删除此条", size=12),
                        ], spacing=6),
                        on_click=delete_current,
                    )
                ],
                icon=ft.Icons.MORE_VERT_ROUNDED,
                icon_color=ft.Colors.ON_SURFACE_VARIANT,
                icon_size=16,
            )
        if is_self:
            controls = [ft.Container(expand=True)]
            if row_menu:
                controls.append(row_menu)
            controls.append(bubble)
            if not self._is_mobile_ui():
                controls.append(avatar)
            row = ft.Row(
                controls,
                alignment=ft.MainAxisAlignment.END,
                vertical_alignment=ft.CrossAxisAlignment.END,
            )
        else:
            controls = [avatar, bubble]
            if row_menu:
                controls.append(row_menu)
            row = ft.Row(
                controls,
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.END,
            )

        if is_file_msg and file_id and ("正在" in file_status or "等待" in file_status):
            cached_state = self._transfer_states.get(file_id, {})
            self._transfer_widgets[file_id] = {
                "row": row,
                "progress": progress_bar,
                "status": status_label,
                "detail": detail_label,
                "pause_button": pause_button,
                "paused": False,
                "percent": float(cached_state.get("percent", 0.0) or 0.0),
                "last_completed": int(cached_state.get("completed", 0) or 0),
                "last_time": time.monotonic(),
                "speed": 0.0,
                "sending": is_self,
                "peer_name": from_name,
                "filename": filename,
            }
            self._start_transfer_watchdog(file_id)

        self._msg_list.controls.append(row)
        self._scroll_bottom()
        return row

    def _file_info_from_content(self, content):
        decoded = decode_file_message(content, self.app.get_receive_dir())
        return {
            "filename": decoded.filename,
            "path": decoded.path,
            "transfer_id": decoded.transfer_id,
        }

    def _remember_transfer_state(self, file_id, **changes):
        if not file_id:
            return {}
        state = self._transfer_states.setdefault(file_id, {})
        state.update(changes)
        state["updated_at"] = time.monotonic()
        return state

    def _render_active_transfers_for(self, friend_name):
        if not self._msg_list or not friend_name:
            return
        for file_id, state in list(self._transfer_states.items()):
            if state.get("peer_name") != friend_name or state.get("final"):
                continue
            content = self._file_message_content(
                state.get("status", "正在发送文件" if state.get("sending") else "正在接收文件"),
                state.get("filename", "文件"),
                state.get("file_path", ""),
                file_id,
            )
            self._append_bubble(
                self.app.device_name if state.get("sending") else friend_name,
                content,
                state.get("timestamp", time.strftime("%H:%M:%S", time.localtime())),
                is_self=bool(state.get("sending")),
            )

    def _file_message_content(
        self, status, filename, file_path, transfer_id=""
    ):
        return encode_file_message(status, filename, file_path, transfer_id)

    def _replace_bubble(self, old_row, from_name, content, timestamp, is_self=False, msg_id=""):
        if not self._msg_list:
            return self._append_bubble(
                from_name, content, timestamp, is_self=is_self, msg_id=msg_id
            )
        replacement = self._build_bubble_row(
            from_name, content, timestamp, is_self, msg_id=msg_id
        )
        try:
            idx = self._msg_list.controls.index(old_row)
            self._msg_list.controls[idx] = replacement
        except ValueError:
            self._msg_list.controls.append(replacement)
        self._scroll_bottom()
        return replacement

    def _build_bubble_row(self, from_name, content, timestamp, is_self=False, msg_id=""):
        before_len = len(self._msg_list.controls)
        row = self._append_bubble(
            from_name, content, timestamp, is_self=is_self, msg_id=msg_id
        )
        if len(self._msg_list.controls) > before_len:
            self._msg_list.controls.pop()
        return row

    def _delete_message_row(self, row, msg_id="", file_id=""):
        delete_id = msg_id or file_id
        if file_id:
            was_pending_offer = file_id in self._pending_file_offers
            self._mark_file_transfer_closed(file_id)
            service = getattr(self.app, "message_service", None)
            try:
                if was_pending_offer and service and hasattr(service, "decline_file_offer"):
                    service.decline_file_offer(file_id)
                elif hasattr(self.app, "cancel_file_transfer"):
                    self.app.cancel_file_transfer(file_id)
            except Exception:
                pass

        if delete_id and hasattr(self.app, "delete_chat_message"):
            try:
                self.app.delete_chat_message(delete_id, is_group=self.is_group)
            except TypeError:
                self.app.delete_chat_message(delete_id)
            except Exception:
                pass

        if row and self._msg_list and row in self._msg_list.controls:
            self._msg_list.controls.remove(row)

        if self.page:
            self.page.update()

    def _scroll_bottom(self):
        if not self._msg_list or not self.page:
            return
        self._scroll_generation += 1
        generation = self._scroll_generation
        self._msg_list.scroll_to(offset=-1, duration=200)

        def delayed_scroll():
            time.sleep(0.08)
            if generation != self._scroll_generation:
                return
            if self._msg_list and self.page:
                self._msg_list.scroll_to(offset=-1, duration=200)
                try:
                    self.page.update()
                except Exception:
                    pass

        threading.Thread(target=delayed_scroll, daemon=True).start()

    # -- platform helpers --------------------------------------------------

    @staticmethod
    def _is_android() -> bool:
        """Best-effort Android detection (matches paths._is_android)."""
        if hasattr(os, "getandroidapplication"):
            return True
        if "ANDROID_ARGUMENT" in os.environ or "ANDROID_APP_PATH" in os.environ:
            return True
        return False

    @classmethod
    def _open_file_with_os(cls, file_path: str):
        """Open a file with the OS default handler (cross-platform)."""
        import platform
        system = platform.system()
        if cls._is_android():
            # Android: use the Intent system via am
            try:
                subprocess.run(
                    ["am", "start", "-a", "android.intent.action.VIEW",
                     "-d", f"file://{file_path}",
                     "-t", "*/*"],
                    check=False,
                )
            except Exception:
                pass
        elif system == "Windows":
            os.startfile(file_path)
        elif system == "Darwin":
            subprocess.run(["open", file_path], check=True)
        else:
            # Linux
            subprocess.run(["xdg-open", file_path], check=False)

    @classmethod
    def _open_folder_with_os(cls, file_path: str, folder_path: str):
        """Open the file's containing folder (cross-platform)."""
        import platform
        system = platform.system()
        if cls._is_android():
            # Android: open the parent folder via content URI or fall back
            # to opening the file itself (which is better than crashing).
            try:
                subprocess.run(
                    ["am", "start", "-a", "android.intent.action.VIEW",
                     "-d", f"file://{folder_path}"],
                    check=False,
                )
            except Exception:
                cls._open_file_with_os(file_path)
        elif system == "Windows":
            win_path = file_path.replace("/", "\\")
            subprocess.run(
                f'explorer /select,"{win_path}"',
                shell=True,
            )
        elif system == "Darwin":
            subprocess.run(["open", "-R", file_path], check=True)
        else:
            # Linux
            subprocess.run(["xdg-open", folder_path], check=False)

    # -- events ------------------------------------------------------------

    def _on_send(self, _e):
        text = (self._input.value or "").strip()
        if not text or not self.current_friend:
            return
        self._input.value = ""

        # Append bubble immediately so the user sees it instantly!
        ts = time.strftime("%H:%M:%S", time.localtime())
        msg_id = str(uuid.uuid4())
        self._append_bubble(
            self.app.device_name,
            text,
            ts,
            is_self=True,
            msg_id=msg_id,
        )
        if self.page:
            self.page.update()

        def task():
            if self.is_group:
                self.app.send_group_chat_message(
                    self.current_group_id,
                    text,
                    msg_id=msg_id,
                )
            else:
                self.app.send_chat_message(self.current_friend, text, msg_id=msg_id)
        threading.Thread(target=task, daemon=True).start()

    async def _pick_file(self, _e):
        # Try native tkinter file dialog first (desktop); fall back to
        # Flet FilePicker on Android where tkinter is not available.
        try:
            import tkinter as tk
        except ImportError:
            await self._pick_file_flet()
            return

        import threading
        def _do_pick():
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            file_path = filedialog.askopenfilename(
                title="选择要发送的文件",
                parent=root,
            )
            root.destroy()
            if file_path:
                self._send_file(file_path)
        threading.Thread(target=_do_pick, daemon=True).start()

    async def _pick_file_flet(self):
        """Use Flet FilePicker for platforms without tkinter (Android)."""
        picker = getattr(self.app, "chat_file_picker", None)
        if not picker:
            picker = ft.FilePicker()
            self.app.chat_file_picker = picker
        # FilePicker is a Service in Flet 0.85+.
        page = self.page
        if page and picker not in page.services:
            page.services.append(picker)

        files = await picker.pick_files(
            dialog_title="选择要发送的文件",
        )
        if files and files[0].path:
            selected_path = files[0].path
            self.show_toast("正在准备文件...")

            def prepare_and_send():
                try:
                    stable_path = self._stage_android_outgoing_file(selected_path)
                    self._send_file(stable_path)
                except Exception as exc:
                    self.show_toast(f"文件准备失败: {exc}")

            threading.Thread(target=prepare_and_send, daemon=True).start()

    def _stage_android_outgoing_file(self, file_path):
        """Copy Android picker results into app-private storage before sending."""
        platform_name = str(getattr(self.page, "platform", "")).lower()
        if platform_name not in ("android", "pageplatform.android") or not file_path or not os.path.isfile(file_path):
            return file_path
        import shutil
        from pathlib import Path

        cache_dir = Path(self.app.paths.data_dir) / "outgoing_files"
        cache_dir.mkdir(parents=True, exist_ok=True)
        source = Path(file_path)
        destination = cache_dir / f"{time.time_ns()}_{source.name}"
        shutil.copy2(source, destination)

        # Keep the cache bounded while preserving recent files for retry.
        cached = sorted(cache_dir.glob("*"), key=lambda item: item.stat().st_mtime, reverse=True)
        for stale in cached[20:]:
            try:
                stale.unlink()
            except OSError:
                pass
        return str(destination)

    def _send_file(self, file_path):
        if not self.current_friend:
            return

        if self.compress_checkbox.value:
            try:
                import zipfile
                import tempfile
                temp_zip_dir = os.path.join(tempfile.gettempdir(), "beiyang_compressed")
                os.makedirs(temp_zip_dir, exist_ok=True)
                zip_filename = os.path.basename(file_path) + ".zip"
                zip_path = os.path.join(temp_zip_dir, zip_filename)
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                    zipf.write(file_path, os.path.basename(file_path))
                file_path = zip_path
            except Exception as e:
                self.show_toast(f"自动压缩失败: {e}")

        filename = os.path.basename(file_path)
        ts = time.strftime("%H:%M:%S", time.localtime())
        transfer_id = str(uuid.uuid4()) if not self.is_group else ""
        sending_content = self._file_message_content(
            "正在发送文件", filename, file_path, transfer_id
        )

        if self.is_group:
            sending_row = self._append_bubble(self.app.device_name, sending_content, ts, is_self=True)
            if self.page:
                self.page.update()

            def worker():
                # Save group chat message & send to others
                content = self._file_message_content("文件", filename, file_path)
                self.app.send_group_chat_message(self.current_group_id, content)

                # Fetch members
                group = self.app.friend_db.get_group(self.current_group_id)
                if group:
                    members = group.get("members", [])
                    my_name = self.app.device_name
                    for m in members:
                        if m != my_name and m in [f["name"] for f in self.app.get_online_friends()]:
                            # Send in background thread
                            threading.Thread(
                                target=lambda member=m: self.app.message_service.send_file(member, file_path),
                                daemon=True
                            ).start()

                done_ts = time.strftime("%H:%M:%S", time.localtime())
                self._replace_bubble(sending_row, self.app.device_name, content, done_ts, is_self=True)
                if self.page:
                    self.page.update()
            threading.Thread(target=worker, daemon=True).start()
        else:
            target_friend = self.current_friend
            self._remember_transfer_state(
                transfer_id,
                peer_name=target_friend,
                filename=filename,
                file_path=file_path,
                sending=True,
                status="正在发送文件",
                completed=0,
                total=os.path.getsize(file_path) if os.path.exists(file_path) else 0,
                percent=0.0,
                timestamp=ts,
                final=False,
            )
            sending_row = self._append_bubble(self.app.device_name, sending_content, ts, is_self=True)
            if self.page:
                self.page.update()
            def worker():
                ok = self.app.send_file_to_friend(
                    target_friend, file_path, transfer_id
                )
                done_ts = time.strftime("%H:%M:%S", time.localtime())
                status = "文件发送失败"
                if ok:
                    status = self.app.message_service.get_file_final_status(transfer_id) if self.app.message_service else "文件"
                content = self._file_message_content(
                    status, filename, file_path, transfer_id
                )
                self._remember_transfer_state(
                    transfer_id,
                    status=status,
                    final=("等待" not in status),
                )
                if self._msg_list is not None and sending_row in self._msg_list.controls:
                    self._replace_bubble(sending_row, self.app.device_name, content, done_ts, is_self=True)
                if "等待" not in status:
                    self._transfer_widgets.pop(transfer_id, None)
                if self.page:
                    self.page.update()
            threading.Thread(target=worker, daemon=True).start()

    def _back_to_list(self, _e):
        self._transfer_widgets.clear()
        self._msg_list = None
        self.current_friend = ""
        self.app.show_view("chat")

    def _confirm_clear(self):
        def do_clear(_e):
            dlg.open = False
            self.app.clear_chat_history(self.current_friend)
            self.page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("清空历史记录 🧹", weight=ft.FontWeight.BOLD),
            content=ft.Text(f"确定清空与「{self.current_friend}」的所有聊天记录吗？此操作不可恢复。"),
            actions=[
                ft.TextButton("取消", on_click=lambda _e: self._close(dlg)),
                ft.ElevatedButton("确认清空", on_click=do_clear, bgcolor=ft.Colors.RED_600, color=ft.Colors.WHITE),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()

    def _close(self, dlg):
        dlg.open = False
        self.page.update()

    # -- incoming ----------------------------------------------------------

    # Sliding window for real-time file-transfer speed (seconds).
    _SPEED_WINDOW = 3.0

    @staticmethod
    def _format_bytes(value):
        value = float(max(0, value or 0))
        for unit in ("B", "KiB", "MiB", "GiB"):
            if value < 1024 or unit == "GiB":
                return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
            value /= 1024

    @classmethod
    def _format_speed(cls, bytes_per_second):
        if not bytes_per_second or bytes_per_second <= 0:
            return "0 B/s"
        return f"{cls._format_bytes(bytes_per_second)}/s"

    # ── transfer watchdog ──────────────────────────────────────────────

    def _start_transfer_watchdog(self, file_id):
        """Periodically refresh stalled transfers so speed decays toward 0."""
        if not file_id or file_id in self._transfer_watchdogs:
            return
        self._transfer_watchdogs.add(file_id)

        def watchdog():
            try:
                while True:
                    time.sleep(0.8)
                    widget = self._transfer_widgets.get(file_id)
                    if not widget:
                        return
                    if widget.get("paused"):
                        continue
                    percent = float(widget.get("percent", 0.0) or 0.0)
                    if percent >= 100:
                        return
                    idle = time.monotonic() - float(widget.get("last_data_ts", 0.0))
                    if idle < 1.5:
                        continue

                    # Decay the displayed speed so the user sees it slowing.
                    self._update_speed(widget, 0, widget.get("last_completed", 0))
                    direction = "发送" if widget.get("sending") else "接收"
                    widget["status"].value = (
                        f"⏳ {direction}等待对端/网络 · {percent:.0f}% · "
                        f"{self._format_speed(widget.get('speed', 0.0))}"
                    )
                    if self.page:
                        try:
                            self.page.update()
                        except Exception:
                            return
            finally:
                self._transfer_watchdogs.discard(file_id)

        threading.Thread(target=watchdog, daemon=True).start()

    # ── speed calculation (sliding-window, real-time) ───────────────────

    @classmethod
    def _update_speed(cls, widget: dict, completed: int, prev_completed: int):
        """Recalculate instant speed using a sliding window of samples.

        Stores ``_speed_samples`` as a deque of *(monotonic_ts, bytes)* in
        *widget*.  Samples older than ``_SPEED_WINDOW`` seconds are pruned
        on every call so the speed always reflects the recent throughput,
        even when the transfer is idle (speed naturally decays to 0).
        """
        now = time.monotonic()
        samples = widget.setdefault("_speed_samples", [])
        # Append a new sample when bytes actually advanced.
        if completed > prev_completed:
            samples.append((now, completed))
        # Prune samples older than the window.
        cutoff = now - cls._SPEED_WINDOW
        while len(samples) > 1 and samples[0][0] < cutoff:
            samples.pop(0)
        # Compute windowed speed.
        if len(samples) >= 2:
            window_dt = samples[-1][0] - samples[0][0]
            window_db = samples[-1][1] - samples[0][1]
            instant = window_db / max(0.05, window_dt)
        elif completed > 0:
            # Not enough history yet — fall back to average since start.
            start_ts = widget.get("_start_ts", now)
            elapsed = max(0.05, now - start_ts)
            instant = completed / elapsed
        else:
            instant = 0.0
        # Exponential moving average for display smoothness.
        prev = float(widget.get("speed", 0.0) or 0.0)
        alpha = 0.45  # higher = more responsive
        widget["speed"] = instant if prev <= 0 else prev * (1 - alpha) + instant * alpha

    # ── widget lookup ───────────────────────────────────────────────────

    def _find_transfer_widget(self, peer_name="", filename="", sending=None):
        for transfer_id, widget in list(self._transfer_widgets.items()):
            if peer_name and widget.get("peer_name") != peer_name:
                continue
            if filename and widget.get("filename") != filename:
                continue
            if sending is not None and bool(widget.get("sending")) != bool(sending):
                continue
            return transfer_id, widget
        return "", None

    @staticmethod
    def _is_final_file_status(status: str) -> bool:
        return bool(status) and "正在" not in status and "等待" not in status

    def _mark_file_transfer_closed(self, file_id: str):
        if not file_id:
            return
        self._closed_file_transfers.add(file_id)
        if file_id in self._transfer_states:
            self._transfer_states[file_id]["final"] = True
        self._transfer_widgets.pop(file_id, None)
        self._pending_file_offers.pop(file_id, None)

    # ── progress callback (called by MessageService) ────────────────────

    def on_file_progress(
        self, file_id, peer_name, filename, completed, total, sending,
        confirmed=0,
    ):
        """Update transfer widget for *file_id*.

        *completed*  – bytes sent (sender) or written (receiver) so far.
        *confirmed*  – bytes the remote side has acknowledged (sender only).
        """
        if file_id in self._closed_file_transfers:
            return
        progress_value = min(1.0, max(0.0, completed / total)) if total else 0.0
        self._remember_transfer_state(
            file_id,
            peer_name=peer_name,
            filename=filename,
            sending=bool(sending),
            status="正在发送文件" if sending else "正在接收文件",
            completed=int(completed or 0),
            total=int(total or 0),
            confirmed=int(confirmed or 0),
            percent=progress_value * 100,
            final=False,
        )
        widget = self._transfer_widgets.get(file_id)
        if not widget:
            old_id, old_widget = self._find_transfer_widget(
                peer_name=peer_name,
                filename=filename,
                sending=sending,
            )
            if old_widget:
                self._transfer_widgets.pop(old_id, None)
                self._transfer_widgets[file_id] = old_widget
                widget = old_widget
        if (
            not widget
            and not sending
            and self.current_friend == peer_name
            and not self.is_group
            and self._msg_list is not None
        ):
            file_path = ""
            service = self.app.message_service
            if service:
                with service._file_lock:
                    state = service._incoming_files.get(file_id, {})
                    if state.get("pending_accept"):
                        return
                    file_path = state.get("final_path", "")
            content = self._file_message_content(
                "正在接收文件", filename, file_path, file_id
            )
            self._append_bubble(
                peer_name,
                content,
                time.strftime("%H:%M:%S", time.localtime()),
                is_self=False,
            )
            widget = self._transfer_widgets.get(file_id)
            self._start_transfer_watchdog(file_id)

        if not widget:
            return

        last_completed = int(widget.get("last_completed", 0) or 0)
        if completed < last_completed:
            return

        # Record the moment we first see data so speed calculation has a
        # meaningful baseline.
        if last_completed == 0 and completed > 0:
            widget.setdefault("_start_ts", time.monotonic())
        if completed > last_completed:
            widget["last_data_ts"] = time.monotonic()

        # ── real-time speed (sliding window) ──
        self._update_speed(widget, completed, last_completed)

        progress = min(1.0, max(0.0, completed / total)) if total else 0.0
        percent = progress * 100
        widget["last_completed"] = int(completed)
        widget["percent"] = percent
        widget["progress"].value = progress

        if not widget.get("paused"):
            if sending and confirmed and confirmed > 0:
                # Show both local-sent and remote-confirmed bytes so the
                # user can see that the other side is keeping up.
                action = "正在发送"
                widget["status"].value = (
                    f"📤 {action} · {percent:.0f}% · "
                    f"{self._format_speed(widget.get('speed', 0.0))}"
                )
                widget["detail"].value = (
                    f"已发 {self._format_bytes(completed)} · "
                    f"已确认 {self._format_bytes(confirmed)} / {self._format_bytes(total)}"
                )
            else:
                action = "正在发送" if sending else "正在接收"
                widget["status"].value = (
                    f"{'📤' if sending else '📥'} {action} · {percent:.0f}% · "
                    f"{self._format_speed(widget.get('speed', 0.0))}"
                )
                widget["detail"].value = (
                    f"{self._format_bytes(completed)} / {self._format_bytes(total)}"
                )

    def on_file_status_changed(self, file_id, status):
        """Update transfer widget for *file_id* to the new status."""
        if file_id in self._closed_file_transfers:
            return
        self._remember_transfer_state(
            file_id,
            status=status,
            final=self._is_final_file_status(status),
        )
        widget = self._transfer_widgets.get(file_id)
        if not widget:
            if self._is_final_file_status(status):
                self._mark_file_transfer_closed(file_id)
            return

        sending = widget.get("sending", False)
        peer_name = widget.get("peer_name", "")
        filename = widget.get("filename", "")
        from_name = self.app.device_name if sending else peer_name

        # Retrieve the file path if available
        file_path = ""
        service = self.app.message_service
        if service:
            with service._file_lock:
                state = service._incoming_files.get(file_id, {}) if not sending else service._active_senders.get(file_id, {})
                file_path = state.get("final_path", "") or state.get("file_path", "")

        content = self._file_message_content(
            status,
            filename,
            file_path,
            file_id,
        )
        timestamp = time.strftime("%H:%M:%S", time.localtime())

        # Replace the old bubble row with the new bubble row
        new_row = self._replace_bubble(
            widget["row"],
            from_name,
            content,
            timestamp,
            is_self=sending,
        )
        # Update the widget reference and clean up if it reached a final state
        widget["row"] = new_row
        if self._is_final_file_status(status):
            self._mark_file_transfer_closed(file_id)
        if self.page:
            self.page.update()

    # ── inline file-offer (no modal) ──────────────────────────────────

    @staticmethod
    def _format_sz(sz):
        for unit in ("B", "KiB", "MiB", "GiB"):
            if sz < 1024 or unit == "GiB":
                return f"{sz:.0f} {unit}" if unit == "B" else f"{sz:.1f} {unit}"
            sz /= 1024

    def add_file_offer(self, from_name, filename, size, file_id):
        """Queue an inline file-offer widget for *from_name*."""
        if file_id in self._pending_file_offers:
            return  # already queued
        self._pending_file_offers[file_id] = {
            "from_name": from_name,
            "filename": filename,
            "size": size,
        }
        # If the chat with this friend is currently open, render it immediately.
        if (self.current_friend == from_name
                and not self.is_group
                and self._msg_list is not None):
            self._render_file_offer(file_id)
        if self.page:
            self.page.update()

    def _render_file_offers_for(self, friend_name):
        """Render all pending file offers for *friend_name*."""
        for file_id, offer in list(self._pending_file_offers.items()):
            if offer["from_name"] == friend_name:
                self._render_file_offer(file_id)

    def _render_file_offer(self, file_id):
        """Insert an inline file-offer bubble into the current chat."""
        offer = self._pending_file_offers.get(file_id)
        if not offer or offer.get("widget"):
            return  # already rendered or already acted upon
        from_name = offer["from_name"]
        filename = offer["filename"]
        size = offer["size"]

        row = None

        def accept(_e):
            content = self._file_message_content(
                "正在接收文件", filename, "", file_id
            )
            if row and row in self._msg_list.controls:
                self._replace_bubble(
                    row,
                    from_name,
                    content,
                    time.strftime("%H:%M:%S", time.localtime()),
                    is_self=False,
                )
            self._pending_file_offers.pop(file_id, None)
            self.app.message_service.accept_file_offer(file_id)
            if self.page:
                self.page.update()

        def decline(_e):
            content = self._file_message_content(
                "已拒绝接收", filename, "", file_id
            )
            if row and row in self._msg_list.controls:
                self._replace_bubble(
                    row,
                    from_name,
                    content,
                    time.strftime("%H:%M:%S", time.localtime()),
                    is_self=False,
                )
            self._pending_file_offers.pop(file_id, None)
            self._mark_file_transfer_closed(file_id)
            self.app.message_service.decline_file_offer(file_id)
            if self.page:
                self.page.update()

        def delete_offer(_e):
            self._delete_message_row(row, msg_id=file_id, file_id=file_id)

        # File Type Icon resolution
        ext = os.path.splitext(filename)[1].lower()
        if ext in (".zip", ".rar", ".7z", ".tar", ".gz"):
            file_icon = ft.Icons.FOLDER_ZIP_ROUNDED
            icon_bg = ft.Colors.AMBER_500
        elif ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
            file_icon = ft.Icons.IMAGE_ROUNDED
            icon_bg = ft.Colors.BLUE_500
        elif ext in (".mp4", ".avi", ".mkv", ".mov", ".flv"):
            file_icon = ft.Icons.VIDEO_LIBRARY_ROUNDED
            icon_bg = ft.Colors.RED_500
        elif ext in (".mp3", ".wav", ".flac", ".ogg", ".m4a"):
            file_icon = ft.Icons.AUDIO_FILE_ROUNDED
            icon_bg = ft.Colors.TEAL_500
        elif ext in (".txt", ".md", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"):
            file_icon = ft.Icons.ARTICLE_ROUNDED
            icon_bg = ft.Colors.BLUE_GREY_500
        else:
            file_icon = ft.Icons.INSERT_DRIVE_FILE_ROUNDED
            icon_bg = ft.Colors.DEEP_PURPLE_500

        icon_container = ft.Container(
            content=ft.Icon(file_icon, color=ft.Colors.WHITE, size=22),
            bgcolor=icon_bg,
            width=40,
            height=40,
            border_radius=8,
            alignment=ft.alignment.Alignment.CENTER,
        )

        accept_btn = ft.IconButton(
            icon=ft.Icons.CHECK_CIRCLE_ROUNDED,
            icon_color=ft.Colors.GREEN_400,
            icon_size=20,
            tooltip="接收文件",
            on_click=accept,
        )
        decline_btn = ft.IconButton(
            icon=ft.Icons.CANCEL_ROUNDED,
            icon_color=ft.Colors.RED_400,
            icon_size=20,
            tooltip="拒绝文件",
            on_click=decline,
        )

        top_row = ft.Row(
            [
                icon_container,
                ft.Column(
                    [
                        ft.Text(
                            filename,
                            size=13,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.ON_SURFACE,
                            overflow=ft.TextOverflow.ELLIPSIS,
                            max_lines=1,
                            width=140,
                        ),
                        ft.Text(
                            f"📁 请求发送文件 · {self._format_sz(size)}",
                            size=10,
                            color=ft.Colors.DEEP_PURPLE_400,
                            overflow=ft.TextOverflow.ELLIPSIS,
                            max_lines=1,
                            width=140,
                        ),
                    ],
                    spacing=1,
                    expand=True,
                ),
                ft.Row(
                    [
                        accept_btn,
                        decline_btn,
                        ft.PopupMenuButton(
                            items=[
                                ft.PopupMenuItem(
                                    content=ft.Row([
                                        ft.Icon(
                                            ft.Icons.DELETE_ROUNDED,
                                            size=14,
                                            color=ft.Colors.RED_400,
                                        ),
                                        ft.Text("删除此条", size=12),
                                    ], spacing=6),
                                    on_click=delete_offer,
                                )
                            ],
                            icon=ft.Icons.MORE_VERT_ROUNDED,
                            icon_color=ft.Colors.ON_SURFACE_VARIANT,
                            icon_size=16,
                        ),
                    ],
                    spacing=0,
                    alignment=ft.MainAxisAlignment.END,
                )
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        bubble_content = ft.Column(
            [
                top_row,
                ft.Text(
                    time.strftime("%H:%M:%S", time.localtime()),
                    size=T.FS_CAPTION,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                    text_align=ft.TextAlign.RIGHT,
                ),
            ],
            spacing=4,
            tight=True,
        )

        bubble = ft.Container(
            content=bubble_content,
            width=320,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            border_radius=T.radius_only(
                top_left=16, top_right=16,
                bottom_right=16,
                bottom_left=4,
            ),
            padding=T.pad_symmetric(horizontal=12, vertical=12),
            shadow=ft.BoxShadow(blur_radius=8, color=ft.Colors.with_opacity(0.04, ft.Colors.BLACK), offset=ft.Offset(0, 2)),
            border=T.border_all(1, ft.Colors.with_opacity(0.15, ft.Colors.DEEP_PURPLE_400)),
        )

        avatar = ft.GestureDetector(
            mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=lambda _: self.app.show_friend_profile(from_name) if hasattr(self.app, "show_friend_profile") else None,
            content=T.avatar_circle(self.app.get_avatar_for_name(from_name), T.AVATAR_SM)
        )

        row = ft.Row([avatar, bubble], alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.END)

        offer["widget"] = row
        self._msg_list.controls.append(row)
        self._scroll_bottom()
        if self.page:
            self.page.update()

    # ── incoming messages ─────────────────────────────────────────────

    def on_new_message(self, from_name, content, timestamp, msg_id=""):
        ts = timestamp
        if len(timestamp) >= 19:
            ts = timestamp[11:19]
        if self.current_friend == from_name and not self.is_group and self._msg_list is not None:
            decoded = decode_file_message(content, self.app.get_receive_dir())
            if decoded.transfer_id and decoded.transfer_id in self._closed_file_transfers:
                return
            widget = None
            if decoded.transfer_id:
                widget = self._transfer_widgets.pop(decoded.transfer_id, None)
            if not widget and decoded.filename:
                old_id, widget = self._find_transfer_widget(
                    peer_name=from_name,
                    filename=decoded.filename,
                    sending=False,
                )
                if widget:
                    self._transfer_widgets.pop(old_id, None)
            if widget:
                self._replace_bubble(
                    widget["row"],
                    from_name,
                    content,
                    ts,
                    is_self=False,
                    msg_id=msg_id or decoded.transfer_id,
                )
                if self._is_final_file_status(decoded.status):
                    self._mark_file_transfer_closed(decoded.transfer_id)
                if self.page:
                    self.page.update()
                return
            self._append_bubble(
                from_name,
                content,
                ts,
                is_self=False,
                msg_id=msg_id or decoded.transfer_id,
            )
            if self.page:
                self.page.update()
        if not self.current_friend and self._list_root is not None:
            self._render_list()

    def on_new_group_message(self, group_id, sender, content, timestamp):
        ts = timestamp
        if len(timestamp) >= 19:
            ts = timestamp[11:19]
        if self.is_group and self.current_group_id == group_id and self._msg_list is not None:
            self._append_bubble(sender, content, ts, is_self=(sender == self.app.device_name))
            if self.page:
                self.page.update()
        if not self.current_friend and self._list_root is not None:
            self._render_list()

    def show_group_info(self, group_id):
        group = self.app.friend_db.get_group(group_id)
        if not group or not self.page:
            return

        name = group.get("group_name", "")
        members = group.get("members", [])

        members_chips = []
        for m in members:
            is_me = (m == self.app.device_name)
            chip_color = ft.Colors.DEEP_PURPLE_400 if is_me else ft.Colors.ON_SURFACE_VARIANT
            members_chips.append(
                ft.Container(
                    content=ft.Row(
                        [
                            T.avatar_circle(self.app.get_avatar_for_name(m) if not is_me else m, 20),
                            ft.Text(m, size=11, color=chip_color, weight=ft.FontWeight.BOLD if is_me else ft.FontWeight.NORMAL),
                        ],
                        spacing=4,
                        tight=True,
                    ),
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                    padding=T.pad_symmetric(horizontal=8, vertical=4),
                    border_radius=8,
                )
            )

        def close_dlg(e):
            dlg.open = False
            self.page.update()
            try:
                self.page.overlay.remove(dlg)
            except Exception:
                pass

        dlg = ft.AlertDialog(
            title=ft.Row(
                [
                    T.avatar_circle("group", 44),
                    ft.Column(
                        [
                            ft.Text(name, size=T.FS_TITLE, weight=ft.FontWeight.BOLD),
                            ft.Text(f"群组 ID: {group_id[:8]}", size=T.FS_CAPTION, color=ft.Colors.ON_SURFACE_VARIANT),
                        ],
                        spacing=2,
                    )
                ],
                spacing=T.SP_SM,
            ),
            content=ft.Column(
                [
                    T.section_title("群成员列表"),
                    ft.Row(members_chips, wrap=True),
                ],
                spacing=T.SP_SM,
                tight=True,
                width=300,
            ),
            actions=[
                ft.TextButton("关闭", on_click=close_dlg),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()

    def show_toast(self, text):
        if hasattr(self.app, "show_toast"):
            self.app.show_toast(text)

    def _on_create_group(self, _e):
        friends = self.app.get_all_friends() or []
        if not friends:
            self.app.show_toast("暂无好友，无法发起群聊哦~")
            return

        selected_friends = []

        group_name_input = ft.TextField(
            hint_text="输入群聊名称...",
            border_radius=8,
            autofocus=True,
        )

        def on_checkbox_change(e, name):
            if e.control.value:
                if name not in selected_friends:
                    selected_friends.append(name)
            else:
                if name in selected_friends:
                    selected_friends.remove(name)

        checkboxes = []
        for f in friends:
            name = f.get("name", "")
            checkboxes.append(
                ft.Checkbox(
                    label=name,
                    value=False,
                    on_change=lambda e, n=name: on_checkbox_change(e, n)
                )
            )

        def close_dialog(e):
            dlg.open = False
            if self.page:
                self.page.update()

        def do_create(e):
            group_name = (group_name_input.value or "").strip()
            if not group_name:
                self.app.show_toast("请输入群聊名称")
                return
            if not selected_friends:
                self.app.show_toast("请选择群成员")
                return

            group_id = self.app.create_group(group_name, selected_friends)
            close_dialog(None)
            self.app.show_toast(f"群聊「{group_name}」创建成功！")
            self.app.open_chat_with(group_name, is_group=True, group_id=group_id)

        dlg = ft.AlertDialog(
            title=ft.Text("发起群聊 👥", weight=ft.FontWeight.BOLD),
            content=ft.Column(
                [
                    ft.Text("群聊名称", size=T.FS_CAPTION, weight=ft.FontWeight.BOLD),
                    group_name_input,
                    ft.Text("选择群成员", size=T.FS_CAPTION, weight=ft.FontWeight.BOLD),
                    ft.Column(checkboxes, scroll=ft.ScrollMode.AUTO, height=200),
                ],
                spacing=T.SP_SM,
                tight=True,
                width=300,
            ),
            actions=[
                ft.TextButton("取消", on_click=close_dialog),
                ft.ElevatedButton("创建", on_click=do_create, bgcolor=ft.Colors.DEEP_PURPLE_500, color=ft.Colors.WHITE),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()

    def show_group_settings(self, group_id):
        group = self.app.friend_db.get_group(group_id)
        if not group or not self.page:
            return

        name = group.get("group_name", "")
        members = group.get("members", [])
        owner = group.get("owner", "")
        only_owner_manage = int(group.get("only_owner_manage", 0) or 0)

        is_owner = (self.app.device_name == owner or not owner)
        can_manage = True
        if only_owner_manage and not is_owner:
            can_manage = False

        group_name_input = ft.TextField(
            value=name,
            hint_text="修改群聊名称...",
            border_radius=8,
            disabled=not can_manage,
        )

        permission_switch = ft.Switch(
            label="仅群主可编辑名称及邀请成员",
            value=bool(only_owner_manage),
            disabled=not is_owner,
            label_position=ft.LabelPosition.RIGHT,
        )

        all_friends = self.app.get_all_friends() or []
        invite_candidates = [f for f in all_friends if f.get("name") not in members]

        selected_invitees = []
        def on_invitee_change(e, m_name):
            if e.control.value:
                if m_name not in selected_invitees:
                    selected_invitees.append(m_name)
            else:
                if m_name in selected_invitees:
                    selected_invitees.remove(m_name)

        checkboxes = []
        for cand in invite_candidates:
            cand_name = cand.get("name", "")
            checkboxes.append(
                ft.Checkbox(
                    label=cand_name,
                    value=False,
                    disabled=not can_manage,
                    on_change=lambda e, cn=cand_name: on_invitee_change(e, cn)
                )
            )

        def close_dialog(e):
            dlg.open = False
            self.page.update()

        def do_save(e):
            new_name = (group_name_input.value or "").strip()
            if not new_name:
                self.app.show_toast("群聊名称不能为空")
                return

            updated_members = list(members)
            for inv in selected_invitees:
                if inv not in updated_members:
                    updated_members.append(inv)

            new_owner = owner if owner else self.app.device_name
            new_only_owner_manage = 1 if permission_switch.value else 0

            self.app.update_group_info(group_id, new_name, updated_members, owner=new_owner, only_owner_manage=new_only_owner_manage)
            close_dialog(None)
            self.app.show_toast("群信息设置已保存并同步 👥")

            self.current_friend = new_name
            self.refresh_header()

        content_items = [
            ft.Text("群聊名称", size=T.FS_CAPTION, weight=ft.FontWeight.BOLD),
            group_name_input,
            ft.Text(f"群主: {owner if owner else self.app.device_name}", size=T.FS_CAPTION, color=ft.Colors.ON_SURFACE_VARIANT),
            permission_switch,
        ]

        if not can_manage:
            content_items.append(
                ft.Text(f"🔒 仅群主 {owner} 可管理该群", color=ft.Colors.RED_300, size=T.FS_CAPTION, weight=ft.FontWeight.BOLD)
            )
        else:
            content_items.append(
                ft.Text("邀请好友加入", size=T.FS_CAPTION, weight=ft.FontWeight.BOLD) if checkboxes else ft.Container()
            )
            if checkboxes:
                content_items.append(
                    ft.Column(checkboxes, scroll=ft.ScrollMode.AUTO, height=120)
                )
            else:
                content_items.append(
                    ft.Text("暂无可邀请的好友", size=T.FS_CAPTION, color=ft.Colors.ON_SURFACE_VARIANT)
                )

        dlg = ft.AlertDialog(
            title=ft.Text("群聊设置 ⚙️", weight=ft.FontWeight.BOLD),
            content=ft.Column(
                content_items,
                spacing=T.SP_SM,
                tight=True,
                width=300,
            ),
            actions=[
                ft.TextButton("取消", on_click=close_dialog),
                ft.ElevatedButton("保存", on_click=do_save, bgcolor=ft.Colors.DEEP_PURPLE_500, color=ft.Colors.WHITE, disabled=not can_manage),
            ] if can_manage else [
                ft.TextButton("关闭", on_click=close_dialog)
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()
