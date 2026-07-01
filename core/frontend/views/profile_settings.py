"""Settings controls and layout for ProfileView."""

import flet as ft

from core.backend.services.update_service import current_app_version

from .. import theme as T


class ProfileSettingsControls:
    """Create system-setting controls and attach them to ProfileView."""

    def __init__(self, owner):
        self.owner = owner
        self.app = owner.app

    def attach(self):
        owner = self.owner
        owner.settings_device_name = ft.Text(
            "--",
            size=T.FS_BODY,
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.ON_SURFACE,
        )
        owner.settings_tcp_port = ft.TextField(
            value="7779",
            keyboard_type=ft.KeyboardType.NUMBER,
            width=120,
            border_radius=10,
            border_color=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            content_padding=10,
        )
        owner.settings_udp_port = ft.Text(
            "8890",
            size=T.FS_BODY,
            weight=ft.FontWeight.W_500,
            color=ft.Colors.ON_SURFACE_VARIANT,
        )
        owner.settings_tcp_hint = ft.Text("", size=T.FS_CAPTION)
        owner.settings_pending_count = ft.Text(
            "0 条消息",
            size=T.FS_BODY,
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.DEEP_PURPLE_400,
        )
        owner.settings_receive_dir = ft.Text(
            "",
            size=T.FS_CAPTION,
            color=ft.Colors.ON_SURFACE_VARIANT,
            selectable=True,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        owner.settings_receive_note = ft.Text(
            "",
            size=T.FS_CAPTION,
            color=ft.Colors.ON_SURFACE_VARIANT,
        )
        owner.receive_dir_input = ft.TextField(
            label=None,
            hint_text="输入保存目录，例如 /storage/emulated/0/Download/Beiyang",
            on_submit=owner._apply_receive_dir_from_input,
            border_radius=12,
            border_color=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            content_padding=10,
            expand=True,
        )
        owner.apply_receive_dir_button = ft.Button(
            "应用路径",
            icon=ft.Icons.CHECK_CIRCLE_ROUNDED,
            on_click=owner._apply_receive_dir_from_input,
            bgcolor=ft.Colors.DEEP_PURPLE_500,
            color=ft.Colors.WHITE,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
        )
        owner.receive_dir_button = ft.Button(
            "选择保存目录",
            icon=ft.Icons.FOLDER_OPEN_ROUNDED,
            on_click=owner._choose_receive_dir,
            bgcolor=ft.Colors.DEEP_PURPLE_500,
            color=ft.Colors.WHITE,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
        )
        owner.receive_dir_input.col = {"sm": 12, "md": 8}
        owner.apply_receive_dir_button.col = {"sm": 12, "md": 2}
        owner.receive_dir_button.col = {"sm": 12, "md": 2}
        owner.current_version = current_app_version(self.app.paths.project_root)
        owner.update_manifest_url = ft.TextField(
            label=None,
            hint_text="latest.json 地址，例如 GitHub Release/Pages 的直链",
            border_radius=12,
            border_color=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            content_padding=10,
            expand=True,
        )
        owner.update_status = ft.Text("", size=T.FS_CAPTION)
        owner.update_check_btn = ft.ElevatedButton(
            "检查更新",
            icon=ft.Icons.SYSTEM_UPDATE_ROUNDED,
            on_click=owner._check_updates,
            bgcolor=ft.Colors.DEEP_PURPLE_500,
            color=ft.Colors.WHITE,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
        )
        owner._theme_selector_row = ft.Container()


class ProfileSettingsPanel:
    """Build the settings tab layout for ProfileView."""

    def __init__(self, owner):
        self.owner = owner

    def build(self):
        owner = self.owner
        return ft.Column(
            [
                self._about_card(),
                T.surface_card(
                    T.section_title("个性化主题"),
                    ft.Text("点击选择系统主题色：", size=T.FS_BODY, color=ft.Colors.ON_SURFACE_VARIANT),
                    owner._theme_selector_row,
                ),
                T.surface_card(
                    T.section_title("自定义背景"),
                    owner._path_row("背景图片", owner.bg_in, "选择并裁剪"),
                ),
                self._update_card(),
                self._network_card(),
                self._receive_dir_card(),
                self._privacy_card(),
            ],
            spacing=T.SP_MD,
            scroll=ft.ScrollMode.AUTO,
        )

    def setting_row(self, label, value_control):
        label_control = ft.Text(label, size=T.FS_BODY, color=ft.Colors.ON_SURFACE_VARIANT)
        label_control.col = {"sm": 12, "md": 4}
        value_container = ft.Container(content=value_control)
        value_container.col = {"sm": 12, "md": 8}
        return ft.ResponsiveRow(
            [label_control, value_container],
            columns=12,
            spacing=T.SP_SM,
            run_spacing=4,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _about_card(self):
        owner = self.owner
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.AUTO_AWESOME_ROUNDED, color=ft.Colors.WHITE, size=24),
                            ft.Text(
                                "相识北洋",
                                size=T.FS_HEADER,
                                weight=ft.FontWeight.W_900,
                                color=ft.Colors.WHITE,
                            ),
                        ],
                        spacing=T.SP_SM,
                    ),
                    ft.Text(
                        f"版本 {owner.current_version}",
                        size=T.FS_BODY,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.with_opacity(0.8, ft.Colors.WHITE),
                    ),
                    ft.Text(
                        "P2P 校园网无网社交 · 洪泛中继路由 · 离线消息漫游",
                        size=T.FS_CAPTION,
                        color=ft.Colors.with_opacity(0.7, ft.Colors.WHITE),
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

    def _update_card(self):
        owner = self.owner
        return T.surface_card(
            T.section_title("应用更新"),
            self.setting_row(
                "当前版本",
                ft.Text(owner.current_version, size=T.FS_BODY, weight=ft.FontWeight.BOLD),
            ),
            ft.Text("更新地址", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Row(
                [
                    owner.update_manifest_url,
                    owner.update_check_btn,
                ],
                spacing=T.SP_SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            owner.update_status,
        )

    def _network_card(self):
        owner = self.owner
        return T.surface_card(
            T.section_title("网络与设备"),
            self.setting_row("本机主机名", owner.settings_device_name),
            ft.Row(
                [
                    ft.Text(
                        "TCP 端口号",
                        size=T.FS_BODY,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                        width=100,
                    ),
                    owner.settings_tcp_port,
                    ft.IconButton(
                        icon=ft.Icons.CHECK_CIRCLE_ROUNDED,
                        icon_color=ft.Colors.DEEP_PURPLE_400,
                        on_click=owner._save_tcp,
                        tooltip="保存端口",
                    ),
                ],
                spacing=T.SP_SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            owner.settings_tcp_hint,
            self.setting_row("UDP 广播端口", owner.settings_udp_port),
        )

    def _receive_dir_card(self):
        owner = self.owner
        return T.surface_card(
            T.section_title("文件接收"),
            self.setting_row("保存位置", owner.settings_receive_dir),
            ft.Row(
                [
                    ft.ElevatedButton(
                        "选择保存目录",
                        icon=ft.Icons.FOLDER_OPEN_ROUNDED,
                        on_click=owner._choose_receive_dir,
                        bgcolor=ft.Colors.DEEP_PURPLE_500,
                        color=ft.Colors.WHITE,
                    ),
                    ft.TextButton(
                        "恢复默认",
                        on_click=owner._reset_receive_dir,
                    ),
                ],
                spacing=T.SP_SM,
            ),
        )

    def _privacy_card(self):
        owner = self.owner
        return T.surface_card(
            T.section_title("安全与隐私"),
            ft.ListTile(
                leading=ft.Icon(ft.Icons.CLEANING_SERVICES_ROUNDED, color=ft.Colors.ORANGE_400),
                title=ft.Text("清空聊天记录", weight=ft.FontWeight.BOLD),
                subtitle=ft.Text("清除本地数据库中所有朋友的历史消息", size=T.FS_CAPTION),
                trailing=ft.Icon(ft.Icons.NAVIGATE_NEXT_ROUNDED),
                on_click=lambda _e: owner._clear_chat(),
            ),
            ft.ListTile(
                leading=ft.Icon(ft.Icons.MARK_AS_UNREAD_ROUNDED, color=ft.Colors.DEEP_PURPLE_400),
                title=ft.Text("清除离线待发送队列", weight=ft.FontWeight.BOLD),
                subtitle=ft.Text("清空缓存中准备转发给朋友的离线数据", size=T.FS_CAPTION),
                trailing=owner.settings_pending_count,
                on_click=lambda _e: owner._clear_pending(),
            ),
        )
