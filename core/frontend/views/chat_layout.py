"""Layout frame builder for ChatView."""

import flet as ft

from .. import theme as T


class ChatLayout:
    """Build the chat tabs and chat-window frame for ChatView."""

    def __init__(self, owner):
        self.owner = owner
        self.app = owner.app
        self.page = owner.page

    def build(self):
        if self.owner.current_friend:
            return self.build_window()
        return self.build_tabs()

    def build_tabs(self):
        tab_bar = ft.TabBar(
            tabs=[
                ft.Tab(label="会话列表", icon=ft.Icons.CHAT_ROUNDED),
                ft.Tab(label="系统通知", icon=ft.Icons.NOTIFICATIONS_ROUNDED),
                ft.Tab(label="雷达发现", icon=ft.Icons.RADAR_ROUNDED),
            ]
        )
        self.owner._tab_bar = tab_bar

        self.owner._list_col = ft.Column(
            spacing=T.SP_SM,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )
        self.owner._list_root = ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("最近会话", size=T.FS_TITLE, weight=ft.FontWeight.BOLD),
                        ft.IconButton(
                            icon=ft.Icons.GROUP_ADD_ROUNDED,
                            icon_color=ft.Colors.DEEP_PURPLE_400,
                            tooltip="发起群聊",
                            on_click=self.owner._on_create_group,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                self.owner._list_col,
            ],
            spacing=T.SP_SM,
            expand=True,
        )

        discover_view = self.app.views.get("discover")
        tab_view = ft.TabBarView(
            expand=True,
            controls=[
                self.owner._list_root,
                self.owner._build_notifications_view(),
                discover_view.build(),
            ],
        )

        def on_tab_change(_e):
            if self.owner.tabs.selected_index == 1:
                self.app.mark_all_notifications_read()

        self.owner.tabs = ft.Tabs(
            length=3,
            expand=True,
            on_change=on_tab_change,
            content=ft.Column(
                controls=[
                    tab_bar,
                    tab_view,
                ],
                expand=True,
            ),
        )
        self.owner._render_list()
        self.owner._render_notifications()
        return self.owner.tabs

    def build_window(self):
        mobile_ui = self.owner._is_mobile_ui()
        self.owner.compress_checkbox.label = None if mobile_ui else "压缩"
        self.owner.compress_checkbox.tooltip = "发送前压缩" if mobile_ui else None

        for offer in self.owner._pending_file_offers.values():
            if isinstance(offer, dict):
                offer.pop("widget", None)

        self._build_header_state()
        self.owner._msg_list = ft.Column(
            spacing=T.SP_MD,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )
        self.owner._input = self._build_input()
        chat_header = self._build_header()
        composer_controls = [
            self._build_attach_button(),
            self.owner.compress_checkbox,
            self.owner._input,
            self._build_send_button(),
        ]

        self.owner._window_root = ft.Column(
            [
                chat_header,
                ft.Container(
                    content=self.owner._msg_list,
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
            spacing=0,
            expand=True,
        )
        self.owner._load_history()
        return self.owner._window_root

    def _build_header_state(self):
        if self.owner.is_group:
            group = self.app.friend_db.get_group(self.owner.current_group_id)
            member_count = len(group.get("members", [])) if group else 0
            self.owner._header_avatar = ft.GestureDetector(
                mouse_cursor=ft.MouseCursor.CLICK,
                on_tap=lambda _: self.owner.show_group_settings(self.owner.current_group_id),
                content=T.avatar_circle("group", T.AVATAR_MD),
            )
            self.owner._header_name = ft.Text(
                self.owner.current_friend,
                size=T.FS_TITLE,
                weight=ft.FontWeight.BOLD,
            )
            self.owner._header_status = ft.Text(
                f"{member_count} 个成员",
                size=T.FS_CAPTION,
                color=ft.Colors.ON_SURFACE_VARIANT,
                weight=ft.FontWeight.NORMAL,
            )
            return

        online = self.owner.current_friend in [
            friend.get("name") for friend in self.app.get_online_friends()
        ]
        self.owner._header_avatar = ft.GestureDetector(
            mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=lambda _: (
                self.app.show_friend_profile(self.owner.current_friend)
                if hasattr(self.app, "show_friend_profile")
                else None
            ),
            content=T.avatar_circle(
                self.app.get_avatar_for_name(self.owner.current_friend),
                T.AVATAR_MD,
                online=online,
            ),
        )
        self.owner._header_name = ft.Text(
            self.owner.current_friend,
            size=T.FS_TITLE,
            weight=ft.FontWeight.BOLD,
        )
        self.owner._header_status = ft.Text(
            "在线" if online else "离线",
            size=T.FS_CAPTION,
            color=ft.Colors.GREEN_400 if online else ft.Colors.ON_SURFACE_VARIANT,
            weight=ft.FontWeight.BOLD if online else ft.FontWeight.NORMAL,
        )

    def _build_input(self):
        return ft.TextField(
            hint_text="输入消息…",
            expand=True,
            autofocus=True,
            border_radius=22,
            border_color=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            content_padding=T.pad_symmetric(horizontal=16, vertical=10),
            on_submit=self.owner._on_send,
        )

    def _build_attach_button(self):
        return ft.IconButton(
            icon=ft.Icons.ADD_ROUNDED,
            icon_color=ft.Colors.DEEP_PURPLE_400,
            icon_size=24,
            on_click=self.owner._pick_file,
            tooltip="发送文件",
        )

    def _build_send_button(self):
        return ft.IconButton(
            icon=ft.Icons.SEND_ROUNDED,
            icon_color=ft.Colors.WHITE,
            icon_size=18,
            bgcolor=ft.Colors.DEEP_PURPLE_500,
            on_click=self.owner._on_send,
            style=ft.ButtonStyle(
                shape=ft.CircleBorder(),
                padding=T.pad_all(12),
            ),
            tooltip="发送消息",
        )

    def _build_header(self):
        return ft.Container(
            content=ft.Row(
                [
                    ft.IconButton(
                        icon=ft.Icons.ARROW_BACK_IOS_NEW_ROUNDED,
                        icon_size=16,
                        on_click=self.owner._back_to_list,
                        tooltip="返回消息列表",
                    ),
                    self.owner._header_avatar,
                    ft.Column(
                        [
                            self.owner._header_name,
                            self.owner._header_status,
                        ],
                        spacing=1,
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                    ft.Container(expand=True),
                    ft.IconButton(
                        icon=ft.Icons.DELETE_SWEEP_ROUNDED,
                        icon_color=ft.Colors.ON_SURFACE_VARIANT,
                        on_click=lambda _e: self.owner._confirm_clear(),
                        tooltip="清空聊天记录",
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=T.pad_symmetric(horizontal=T.SP_SM, vertical=T.SP_SM),
            border=ft.Border(
                bottom=ft.BorderSide(
                    1,
                    ft.Colors.with_opacity(0.06, ft.Colors.ON_SURFACE),
                )
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            margin=T.pad_only(left=-T.SP_LG, right=-T.SP_LG, top=-T.SP_LG),
        )
