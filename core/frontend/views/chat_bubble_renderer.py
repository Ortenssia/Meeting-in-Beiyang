"""Message bubble rendering for ChatView."""

import os
import threading
import time
import uuid

import flet as ft

from .. import theme as T
from .chat_file_offer_controller import ChatFileOfferController


class ChatBubbleRenderer:
    """Build and append chat message rows for text, code, and file messages."""

    def __init__(self, owner):
        self.owner = owner
        self.app = owner.app

    def append_bubble(self, from_name, content, timestamp, is_self=False, msg_id=""):
        owner = self.owner
        bubble_content = None

        is_file_msg = False
        file_status = ""
        filename = ""
        transfer_id = ""
        file_id = ""
        row = None

        def delete_current(_e=None):
            owner._delete_message_row(row, msg_id=msg_id, file_id=file_id)

        if owner._is_file_message_content(content):
            idx = content.find("]")
            tag = content[1:idx]
            file_info = owner._file_info_from_content(content)
            is_file_msg = True
            filename = file_info["filename"]
            file_path = file_info["path"]
            transfer_id = file_info["transfer_id"]
            file_status = tag

        if is_file_msg:
            file_card_width = owner._file_bubble_width()
            file_text_width = max(100, file_card_width - (112 if owner._is_mobile_ui() else 140))
            file_id = transfer_id
            if self.app.message_service:
                with self.app.message_service._file_lock:
                    file_id = file_id or self.app.message_service.file_transfer.active_file_id_for(filename)

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

            cached_state = owner._transfer_states.get(file_id, {})
            if cached_state and not cached_state.get("final"):
                completed = int(cached_state.get("completed", 0) or 0)
                total = int(cached_state.get("total", 0) or 0)
                pb_val = min(1.0, completed / total) if total else 0.0
                percent = pb_val * 100
                direction = "发送" if cached_state.get("sending") else "接收"
                status_text = f"{direction}中 · {percent:.0f}%"
                detail_text = (
                    f"{owner._format_bytes(completed)} / {owner._format_bytes(total)}"
                    if total
                    else "等待对端/网络"
                )

            def open_file():
                def worker():
                    if os.path.exists(file_path):
                        try:
                            owner._open_file_with_os(file_path)
                        except Exception as exc:
                            owner.show_toast(f"打开文件失败: {exc}")
                    else:
                        owner.show_toast("文件不存在或未在此电脑接收")

                threading.Thread(target=worker, daemon=True).start()

            def open_folder():
                def worker():
                    folder_path = os.path.dirname(file_path) or self.app.get_receive_dir()
                    if os.path.exists(file_path):
                        try:
                            owner._open_folder_with_os(file_path, folder_path)
                        except Exception:
                            try:
                                owner._open_file_with_os(folder_path)
                            except Exception as exc:
                                owner.show_toast(f"打开文件夹失败: {exc}")
                    else:
                        if os.path.exists(folder_path):
                            try:
                                owner._open_file_with_os(folder_path)
                            except Exception as exc:
                                owner.show_toast(f"打开文件夹失败: {exc}")
                        else:
                            owner.show_toast("接收文件夹不存在")

                threading.Thread(target=worker, daemon=True).start()

            def copy_path():
                try:
                    if owner.page:
                        owner.page.set_clipboard(file_path)
                        owner.show_toast("文件路径已复制")
                except Exception:
                    pass

            def decompress_zip():
                def worker():
                    import zipfile

                    if os.path.exists(file_path):
                        try:
                            dest_dir = os.path.dirname(file_path)
                            with zipfile.ZipFile(file_path, "r") as zip_ref:
                                zip_ref.extractall(dest_dir)
                            owner.show_toast("解压缩成功！🎉")
                        except Exception as exc:
                            owner.show_toast(f"解压失败: {exc}")
                    else:
                        owner.show_toast("文件不存在或未下载完成")

                threading.Thread(target=worker, daemon=True).start()

            def retry_file():
                if not is_self:
                    return
                if not file_path or not os.path.exists(file_path):
                    owner.show_toast("原文件不存在，无法续传")
                    return
                target_friend = owner.current_friend
                retry_id = str(uuid.uuid4())
                pending_content = owner._file_message_content(
                    "正在发送文件",
                    filename,
                    file_path,
                    retry_id,
                )
                retry_row = owner._replace_bubble(
                    row,
                    self.app.device_name,
                    pending_content,
                    time.strftime("%H:%M:%S", time.localtime()),
                    is_self=True,
                )
                if owner.page:
                    owner.page.update()

                def worker():
                    ok = False
                    if target_friend and not owner.is_group:
                        ok = self.app.send_file_to_friend(target_friend, file_path, retry_id)
                    status = "文件" if ok else "文件发送失败"
                    done_content = owner._file_message_content(status, filename, file_path, retry_id)
                    owner._replace_bubble(
                        retry_row,
                        self.app.device_name,
                        done_content,
                        time.strftime("%H:%M:%S", time.localtime()),
                        is_self=True,
                    )
                    owner._transfer_widgets.pop(retry_id, None)
                    if owner.page:
                        owner.page.update()

                threading.Thread(target=worker, daemon=True).start()

            file_icon, icon_bg = ChatFileOfferController._file_icon(filename)
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
                widget = owner._transfer_widgets.get(file_id)
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
                if owner.page:
                    owner.page.update()

            pause_button = ft.IconButton(
                icon=ft.Icons.PAUSE_ROUNDED,
                icon_color=ft.Colors.ON_SURFACE_VARIANT,
                icon_size=16,
                tooltip="暂停传输",
                on_click=lambda _: toggle_pause(),
                visible=not owner._is_mobile_ui(),
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
                            pause_button
                            if ("正在" in file_status and file_id and is_self)
                            else ft.Container(),
                            ft.IconButton(
                                icon=ft.Icons.CANCEL_OUTLINED,
                                icon_color=ft.Colors.RED_400,
                                icon_size=16,
                                tooltip="取消",
                                on_click=lambda _, fid=file_id: self.app.cancel_file_transfer(fid)
                                if fid
                                else None,
                                visible=not owner._is_mobile_ui(),
                            )
                            if ("正在" in file_status and file_id)
                            else ft.Container(),
                            ft.IconButton(
                                icon=ft.Icons.REFRESH_ROUNDED,
                                icon_color=ft.Colors.DEEP_PURPLE_400,
                                icon_size=16,
                                tooltip="重试/续传",
                                on_click=lambda _e: retry_file(),
                            )
                            if ("失败" in file_status and is_self)
                            else ft.Container(),
                            ft.PopupMenuButton(
                                items=[
                                    ft.PopupMenuItem(
                                        content=ft.Row(
                                            [
                                                ft.Icon(
                                                    ft.Icons.CANCEL_OUTLINED,
                                                    size=14,
                                                    color=ft.Colors.RED_400,
                                                ),
                                                ft.Text("取消传输", size=12),
                                            ],
                                            spacing=6,
                                        ),
                                        on_click=lambda _, fid=file_id: self.app.cancel_file_transfer(fid)
                                        if fid
                                        else None,
                                        visible=bool("正在" in file_status and file_id),
                                    ),
                                    ft.PopupMenuItem(
                                        content=ft.Row(
                                            [
                                                ft.Icon(
                                                    ft.Icons.OPEN_IN_NEW_ROUNDED,
                                                    size=14,
                                                    color=ft.Colors.DEEP_PURPLE_400,
                                                ),
                                                ft.Text("打开文件", size=12),
                                            ],
                                            spacing=6,
                                        ),
                                        on_click=lambda _: open_file(),
                                    ),
                                    ft.PopupMenuItem(
                                        content=ft.Row(
                                            [
                                                ft.Icon(
                                                    ft.Icons.FOLDER_OPEN_ROUNDED,
                                                    size=14,
                                                    color=ft.Colors.DEEP_PURPLE_400,
                                                ),
                                                ft.Text("打开文件夹", size=12),
                                            ],
                                            spacing=6,
                                        ),
                                        on_click=lambda _: open_folder(),
                                    ),
                                    ft.PopupMenuItem(
                                        content=ft.Row(
                                            [
                                                ft.Icon(
                                                    ft.Icons.COPY_ALL_ROUNDED,
                                                    size=14,
                                                    color=ft.Colors.DEEP_PURPLE_400,
                                                ),
                                                ft.Text("复制路径", size=12),
                                            ],
                                            spacing=6,
                                        ),
                                        on_click=lambda _: copy_path(),
                                    ),
                                    ft.PopupMenuItem(
                                        content=ft.Row(
                                            [
                                                ft.Icon(
                                                    ft.Icons.UNARCHIVE_ROUNDED,
                                                    size=14,
                                                    color=ft.Colors.DEEP_PURPLE_400,
                                                ),
                                                ft.Text("解压 ZIP", size=12),
                                            ],
                                            spacing=6,
                                        ),
                                        on_click=lambda _: decompress_zip(),
                                    )
                                    if filename.lower().endswith(".zip")
                                    else ft.PopupMenuItem(visible=False),
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
                                        on_click=delete_current,
                                    ),
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
                    ft.Container(
                        content=progress_bar,
                        margin=ft.Margin.only(top=6),
                    )
                    if "正在" in file_status
                    else ft.Container(),
                ],
                spacing=0,
                tight=True,
            )
        else:
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
                def copy_code():
                    if owner.page:
                        owner.page.set_clipboard(code_content)
                        owner.show_toast("代码已复制到剪贴板 📋")

                bubble_content = ft.Column(
                    [
                        ft.Container(
                            content=ft.Column(
                                [
                                    ft.Row(
                                        [
                                            ft.Text(
                                                "Python 代码 🐍",
                                                size=12,
                                                color=ft.Colors.DEEP_PURPLE_200,
                                                weight=ft.FontWeight.BOLD,
                                            ),
                                            ft.IconButton(
                                                icon=ft.Icons.COPY_ALL_ROUNDED,
                                                icon_size=16,
                                                icon_color=ft.Colors.DEEP_PURPLE_200,
                                                tooltip="复制代码",
                                                on_click=lambda _: copy_code(),
                                            ),
                                        ],
                                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                        height=24,
                                    ),
                                    ft.Divider(
                                        height=1,
                                        color=ft.Colors.with_opacity(0.1, ft.Colors.ON_SURFACE),
                                    ),
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
                            color=ft.Colors.with_opacity(0.7, ft.Colors.WHITE)
                            if is_self
                            else ft.Colors.ON_SURFACE_VARIANT,
                            text_align=ft.TextAlign.RIGHT,
                        ),
                    ],
                    spacing=T.SP_XS,
                )
            else:
                bubble_content = ft.Column(
                    [
                        ft.Text(
                            content,
                            size=T.FS_TEXT,
                            color=ft.Colors.WHITE if is_self else ft.Colors.ON_SURFACE,
                            selectable=True,
                            weight=ft.FontWeight.W_500,
                        ),
                        ft.Text(
                            timestamp,
                            size=T.FS_CAPTION,
                            color=ft.Colors.with_opacity(0.7, ft.Colors.WHITE)
                            if is_self
                            else ft.Colors.ON_SURFACE_VARIANT,
                            text_align=ft.TextAlign.RIGHT,
                        ),
                    ],
                    spacing=4,
                )

        if is_file_msg:
            bubble_bg = ft.Colors.SURFACE_CONTAINER_LOW
            bubble_border = T.border_all(
                1,
                ft.Colors.with_opacity(
                    0.15,
                    ft.Colors.DEEP_PURPLE_400 if is_self else ft.Colors.ON_SURFACE,
                ),
            )
        else:
            bubble_bg = None if is_self else ft.Colors.SURFACE_CONTAINER_HIGH
            bubble_border = (
                T.border_all(1, ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE))
                if not is_self
                else None
            )

        bubble = ft.Container(
            content=bubble_content,
            width=file_card_width if is_file_msg else None,
            gradient=T.GRADIENT_PRIMARY if is_self and not is_file_msg else None,
            bgcolor=bubble_bg,
            border_radius=T.radius_only(
                top_left=16,
                top_right=16,
                bottom_right=4 if is_self else 16,
                bottom_left=16 if is_self else 4,
            ),
            padding=T.pad_symmetric(horizontal=12, vertical=12),
            shadow=ft.BoxShadow(
                blur_radius=8,
                color=ft.Colors.with_opacity(0.04, ft.Colors.BLACK),
                offset=ft.Offset(0, 2),
            ),
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
            on_tap=lambda _: self.app.show_friend_profile(from_name)
            if hasattr(self.app, "show_friend_profile")
            else None,
            content=T.avatar_circle(self.app.get_avatar_for_name(from_name), T.AVATAR_SM),
        )
        row_menu = None
        if not is_file_msg:
            row_menu = ft.PopupMenuButton(
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
            if not owner._is_mobile_ui():
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
            cached_state = owner._transfer_states.get(file_id, {})
            owner._transfer_widgets[file_id] = {
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
            owner._start_transfer_watchdog(file_id)

        owner._msg_list.controls.append(row)
        owner._scroll_bottom()
        return row
