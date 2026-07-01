"""Profile view: avatar, basic info, tags, bio, matching conditions.

Each field auto-saves independently on blur or on explicit interaction,
so there is no single "save" button that can be swallowed by the scroll
container.
"""
import os
import threading
import time

import flet as ft

from core.backend.services.update_service import default_manifest_url

from .. import theme as T
from .profile_media_controller import ProfileMediaController
from .profile_settings import ProfileSettingsControls, ProfileSettingsPanel
from .profile_settings_controller import ProfileSettingsController
from .profile_tags import TagInput
from .profile_update_controller import ProfileUpdateController


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
        self._draft_card_bg = ""
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
        self.card_bg_in = ft.TextField(
            label="自定义名片背景路径",
            on_change=lambda e: setattr(self, '_draft_card_bg', e.control.value or ''),
            on_blur=lambda _e: self._auto_save("card_bg"),
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

        self.bg_opacity_dd.label = None
        self.bg_opacity_dd.hint_text = "选择背景透明度..."
        self.bg_params_row = ft.Column(
            [
                ft.Text("背景透明度", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE_VARIANT),
                self.bg_opacity_dd,
            ],
            spacing=4,
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
        self._auto_accept_layout = ft.Container()

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

        self.settings_controls = ProfileSettingsControls(self)
        self.settings_panel = ProfileSettingsPanel(self)
        self.media_controller = ProfileMediaController(self)
        self.settings_controller = ProfileSettingsController(self)
        self.update_controller = ProfileUpdateController(self)
        self.settings_controls.attach()

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
                ft.Text(f"相识北洋 版本 {self.current_version}", size=11, color=ft.Colors.ON_SURFACE_VARIANT),
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
        self.name_in.col = {"sm": 12, "md": 6}
        self.user_id_in.col = {"sm": 12, "md": 6}
        self.basic_fields_layout = ft.ResponsiveRow(
            [self.name_in, self.user_id_in],
            columns=12,
            spacing=T.SP_MD,
            run_spacing=T.SP_SM,
        )
        self.right_panel = ft.Column(
            [
                # Section 1: 基本资料
                make_section(ft.Column([
                    ft.Text("基本资料", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.PRIMARY),
                    self.basic_fields_layout,
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
                    self._auto_accept_layout,
                    ft.Container(height=8),
                    self._update_mode_container,
                ], spacing=12)),

                ft.Divider(height=32, thickness=1, color=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE)),

                # Section 4: 应用更新
                make_section(ft.Column([
                    ft.Text("应用更新", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.PRIMARY),
                    self._setting_row("当前版本", ft.Text(self.current_version, size=T.FS_BODY, weight=ft.FontWeight.BOLD)),
                    ft.Text("更新地址", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Row(
                        [
                            self.update_manifest_url,
                            self.update_check_btn,
                        ],
                        spacing=T.SP_SM,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self.update_status,
                    ft.Text(
                        "建议使用 GitHub Releases/Pages 托管 latest.json，APK/EXE 作为 Release assets。",
                        size=11,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                ], spacing=12)),

                ft.Divider(height=32, thickness=1, color=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE)),

                # Section 5: 网络与设备
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

                # Section 6: 文件接收与背景
                make_section(ft.Column([
                    ft.Text("文件接收与背景", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.PRIMARY),
                    self._setting_row("当前保存位置", self.settings_receive_dir),
                    self.settings_receive_note,
                    ft.ResponsiveRow(
                        [
                            self.receive_dir_input,
                            self.apply_receive_dir_button,
                            self.receive_dir_button,
                        ],
                        columns=12,
                        spacing=T.SP_SM,
                        run_spacing=T.SP_SM,
                    ),
                    ft.Divider(height=24, thickness=1, color=ft.Colors.with_opacity(0.06, ft.Colors.ON_SURFACE)),
                    self._path_row("名片背景", self.card_bg_in, "选择并裁剪"),
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
            padding=ft.Padding.only(left=8, right=8, top=6, bottom=12),
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
        control.label = None
        control.hint_text = f"选择{label}路径..."
        control.col = {"sm": 12, "md": 9}
        btn.col = {"sm": 12, "md": 3}
        return ft.Column(
            [
                ft.Text(label, size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.ResponsiveRow(
                    [control, btn],
                    columns=12,
                    spacing=T.SP_SM,
                    run_spacing=T.SP_SM,
                ),
            ],
            spacing=4,
        )

    async def _browse(self, target):
        await self.media_controller.browse(target)

    async def _browse_flet(self, target):
        await self.media_controller.browse_flet(target)

    def _open_crop_editor(self, source_path, target):
        self.media_controller.open_crop_editor(source_path, target)

    def _apply_cropped_media(self, output_path, target):
        self.media_controller.apply_cropped_media(output_path, target)

    def _apply_background_preview(self, bg_path):
        self.media_controller.apply_background_preview(bg_path)

    def _build_default_avatars(self):
        self.media_controller.build_default_avatars()

    def _select_default_avatar(self, path):
        self.media_controller.select_default_avatar(path)

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
            self.card_bg_in.value = profile.get("card_bg", "")
            # Sync draft values so _auto_save uses the loaded data.
            self._draft_name = profile.get("name", "")
            self._draft_user_id = profile.get("user_id", "")
            self._draft_bio = profile.get("bio", "")
            self._draft_avatar = profile.get("avatar", "")
            self._draft_bg = profile.get("background", "")
            self._draft_card_bg = profile.get("card_bg", "")
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
            self.receive_dir_input.value = self.app.get_receive_dir()
            self.update_manifest_url.value = (
                self.app.friend_db.get_app_setting("update_manifest_url", "")
                or default_manifest_url()
            )

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

            # Apply the selected images for page background and profile card banner.
            bg_path = profile.get("background", "").strip()
            card_bg_path = profile.get("card_bg", "").strip()
            self.cover_container.content = None
            if card_bg_path and os.path.exists(card_bg_path):
                self.cover_container.gradient = None
                self.cover_container.image = ft.DecorationImage(src=card_bg_path, fit=ft.BoxFit.COVER)
            else:
                self.cover_container.image = None
                self.cover_container.gradient = T.GRADIENT_PRIMARY
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
            self.page.on_resize = self._on_page_resize
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
            "card_bg": (self._draft_card_bg or self.card_bg_in.value or "").strip(),
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

        # Check if narrow layout
        width = self.page.width if (self.page and self.page.width) else 1000
        is_narrow = (width < 850)

        if is_narrow:
            auto_card.content.expand = False
            manual_card.content.expand = False
            layout = ft.Column([auto_card, manual_card], spacing=10)
        else:
            auto_card.content.expand = True
            manual_card.content.expand = True
            layout = ft.Row([auto_card, manual_card], spacing=10, expand=True)

        self._update_mode_container.content = layout
        return self._update_mode_container

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
        is_narrow = (width < 850)
        platform_name = str(getattr(self.page, "platform", "")).lower()
        is_android = platform_name in ("android", "pageplatform.android")
        is_mobile = is_android or platform_name in ("ios", "pageplatform.ios") or width < 600
        self.main_layout.padding = ft.Padding.only(
            left=2 if is_mobile else 20,
            right=2 if is_mobile else 20,
            top=4 if is_mobile else 10,
            bottom=8 if is_mobile else 20,
        )
        if is_android:
            self.receive_dir_button.disabled = False
            self.receive_dir_button.text = "选择保存目录"
            self.settings_receive_note.value = "提示：Android 系统可能限制部分目录的写入权限，建议选择Download等公共目录。"
        else:
            self.receive_dir_button.disabled = False
            self.receive_dir_button.text = "选择保存目录"
            self.settings_receive_note.value = ""

        # Dynamically set auto-accept layout controls
        if is_narrow:
            self._auto_accept_layout.content = ft.Column(
                [
                    self.min_match_row,
                    self.auto_accept,
                ],
                spacing=10,
            )
        else:
            self._auto_accept_layout.content = ft.Row(
                [
                    ft.Container(content=self.min_match_row, expand=True),
                    self.auto_accept,
                ],
                spacing=20,
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            )

        # Rebuild update mode selector layout dynamically
        self._build_update_mode_selector()

        if is_narrow:
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
        return self.settings_panel.build()

    def _setting_row(self, label, value_control):
        return self.settings_panel.setting_row(label, value_control)

    def _check_updates(self, _e):
        self.update_controller.check_updates(_e)

    def _set_update_status(self, text, color):
        self.update_controller.set_status(text, color)

    def _show_update_dialog(self, info):
        self.update_controller.show_dialog(info)

    def _open_url(self, url):
        return self.update_controller.open_url(url)

    def _current_update_platform(self):
        return self.update_controller.current_platform()

    def _save_tcp(self, _e):
        self.settings_controller.save_tcp(_e)

    async def _choose_receive_dir(self, _e):
        await self.settings_controller.choose_receive_dir(_e)

    async def _choose_receive_dir_flet(self):
        await self.settings_controller.choose_receive_dir_flet()

    def _on_receive_dir_selected(self, e):
        self.settings_controller.on_receive_dir_selected(e)

    def _reset_receive_dir(self, _e):
        self.settings_controller.reset_receive_dir(_e)

    def _apply_receive_dir_from_input(self, _e):
        self.settings_controller.apply_receive_dir_from_input(_e)

    def _normalize_receive_dir(self, directory):
        return self.settings_controller.normalize_receive_dir(directory)

    def _apply_receive_dir(self, directory):
        self.settings_controller.apply_receive_dir(directory)

    def _clear_chat(self):
        self.settings_controller.clear_chat()

    def _clear_pending(self):
        self.settings_controller.clear_pending()

    def _confirm(self, message, on_ok, ok_text="确认"):
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("确认操作 ⚠️", weight=ft.FontWeight.BOLD),
            content=ft.Text(message),
            actions_alignment=ft.MainAxisAlignment.END,
        )
        def handle_ok(e):
            self._close(dlg)
            on_ok(e)

        dlg.actions = [
            ft.TextButton("取消", on_click=lambda _e: self._close(dlg)),
            ft.ElevatedButton(
                ok_text,
                on_click=handle_ok,
                bgcolor=ft.Colors.RED_600,
                color=ft.Colors.WHITE
            ),
        ]
        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()

    def _close(self, dlg):
        dlg.open = False
        self.page.update()
