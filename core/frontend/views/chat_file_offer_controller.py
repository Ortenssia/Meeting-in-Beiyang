"""Inline file-offer widgets for ChatView."""

import os
import time

import flet as ft

from .. import theme as T


class ChatFileOfferController:
    """Queue, render, accept, and decline inline file offers."""

    def __init__(self, owner):
        self.owner = owner
        self.app = owner.app

    @staticmethod
    def format_size(size):
        for unit in ("B", "KiB", "MiB", "GiB"):
            if size < 1024 or unit == "GiB":
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024

    def add_file_offer(self, from_name, filename, size, file_id):
        """Queue an inline file-offer widget for *from_name*."""
        owner = self.owner
        if file_id in owner._pending_file_offers:
            return
        owner._pending_file_offers[file_id] = {
            "from_name": from_name,
            "filename": filename,
            "size": size,
        }
        if owner.current_friend == from_name and not owner.is_group and owner._msg_list is not None:
            self.render_file_offer(file_id)
        if owner.page:
            owner.page.update()

    def render_file_offers_for(self, friend_name):
        owner = self.owner
        for file_id, offer in list(owner._pending_file_offers.items()):
            if offer["from_name"] == friend_name:
                self.render_file_offer(file_id)

    def render_file_offer(self, file_id):
        """Insert an inline file-offer bubble into the current chat."""
        owner = self.owner
        offer = owner._pending_file_offers.get(file_id)
        if not offer or offer.get("widget"):
            return
        from_name = offer["from_name"]
        filename = offer["filename"]
        size = offer["size"]

        row = None

        def accept(_e):
            content = owner._file_message_content("正在接收文件", filename, "", file_id)
            if row and row in owner._msg_list.controls:
                owner._replace_bubble(
                    row,
                    from_name,
                    content,
                    time.strftime("%H:%M:%S", time.localtime()),
                    is_self=False,
                )
            owner._pending_file_offers.pop(file_id, None)
            self.app.message_service.accept_file_offer(file_id)
            if owner.page:
                owner.page.update()

        def decline(_e):
            content = owner._file_message_content("已拒绝接收", filename, "", file_id)
            if row and row in owner._msg_list.controls:
                owner._replace_bubble(
                    row,
                    from_name,
                    content,
                    time.strftime("%H:%M:%S", time.localtime()),
                    is_self=False,
                )
            owner._pending_file_offers.pop(file_id, None)
            owner._mark_file_transfer_closed(file_id)
            self.app.message_service.decline_file_offer(file_id)
            if owner.page:
                owner.page.update()

        def delete_offer(_e):
            owner._delete_message_row(row, msg_id=file_id, file_id=file_id)

        file_icon, icon_bg = self._file_icon(filename)
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
                            f"📁 请求发送文件 · {self.format_size(size)}",
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
                                    content=ft.Row(
                                        [
                                            ft.Icon(
                                                ft.Icons.DELETE_ROUNDED,
                                                size=14,
                                                color=ft.Colors.RED_400,
                                            ),
                                            ft.Text("删除此条", size=12),
                                        ],
                                        spacing=6,
                                    ),
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
                ),
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
                top_left=16,
                top_right=16,
                bottom_right=16,
                bottom_left=4,
            ),
            padding=T.pad_symmetric(horizontal=12, vertical=12),
            shadow=ft.BoxShadow(
                blur_radius=8,
                color=ft.Colors.with_opacity(0.04, ft.Colors.BLACK),
                offset=ft.Offset(0, 2),
            ),
            border=T.border_all(1, ft.Colors.with_opacity(0.15, ft.Colors.DEEP_PURPLE_400)),
        )
        avatar = ft.GestureDetector(
            mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=lambda _: self.app.show_friend_profile(from_name)
            if hasattr(self.app, "show_friend_profile")
            else None,
            content=T.avatar_circle(self.app.get_avatar_for_name(from_name), T.AVATAR_SM),
        )

        row = ft.Row(
            [avatar, bubble],
            alignment=ft.MainAxisAlignment.START,
            vertical_alignment=ft.CrossAxisAlignment.END,
        )
        offer["widget"] = row
        owner._msg_list.controls.append(row)
        owner._scroll_bottom()
        if owner.page:
            owner.page.update()

    @staticmethod
    def _file_icon(filename):
        ext = os.path.splitext(filename)[1].lower()
        if ext in (".zip", ".rar", ".7z", ".tar", ".gz"):
            return ft.Icons.FOLDER_ZIP_ROUNDED, ft.Colors.AMBER_500
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
            return ft.Icons.IMAGE_ROUNDED, ft.Colors.BLUE_500
        if ext in (".mp4", ".avi", ".mkv", ".mov", ".flv"):
            return ft.Icons.VIDEO_LIBRARY_ROUNDED, ft.Colors.RED_500
        if ext in (".mp3", ".wav", ".flac", ".ogg", ".m4a"):
            return ft.Icons.AUDIO_FILE_ROUNDED, ft.Colors.TEAL_500
        if ext in (".txt", ".md", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"):
            return ft.Icons.ARTICLE_ROUNDED, ft.Colors.BLUE_GREY_500
        return ft.Icons.INSERT_DRIVE_FILE_ROUNDED, ft.Colors.DEEP_PURPLE_500
