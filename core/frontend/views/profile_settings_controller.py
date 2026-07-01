"""Settings actions for the profile view."""

import os
import threading
import time
from pathlib import Path

import flet as ft


class ProfileSettingsController:
    """Handle network, receive-directory, and privacy settings actions."""

    def __init__(self, owner):
        self.owner = owner

    def save_tcp(self, _e):
        owner = self.owner
        try:
            port = int((owner.settings_tcp_port.value or "").strip())
            if port < 1024 or port > 65535:
                owner.settings_tcp_hint.value = "❌ 端口范围应在 1024-65535"
                owner.settings_tcp_hint.color = ft.Colors.RED_400
                owner.page.update()
                return
            owner.app.set_tcp_port(port)
            owner.settings_tcp_hint.value = f"✨ 端口已改为 {port}（将在应用重启后生效）"
            owner.settings_tcp_hint.color = ft.Colors.GREEN_400
        except ValueError:
            owner.settings_tcp_hint.value = "❌ 请输入有效的数字端口"
            owner.settings_tcp_hint.color = ft.Colors.RED_400
        owner.page.update()

        def _clear():
            time.sleep(3)
            owner.settings_tcp_hint.value = ""
            try:
                owner.page.update()
            except Exception:
                pass

        threading.Thread(target=_clear, daemon=True).start()

    async def choose_receive_dir(self, _e):
        owner = self.owner
        platform_name = str(getattr(owner.page, "platform", "")).lower() if owner.page else ""
        is_android = platform_name in ("android", "pageplatform.android")
        if is_android:
            await self.choose_receive_dir_flet()
            return
        try:
            import tkinter as tk
        except ImportError:
            await self.choose_receive_dir_flet()
            return

        def _do_pick():
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selected = filedialog.askdirectory(
                title="选择接收文件保存目录",
                initialdir=owner.app.get_receive_dir(),
                parent=root,
            )
            root.destroy()
            if selected:
                self.apply_receive_dir(selected)

        threading.Thread(target=_do_pick, daemon=True).start()

    async def choose_receive_dir_flet(self):
        owner = self.owner
        platform_name = str(getattr(owner.page, "platform", "")) if owner.page else ""
        is_android = platform_name.lower() in ("android", "pageplatform.android")

        picker = getattr(owner.app, "receive_dir_picker", None)
        if not picker:
            picker = ft.FilePicker()
            owner.app.receive_dir_picker = picker
        picker.on_result = owner._on_receive_dir_selected
        page = owner.page
        if page and picker not in page.services:
            page.services.append(picker)
            try:
                page.update()
            except Exception:
                pass

        if is_android:
            # Android's SAF directory picker is unreliable — fall back to
            # manual path input with a suggested public path.
            owner.receive_dir_input.value = "/storage/emulated/0/Download/Beiyang"
            owner.settings_tcp_hint.value = (
                "\uD83D\uDCA1 Android 目录选择器受限，请在上方输入框中直接输入保存路径后点「应用路径」。\n"
                "推荐使用 /storage/emulated/0/Download/Beiyang（可在文件管理器中找到）"
            )
            owner.settings_tcp_hint.color = ft.Colors.ON_SURFACE_VARIANT
            if owner.page:
                owner.page.update()
            return

        try:
            await picker.get_directory_path(
                dialog_title="选择接收文件保存目录",
                initial_directory=owner.app.get_receive_dir(),
            )
        except Exception as exc:
            owner.settings_tcp_hint.value = f"目录选择器不可用，可手动输入路径: {exc}"
            owner.settings_tcp_hint.color = ft.Colors.ORANGE_400
            if owner.page:
                owner.page.update()

    def on_receive_dir_selected(self, e):
        owner = self.owner
        if e.path:
            self.apply_receive_dir(e.path)
        else:
            owner.settings_tcp_hint.value = "未选择目录；Android 可直接手动输入保存路径后点“应用路径”"
            owner.settings_tcp_hint.color = ft.Colors.ON_SURFACE_VARIANT
            if owner.page:
                owner.page.update()

    def reset_receive_dir(self, _e):
        owner = self.owner
        self.apply_receive_dir(str(owner.app.paths.received_files_dir))

    def apply_receive_dir_from_input(self, _e):
        self.apply_receive_dir(self.owner.receive_dir_input.value)

    def normalize_receive_dir(self, directory):
        owner = self.owner
        value = (directory or "").strip().strip('"').strip("'")
        if not value:
            raise ValueError("保存路径不能为空")
        if value.startswith("content://"):
            raise ValueError("当前运行时不能直接写入 content:// 目录，请输入文件系统路径")
        if owner.page:
            platform_name = str(getattr(owner.page, "platform", "")).lower()
        else:
            platform_name = ""
        is_android = platform_name in ("android", "pageplatform.android")
        path = Path(value).expanduser()
        if is_android and not path.is_absolute():
            path = Path(owner.app.paths.received_files_dir).parent / path
        return str(path)

    def apply_receive_dir(self, directory):
        owner = self.owner
        try:
            directory = self.normalize_receive_dir(directory)
            os.makedirs(directory, exist_ok=True)
            resolved = owner.app.set_receive_dir(directory)
            owner.settings_receive_dir.value = resolved
            owner.receive_dir_input.value = resolved
            owner.settings_tcp_hint.value = "✨ 文件保存位置已更新"
            owner.settings_tcp_hint.color = ft.Colors.GREEN_400
        except Exception as exc:
            msg = str(exc)
            is_android = str(owner.page.platform).lower() in ("android", "pageplatform.android") if owner.page else False
            if is_android:
                msg += "\n💡 提示: 安卓平台受限制，建议使用默认或私有目录"
            owner.settings_tcp_hint.value = f"❌ 保存位置更新失败: {msg}"
            owner.settings_tcp_hint.color = ft.Colors.RED_400
        if owner.page:
            owner.page.update()

    def clear_chat(self):
        owner = self.owner

        def do_clear(_e):
            for f in owner.app.get_all_friends():
                owner.app.clear_chat_history(f.get("name", ""))
            owner.settings_tcp_hint.value = "✨ 本地聊天记录清理成功"
            owner.settings_tcp_hint.color = ft.Colors.GREEN_400
            owner.page.update()

        owner._confirm(
            "确定清除所有聊天记录吗？此操作将彻底擦除本地消息历史，且不可撤销。",
            on_ok=do_clear,
            ok_text="确认清空",
        )

    def clear_pending(self):
        owner = self.owner

        def do_clear(_e):
            for f in owner.app.get_all_friends():
                owner.app.clear_pending_messages(f.get("name", ""))
            owner.settings_pending_count.value = "0 条消息"
            owner.settings_tcp_hint.value = "✨ 离线待发送消息队列已清空"
            owner.settings_tcp_hint.color = ft.Colors.GREEN_400
            owner.page.update()

        owner._confirm(
            "确定清空待发送队列吗？清空后，离线的好友上线时将无法收到这些缓存的数据包。",
            on_ok=do_clear,
            ok_text="确认清空",
        )
