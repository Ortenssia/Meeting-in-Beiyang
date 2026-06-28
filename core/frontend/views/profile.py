"""Profile view: avatar, basic info, tags, bio, matching conditions.

Each field auto-saves independently on blur or on explicit interaction,
so there is no single "save" button that can be swallowed by the scroll
container.
"""
import os
import threading
import time
from pathlib import Path

import flet as ft

from .. import theme as T
from ..image_crop import CropState, image_size, render_crop


class TagInput(ft.Column):
    """QQ-style personality tag bubbles with an inline add composer.

    Calls *on_changed* (if set) whenever the tag list is modified so the
    profile view can persist the update automatically.
    """

    TAG_COLORS = [
        (ft.Colors.DEEP_PURPLE_400, ft.Colors.PURPLE_300),
        (ft.Colors.PINK_500, ft.Colors.PINK_300),
        (ft.Colors.BLUE_500, ft.Colors.CYAN_300),
        (ft.Colors.ORANGE_500, ft.Colors.AMBER_300),
        (ft.Colors.GREEN_500, ft.Colors.TEAL_300),
    ]

    def __init__(self, hint="输入后回车，例如：编程、篮球"):
        super().__init__(spacing=T.SP_SM)
        self._tags = []
        self._draft_text = ""
        self.hint = hint
        self.on_changed = None  # callable() fired after add / remove

        self.input = ft.TextField(
            hint_text=hint,
            expand=True,
            on_change=self._on_input_change,
            on_submit=self._add,
            border=ft.InputBorder.NONE,
            content_padding=T.pad_symmetric(horizontal=12, vertical=8),
            prefix_icon=ft.Icons.TAG_ROUNDED,
            bgcolor=ft.Colors.TRANSPARENT,
        )
        self.add_btn = ft.IconButton(
            icon=ft.Icons.ADD_CIRCLE_ROUNDED,
            icon_color=ft.Colors.WHITE,
            icon_size=28,
            bgcolor=ft.Colors.DEEP_PURPLE_500,
            on_click=self._add,
            tooltip="添加标签",
            style=ft.ButtonStyle(shape=ft.CircleBorder()),
        )
        self.chips = ft.Row(spacing=8, run_spacing=8, wrap=True)
        self.controls = [
            ft.Container(
                content=ft.Row(
                    [self.input, self.add_btn],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                border_radius=999,
                bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.SURFACE_CONTAINER_LOW),
                border=T.border_all(1, ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE)),
                padding=T.pad_symmetric(horizontal=8, vertical=4),
            ),
            self.chips,
        ]

    def _on_input_change(self, e):
        self._draft_text = e.control.value or ""

    def _add(self, _e=None):
        raw = (self.input.value or self._draft_text or "").strip()
        if not raw:
            return
        normalized = raw.replace("，", ",").replace("、", ",").replace(" ", ",")
        parts = [p.strip() for p in normalized.split(",") if p.strip()]
        changed = False
        for tag in parts:
            if tag and tag not in self._tags:
                self._tags.append(tag)
                self.chips.controls.append(self._tag_bubble(tag))
                changed = True
        self.input.value = ""
        self._draft_text = ""
        try:
            self.update()
        except Exception:
            pass
        if changed and self.on_changed:
            self.on_changed()

    def _make_remove(self, tag):
        def _remove(e):
            if tag in self._tags:
                self._tags.remove(tag)
            for c in list(self.chips.controls):
                if getattr(c, "data", None) == tag:
                    self.chips.controls.remove(c)
            try:
                self.update()
            except Exception:
                pass
            if self.on_changed:
                self.on_changed()
        return _remove

    def _tag_bubble(self, tag):
        idx = len(self._tags) % len(self.TAG_COLORS)
        left, right = self.TAG_COLORS[idx]
        return ft.Container(
            data=tag,
            content=ft.Row(
                [
                    ft.Text(
                        f"#{tag}",
                        size=13,
                        color=ft.Colors.WHITE,
                        weight=ft.FontWeight.W_700,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.CLOSE_ROUNDED,
                        icon_size=14,
                        icon_color=ft.Colors.WHITE,
                        width=24,
                        height=24,
                        padding=0,
                        on_click=self._make_remove(tag),
                    ),
                ],
                spacing=2,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            gradient=ft.LinearGradient(
                begin=ft.alignment.Alignment.CENTER_LEFT,
                end=ft.alignment.Alignment.CENTER_RIGHT,
                colors=[left, right],
            ),
            border_radius=999,
            padding=T.pad_only(left=14, right=4, top=6, bottom=6),
            shadow=ft.BoxShadow(
                blur_radius=10,
                color=ft.Colors.with_opacity(0.18, left),
                offset=ft.Offset(0, 3),
            ),
        )

    def get_tags(self):
        self._add()
        return list(self._tags)

    def set_tags(self, tags):
        self._tags = []
        self._draft_text = ""
        self.input.value = ""
        self.chips.controls.clear()
        for tag in (tags or []):
            tag = tag.strip()
            if tag and tag not in self._tags:
                self._tags.append(tag)
                self.chips.controls.append(self._tag_bubble(tag))
        try:
            self.update()
        except Exception:
            pass


class ProfileView:
    def __init__(self, app):
        self.app = app
        self.page = app.page

        # Draft values — updated on every keystroke via on_change so that
        # _auto_save always sees the absolute latest text even when on_blur
        # or on_tap_outside fires before a pending value sync.
        self._draft_name = ""
        self._draft_bio = ""
        self._draft_avatar = ""
        self._draft_bg = ""
        self._draft_user_id = ""

        self.profile_display_name = ft.Text("", size=T.FS_TITLE, weight=ft.FontWeight.W_800)
        self.profile_display_id = ft.Text(
            "",
            size=T.FS_CAPTION,
            color=ft.Colors.ON_SURFACE_VARIANT,
            overflow=ft.TextOverflow.ELLIPSIS,
            max_lines=1,
            weight=ft.FontWeight.W_500,
        )
        self.profile_display_id_click = ft.GestureDetector(
            mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=self._copy_id,
            content=self.profile_display_id,
            tooltip="点击复制 ID",
        )

        self.name_in = ft.TextField(
            label="我的昵称",
            on_change=self._on_name_change,
            on_blur=self._on_name_blur,
            on_tap_outside=lambda _e: self._auto_save("name"),
            border_radius=12,
            border_color=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            expand=True,
            height=48,  # Force identical height to ID field
        )
        self.user_id_in = ft.TextField(
            label="用户ID（修改后好友需重新搜索）",
            on_change=lambda e: setattr(self, '_draft_user_id', e.control.value or ''),
            on_blur=lambda _e: self._auto_save("user_id"),
            border_radius=12,
            border_color=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            expand=True,
            height=48,  # Force identical height to name field
            suffix=ft.IconButton(
                icon=ft.Icons.COPY_ROUNDED,
                icon_color=ft.Colors.DEEP_PURPLE_400,
                icon_size=20,
                on_click=lambda _e: self.page.set_clipboard(self.user_id_in.value or ""),
                tooltip="复制 ID",
            ),
        )
        self.avatar_in = ft.TextField(
            label="自定义头像路径",
            on_change=lambda e: setattr(self, '_draft_avatar', e.control.value or ''),
            on_blur=lambda _e: self._auto_save("avatar"),
            border_radius=12,
            border_color=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        )
        self.bg_in = ft.TextField(
            label="自定义背景路径",
            on_change=lambda e: setattr(self, '_draft_bg', e.control.value or ''),
            on_blur=lambda _e: self._auto_save("background"),
            border_radius=12,
            border_color=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        )
        self.bg_fit_dd = ft.Dropdown(
            label="填充模式",
            value="cover",
            options=[
                ft.dropdown.Option("cover", "裁剪铺满"),
                ft.dropdown.Option("contain", "完整包含"),
                ft.dropdown.Option("fill", "拉伸缩放"),
            ],
            border_radius=12,
            border_color=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            height=48,
            expand=True,
        )
        self.bg_fit_dd.on_select = self._on_bg_param_change

        self.bg_align_dd = ft.Dropdown(
            label="对齐位置",
            value="center",
            options=[
                ft.dropdown.Option("center", "居中对齐"),
                ft.dropdown.Option("top", "顶部对齐"),
                ft.dropdown.Option("bottom", "底部对齐"),
                ft.dropdown.Option("left", "靠左对齐"),
                ft.dropdown.Option("right", "靠右对齐"),
            ],
            border_radius=12,
            border_color=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            height=48,
            expand=True,
        )
        self.bg_align_dd.on_select = self._on_bg_param_change

        self.bg_opacity_dd = ft.Dropdown(
            label="背景透明度",
            value="0.15",
            options=[
                ft.dropdown.Option("0.05", "微弱 (5%)"),
                ft.dropdown.Option("0.10", "柔和 (10%)"),
                ft.dropdown.Option("0.15", "清晰 (15%)"),
                ft.dropdown.Option("0.25", "明艳 (25%)"),
                ft.dropdown.Option("0.40", "重彩 (40%)"),
            ],
            border_radius=12,
            border_color=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            height=48,
            expand=True,
        )
        self.bg_opacity_dd.on_select = self._on_bg_param_change

        self.bg_params_row = ft.Row(
            [self.bg_fit_dd, self.bg_align_dd, self.bg_opacity_dd],
            spacing=T.SP_SM,
        )
        self.bio_in = ft.TextField(
            label="个人简介",
            multiline=True,
            min_lines=3,
            max_lines=5,
            on_change=self._on_bio_change,
            on_blur=lambda _e: self._auto_save("bio"),
            on_tap_outside=lambda _e: self._auto_save("bio"),
            border_radius=12,
            border_color=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            hint_text="向大家介绍一下你自己吧…",
        )

        self.tags_input = TagInput("输入兴趣，逗号或回车分割")
        self.req_input = TagInput("必选兴趣（如：计算机）")
        self.opt_input = TagInput("可选兴趣（如：唱歌）")

        # Minimum match count counter component
        self.min_match_value = ft.Text("1", size=14, weight=ft.FontWeight.BOLD)
        self.min_match_row = ft.Row(
            [
                ft.Text("最少匹配标签数", size=T.FS_BODY, color=ft.Colors.ON_SURFACE, weight=ft.FontWeight.W_500),
                ft.Container(expand=True),
                ft.Row(
                    [
                        ft.IconButton(
                            icon=ft.Icons.REMOVE_CIRCLE_OUTLINED,
                            icon_color=ft.Colors.DEEP_PURPLE_400,
                            icon_size=20,
                            on_click=self._on_min_match_decrement,
                            tooltip="减少",
                        ),
                        self.min_match_value,
                        ft.IconButton(
                            icon=ft.Icons.ADD_CIRCLE_OUTLINED,
                            icon_color=ft.Colors.DEEP_PURPLE_400,
                            icon_size=20,
                            on_click=self._on_min_match_increment,
                            tooltip="增加",
                        ),
                    ],
                    spacing=4,
                )
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        self.auto_accept = ft.Switch(
            label="满足标签条件时自动同意好友申请",
            on_change=lambda _e: self._auto_save("conditions"),
            active_color=ft.Colors.DEEP_PURPLE_500,
        )

        # Profile update mode cards component
        self._update_mode_value = "auto"
        self._update_mode_row = ft.Row(spacing=10, expand=True)
        self._update_mode_container = ft.Container(
            content=self._update_mode_row,
            margin=ft.Margin.only(top=4),
        )

        # Inline save feedback (replaces the old status + save button).
        self._save_status = ft.Text(
            "",
            size=T.FS_CAPTION,
            weight=ft.FontWeight.BOLD,
        )
        self._save_spinner = ft.ProgressBar(
            width=60,
            height=3,
            color=ft.Colors.DEEP_PURPLE_400,
            bgcolor=ft.Colors.TRANSPARENT,
            visible=False,
        )

        self._avatar_name = ""

        # Dedicated avatar holder for dynamic updates
        self.avatar_holder = ft.Container(
            content=T.avatar_circle("", T.AVATAR_LG),
            width=T.AVATAR_LG,
            height=T.AVATAR_LG,
        )

        self.cover_container = ft.Container(
            height=100,
            border_radius=T.R_LG,
            gradient=T.GRADIENT_PRIMARY,
            border=T.border_all(1, ft.Colors.with_opacity(0.1, ft.Colors.WHITE)),
        )

        self.file_picker = getattr(app, "profile_file_picker", None) or ft.FilePicker()

        self.DEFAULT_AVATARS = list(app.paths.default_avatar_assets)
        self.default_avatars_row = ft.Row(
            spacing=T.SP_MD, alignment=ft.MainAxisAlignment.START, height=48
        )

        # System settings tab controls
        self.settings_device_name = ft.Text("--", size=T.FS_BODY, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE)
        self.settings_tcp_port = ft.TextField(
            label="TCP 端口", value="7779",
            keyboard_type=ft.KeyboardType.NUMBER, width=120,
            border_radius=10, border_color=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            content_padding=10,
        )
        self.settings_udp_port = ft.Text("8890", size=T.FS_BODY, weight=ft.FontWeight.W_500, color=ft.Colors.ON_SURFACE_VARIANT)
        self.settings_tcp_hint = ft.Text("", size=T.FS_CAPTION)
        self.settings_pending_count = ft.Text("0 条消息", size=T.FS_BODY, weight=ft.FontWeight.BOLD, color=ft.Colors.DEEP_PURPLE_400)
        self.settings_receive_dir = ft.Text("", size=T.FS_CAPTION, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True, overflow=ft.TextOverflow.ELLIPSIS)
        self._theme_selector_row = ft.Container()

        self._built = None
        self._loading = False  # guard against save-during-load cycles
        self._save_pending = False  # debounce flag

    # -- build ---------------------------------------------------------------

    def build(self):
        if self._built is not None:
            return self._built
        self._built = self._create_view()
        return self._built

    def _create_view(self):
        # Premium profile identity card for the left column
        self.identity_card = ft.Container(
            content=ft.Stack(
                [
                    self.cover_container,
                    ft.Container(
                        content=self.avatar_holder,
                        top=60,
                        left=24,
                    ),
                    ft.Container(
                        content=ft.Column(
                            [
                                self.profile_display_name,
                                self.profile_display_id_click,  # GestureDetector wrapping self.profile_display_id
                            ],
                            spacing=1,
                            tight=True,
                        ),
                        top=104,
                        left=112,
                        width=188,  # Truncate long IDs with ellipsis
                    )
                ],
                height=150,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            border_radius=T.R_LG,
            border=T.border_all(1, ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE)),
        )

        # Inline save indicator row
        self.save_indicator = ft.Row(
            [
                self._save_spinner,
                self._save_status,
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # Left Column: Identity Card, Theme Customization, System Info
        self.left_panel = ft.Column(
            [
                self.identity_card,
                ft.Container(height=4),
                ft.Text("个性化主题", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.PRIMARY),
                ft.Text("点击选择系统主题色：", size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                self._theme_selector_row,
                
                ft.Divider(height=24, thickness=1, color=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE)),
                
                ft.Row(
                    [
                        ft.Icon(ft.Icons.AUTO_AWESOME_ROUNDED, color=ft.Colors.DEEP_PURPLE_400, size=18),
                        ft.Text("系统信息", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.PRIMARY),
                    ],
                    spacing=6,
                ),
                ft.Text("相识北洋 版本 3.0.0", size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text("P2P 局域网无网社交平台", size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text("洪泛中继路由 · 离线消息漫游", size=10, color=ft.Colors.ON_SURFACE_VARIANT),
            ],
            width=320,
            spacing=12,
        )

        # Use a list of containers to dynamically manage right padding to offset from the Column scrollbar
        self._section_containers = []
        self._right_panel_padding = ft.Padding.only(right=24)

        def make_section(content):
            c = ft.Container(content=content, padding=self._right_panel_padding)
            self._section_containers.append(c)
            return c

        # Right Column: Unified scrolling form sections with elegant divider lines
        self.right_panel = ft.Column(
            [
                # Section 1: 基本资料
                make_section(ft.Column([
                    ft.Text("基本资料", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.PRIMARY),
                    ft.Row(
                        [self.name_in, self.user_id_in],
                        spacing=T.SP_MD,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                    ft.Text(
                        "用户ID留空则自动生成；修改后旧ID将不再被好友识别",
                        size=11,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    self._path_row("头像路径", self.avatar_in, "选择并裁剪"),
                    self.default_avatars_row,
                ], spacing=12)),
                
                ft.Divider(height=32, thickness=1, color=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE)),
                
                # Section 2: 个性展示
                make_section(ft.Column([
                    ft.Text("个性展示", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.PRIMARY),
                    self.tags_input,
                    ft.Container(height=4),
                    self.bio_in,
                ], spacing=12)),
                
                ft.Divider(height=32, thickness=1, color=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE)),
                
                # Section 3: 自动同意匹配条件与同步偏好
                make_section(ft.Column([
                    ft.Text("自动同意匹配条件", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.PRIMARY),
                    ft.Text(
                        "配置必选与可选交友标签以开启自动匹配通过：",
                        size=T.FS_CAPTION,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    self.req_input,
                    self.opt_input,
                    ft.Row(
                        [
                            ft.Container(content=self.min_match_row, expand=True),
                            self.auto_accept,
                        ],
                        spacing=20,
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(height=8),
                    self._update_mode_container,
                ], spacing=12)),
                
                ft.Divider(height=32, thickness=1, color=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE)),
                
                # Section 4: 网络与设备
                make_section(ft.Column([
                    ft.Text("网络与设备", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.PRIMARY),
                    self._setting_row("本机主机名", self.settings_device_name),
                    ft.Row(
                        [
                            ft.Text("TCP 监听端口", size=T.FS_BODY, color=ft.Colors.ON_SURFACE_VARIANT, width=100),
                            self.settings_tcp_port,
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
                    self.settings_tcp_hint,
                    self._setting_row("UDP 广播端口", self.settings_udp_port),
                ], spacing=12)),
                
                ft.Divider(height=32, thickness=1, color=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE)),
                
                # Section 5: 文件接收与背景
                make_section(ft.Column([
                    ft.Text("文件接收与背景", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.PRIMARY),
                    self._setting_row("保存位置", self.settings_receive_dir),
                    ft.Row(
                        [
                            ft.ElevatedButton(
                                "选择保存目录",
                                icon=ft.Icons.FOLDER_OPEN_ROUNDED,
                                on_click=self._choose_receive_dir,
                                bgcolor=ft.Colors.DEEP_PURPLE_500,
                                color=ft.Colors.WHITE,
                                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
                            ),
                        ]
                    ),
                    ft.Divider(height=24, thickness=1, color=ft.Colors.with_opacity(0.06, ft.Colors.ON_SURFACE)),
                    self._path_row("背景图片", self.bg_in, "选择并裁剪"),
                    self.bg_params_row,
                ], spacing=12)),
            ],
            spacing=T.SP_MD,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        self.main_layout = ft.Container(
            expand=True,
            padding=ft.Padding.only(left=20, right=20, top=10, bottom=20),
        )
        
        return self.main_layout

    def _path_row(self, label, control, pick_label):
        async def browse(_e):
            await self._browse(control)

        btn = ft.OutlinedButton(
            pick_label,
            on_click=browse,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
        )
        control.expand = True
        return ft.Row(
            [control, btn],
            spacing=T.SP_SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    async def _browse(self, target):
        try:
            import tkinter as tk
        except ImportError:
            await self._browse_flet(target)
            return

        def _do_pick():
            from tkinter import filedialog

            root = self.app.get_tk_root()
            if root:
                root.attributes("-topmost", True)
            file_path = filedialog.askopenfilename(
                title="选择图片",
                parent=root,
                filetypes=[("图片文件", "*.png;*.jpg;*.jpeg;*.bmp")],
            )
            if file_path:
                self._open_crop_editor(file_path, target)

        threading.Thread(target=_do_pick, daemon=True).start()

    async def _browse_flet(self, target):
        """Use Flet FilePicker for platforms without tkinter (Android)."""
        picker = getattr(self.app, "profile_file_picker", None)
        if not picker:
            picker = ft.FilePicker()
            self.app.profile_file_picker = picker
        page = self.page
        if page and picker not in page.services:
            page.services.append(picker)

        files = await picker.pick_files(
            dialog_title="选择图片",
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["png", "jpg", "jpeg", "bmp"],
        )
        if files and files[0].path:
            file_path = files[0].path
            self._open_crop_editor(file_path, target)

    def _open_crop_editor(self, source_path, target):
        """Open a draggable, zoomable crop viewport for avatar or cover media."""
        is_avatar = target == self.avatar_in
        viewport_width, viewport_height = ((300, 300) if is_avatar else (336, 112))
        output_size = ((512, 512) if is_avatar else (1500, 500))
        try:
            source_width, source_height = image_size(source_path)
            state = CropState(
                source_width,
                source_height,
                viewport_width,
                viewport_height,
            )
        except Exception as exc:
            self._save_status.value = f"✗ 无法读取图片：{exc}"
            self._save_status.color = ft.Colors.RED_400
            if self.page:
                self.page.update()
            return

        # Generate a smaller preview version of the image to send to Flet UI
        preview_path = source_path
        try:
            from PIL import Image, ImageOps
            temp_dir = Path(self.app.paths.data_dir) / "temp_previews"
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_file = temp_dir / f"preview_{time.time_ns()}.jpg"
            
            with Image.open(source_path) as img:
                img = ImageOps.exif_transpose(img)
                # Downscale to max 1024px while keeping aspect ratio
                img.thumbnail((1024, 1024))
                img.save(temp_file, "JPEG", quality=80)
                preview_path = str(temp_file)
        except Exception as exc:
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
                if self.page:
                    self.page.update()

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

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("裁剪头像" if is_avatar else "裁剪个人背景"),
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
            if self.page:
                self.page.pop_dialog()
            cleanup()

        def confirm(_e):
            try:
                media_dir = Path(self.app.paths.data_dir) / "profile_media"
                stamp = time.time_ns()
                filename = f"{'avatar' if is_avatar else 'background'}_crop_{stamp}{'.png' if is_avatar else '.jpg'}"
                output_path = render_crop(
                    source_path,
                    str(media_dir / filename),
                    state,
                    output_size,
                )
                if self.page:
                    self.page.pop_dialog()
                self._apply_cropped_media(output_path, target)
                cleanup()
            except Exception as exc:
                error_text.value = f"裁剪失败：{exc}"
                try:
                    error_text.update()
                except Exception:
                    if self.page:
                        self.page.update()

        dialog.actions = [
            ft.TextButton("取消", on_click=cancel),
            ft.FilledButton("使用此区域", icon=ft.Icons.CROP_ROUNDED, on_click=confirm),
        ]
        if self.page:
            self.page.show_dialog(dialog)

    def _apply_cropped_media(self, output_path, target):
        target.value = output_path
        if target == self.avatar_in:
            self._draft_avatar = output_path
            self._avatar_name = output_path
            self.avatar_holder.content = T.avatar_circle(
                self.app.paths.asset_src(output_path), T.AVATAR_LG
            )
            self._build_default_avatars()
            source = "avatar"
        else:
            self._draft_bg = output_path
            # A crop already defines the composition; keep rendering centered.
            self.bg_fit_dd.value = "cover"
            self.bg_align_dd.value = "center"
            self.app.friend_db.set_app_setting("bg_fit", "cover")
            self.app.friend_db.set_app_setting("bg_align", "center")
            self._apply_background_preview(output_path)
            source = "background"
        if self.page:
            self.page.update()
        self._auto_save(source)

    def _apply_background_preview(self, bg_path):
        if bg_path and os.path.exists(bg_path):
            self.main_layout.image = ft.DecorationImage(
                src=bg_path,
                fit=self._get_bg_fit(self.bg_fit_dd.value),
                alignment=self._get_bg_align(self.bg_align_dd.value),
                opacity=float(self.bg_opacity_dd.value or "0.15"),
            )
            self.cover_container.gradient = None
            self.cover_container.image = ft.DecorationImage(src=bg_path, fit=ft.BoxFit.COVER)
        else:
            self.main_layout.image = None
            self.cover_container.image = None
            self.cover_container.gradient = T.GRADIENT_PRIMARY

    def _build_default_avatars(self):
        self.default_avatars_row.controls.clear()
        selected_path = (self.avatar_in.value or "").strip()
        for name, path in self.DEFAULT_AVATARS:
            selected_asset = self.app.paths.asset_src(selected_path)
            is_selected = selected_asset == path or selected_path.endswith(name)
            avatar_btn = ft.GestureDetector(
                mouse_cursor=ft.MouseCursor.CLICK,
                on_tap=lambda _e, p=path: self._select_default_avatar(p),
                content=ft.Container(
                    content=T.avatar_circle(self.app.paths.asset_src(path), 40),
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
            self.default_avatars_row.controls.append(avatar_btn)

    def _select_default_avatar(self, path):
        self.avatar_in.value = path
        self._draft_avatar = path
        self._avatar_name = path
        self.avatar_holder.content = T.avatar_circle(
            self.app.paths.asset_src(path), T.AVATAR_LG
        )
        self._build_default_avatars()
        if self.page:
            self.page.update()
        self._auto_save("avatar")

    # -- lifecycle -----------------------------------------------------------

    def on_enter(self):
        self._load()

    def _load(self):
        self._loading = True
        try:
            profile = self.app.get_my_profile()
            if not profile:
                return
            self._avatar_name = profile.get("name", "")
            if profile.get("avatar"):
                self.avatar_in.value = profile.get("avatar", "")
                self._avatar_name = profile.get("avatar", "")
            self.name_in.value = profile.get("name", "")
            self.user_id_in.value = profile.get("user_id", "")
            self.profile_display_name.value = profile.get("name", "")
            self.profile_display_id.value = f"@{profile.get('user_id', '')}"
            self.bio_in.value = profile.get("bio", "")
            self.bg_in.value = profile.get("background", "")
            # Sync draft values so _auto_save uses the loaded data.
            self._draft_name = profile.get("name", "")
            self._draft_user_id = profile.get("user_id", "")
            self._draft_bio = profile.get("bio", "")
            self._draft_avatar = profile.get("avatar", "")
            self._draft_bg = profile.get("background", "")
            self.tags_input.set_tags(profile.get("tags", []))
            cond = profile.get("conditions", {})
            self.req_input.set_tags(cond.get("required_tags", []))
            self.opt_input.set_tags(cond.get("optional_tags", []))
            self.min_match_value.value = str(cond.get("min_match_count", 1))
            self.auto_accept.value = cond.get("auto_accept", False)
            # Profile update mode is an app-level setting, not part of conditions.
            mode = self.app.friend_db.get_app_setting("profile_update_mode", "auto")
            self._update_mode_value = mode if mode in ("auto", "manual") else "auto"
            self._build_update_mode_selector()

            # Load settings values
            info = self.app.get_local_device_info()
            if info:
                self.settings_device_name.value = info.get("name", "--")
            self.settings_pending_count.value = f"{self.app.get_pending_message_count() or 0} 条消息"
            if hasattr(self.app, "tcp_port"):
                self.settings_tcp_port.value = str(self.app.tcp_port)
            self.settings_receive_dir.value = self.app.get_receive_dir()

            self._build_default_avatars()

            self.avatar_holder.content = T.avatar_circle(
                self.app.paths.asset_src(self._avatar_name), T.AVATAR_LG
            )

            # Load custom background configuration
            bg_fit = self.app.friend_db.get_app_setting("bg_fit") or "cover"
            bg_align = self.app.friend_db.get_app_setting("bg_align") or "center"
            bg_opacity = self.app.friend_db.get_app_setting("bg_opacity") or "0.15"

            self.bg_fit_dd.value = bg_fit
            self.bg_align_dd.value = bg_align
            self.bg_opacity_dd.value = bg_opacity

            # Apply the selected image both as the page ambience and profile cover.
            bg_path = profile.get("background", "").strip()
            self.cover_container.content = None
            self._apply_background_preview(bg_path)

            self._theme_selector_row.content = self._build_theme_selector()

            if self.page:
                self.page.update()
        finally:
            self._loading = False

        # Wire tag change callbacks — done AFTER loading so the initial
        # set_tags calls above don't trigger spurious saves.
        self.tags_input.on_changed = lambda: self._auto_save("tags")
        self.req_input.on_changed = lambda: self._auto_save("conditions")
        self.opt_input.on_changed = lambda: self._auto_save("conditions")

        # Responsive window size listener wiring
        if self.page:
            self.page.on_resized = self._on_page_resize
            self._update_responsive_layout()

    # -- auto-save engine ----------------------------------------------------

    # -- event handlers ------------------------------------------------------

    def _on_name_change(self, e):
        self._draft_name = e.control.value or ""
        self.profile_display_name.value = self._draft_name
        # Update avatar preview dynamically as the name changes.
        avatar_path = (self.avatar_in.value or "").strip()
        self._avatar_name = (
            avatar_path
            if avatar_path.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp"))
            else (self._draft_name or "")
        )
        self.avatar_holder.content = T.avatar_circle(
            self.app.paths.asset_src(self._avatar_name), T.AVATAR_LG
        )
        if self.page:
            self.page.update()

    def _on_name_blur(self, e):
        """Save profile when the user finishes editing their nickname."""
        self._auto_save("name")

    def _on_bio_change(self, e):
        self._draft_bio = e.control.value or ""

    def _save_bio(self, e):
        """Dedicated save button for the signature/bio field."""
        name = (self._draft_name or self.name_in.value or "").strip()
        if not name:
            self._save_status.value = "✗ 请先填写昵称"
            self._save_status.color = ft.Colors.RED_400
            if self.page:
                self.page.update()
            return

        profile = {
            "name": name,
            "user_id": (self._draft_user_id or self.user_id_in.value or "").strip(),
            "tags": self.tags_input.get_tags(),
            "bio": (self._draft_bio or self.bio_in.value or "").strip(),
            "avatar": (self._draft_avatar or self.avatar_in.value or "").strip(),
            "background": (self._draft_bg or self.bg_in.value or "").strip(),
            "conditions": {
                "required_tags": self.req_input.get_tags(),
                "optional_tags": self.opt_input.get_tags(),
                "min_match_count": int(self.min_match_value.value or "1"),
                "auto_accept": self.auto_accept.value,
            },
        }
        try:
            ok = self.app.save_profile(profile)
            # Persist profile update mode separately (app setting, not profile field).
            mode = getattr(self, "_update_mode_value", "auto")
            self.app.friend_db.set_app_setting("profile_update_mode", mode)
            if ok:
                self._save_status.value = "✓ 签名已保存"
                self._save_status.color = ft.Colors.GREEN_400
            else:
                self._save_status.value = "✗ 保存失败"
                self._save_status.color = ft.Colors.RED_400
        except Exception as exc:
            self._save_status.value = f"✗ {exc}"
            self._save_status.color = ft.Colors.RED_400
        if self.page:
            self.page.update()

        def _clear():
            time.sleep(2.5)
            try:
                if self._save_status.value.startswith("✓"):
                    self._save_status.value = ""
                if self.page:
                    self.page.update()
            except Exception:
                pass

        threading.Thread(target=_clear, daemon=True).start()

    def _on_bg_param_change(self, _e):
        bg_path = (self.bg_in.value or "").strip()
        self._apply_background_preview(bg_path)
        if self.page:
            self.page.update()
        
        # Save settings
        self.app.friend_db.set_app_setting("bg_fit", self.bg_fit_dd.value)
        self.app.friend_db.set_app_setting("bg_align", self.bg_align_dd.value)
        self.app.friend_db.set_app_setting("bg_opacity", self.bg_opacity_dd.value)

    def _get_bg_fit(self, val):
        if val == "contain":
            return ft.BoxFit.CONTAIN
        if val == "fill":
            return ft.BoxFit.FILL
        return ft.BoxFit.COVER

    def _get_bg_align(self, val):
        if val == "top":
            return ft.alignment.top_center
        if val == "bottom":
            return ft.alignment.bottom_center
        if val == "left":
            return ft.alignment.center_left
        if val == "right":
            return ft.alignment.center_right
        return ft.alignment.center

    # -- auto-save engine ----------------------------------------------------

    def _auto_save(self, source: str = ""):
        """Persist the current form state to the database.

        Each field calls this independently on blur / change, so the user
        never needs a global "save" button.  Values are read from the
        continuously-updated draft variables rather than the controls
        directly, guarding against any event-ordering edge case where
        on_blur/on_tap_outside fires before the last on_change value sync.
        """
        if self._loading:
            return
        if self._save_pending:
            return
        self._save_pending = True

        # Use draft values (updated on every keystroke via on_change) so we
        # always persist the latest user input.
        name = (self._draft_name or self.name_in.value or "").strip()
        if not name:
            self._save_pending = False
            return

        profile = {
            "name": name,
            "user_id": (self._draft_user_id or self.user_id_in.value or "").strip(),
            "tags": self.tags_input.get_tags(),
            "bio": (self._draft_bio or self.bio_in.value or "").strip(),
            "avatar": (self._draft_avatar or self.avatar_in.value or "").strip(),
            "background": (self._draft_bg or self.bg_in.value or "").strip(),
            "conditions": {
                "required_tags": self.req_input.get_tags(),
                "optional_tags": self.opt_input.get_tags(),
                "min_match_count": int(self.min_match_value.value or "1"),
                "auto_accept": self.auto_accept.value,
            },
        }

        try:
            self._save_spinner.visible = True
            self._save_status.value = ""
            if self.page:
                self.page.update()

            ok = self.app.save_profile(profile)
            mode = getattr(self, "_update_mode_value", "auto")
            self.app.friend_db.set_app_setting("profile_update_mode", mode)
            if ok:
                self._save_status.value = "✓ 已保存"
                self._save_status.color = ft.Colors.GREEN_400
                self.profile_display_name.value = name
                self.profile_display_id.value = f"@{profile['user_id']}"
            else:
                self._save_status.value = "✗ 保存失败"
                self._save_status.color = ft.Colors.RED_400
        except Exception as exc:
            self._save_status.value = f"✗ {exc}"
            self._save_status.color = ft.Colors.RED_400
        finally:
            self._save_spinner.visible = False
            self._save_pending = False  # release immediately so next blur saves
            if self.page:
                self.page.update()

        # Clear the success indicator after a few seconds.
        def _clear_status():
            time.sleep(2.5)
            try:
                if self._save_status.value.startswith("✓"):
                    self._save_status.value = ""
                if self.page:
                    self.page.update()
            except Exception:
                pass

        threading.Thread(target=_clear_status, daemon=True).start()

    def _on_min_match_decrement(self, _e):
        val = int(self.min_match_value.value or "1")
        if val > 1:
            val -= 1
            self.min_match_value.value = str(val)
            if self.page:
                self.page.update()
            self._auto_save("conditions")

    def _on_min_match_increment(self, _e):
        val = int(self.min_match_value.value or "1")
        if val < 10:
            val += 1
            self.min_match_value.value = str(val)
            if self.page:
                self.page.update()
            self._auto_save("conditions")

    def _build_update_mode_selector(self):
        current_mode = getattr(self, "_update_mode_value", "auto")
        is_auto = (current_mode == "auto")
        
        auto_card = ft.GestureDetector(
            on_tap=lambda _: self._set_update_mode("auto"),
            mouse_cursor=ft.MouseCursor.CLICK,
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.SYNC_ROUNDED, 
                                    color=ft.Colors.WHITE if is_auto else ft.Colors.DEEP_PURPLE_400, 
                                    size=16
                                ),
                                ft.Text(
                                    "自动同步", 
                                    size=13, 
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.WHITE if is_auto else ft.Colors.ON_SURFACE
                                ),
                            ],
                            spacing=6,
                        ),
                        ft.Text(
                            "好友更新资料后在后台自动更新你的本地缓存",
                            size=10,
                            color=ft.Colors.with_opacity(0.8, ft.Colors.WHITE) if is_auto else ft.Colors.ON_SURFACE_VARIANT,
                        )
                    ],
                    spacing=4,
                    tight=True,
                ),
                bgcolor=ft.Colors.DEEP_PURPLE_500 if is_auto else ft.Colors.SURFACE_CONTAINER,
                border=T.border_all(1.5, ft.Colors.DEEP_PURPLE_400 if is_auto else ft.Colors.with_opacity(0.1, ft.Colors.ON_SURFACE)),
                border_radius=10,
                padding=12,
                expand=True,
            )
        )

        is_manual = (current_mode == "manual")
        manual_card = ft.GestureDetector(
            on_tap=lambda _: self._set_update_mode("manual"),
            mouse_cursor=ft.MouseCursor.CLICK,
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.TOUCH_APP_ROUNDED, 
                                    color=ft.Colors.WHITE if is_manual else ft.Colors.DEEP_PURPLE_400, 
                                    size=16
                                ),
                                ft.Text(
                                    "手动请求", 
                                    size=13, 
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.WHITE if is_manual else ft.Colors.ON_SURFACE
                                ),
                            ],
                            spacing=6,
                        ),
                        ft.Text(
                            "有更新时显示红点提示，由你决定何时手动同步",
                            size=10,
                            color=ft.Colors.with_opacity(0.8, ft.Colors.WHITE) if is_manual else ft.Colors.ON_SURFACE_VARIANT,
                        )
                    ],
                    spacing=4,
                    tight=True,
                ),
                bgcolor=ft.Colors.DEEP_PURPLE_500 if is_manual else ft.Colors.SURFACE_CONTAINER,
                border=T.border_all(1.5, ft.Colors.DEEP_PURPLE_400 if is_manual else ft.Colors.with_opacity(0.1, ft.Colors.ON_SURFACE)),
                border_radius=10,
                padding=12,
                expand=True,
            )
        )

        self._update_mode_row.controls = [auto_card, manual_card]
        return self._update_mode_row

    def _set_update_mode(self, mode):
        self._update_mode_value = mode
        self._build_update_mode_selector()
        if self.page:
            self.page.update()
        self._auto_save("profile_update_mode")

    def _copy_id(self, _e):
        clean_id = (self.profile_display_id.value or "").lstrip("@")
        if clean_id:
            if self.page:
                self.page.set_clipboard(clean_id)
            self._save_status.value = "✓ ID已复制"
            self._save_status.color = ft.Colors.GREEN_400
            if self.page:
                self.page.update()
            
            def _clear():
                time.sleep(2)
                try:
                    if self._save_status.value == "✓ ID已复制":
                        self._save_status.value = ""
                        if self.page:
                            self.page.update()
                except Exception:
                    pass
            threading.Thread(target=_clear, daemon=True).start()

    def _on_page_resize(self, _e):
        self._update_responsive_layout()

    def _update_responsive_layout(self):
        if not self.main_layout or not self.main_layout.page:
            return
            
        width = self.page.width if self.page else 1000
        
        if width < 850:
            # Stacked vertical mode (e.g. narrow windows)
            self.left_panel.width = None
            
            # Disable right panel internal scroll to avoid nested scrollbars
            self.right_panel.scroll = None
            self.right_panel.expand = False
            
            # Clear section padding so fields take up full width
            self._right_panel_padding = None
            for c in getattr(self, "_section_containers", []):
                c.padding = None
            
            # Combined single scrolling column
            stacked_content = ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("个人资料与设置", size=T.FS_HEADER, weight=ft.FontWeight.W_800),
                            ft.Container(expand=1),
                            self.save_indicator,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Container(height=4),
                    self.left_panel,
                    ft.Divider(height=32, thickness=1, color=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE)),
                    self.right_panel,
                ],
                spacing=20,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
            )
            self.main_layout.content = stacked_content
        else:
            # Side-by-side desktop mode
            self.left_panel.width = 320
            
            # Enable right panel internal scroll
            self.right_panel.scroll = ft.ScrollMode.AUTO
            self.right_panel.expand = True
            
            # Set section padding to shift content left, leaving room for the scrollbar
            self._right_panel_padding = ft.Padding.only(right=24)
            for c in getattr(self, "_section_containers", []):
                c.padding = self._right_panel_padding
            
            side_by_side = ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("个人资料与设置", size=T.FS_HEADER, weight=ft.FontWeight.W_800),
                            ft.Container(expand=1),
                            self.save_indicator,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Container(height=4),
                    ft.Row(
                        [
                            self.left_panel,
                            self.right_panel,
                        ],
                        spacing=24,
                        alignment=ft.MainAxisAlignment.START,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        expand=True,
                    ),
                ],
                spacing=T.SP_SM,
                expand=True,
            )
            self.main_layout.content = side_by_side

        try:
            self.main_layout.update()
        except Exception:
            pass

    def _build_theme_selector(self):
        if not hasattr(self, "_theme_buttons"):
            self._theme_buttons = {}
            self._theme_row = ft.Row(spacing=10, wrap=True)

            for key, details in T.THEME_COLORS.items():
                container = ft.Container(
                    width=36,
                    height=36,
                    border_radius=18,
                    bgcolor=details["seed"],
                    tooltip=details["name"],
                    alignment=ft.alignment.Alignment.CENTER,
                )
                btn = ft.GestureDetector(
                    mouse_cursor=ft.MouseCursor.CLICK,
                    on_tap=lambda _e, k=key: self._on_select_theme(k),
                    content=container,
                )
                self._theme_buttons[key] = (btn, container)
                self._theme_row.controls.append(btn)

        current_theme = self.app.friend_db.get_app_setting("theme_color", "DEEP_PURPLE")
        for key, (btn, container) in self._theme_buttons.items():
            is_selected = (key == current_theme)
            container.border = T.border_all(3, ft.Colors.WHITE) if is_selected else T.border_all(1.5, ft.Colors.with_opacity(0.15, ft.Colors.ON_SURFACE))
            container.shadow = T.SHADOW_GLOW if is_selected else None
            container.content = ft.Icon(ft.Icons.CHECK_ROUNDED, color=ft.Colors.WHITE, size=16) if is_selected else None

        return self._theme_row

    def _on_select_theme(self, color_key):
        self.app.friend_db.set_app_setting("theme_color", color_key)
        self.app.update_theme_and_background()
        self._build_theme_selector()
        self._load()

    def _build_settings_tab(self):
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
                about_card,
                T.surface_card(
                    T.section_title("个性化主题"),
                    ft.Text("点击选择系统主题色：", size=T.FS_BODY, color=ft.Colors.ON_SURFACE_VARIANT),
                    self._theme_selector_row,
                ),
                T.surface_card(
                    T.section_title("自定义背景"),
                    self._path_row("背景图片", self.bg_in, "选择并裁剪"),
                ),
                T.surface_card(
                    T.section_title("网络与设备"),
                    self._setting_row("本机主机名", self.settings_device_name),
                    ft.Row(
                        [
                            ft.Text("TCP 端口号", size=T.FS_BODY,
                                    color=ft.Colors.ON_SURFACE_VARIANT, width=100),
                            self.settings_tcp_port,
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
                    self.settings_tcp_hint,
                    self._setting_row("UDP 广播端口", self.settings_udp_port),
                ),
                T.surface_card(
                    T.section_title("文件接收"),
                    self._setting_row("保存位置", self.settings_receive_dir),
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
                        trailing=self.settings_pending_count,
                        on_click=lambda _e: self._clear_pending(),
                    ),
                ),
            ],
            spacing=T.SP_MD,
            scroll=ft.ScrollMode.AUTO,
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

    def _save_tcp(self, _e):
        try:
            port = int((self.settings_tcp_port.value or "").strip())
            if port < 1024 or port > 65535:
                self.settings_tcp_hint.value = "❌ 端口范围应在 1024-65535"
                self.settings_tcp_hint.color = ft.Colors.RED_400
                self.page.update()
                return
            self.app.set_tcp_port(port)
            self.settings_tcp_hint.value = f"✨ 端口已改为 {port}（将在应用重启后生效）"
            self.settings_tcp_hint.color = ft.Colors.GREEN_400
        except ValueError:
            self.settings_tcp_hint.value = "❌ 请输入有效的数字端口"
            self.settings_tcp_hint.color = ft.Colors.RED_400
        self.page.update()

        def _clear():
            time.sleep(3)
            self.settings_tcp_hint.value = ""
            try:
                self.page.update()
            except Exception:
                pass
        threading.Thread(target=_clear, daemon=True).start()

    async def _choose_receive_dir(self, _e):
        try:
            import tkinter as tk
        except ImportError:
            await self._choose_receive_dir_flet()
            return

        def _do_pick():
            from tkinter import filedialog

            root = self.app.get_tk_root()
            if root:
                root.attributes("-topmost", True)
            selected = filedialog.askdirectory(
                title="选择接收文件保存目录",
                initialdir=self.app.get_receive_dir(),
                parent=root,
            )
            if selected:
                self._apply_receive_dir(selected)

        threading.Thread(target=_do_pick, daemon=True).start()

    async def _choose_receive_dir_flet(self):
        picker = getattr(self.app, "receive_dir_picker", None)
        if not picker:
            picker = ft.FilePicker()
            self.app.receive_dir_picker = picker
        picker.on_result = self._on_receive_dir_selected
        page = self.page
        if page and picker not in page.services:
            page.services.append(picker)
        await picker.get_directory_path(
            dialog_title="选择接收文件保存目录",
            initial_directory=self.app.get_receive_dir(),
        )

    def _on_receive_dir_selected(self, e):
        if e.path:
            self._apply_receive_dir(e.path)

    def _reset_receive_dir(self, _e):
        self._apply_receive_dir(str(self.app.paths.received_files_dir))

    def _apply_receive_dir(self, directory):
        try:
            import os
            os.makedirs(directory, exist_ok=True)
            resolved = self.app.set_receive_dir(directory)
            self.settings_receive_dir.value = resolved
            self.settings_tcp_hint.value = "✨ 文件保存位置已更新"
            self.settings_tcp_hint.color = ft.Colors.GREEN_400
        except Exception as exc:
            self.settings_tcp_hint.value = f"❌ 保存位置更新失败: {exc}"
            self.settings_tcp_hint.color = ft.Colors.RED_400
        if self.page:
            self.page.update()

    def _clear_chat(self):
        def do_clear(_e):
            dlg.open = False
            for f in self.app.get_all_friends():
                self.app.clear_chat_history(f.get("name", ""))
            self.settings_tcp_hint.value = "✨ 本地聊天记录清理成功"
            self.settings_tcp_hint.color = ft.Colors.GREEN_400
            self.page.update()

        self._confirm("确定清除所有聊天记录吗？此操作将彻底擦除本地消息历史，且不可撤销。",
                      on_ok=do_clear, ok_text="确认清空")

    def _clear_pending(self):
        def do_clear(_e):
            dlg.open = False
            for f in self.app.get_all_friends():
                self.app.clear_pending_messages(f.get("name", ""))
            self.settings_pending_count.value = "0 条消息"
            self.settings_tcp_hint.value = "✨ 离线待发送消息队列已清空"
            self.settings_tcp_hint.color = ft.Colors.GREEN_400
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
