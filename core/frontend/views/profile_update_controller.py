"""Application update workflow for the profile settings page."""

import threading

import flet as ft

from core.backend.services.update_service import UpdateCheckError, check_for_updates

from .. import theme as T


class ProfileUpdateController:
    """Handle update checks, status feedback, and update dialogs."""

    def __init__(self, owner):
        self.owner = owner

    def check_updates(self, _e):
        owner = self.owner
        manifest_url = (owner.update_manifest_url.value or "").strip()
        if not manifest_url:
            owner.update_status.value = "请先填写 latest.json 更新地址"
            owner.update_status.color = ft.Colors.RED_400
            if owner.page:
                owner.page.update()
            return

        owner.app.friend_db.set_app_setting("update_manifest_url", manifest_url)
        owner.update_check_btn.disabled = True
        owner.update_status.value = "正在检查更新..."
        owner.update_status.color = ft.Colors.ON_SURFACE_VARIANT
        if owner.page:
            owner.page.update()

        def worker():
            try:
                info = check_for_updates(
                    manifest_url,
                    current_version=owner.current_version,
                    target_platform=self.current_platform(),
                )
            except UpdateCheckError as exc:
                self.set_status(f"检查失败：{exc}", ft.Colors.RED_400)
                owner.update_check_btn.disabled = False
                return
            except Exception as exc:
                self.set_status(f"检查失败：{exc}", ft.Colors.RED_400)
                owner.update_check_btn.disabled = False
                return

            owner.update_check_btn.disabled = False
            if not info.has_update:
                self.set_status(
                    f"已是最新版本：{info.current_version}",
                    ft.Colors.GREEN_400,
                )
                return
            self.show_dialog(info)

        threading.Thread(target=worker, daemon=True).start()

    def set_status(self, text, color):
        owner = self.owner
        owner.update_status.value = text
        owner.update_status.color = color
        try:
            if owner.page:
                owner.page.update()
        except Exception:
            pass

    def show_dialog(self, info):
        owner = self.owner
        asset = info.asset
        download_url = asset.url if asset else ""
        notes = info.notes.strip() or "暂无更新说明"
        sha256 = asset.sha256 if asset else ""
        status = ft.Text("", size=T.FS_CAPTION, color=ft.Colors.ON_SURFACE_VARIANT)

        def copy_url(_e):
            if download_url and owner.page:
                owner.page.set_clipboard(download_url)
                status.value = "下载链接已复制"
                status.color = ft.Colors.GREEN_400
                owner.page.update()

        def open_url(_e):
            if not download_url:
                return
            if self.open_url(download_url):
                owner._close(dlg)
            else:
                copy_url(_e)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("发现新版本", weight=ft.FontWeight.BOLD),
            content=ft.Column(
                [
                    ft.Text(f"当前版本：{info.current_version}", size=T.FS_BODY),
                    ft.Text(f"最新版本：{info.latest_version}", size=T.FS_BODY, weight=ft.FontWeight.BOLD),
                    ft.Divider(height=16, color=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE)),
                    ft.Text("更新说明", size=T.FS_BODY, weight=ft.FontWeight.BOLD),
                    ft.Text(notes, size=T.FS_CAPTION, selectable=True),
                    ft.Text(f"SHA256：{sha256}" if sha256 else "SHA256：清单未提供", size=11, selectable=True),
                    status,
                ],
                width=320,
                tight=True,
                spacing=8,
            ),
            actions_alignment=ft.MainAxisAlignment.END,
        )

        actions = [ft.TextButton("关闭", on_click=lambda _e: owner._close(dlg))]
        if download_url:
            actions.insert(0, ft.TextButton("复制链接", on_click=copy_url))
            actions.insert(
                1,
                ft.ElevatedButton(
                    "打开下载",
                    icon=ft.Icons.OPEN_IN_BROWSER_ROUNDED,
                    on_click=open_url,
                    bgcolor=ft.Colors.DEEP_PURPLE_500,
                    color=ft.Colors.WHITE,
                ),
            )
            self.set_status(
                f"发现新版本 {info.latest_version}",
                ft.Colors.GREEN_400,
            )
        else:
            self.set_status(
                f"发现新版本 {info.latest_version}，但清单没有当前平台下载地址",
                ft.Colors.ORANGE_400,
            )
        dlg.actions = actions

        try:
            owner.page.overlay.append(dlg)
            dlg.open = True
            owner.page.update()
        except Exception:
            pass

    def open_url(self, url):
        owner = self.owner
        try:
            launcher = getattr(owner.page, "launch_url", None)
            if callable(launcher):
                launcher(url)
                return True
        except Exception:
            pass
        try:
            import webbrowser
            return bool(webbrowser.open(url))
        except Exception:
            return False

    def current_platform(self):
        owner = self.owner
        if owner.page and str(owner.page.platform).lower() in ("android", "pageplatform.android"):
            return "android"
        return None
