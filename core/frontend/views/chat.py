"""Chat view: chat list + chat window with bubbles and file transfer."""
import os
import time
import threading
import uuid

import flet as ft

from .. import theme as T
from .chat_bubble_renderer import ChatBubbleRenderer
from .chat_file_tools import (
    decode_file_content,
    file_info_from_content,
    file_message_content,
    format_bytes,
    format_speed,
    is_android,
    is_file_message,
    is_final_file_status,
    open_file_with_os,
    open_folder_with_os,
)
from .chat_file_offer_controller import ChatFileOfferController
from .chat_group_controller import ChatGroupController
from .chat_layout import ChatLayout
from .chat_notifications import ChatNotificationsPanel
from .chat_transfer_controller import ChatTransferController


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
        self.bubble_renderer = ChatBubbleRenderer(self)
        self.layout = ChatLayout(self)
        self.file_offer_controller = ChatFileOfferController(self)
        self.group_controller = ChatGroupController(self)
        self.notifications_panel = ChatNotificationsPanel(self)
        self.transfer_controller = ChatTransferController(self)
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
        return self.layout.build()

    def _build_tabs(self):
        return self.layout.build_tabs()

    def _build_window(self):
        return self.layout.build_window()

    # -- lifecycle ---------------------------------------------------------

    def on_enter(self):
        if not self.current_friend:
            self._render_list()
            self._render_notifications()

    def _build_notifications_view(self):
        return self.notifications_panel.build()

    def _render_notifications(self):
        self.notifications_panel.render()

    def _on_mark_all_read(self, e):
        self.notifications_panel.mark_all_read(e)

    def _on_clear_notifications(self, e):
        self.notifications_panel.clear_notifications(e)

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
                if self._is_file_message_content(last_msg)
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
        return self.bubble_renderer.append_bubble(
            from_name,
            content,
            timestamp,
            is_self=is_self,
            msg_id=msg_id,
        )

    def _file_info_from_content(self, content):
        return file_info_from_content(content, self.app.get_receive_dir())

    @staticmethod
    def _is_file_message_content(content):
        return is_file_message(content)

    def _remember_transfer_state(self, file_id, **changes):
        return self.transfer_controller.remember_state(file_id, **changes)

    def _render_active_transfers_for(self, friend_name):
        self.transfer_controller.render_active_for(friend_name)

    def _file_message_content(
        self, status, filename, file_path, transfer_id=""
    ):
        return file_message_content(status, filename, file_path, transfer_id)

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
        return is_android()

    @classmethod
    def _open_file_with_os(cls, file_path: str):
        open_file_with_os(file_path)

    @classmethod
    def _open_folder_with_os(cls, file_path: str, folder_path: str):
        open_folder_with_os(file_path, folder_path)

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
        return format_bytes(value)

    @classmethod
    def _format_speed(cls, bytes_per_second):
        return format_speed(bytes_per_second)

    # ── transfer watchdog ──────────────────────────────────────────────

    def _start_transfer_watchdog(self, file_id):
        self.transfer_controller.start_watchdog(file_id)

    # ── speed calculation (sliding-window, real-time) ───────────────────

    @classmethod
    def _update_speed(cls, widget: dict, completed: int, prev_completed: int):
        # Kept for old call sites; instance methods use transfer_controller directly.
        ChatTransferController(None).update_speed(widget, completed, prev_completed)

    # ── widget lookup ───────────────────────────────────────────────────

    def _find_transfer_widget(self, peer_name="", filename="", sending=None):
        return self.transfer_controller.find_widget(peer_name, filename, sending)

    @staticmethod
    def _is_final_file_status(status: str) -> bool:
        return is_final_file_status(status)

    def _mark_file_transfer_closed(self, file_id: str):
        self.transfer_controller.mark_closed(file_id)

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
        return ChatFileOfferController.format_size(sz)

    def add_file_offer(self, from_name, filename, size, file_id):
        self.file_offer_controller.add_file_offer(from_name, filename, size, file_id)

    def _render_file_offers_for(self, friend_name):
        self.file_offer_controller.render_file_offers_for(friend_name)

    def _render_file_offer(self, file_id):
        self.file_offer_controller.render_file_offer(file_id)

    # ── incoming messages ─────────────────────────────────────────────

    def on_new_message(self, from_name, content, timestamp, msg_id=""):
        ts = timestamp
        if len(timestamp) >= 19:
            ts = timestamp[11:19]
        if self.current_friend == from_name and not self.is_group and self._msg_list is not None:
            decoded = decode_file_content(content, self.app.get_receive_dir())
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
        self.group_controller.show_group_info(group_id)

    def show_toast(self, text):
        if hasattr(self.app, "show_toast"):
            self.app.show_toast(text)

    def _on_create_group(self, _e):
        self.group_controller.create_group(_e)

    def show_group_settings(self, group_id):
        self.group_controller.show_group_settings(group_id)
