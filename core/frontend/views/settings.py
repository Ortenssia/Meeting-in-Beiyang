"""Settings view: device/network, data cleanup, about."""
import os
import threading
import time

import flet as ft

from .. import theme as T


class SettingsView:
    DEFAULT_UDP = 8890
    DEFAULT_TCP = 7779

    def __init__(self, app):
        self.app = app
        self.page = app.page
        self.device_name = ft.Text("--", size=T.FS_BODY, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE)
        self.tcp_port = ft.TextField(
            label="TCP 端口", value=str(self.DEFAULT_TCP),
            keyboard_type=ft.KeyboardType.NUMBER, width=120,
            border_radius=10, border_color=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            content_padding=10,
        )
        self.udp_port = ft.Text(str(self.DEFAULT_UDP), size=T.FS_BODY, weight=ft.FontWeight.W_500,
                                color=ft.Colors.ON_SURFACE_VARIANT)
        self.tcp_hint = ft.Text("", size=T.FS_CAPTION)
        self.pending_count = ft.Text("0 条消息", size=T.FS_BODY, weight=ft.FontWeight.BOLD,
                                     color=ft.Colors.DEEP_PURPLE_400)
        self.receive_dir = ft.Text("", size=T.FS_CAPTION, color=ft.Colors.ON_SURFACE_VARIANT,
                                   selectable=True, overflow=ft.TextOverflow.ELLIPSIS)

    def build(self):
        # Premium Brand Badge/Card (About Card)
        about_card = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.AUTO_AWESOME_ROUNDED, color=ft.Colors.WHITE, size=24),
                            ft.Text("相识北洋", size=T.FS_HEADER, weight=ft.FontWeight.W_900,
                                    color=ft.Colors.WHITE),
                        ],
                        spacing=T.SP_SM,
                    ),
                    ft.Text("版本 3.0.0", size=T.FS_BODY, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.with_opacity(0.8, ft.Colors.WHITE)),
                    ft.Text("P2P 校园网无网社交 · 洪泛中继路由 · 离线消息漫游",
                            size=T.FS_CAPTION, color=ft.Colors.with_opacity(0.7, ft.Colors.WHITE)),
                    ft.Divider(color=ft.Colors.with_opacity(0.15, ft.Colors.WHITE), height=8),
                    ft.Row(
                        [
                            ft.Text(f"默认 UDP: {self.DEFAULT_UDP}", size=T.FS_CAPTION, color=ft.Colors.with_opacity(0.8, ft.Colors.WHITE)),
                            ft.Text("•", size=T.FS_CAPTION, color=ft.Colors.with_opacity(0.8, ft.Colors.WHITE)),
                            ft.Text(f"默认 TCP: {self.DEFAULT_TCP}", size=T.FS_CAPTION, color=ft.Colors.with_opacity(0.8, ft.Colors.WHITE)),
                        ],
                        spacing=T.SP_SM,
                    ),
                ],
                spacing=6,
            ),
            padding=T.SP_LG,
            border_radius=T.R_LG,
            gradient=T.GRADIENT_PRIMARY,
            shadow=T.SHADOW_GLOW,
            border=T.border_all(1, ft.Colors.with_opacity(0.15, ft.Colors.WHITE)),
        )

        return ft.Column(
            [
                ft.Text("系统设置", size=T.FS_HEADER, weight=ft.FontWeight.W_800),
                ft.Column(
                    [
                        about_card,
                        
                        T.surface_card(
                            T.section_title("网络与设备"),
                            self._setting_row("本机主机名", self.device_name),
                            ft.Row(
                                [
                                    ft.Text("TCP 端口号", size=T.FS_BODY,
                                            color=ft.Colors.ON_SURFACE_VARIANT, width=100),
                                    self.tcp_port,
                                    ft.IconButton(
                                        icon=ft.Icons.CHECK_CIRCLE_ROUNDED,
                                        icon_color=ft.Colors.DEEP_PURPLE_400,
                                        on_click=self._save_tcp,
                                        tooltip="保存端口"
                                    ),
                                ],
                                spacing=T.SP_SM,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            self.tcp_hint,
                            self._setting_row("UDP 广播端口", self.udp_port),
                        ),

                        T.surface_card(
                            T.section_title("文件接收"),
                            self._setting_row("保存位置", self.receive_dir),
                            ft.Row(
                                [
                                    ft.ElevatedButton(
                                        "选择保存目录",
                                        icon=ft.Icons.FOLDER_OPEN_ROUNDED,
                                        on_click=self._choose_receive_dir,
                                        bgcolor=ft.Colors.DEEP_PURPLE_500,
                                        color=ft.Colors.WHITE,
                                    ),
                                    ft.TextButton(
                                        "恢复默认",
                                        on_click=self._reset_receive_dir,
                                    ),
                                ],
                                spacing=T.SP_SM,
                            ),
                        ),
                        
                        T.surface_card(
                            T.section_title("安全与隐私"),
                            ft.ListTile(
                                leading=ft.Icon(ft.Icons.CLEANING_SERVICES_ROUNDED, color=ft.Colors.ORANGE_400),
                                title=ft.Text("清空聊天记录", weight=ft.FontWeight.BOLD),
                                subtitle=ft.Text("清除本地数据库中所有朋友的历史消息", size=T.FS_CAPTION),
                                trailing=ft.Icon(ft.Icons.NAVIGATE_NEXT_ROUNDED),
                                on_click=lambda _e: self._clear_chat(),
                            ),
                            ft.ListTile(
                                leading=ft.Icon(ft.Icons.MARK_AS_UNREAD_ROUNDED, color=ft.Colors.DEEP_PURPLE_400),
                                title=ft.Text("清除离线待发送队列", weight=ft.FontWeight.BOLD),
                                subtitle=ft.Text("清空缓存中准备转发给朋友的离线数据", size=T.FS_CAPTION),
                                trailing=self.pending_count,
                                on_click=lambda _e: self._clear_pending(),
                            ),
                        ),
                    ],
                    spacing=T.SP_MD, expand=True, scroll=ft.ScrollMode.AUTO,
                ),
            ],
            spacing=T.SP_SM, expand=True,
        )

    def _setting_row(self, label, value_control):
        return ft.Row(
            [
                ft.Text(label, size=T.FS_BODY, color=ft.Colors.ON_SURFACE_VARIANT, width=120),
                ft.Container(expand=True),
                value_control,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    # -- lifecycle ---------------------------------------------------------

    def on_enter(self):
        info = self.app.get_local_device_info()
        if info:
            self.device_name.value = info.get("name", "--")
        self.pending_count.value = f"{self.app.get_pending_message_count() or 0} 条消息"
        if hasattr(self.app, "tcp_port"):
            self.tcp_port.value = str(self.app.tcp_port)
        self.receive_dir.value = self.app.get_receive_dir()
        if self.page:
            self.page.update()

    # -- events ------------------------------------------------------------

    def _save_tcp(self, _e):
        try:
            port = int((self.tcp_port.value or "").strip())
            if port < 1024 or port > 65535:
                self.tcp_hint.value = "❌ 端口范围应在 1024-65535"
                self.tcp_hint.color = ft.Colors.RED_400
                self.page.update()
                return
            self.app.set_tcp_port(port)
            self.tcp_hint.value = f"✨ 端口已改为 {port}（将在应用重启后生效）"
            self.tcp_hint.color = ft.Colors.GREEN_400
        except ValueError:
            self.tcp_hint.value = "❌ 请输入有效的数字端口"
            self.tcp_hint.color = ft.Colors.RED_400
        self.page.update()

        def _clear():
            time.sleep(3)
            self.tcp_hint.value = ""
            try:
                self.page.update()
            except Exception:
                pass
        threading.Thread(target=_clear, daemon=True).start()

    def _choose_receive_dir(self, _e):
        def _do_pick():
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selected = filedialog.askdirectory(
                title="选择接收文件保存目录",
                initialdir=self.app.get_receive_dir(),
                parent=root,
            )
            root.destroy()
            if selected:
                self._apply_receive_dir(selected)

        threading.Thread(target=_do_pick, daemon=True).start()

    def _reset_receive_dir(self, _e):
        self._apply_receive_dir(str(self.app.paths.received_files_dir))

    def _apply_receive_dir(self, directory):
        try:
            os.makedirs(directory, exist_ok=True)
            resolved = self.app.set_receive_dir(directory)
            self.receive_dir.value = resolved
            self.tcp_hint.value = "✨ 文件保存位置已更新"
            self.tcp_hint.color = ft.Colors.GREEN_400
        except Exception as exc:
            self.tcp_hint.value = f"❌ 保存位置更新失败: {exc}"
            self.tcp_hint.color = ft.Colors.RED_400
        if self.page:
            self.page.update()

    def _clear_chat(self):
        def do_clear(_e):
            dlg.open = False
            for f in self.app.get_all_friends():
                self.app.clear_chat_history(f.get("name", ""))
            self.tcp_hint.value = "✨ 本地聊天记录清理成功"
            self.tcp_hint.color = ft.Colors.GREEN_400
            self.page.update()

        self._confirm("确定清除所有聊天记录吗？此操作将彻底擦除本地消息历史，且不可撤销。",
                      on_ok=do_clear, ok_text="确认清空")

    def _clear_pending(self):
        def do_clear(_e):
            dlg.open = False
            for f in self.app.get_all_friends():
                self.app.clear_pending_messages(f.get("name", ""))
            self.pending_count.value = "0 条消息"
            self.tcp_hint.value = "✨ 离线待发送消息队列已清空"
            self.tcp_hint.color = ft.Colors.GREEN_400
            self.page.update()

        self._confirm("确定清空待发送队列吗？清空后，离线的好友上线时将无法收到这些缓存的数据包。",
                      on_ok=do_clear, ok_text="确认清空")

    def _confirm(self, message, on_ok, ok_text="确认"):
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("确认操作 ⚠️", weight=ft.FontWeight.BOLD),
            content=ft.Text(message),
            actions=[
                ft.TextButton("取消", on_click=lambda _e: self._close(dlg)),
                ft.ElevatedButton(
                    ok_text, 
                    on_click=on_ok,
                    bgcolor=ft.Colors.RED_600, 
                    color=ft.Colors.WHITE
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()

    def _close(self, dlg):
        dlg.open = False
        self.page.update()
