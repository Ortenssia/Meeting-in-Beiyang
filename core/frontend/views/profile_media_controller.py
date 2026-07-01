"""Avatar, background, and crop editing workflow for ProfileView."""

import os
import threading
import time
from pathlib import Path

import flet as ft

from .. import theme as T
from ..image_crop import CropState, image_size, render_crop


class ProfileMediaController:
    """Handle profile media picking, cropping, previews, and default avatars."""

    def __init__(self, owner):
        self.owner = owner

    async def browse(self, target):
        owner = self.owner
        try:
            import tkinter as tk
        except ImportError:
            await self.browse_flet(target)
            return

        def _do_pick():
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            file_path = filedialog.askopenfilename(
                title="选择图片",
                parent=root,
                filetypes=[("图片文件", "*.png;*.jpg;*.jpeg;*.bmp")],
            )
            root.destroy()
            if file_path:
                self.open_crop_editor(file_path, target)

        threading.Thread(target=_do_pick, daemon=True).start()

    async def browse_flet(self, target):
        """Use Flet FilePicker for platforms without tkinter (Android)."""
        owner = self.owner
        picker = getattr(owner.app, "profile_file_picker", None)
        if not picker:
            picker = ft.FilePicker()
            owner.app.profile_file_picker = picker
        page = owner.page
        if page and picker not in page.services:
            page.services.append(picker)

        files = await picker.pick_files(
            dialog_title="选择图片",
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["png", "jpg", "jpeg", "bmp"],
        )
        if files and files[0].path:
            source_path = files[0].path
            # On Android the picker returns a content:// URI which PIL cannot
            # open directly — copy to a local temp file first.
            if source_path.startswith("content://"):
                import shutil
                from pathlib import Path
                tmp_dir = Path(owner.app.paths.data_dir) / "temp_previews"
                tmp_dir.mkdir(parents=True, exist_ok=True)
                local = tmp_dir / f"picker_{int(time.time_ns())}.jpg"
                # content:// URIs are readable via standard file I/O on Android
                # (the Flet runtime bridges them through the OS).
                try:
                    with open(source_path, "rb") as src:
                        with open(local, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                    source_path = str(local)
                except Exception:
                    pass  # keep original path, try anyway
            self.open_crop_editor(source_path, target)

    def open_crop_editor(self, source_path, target):
        """Open a draggable, zoomable crop viewport for avatar or cover media."""
        owner = self.owner
        is_avatar = target == owner.avatar_in
        is_card_bg = target == owner.card_bg_in
        if is_avatar:
            viewport_width, viewport_height = (300, 300)
            output_size = (512, 512)
        elif is_card_bg:
            viewport_width, viewport_height = (336, 112)
            output_size = (1500, 500)
        else:
            viewport_width, viewport_height = (210, 370)
            output_size = (1080, 1920)
        try:
            source_width, source_height = image_size(source_path)
            state = CropState(
                source_width,
                source_height,
                viewport_width,
                viewport_height,
            )
        except Exception as exc:
            owner._save_status.value = f"✗ 无法读取图片：{exc}"
            owner._save_status.color = ft.Colors.RED_400
            if owner.page:
                owner.page.update()
            return

        preview_path = source_path
        try:
            from PIL import Image, ImageOps
            temp_dir = Path(owner.app.paths.data_dir) / "temp_previews"
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_file = temp_dir / f"preview_{time.time_ns()}.jpg"

            with Image.open(source_path) as img:
                img = ImageOps.exif_transpose(img)
                img.thumbnail((1024, 1024))
                img.save(temp_file, "JPEG", quality=80)
                preview_path = str(temp_file)
        except Exception:
            pass

        preview = ft.Image(
            src=preview_path,
            fit=ft.BoxFit.FILL,
            width=state.display_width,
            height=state.display_height,
            left=state.x,
            top=state.y,
            filter_quality=ft.FilterQuality.HIGH,
        )
        hint = ft.Text(
            "拖动图片选择显示区域，滑动缩放",
            size=T.FS_CAPTION,
            color=ft.Colors.ON_SURFACE_VARIANT,
            text_align=ft.TextAlign.CENTER,
        )
        error_text = ft.Text("", size=T.FS_CAPTION, color=ft.Colors.RED_400)

        def refresh_preview():
            preview.width = state.display_width
            preview.height = state.display_height
            preview.left = state.x
            preview.top = state.y
            try:
                preview.update()
            except Exception:
                if owner.page:
                    owner.page.update()

        def on_pan(e):
            delta = getattr(e, "local_delta", None)
            if delta is None:
                return
            state.pan(delta.x, delta.y)
            refresh_preview()

        def on_zoom(e):
            state.set_zoom(float(e.control.value or 1.0))
            refresh_preview()

        viewport = ft.GestureDetector(
            mouse_cursor=ft.MouseCursor.MOVE,
            drag_interval=12,
            on_pan_update=on_pan,
            content=ft.Container(
                content=ft.Stack([preview], clip_behavior=ft.ClipBehavior.HARD_EDGE),
                width=viewport_width,
                height=viewport_height,
                bgcolor=ft.Colors.BLACK,
                border_radius=(viewport_width / 2 if is_avatar else 14),
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                border=T.border_all(2, ft.Colors.with_opacity(0.75, ft.Colors.WHITE)),
            ),
        )
        zoom_slider = ft.Slider(
            min=1.0,
            max=4.0,
            value=1.0,
            divisions=60,
            on_change=on_zoom,
            active_color=ft.Colors.DEEP_PURPLE_400,
        )

        if target == owner.avatar_in:
            title_str = "裁剪头像"
        elif target == owner.card_bg_in:
            title_str = "裁剪名片背景"
        else:
            title_str = "裁剪全局背景"

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title_str),
            content=ft.Column(
                [
                    ft.Container(viewport, alignment=ft.alignment.Alignment.CENTER),
                    hint,
                    ft.Row(
                        [ft.Icon(ft.Icons.ZOOM_OUT_ROUNDED, size=18), zoom_slider,
                         ft.Icon(ft.Icons.ZOOM_IN_ROUNDED, size=18)],
                        spacing=4,
                    ),
                    error_text,
                ],
                width=360,
                spacing=10,
                tight=True,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            actions_alignment=ft.MainAxisAlignment.END,
        )

        def cleanup():
            if preview_path != source_path:
                try:
                    if os.path.exists(preview_path):
                        os.remove(preview_path)
                except Exception:
                    pass

        def cancel(_e):
            if owner.page:
                owner.page.pop_dialog()
            cleanup()

        def confirm(_e):
            try:
                media_dir = Path(owner.app.paths.data_dir) / "profile_media"
                stamp = time.time_ns()
                prefix = "avatar" if target == owner.avatar_in else ("card_bg" if target == owner.card_bg_in else "background")
                filename = f"{prefix}_crop_{stamp}{'.png' if target == owner.avatar_in else '.jpg'}"
                output_path = render_crop(
                    source_path,
                    str(media_dir / filename),
                    state,
                    output_size,
                )
                if owner.page:
                    owner.page.pop_dialog()
                self.apply_cropped_media(output_path, target)
                cleanup()
            except Exception as exc:
                error_text.value = f"裁剪失败：{exc}"
                try:
                    error_text.update()
                except Exception:
                    if owner.page:
                        owner.page.update()

        dialog.actions = [
            ft.TextButton("取消", on_click=cancel),
            ft.FilledButton("使用此区域", icon=ft.Icons.CROP_ROUNDED, on_click=confirm),
        ]
        if owner.page:
            owner.page.show_dialog(dialog)

    def apply_cropped_media(self, output_path, target):
        owner = self.owner
        target.value = output_path
        if target == owner.avatar_in:
            owner._draft_avatar = output_path
            owner._avatar_name = output_path
            owner.avatar_holder.content = T.avatar_circle(
                owner.app.paths.asset_src(output_path), T.AVATAR_LG
            )
            self.build_default_avatars()
            source = "avatar"
        elif target == owner.card_bg_in:
            owner._draft_card_bg = output_path
            owner.cover_container.gradient = None
            owner.cover_container.image = ft.DecorationImage(src=output_path, fit=ft.BoxFit.COVER)
            source = "card_bg"
        else:
            owner._draft_bg = output_path
            owner.bg_fit_dd.value = "cover"
            owner.bg_align_dd.value = "center"
            owner.app.friend_db.set_app_setting("bg_fit", "cover")
            owner.app.friend_db.set_app_setting("bg_align", "center")
            self.apply_background_preview(output_path)
            source = "background"
        if owner.page:
            owner.page.update()
        owner._auto_save(source)

    def apply_background_preview(self, bg_path):
        owner = self.owner
        if bg_path and os.path.exists(bg_path):
            owner.main_layout.image = ft.DecorationImage(
                src=bg_path,
                fit=ft.BoxFit.COVER,
                alignment=ft.alignment.Alignment.CENTER,
                opacity=float(owner.bg_opacity_dd.value or "0.15"),
            )
            owner.cover_container.gradient = None
            owner.cover_container.image = ft.DecorationImage(src=bg_path, fit=ft.BoxFit.COVER)
        else:
            owner.main_layout.image = None
            owner.cover_container.image = None
            owner.cover_container.gradient = T.GRADIENT_PRIMARY

    def build_default_avatars(self):
        owner = self.owner
        owner.default_avatars_row.controls.clear()
        selected_path = (owner.avatar_in.value or "").strip()
        for name, path in owner.DEFAULT_AVATARS:
            selected_asset = owner.app.paths.asset_src(selected_path)
            is_selected = selected_asset == path or selected_path.endswith(name)
            avatar_btn = ft.GestureDetector(
                mouse_cursor=ft.MouseCursor.CLICK,
                on_tap=lambda _e, p=path: self.select_default_avatar(p),
                content=ft.Container(
                    content=T.avatar_circle(owner.app.paths.asset_src(path), 40),
                    padding=2,
                    border_radius=24,
                    border=(
                        T.border_all(2, ft.Colors.DEEP_PURPLE_400)
                        if is_selected
                        else T.border_all(2, ft.Colors.TRANSPARENT)
                    ),
                    animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
                ),
            )
            owner.default_avatars_row.controls.append(avatar_btn)

    def select_default_avatar(self, path):
        owner = self.owner
        owner.avatar_in.value = path
        owner._draft_avatar = path
        owner._avatar_name = path
        owner.avatar_holder.content = T.avatar_circle(
            owner.app.paths.asset_src(path), T.AVATAR_LG
        )
        self.build_default_avatars()
        if owner.page:
            owner.page.update()
        owner._auto_save("avatar")
