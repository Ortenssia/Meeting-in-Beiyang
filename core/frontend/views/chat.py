"""Chat view: chat list + chat window with bubbles and file transfer."""
import os
import time
import threading

import flet as ft

from core.backend.shared.file_message import decode_file_message, encode_file_message

from .. import theme as T


class ChatView:
    def __init__(self, app):
        self.app = app
        self.page = app.page
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
        self.file_picker = getattr(app, "chat_file_picker", None) or ft.FilePicker()
        self.compress_checkbox = ft.Checkbox(
            label="压缩发送",
            value=False,
            fill_color=ft.Colors.DEEP_PURPLE_400,
        )

    # -- build -------------------------------------------------------------

    def build(self):
        if self.current_friend:
            return self._build_window()
        return self._build_list()

    def _build_list(self):
        self._list_root = ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("消息列表", size=T.FS_HEADER, weight=ft.FontWeight.W_800),
                        ft.IconButton(
                            icon=ft.Icons.GROUP_ADD_ROUNDED,
                            icon_color=ft.Colors.DEEP_PURPLE_400,
                            tooltip="发起群聊",
                            on_click=self._on_create_group,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Column(spacing=T.SP_SM, expand=True, scroll=ft.ScrollMode.AUTO),
            ],
            spacing=T.SP_SM, expand=True,
        )
        self._render_list()
        return self._list_root

    def _build_window(self):
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

        self._window_root = ft.Column(
            [
                chat_header,
                ft.Container(
                    content=self._msg_list,
                    padding=T.pad_symmetric(vertical=10),
                    expand=True,
                ),
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Row([self.compress_checkbox], spacing=5),
                            ft.Row([attach_btn, self._input, send_btn], spacing=T.SP_SM),
                        ],
                        spacing=2,
                        tight=True,
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
        if not self.current_friend or not self._header_avatar:
            return
            
        if self.is_group:
            group = self.app.friend_db.get_group(self.current_group_id)
            member_count = len(group.get("members", [])) if group else 0
            self._header_avatar = ft.GestureDetector(
                mouse_cursor=ft.MouseCursor.CLICK,
                on_tap=lambda _: self.show_group_settings(self.current_group_id),
                content=T.avatar_circle("group", T.AVATAR_MD)
            )
            self._header_status.value = f"{member_count} 个成员"
            self._header_status.color = ft.Colors.ON_SURFACE_VARIANT
            self._header_status.weight = ft.FontWeight.NORMAL
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
            self._header_status.value = "在线" if online else "离线"
            self._header_status.color = ft.Colors.GREEN_400 if online else ft.Colors.ON_SURFACE_VARIANT
            self._header_status.weight = ft.FontWeight.BOLD if online else ft.FontWeight.NORMAL
            
        # Rebuild chat window header controls
        header_row = self._window_root.controls[0].content
        header_row.controls[1] = self._header_avatar
        if self.page:
            self.page.update()

    # -- chat list ---------------------------------------------------------

    def _render_list(self):
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
                    alignment=ft.Alignment.CENTER, 
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
            file_info = self._file_info_from_content(last_msg) if "文件" in parts[0] else None
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
                self._append_bubble(sender, content, ts, is_self=is_self)
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
                self._append_bubble(from_name, content, ts, is_self=is_self)
        self._scroll_bottom()

    def _append_bubble(self, from_name, content, timestamp, is_self=False):
        bubble_content = None
        
        # Check if the message is a file transfer representation
        is_file_msg = False
        file_status = ""
        filename = ""
        
        if content.startswith("[") and "]" in content:
            idx = content.find("]")
            tag = content[1:idx]
            if "文件" in tag:
                file_info = self._file_info_from_content(content)
                is_file_msg = True
                filename = file_info["filename"]
                file_path = file_info["path"]
                file_status = tag

        if is_file_msg:
            # Resolve file_id for active cancel action
            file_id = ""
            if self.app.message_service:
                with self.app.message_service._file_lock:
                    file_id = self.app.message_service.file_transfer.active_file_id_for(filename)
            
            # Styled File Card Redesign
            card_color = ft.Colors.with_opacity(0.08, ft.Colors.WHITE if is_self else ft.Colors.DEEP_PURPLE)
            icon_color = ft.Colors.WHITE if is_self else ft.Colors.DEEP_PURPLE_400
            status_text = file_status
            pb_val = 0.0
            pb_color = ft.Colors.WHITE if is_self else ft.Colors.BLUE_400
            
            if "正在" in file_status:
                pb_val = None  # Indeterminate progress
                status_text = "📁 " + file_status
            elif "失败" in file_status:
                pb_val = 1.0
                pb_color = ft.Colors.RED_400
                icon_color = ft.Colors.RED_400
                status_text = "❌ " + file_status
            else:
                pb_val = 1.0
                pb_color = ft.Colors.GREEN_400 if not is_self else ft.Colors.WHITE
                icon_color = ft.Colors.GREEN_400 if not is_self else ft.Colors.WHITE
                status_text = "✅ " + file_status

            def open_file():
                def worker():
                    if os.path.exists(file_path):
                        try:
                            os.startfile(file_path)
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
                            import subprocess
                            subprocess.run(f'explorer /select,"{file_path.replace("/", "\\")}"')
                        except Exception:
                            try:
                                os.startfile(folder_path)
                            except Exception as e:
                                self.show_toast(f"打开文件夹失败: {e}")
                    else:
                        if os.path.exists(folder_path):
                            try:
                                os.startfile(folder_path)
                            except Exception as e:
                                self.show_toast(f"打开文件夹失败: {e}")
                        else:
                            self.show_toast("接收文件夹不存在")
                import threading
                threading.Thread(target=worker, daemon=True).start()

            def copy_path():
                def worker():
                    if self.page:
                        self.page.set_clipboard(file_path)
                        self.show_toast("文件路径已复制")
                import threading
                threading.Thread(target=worker, daemon=True).start()

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
                pending_content = self._file_message_content(
                    "正在发送文件", filename, file_path
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
                        ok = self.app.send_file_to_friend(target_friend, file_path)
                    status = "文件" if ok else "文件发送失败"
                    done_content = self._file_message_content(status, filename, file_path)
                    self._replace_bubble(
                        retry_row,
                        self.app.device_name,
                        done_content,
                        time.strftime("%H:%M:%S", time.localtime()),
                        is_self=True,
                    )
                    if self.page:
                        self.page.update()

                threading.Thread(target=worker, daemon=True).start()

            bubble_content = ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.FILE_PRESENT_ROUNDED, color=icon_color, size=32),
                            ft.Column(
                                [
                                    ft.Text(
                                        filename, 
                                        size=T.FS_TEXT, 
                                        weight=ft.FontWeight.BOLD, 
                                        color=ft.Colors.WHITE if is_self else ft.Colors.ON_SURFACE,
                                        overflow=ft.TextOverflow.ELLIPSIS, 
                                        max_lines=1,
                                        width=150
                                    ),
                                    ft.Text(
                                        status_text, 
                                        size=T.FS_CAPTION, 
                                        color=ft.Colors.with_opacity(0.7, ft.Colors.WHITE) if is_self else ft.Colors.ON_SURFACE_VARIANT
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.CANCEL_OUTLINED,
                                icon_color=ft.Colors.RED_400 if is_self else ft.Colors.RED_300,
                                icon_size=18,
                                tooltip="取消传输",
                                on_click=lambda _, fid=file_id: self.app.cancel_file_transfer(fid) if fid else None,
                            ) if ("正在" in file_status and file_id) else ft.Container(),
                            ft.IconButton(
                                icon=ft.Icons.REFRESH_ROUNDED,
                                icon_color=ft.Colors.WHITE if is_self else ft.Colors.DEEP_PURPLE_400,
                                icon_size=18,
                                tooltip="重试/续传",
                                on_click=lambda _e: retry_file(),
                            ) if ("失败" in file_status and is_self) else ft.Container(),
                            ft.PopupMenuButton(
                                items=[
                                    ft.PopupMenuItem(
                                        content=ft.Row(
                                            [
                                                ft.Icon(ft.Icons.OPEN_IN_NEW_ROUNDED, size=16, color=ft.Colors.DEEP_PURPLE_400),
                                                ft.Text("打开文件", size=13, weight=ft.FontWeight.W_500),
                                            ],
                                            spacing=10,
                                        ),
                                        on_click=lambda _: open_file()
                                    ),
                                    ft.PopupMenuItem(
                                        content=ft.Row(
                                            [
                                                ft.Icon(ft.Icons.FOLDER_OPEN_ROUNDED, size=16, color=ft.Colors.DEEP_PURPLE_400),
                                                ft.Text("打开所在文件夹", size=13, weight=ft.FontWeight.W_500),
                                            ],
                                            spacing=10,
                                        ),
                                        on_click=lambda _: open_folder()
                                    ),
                                    ft.PopupMenuItem(
                                        content=ft.Row(
                                            [
                                                ft.Icon(ft.Icons.COPY_ALL_ROUNDED, size=16, color=ft.Colors.DEEP_PURPLE_400),
                                                ft.Text("复制文件路径", size=13, weight=ft.FontWeight.W_500),
                                            ],
                                            spacing=10,
                                        ),
                                        on_click=lambda _: copy_path()
                                    ),
                                    ft.PopupMenuItem(
                                        content=ft.Row(
                                            [
                                                ft.Icon(ft.Icons.UNARCHIVE_ROUNDED, size=16, color=ft.Colors.DEEP_PURPLE_400),
                                                ft.Text("解压到当前目录", size=13, weight=ft.FontWeight.W_500),
                                            ],
                                            spacing=10,
                                        ),
                                        on_click=lambda _: decompress_zip()
                                    ) if filename.lower().endswith(".zip") else ft.PopupMenuItem(visible=False),
                                ],
                                icon=ft.Icons.MORE_HORIZ_ROUNDED,
                                icon_color=icon_color,
                                icon_size=18,
                            )
                        ],
                        spacing=T.SP_SM,
                    ),
                    ft.ProgressBar(value=pb_val, color=pb_color, bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.ON_SURFACE), height=3),
                ],
                spacing=T.SP_SM,
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

        bubble = ft.Container(
            content=bubble_content,
            width=250 if is_file_msg else None,
            gradient=T.GRADIENT_PRIMARY if is_self and not is_file_msg else None,
            bgcolor=ft.Colors.with_opacity(0.18, ft.Colors.DEEP_PURPLE_400) if is_self and is_file_msg else (None if is_self else ft.Colors.SURFACE_CONTAINER_HIGH),
            border_radius=T.radius_only(
                top_left=16, top_right=16,
                bottom_right=4 if is_self else 16,
                bottom_left=16 if is_self else 4,
            ),
            padding=T.pad_symmetric(horizontal=14, vertical=10),
            shadow=ft.BoxShadow(blur_radius=8, color=ft.Colors.with_opacity(0.04, ft.Colors.BLACK), offset=ft.Offset(0, 2)),
            border=T.border_all(1, ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE)) if not is_self else None,
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
        if is_self:
            row = ft.Row([ft.Container(expand=True), bubble, avatar],
                         alignment=ft.MainAxisAlignment.END, vertical_alignment=ft.CrossAxisAlignment.END)
        else:
            row = ft.Row([avatar, bubble], alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.END)
            
        self._msg_list.controls.append(row)
        self._scroll_bottom()
        return row

    def _file_info_from_content(self, content):
        decoded = decode_file_message(content, self.app.get_receive_dir())
        return {"filename": decoded.filename, "path": decoded.path}

    def _file_message_content(self, status, filename, file_path):
        return encode_file_message(status, filename, file_path)

    def _replace_bubble(self, old_row, from_name, content, timestamp, is_self=False):
        if not self._msg_list:
            return self._append_bubble(from_name, content, timestamp, is_self=is_self)
        replacement = self._build_bubble_row(from_name, content, timestamp, is_self)
        try:
            idx = self._msg_list.controls.index(old_row)
            self._msg_list.controls[idx] = replacement
        except ValueError:
            self._msg_list.controls.append(replacement)
        self._scroll_bottom()
        return replacement

    def _build_bubble_row(self, from_name, content, timestamp, is_self=False):
        before_len = len(self._msg_list.controls)
        row = self._append_bubble(from_name, content, timestamp, is_self=is_self)
        if len(self._msg_list.controls) > before_len:
            self._msg_list.controls.pop()
        return row

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

    # -- events ------------------------------------------------------------

    def _on_send(self, _e):
        text = (self._input.value or "").strip()
        if not text or not self.current_friend:
            return
        self._input.value = ""

        def task():
            if self.is_group:
                self.app.send_group_chat_message(self.current_group_id, text)
            else:
                self.app.send_chat_message(self.current_friend, text)
            ts = time.strftime("%H:%M:%S", time.localtime())
            self._append_bubble(self.app.device_name, text, ts, is_self=True)
            if self.page:
                self.page.update()
        threading.Thread(target=task, daemon=True).start()

    def _pick_file(self, _e):
        import threading
        def _do_pick():
            import tkinter as tk
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

    def _send_file(self, file_path):
        if not self.current_friend:
            return
            
        if self.compress_checkbox.value:
            try:
                import zipfile
                temp_zip_dir = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "beiyang_compressed")
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
        sending_content = self._file_message_content("正在发送文件", filename, file_path)
        
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
            sending_row = self._append_bubble(self.app.device_name, sending_content, ts, is_self=True)
            if self.page:
                self.page.update()

            def worker():
                ok = self.app.send_file_to_friend(self.current_friend, file_path)
                done_ts = time.strftime("%H:%M:%S", time.localtime())
                status = "文件" if ok else "文件发送失败"
                content = self._file_message_content(status, filename, file_path)
                self._replace_bubble(sending_row, self.app.device_name, content, done_ts, is_self=True)
                if self.page:
                    self.page.update()
            threading.Thread(target=worker, daemon=True).start()

    def _back_to_list(self, _e):
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

    def on_new_message(self, from_name, content, timestamp):
        ts = timestamp
        if len(timestamp) >= 19:
            ts = timestamp[11:19]
        if self.current_friend == from_name and not self.is_group and self._msg_list is not None:
            self._append_bubble(from_name, content, ts, is_self=False)
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
