import os
import time
import threading
import flet as ft
from core.frontend import theme as T

class MomentsView:
    """朋友圈/空间动态视图 (P2P Moments View)"""

    def __init__(self, app):
        self.app = app
        self.page = None
        self.root = None
        self._media_path = ""

        # UI elements
        self.post_input = ft.TextField(
            hint_text="分享新鲜事...",
            multiline=True,
            min_lines=2,
            max_lines=5,
            border=ft.InputBorder.NONE,
            bgcolor=ft.Colors.TRANSPARENT,
            content_padding=T.pad_all(4),
        )
        self.media_btn = ft.IconButton(
            icon=ft.Icons.IMAGE_ROUNDED,
            icon_color=ft.Colors.DEEP_PURPLE_400,
            tooltip="添加图片",
            on_click=self._pick_image,
        )
        self.media_indicator = ft.Text("", size=T.FS_CAPTION, color=ft.Colors.ON_SURFACE_VARIANT)
        self.media_row = ft.Row([self.media_btn, self.media_indicator], spacing=10)
        self.image_preview = ft.Image(src=None, visible=False, height=100, fit=ft.BoxFit.FIT_HEIGHT)

        self.publish_btn = ft.ElevatedButton(
            "发布动态",
            icon=ft.Icons.SEND_ROUNDED,
            on_click=self._on_publish,
            bgcolor=ft.Colors.DEEP_PURPLE_500,
            color=ft.Colors.WHITE,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=T.pad_symmetric(horizontal=16, vertical=12),
            ),
        )

        self.feed_col = ft.Column(spacing=T.SP_MD, scroll=ft.ScrollMode.AUTO, expand=True)

    def build(self):
        self.page = self.app.page
        if not self.root:
            # Publish card
            publish_card = ft.Container(
                content=ft.Column(
                    [
                        self.post_input,
                        self.image_preview,
                        ft.Divider(height=1, color=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE)),
                        ft.Row(
                            [
                                self.media_row,
                                self.publish_btn,
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    ],
                    spacing=T.SP_SM,
                ),
                padding=T.pad_symmetric(horizontal=16, vertical=12),
                border_radius=T.R_MD,
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
                border=T.border_all(1, ft.Colors.with_opacity(0.06, ft.Colors.ON_SURFACE)),
                shadow=T.SHADOW_CARD,
            )

            self.root = ft.Column(
                [
                    ft.Row(
                        [
                            ft.Row(
                                [
                                    ft.Icon(ft.Icons.AUTO_AWESOME_ROUNDED, color=ft.Colors.DEEP_PURPLE_400, size=24),
                                    ft.Text("北洋空间", size=T.FS_HEADER, weight=ft.FontWeight.W_800),
                                ],
                                spacing=8,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.REFRESH_ROUNDED,
                                tooltip="刷新动态",
                                on_click=lambda _: self.refresh(force_sync=True)
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    publish_card,
                    ft.Text("空间墙", size=T.FS_TITLE, weight=ft.FontWeight.BOLD),
                    self.feed_col,
                ],
                spacing=T.SP_MD,
                expand=True,
            )
            self.refresh()
        return self.root

    def on_enter(self):
        self.refresh()

    def refresh(self, force_sync=False):
        if force_sync:
            self.app.sync_moments()
            self.app.show_toast("已向在线好友发送同步请求 🔄")

        # Load from DB
        moments = self.app.get_moments() or []
        self.feed_col.controls.clear()
        
        if not moments:
            self.feed_col.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(ft.Icons.AUTO_AWESOME_ROUNDED, size=48, color=ft.Colors.ON_SURFACE_VARIANT),
                            ft.Text("暂无动态，快去发布吧~", color=ft.Colors.ON_SURFACE_VARIANT),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=T.SP_SM,
                    ),
                    alignment=ft.alignment.Alignment.CENTER,
                    padding=T.pad_all(40),
                )
            )
        else:
            for m in moments:
                self.feed_col.controls.append(self._build_moment_card(m))
        
        if self.page:
            self.page.update()

    def on_moments_changed(self):
        self.refresh()

    def _build_moment_card(self, m) -> ft.Control:
        author = m.get("author", "")
        content = m.get("content", "")
        media_path = m.get("media_path", "")
        ts = m.get("timestamp", "")
        if len(ts) >= 19:
            ts = ts[:16] # Show YYYY-MM-DD HH:MM

        media_image = None
        if media_path and os.path.exists(media_path):
            try:
                import base64
                with open(media_path, "rb") as f:
                    img_bytes = f.read()
                b64 = base64.b64encode(img_bytes).decode()
                # Determine MIME type from extension.
                ext = os.path.splitext(media_path)[1].lower()
                mime_map = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".gif": "image/gif",
                    ".bmp": "image/bmp",
                    ".webp": "image/webp",
                }
                mime = mime_map.get(ext, "image/png")
                data_uri = f"data:{mime};base64,{b64}"
                media_image = ft.Container(
                    content=ft.Image(
                        src=data_uri,
                        border_radius=8,
                        fit=ft.BoxFit.FIT_WIDTH,
                    ),
                    margin=ft.margin.only(top=8),
                    border_radius=8,
                    clip_behavior=ft.ClipBehavior.HARD_EDGE,
                )
            except Exception:
                pass

        card = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            T.avatar_circle(self.app.get_avatar_for_name(author), T.AVATAR_MD),
                            ft.Column(
                                [
                                    ft.Text(author, size=T.FS_TEXT, weight=ft.FontWeight.BOLD),
                                    ft.Text(ts, size=T.FS_CAPTION, color=ft.Colors.ON_SURFACE_VARIANT),
                                ],
                                spacing=2,
                            ),
                        ],
                        spacing=T.SP_SM,
                    ),
                    ft.Text(content, size=T.FS_BODY),
                    media_image if media_image else ft.Container(),
                ],
                spacing=T.SP_SM,
            ),
            padding=T.SP_MD,
            border_radius=T.R_MD,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            border=T.border_all(1, ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE)),
        )
        return card

    def _pick_image(self, _e):
        try:
            import tkinter as tk
        except ImportError:
            self.app.page.run_thread(self._pick_image_flet)
            return

        import threading
        def _do_pick():
            from tkinter import filedialog
            root = self.app.get_tk_root()
            if root:
                root.attributes("-topmost", True)
            file_path = filedialog.askopenfilename(
                title="选择分享图片",
                parent=root,
                filetypes=[("图片文件", "*.png;*.jpg;*.jpeg;*.bmp;*.gif;*.webp")],
            )
            if file_path:
                self._apply_picked_image(file_path)

        threading.Thread(target=_do_pick, daemon=True).start()

    async def _pick_image_flet(self):
        picker = getattr(self.app, "moment_image_picker", None)
        if not picker:
            picker = ft.FilePicker()
            self.app.moment_image_picker = picker
        picker.on_result = self._on_moment_image_selected
        page = self.page
        if page and picker not in page.services:
            page.services.append(picker)
        await picker.pick_files(
            dialog_title="选择分享图片",
            file_type=ft.FilePickerFileType.IMAGE,
        )

    def _on_moment_image_selected(self, e):
        if e.files and e.files[0].path:
            self._apply_picked_image(e.files[0].path)

    def _apply_picked_image(self, file_path):
        self._media_path = file_path
        self.media_indicator.value = os.path.basename(file_path)
        try:
            import base64
            with open(file_path, "rb") as f:
                img_bytes = f.read()
            b64 = base64.b64encode(img_bytes).decode()
            ext = os.path.splitext(file_path)[1].lower()
            mime = "image/png" if ext == ".png" else "image/jpeg"
            self.image_preview.src = f"data:{mime};base64,{b64}"
            self.image_preview.visible = True
        except Exception:
            pass
        if self.page:
            self.page.update()

    def _on_publish(self, _e):
        content = (self.post_input.value or "").strip()
        if not content and not self._media_path:
            self.app.show_toast("不能发布空内容喔~")
            return
        
        ok = self.app.publish_moment(content, self._media_path)
        if ok:
            self.post_input.value = ""
            self._media_path = ""
            self.media_indicator.value = ""
            self.image_preview.visible = False
            self.image_preview.src = None
            self.app.show_toast("空间动态发布成功 🌌")
            self.refresh()
        else:
            self.app.show_toast("发布失败")
