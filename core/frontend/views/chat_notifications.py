"""System notification panel for ChatView."""

import re
import threading

import flet as ft

from .. import theme as T


class ChatNotificationsPanel:
    """Render and handle the system-notification tab."""

    def __init__(self, owner):
        self.owner = owner
        self.app = owner.app
        self.page = owner.page
        self.column = None

    def build(self):
        self.column = ft.Column(spacing=T.SP_SM, expand=True, scroll=ft.ScrollMode.AUTO)
        self.owner._notifications_col = self.column

        return ft.Column(
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
                                    on_click=self.mark_all_read,
                                    style=ft.ButtonStyle(
                                        padding=T.pad_symmetric(horizontal=8, vertical=4)
                                    ),
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.DELETE_SWEEP_ROUNDED,
                                    icon_color=ft.Colors.RED_400,
                                    tooltip="清空通知",
                                    on_click=self.clear_notifications,
                                ),
                            ],
                            spacing=0,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                self.column,
            ],
            spacing=T.SP_SM,
            expand=True,
        )

    def render(self):
        if self.column is None:
            return

        with self.owner._lock:
            self.column.controls.clear()
            notifications = self.app.get_system_notifications()
            self._update_tab_label(notifications)

            if not notifications:
                self.column.controls.append(self._empty_state())
            else:
                for notification in notifications:
                    self.column.controls.append(self._notification_card(notification))

            if self.page:
                self.page.update()

    def mark_all_read(self, _e=None):
        self.app.mark_all_notifications_read()
        self.render()

    def clear_notifications(self, _e=None):
        self.app.clear_system_notifications()
        self.render()

    def _update_tab_label(self, notifications):
        unread_count = sum(1 for item in notifications if item.get("is_read", 0) == 0)
        tab_bar = getattr(self.owner, "_tab_bar", None)
        if not tab_bar:
            return
        if unread_count > 0:
            tab_bar.tabs[1].label = f"系统通知 ({unread_count})"
            tab_bar.tabs[1].icon = ft.Icons.NOTIFICATION_IMPORTANT_ROUNDED
        else:
            tab_bar.tabs[1].label = "系统通知"
            tab_bar.tabs[1].icon = ft.Icons.NOTIFICATIONS_ROUNDED

    def _empty_state(self):
        return ft.Container(
            content=ft.Column(
                [
                    ft.Icon(
                        ft.Icons.NOTIFICATIONS_NONE_ROUNDED,
                        size=48,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                        opacity=0.5,
                    ),
                    ft.Text(
                        "暂无系统通知",
                        size=T.FS_BODY,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                        weight=ft.FontWeight.W_500,
                    ),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=T.SP_SM,
            ),
            alignment=ft.alignment.Alignment.CENTER,
            expand=True,
            padding=T.SP_2XL,
        )

    def _notification_card(self, notification):
        is_read = notification.get("is_read", 0) == 1
        category = notification.get("category", "info")
        icon, icon_color = self._category_icon(category)
        action_row = self._action_row(notification, category)

        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(icon, color=icon_color, size=24),
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text(
                                        notification.get("title", ""),
                                        size=T.FS_BODY,
                                        weight=ft.FontWeight.BOLD,
                                    ),
                                    ft.Text(
                                        notification.get("timestamp", "")[-8:]
                                        if len(notification.get("timestamp", "")) >= 8
                                        else "",
                                        size=T.FS_CAPTION,
                                        color=ft.Colors.ON_SURFACE_VARIANT,
                                    ),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            ),
                            ft.Text(
                                notification.get("content", ""),
                                size=T.FS_BODY,
                                color=(
                                    ft.Colors.ON_SURFACE
                                    if not is_read
                                    else ft.Colors.ON_SURFACE_VARIANT
                                ),
                                weight=(
                                    ft.FontWeight.NORMAL
                                    if is_read
                                    else ft.FontWeight.W_500
                                ),
                            ),
                            action_row,
                        ],
                        spacing=T.SP_XS,
                        expand=True,
                    ),
                ],
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=T.SP_MD,
            border_radius=T.R_SM,
            bgcolor=(
                ft.Colors.SURFACE_CONTAINER_HIGH
                if is_read
                else ft.Colors.with_opacity(0.08, ft.Colors.DEEP_PURPLE)
            ),
            border=T.border_all(1, ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE)),
        )

    def _category_icon(self, category):
        if category == "success":
            return ft.Icons.CHECK_CIRCLE_ROUNDED, ft.Colors.GREEN_400
        if category == "warning":
            return ft.Icons.WARNING_ROUNDED, ft.Colors.ORANGE_400
        if category == "error":
            return ft.Icons.ERROR_ROUNDED, ft.Colors.RED_400
        if category == "friend_request":
            return ft.Icons.PERSON_ADD_ROUNDED, ft.Colors.DEEP_PURPLE_400
        if category == "file_offer":
            return ft.Icons.FOLDER_ZIP_ROUNDED, ft.Colors.BLUE_400
        return ft.Icons.INFO_ROUNDED, ft.Colors.BLUE_400

    def _action_row(self, notification, category):
        if category == "friend_request":
            return self._friend_request_action(notification)
        if category == "file_offer":
            return self._file_offer_action(notification)
        return ft.Container()

    def _friend_request_action(self, notification):
        match = re.search(r"「([^」]+)」", notification.get("content", ""))
        sender_name = match.group(1) if match else ""
        request = self.app.friend_db.get_friend_request(name=sender_name) if sender_name else None
        is_pending = bool(request and request.get("status") == "pending")

        if not is_pending:
            status_text = "已同意"
            text_color = ft.Colors.GREEN_400
            if request and request.get("status") == "rejected":
                status_text = "已忽略"
                text_color = ft.Colors.ON_SURFACE_VARIANT
            return self._status_text(status_text, text_color)

        return ft.Container(
            content=ft.Row(
                [
                    ft.ElevatedButton(
                        "同意并添加",
                        icon=ft.Icons.CHECK_ROUNDED,
                        on_click=self._accept_friend_request(sender_name, request, notification["id"]),
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
                        on_click=self._ignore_friend_request(request, notification["id"]),
                        style=ft.ButtonStyle(
                            padding=T.pad_symmetric(horizontal=12, vertical=6)
                        ),
                        height=32,
                    ),
                ],
                spacing=T.SP_SM,
            ),
            margin=ft.Margin.only(top=T.SP_SM),
        )

    def _accept_friend_request(self, sender_name, request, notification_id):
        def on_accept_click(_e):
            self.app.friend_db.add_friend(
                name=sender_name,
                ip=request["ip"],
                port=request["port"],
                tags=request.get("tags", []),
                bio=request.get("bio", ""),
                category="朋友",
                user_id=request.get("user_id", ""),
                status="accepted",
            )
            self.app.friend_db.set_friend_request_status(
                "accepted",
                user_id=request.get("user_id", ""),
                name=sender_name,
                ip=request["ip"],
                port=request["port"],
            )
            threading.Thread(
                target=self.app.message_service.send_friend_accept,
                args=(sender_name, request["ip"]),
                daemon=True,
            ).start()
            self.app.mark_notification_read(notification_id)
            self.app.views["friends"].refresh()
            if "discover" in self.app.views:
                self.app.views["discover"].refresh_online()
            self.render()

        return on_accept_click

    def _ignore_friend_request(self, request, notification_id):
        def on_ignore_click(_e):
            self.app.friend_db.set_friend_request_status(
                "rejected",
                user_id=request.get("user_id", ""),
                name=request["name"],
                ip=request["ip"],
                port=request["port"],
            )
            self.app.mark_notification_read(notification_id)
            self.render()

        return on_ignore_click

    def _file_offer_action(self, notification):
        match = re.search(r"\[文件ID:([^\]]+)\]", notification.get("content", ""))
        file_id = match.group(1) if match else ""
        is_pending = False
        if file_id and self.app.message_service:
            is_pending = file_id in self.app.message_service._pending_file_offers

        if not is_pending:
            return self._file_offer_status(file_id)

        return ft.Container(
            content=ft.Row(
                [
                    ft.ElevatedButton(
                        "同意并接收",
                        icon=ft.Icons.CHECK_ROUNDED,
                        on_click=self._accept_file_offer(file_id, notification["id"]),
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
                        on_click=self._decline_file_offer(file_id, notification["id"]),
                        style=ft.ButtonStyle(
                            padding=T.pad_symmetric(horizontal=12, vertical=6)
                        ),
                        height=32,
                    ),
                ],
                spacing=T.SP_SM,
            ),
            margin=ft.Margin.only(top=T.SP_SM),
        )

    def _accept_file_offer(self, file_id, notification_id):
        def on_file_accept_click(_e):
            self.app.message_service.accept_file_offer(file_id)
            self.app.mark_notification_read(notification_id)
            self.owner._pending_file_offers.pop(file_id, None)
            self.render()
            if self.owner.current_friend:
                self.owner.reload_current()

        return on_file_accept_click

    def _decline_file_offer(self, file_id, notification_id):
        def on_file_decline_click(_e):
            self.app.message_service.decline_file_offer(file_id)
            self.app.mark_notification_read(notification_id)
            self.owner._pending_file_offers.pop(file_id, None)
            self.render()
            if self.owner.current_friend:
                self.owner.reload_current()

        return on_file_decline_click

    def _file_offer_status(self, file_id):
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
            elif file_id in self.owner._closed_file_transfers:
                status_text = "已拒绝"
                text_color = ft.Colors.RED_400

        return self._status_text(status_text, text_color)

    def _status_text(self, text, color):
        return ft.Container(
            content=ft.Text(text, size=12, color=color, weight=ft.FontWeight.BOLD),
            margin=ft.Margin.only(top=T.SP_XS),
        )
