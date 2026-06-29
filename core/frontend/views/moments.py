import os
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
        self.image_preview = ft.Image(src="placeholder", visible=False, height=100, fit=ft.BoxFit.FIT_HEIGHT)

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

        is_my_post = False
        if self.app:
            if self.app.device_name and author == self.app.device_name:
                is_my_post = True
            elif hasattr(self.app, "runtime") and self.app.runtime and getattr(self.app.runtime, "device_name", None) and author == self.app.runtime.device_name:
                is_my_post = True
            else:
                try:
                    my_profile = self.app.friend_db.get_my_profile() if self.app.friend_db else None
                    if my_profile and author == my_profile.get("name", ""):
                        is_my_post = True
                except Exception:
                    pass

        media_image = None
        if media_path and os.path.exists(media_path):
            try:
                img_ctrl = ft.Image(
                    src=media_path,
                    border_radius=8,
                    fit=ft.BoxFit.FIT_WIDTH,
                )
                media_image = ft.Container(
                    content=img_ctrl,
                    margin={"top": 8},
                    border_radius=8,
                    clip_behavior=ft.ClipBehavior.HARD_EDGE,
                )
            except Exception:
                pass

        # Comments section data fetching & rendering
        post_id = m.get("post_id", "")
        comments = self.app.get_moment_comments(post_id) or []

        comments_list = ft.Column(spacing=6)
        for c in comments:
            comments_list.controls.append(
                ft.Text.rich(
                    ft.TextSpan(
                        [
                            ft.TextSpan(f"{c['author']}: ", style=ft.TextStyle(weight=ft.FontWeight.BOLD, size=11, color=ft.Colors.DEEP_PURPLE_400)),
                            ft.TextSpan(c['content'], style=ft.TextStyle(size=11, color=ft.Colors.ON_SURFACE)),
                        ]
                    )
                )
            )

        comment_input = ft.TextField(
            hint_text="添加评论...",
            text_size=12,
            border_radius=8,
            height=30,
            expand=True,
            content_padding=T.pad_symmetric(horizontal=10, vertical=0),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            border_color=ft.Colors.with_opacity(0.1, ft.Colors.ON_SURFACE),
        )

        def send_comment_click(_e):
            val = (comment_input.value or "").strip()
            if not val:
                return
            self.app.publish_moment_comment(post_id, val)
            comment_input.value = ""
            try:
                comment_input.update()
            except Exception:
                pass
            self.refresh()
            if hasattr(self.app, "_refresh_personal_space_feed") and self.app._refresh_personal_space_feed:
                try:
                    self.app._refresh_personal_space_feed()
                except Exception:
                    pass

        send_btn = ft.IconButton(
            icon=ft.Icons.SEND_ROUNDED,
            icon_size=14,
            icon_color=ft.Colors.DEEP_PURPLE_400,
            on_click=send_comment_click,
            padding=0,
        )

        card = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.GestureDetector(
                                content=T.avatar_circle(self.app.get_avatar_for_name(author), T.AVATAR_MD),
                                on_tap=lambda _e: self.app.show_friend_profile(author),
                                mouse_cursor=ft.MouseCursor.CLICK,
                            ),
                            ft.Column(
                                [
                                    ft.Row(
                                        [
                                            ft.GestureDetector(
                                                content=ft.Text(author, size=T.FS_TEXT, weight=ft.FontWeight.BOLD),
                                                on_tap=lambda _e: self.app.show_friend_profile(author),
                                                mouse_cursor=ft.MouseCursor.CLICK,
                                            ),
                                            ft.Container(
                                                content=ft.Text("我的", size=9, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                                                bgcolor=ft.Colors.DEEP_PURPLE_400,
                                                padding={"left": 6, "top": 2, "right": 6, "bottom": 2},
                                                border_radius=6,
                                                margin={"left": 4},
                                            ) if is_my_post else ft.Container()
                                        ],
                                        alignment=ft.MainAxisAlignment.START,
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    ),
                                    ft.Text(ts, size=T.FS_CAPTION, color=ft.Colors.ON_SURFACE_VARIANT),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE_ROUNDED,
                                icon_color=ft.Colors.RED_300,
                                tooltip="删除动态",
                                on_click=lambda _e, pid=m.get("post_id"): self._on_delete_moment(pid),
                            ) if is_my_post else ft.Container()
                        ],
                        spacing=T.SP_SM,
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Text(content, size=T.FS_BODY),
                    media_image if media_image else ft.Container(),
                    ft.Divider(height=6, thickness=1, color=ft.Colors.with_opacity(0.04, ft.Colors.ON_SURFACE)) if comments else ft.Container(),
                    comments_list if comments else ft.Container(),
                    ft.Row(
                        [comment_input, send_btn],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    )
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

        def _do_pick():
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            file_path = filedialog.askopenfilename(
                title="选择分享图片",
                parent=root,
                filetypes=[("图片文件", "*.png;*.jpg;*.jpeg;*.bmp;*.gif;*.webp")],
            )
            root.destroy()
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
            try:
                page.update()
            except Exception:
                pass
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
            self.image_preview.src = file_path
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
            self.image_preview.src = "placeholder"
            self.image_preview.src_base64 = None
            self.app.show_toast("空间动态发布成功 🌌")
            self.refresh()
        else:
            self.app.show_toast("发布失败")

    def _on_delete_moment(self, post_id: str):
        def confirm_delete(_e2):
            self.app.delete_moment(post_id)
            dlg.open = False
            self.page.update()
            self.refresh()
            self.app.show_toast("动态已删除 🗑️")

        dlg = ft.AlertDialog(
            title=ft.Text("确认删除吗？", weight=ft.FontWeight.BOLD),
            content=ft.Text("此操作将永久从您的本地设备上删除该条空间动态。"),
            actions=[
                ft.TextButton("取消", on_click=lambda _e: self._close_dialog(dlg)),
                ft.ElevatedButton("删除", on_click=confirm_delete, bgcolor=ft.Colors.RED_400, color=ft.Colors.WHITE),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()

    def _close_dialog(self, dlg):
        dlg.open = False
        self.page.update()
