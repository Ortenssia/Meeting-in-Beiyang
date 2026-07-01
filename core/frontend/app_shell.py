"""Flet page shell construction for BeiyangApp."""

import flet as ft

from . import theme as T
from .views.chat import ChatView
from .views.discover import DiscoverView
from .views.friends import FriendsView
from .views.moments import MomentsView
from .views.profile import ProfileView


class AppShellBuilder:
    """Build page-level Flet controls and view instances."""

    def __init__(self, app, nav_class):
        self.app = app
        self.nav_class = nav_class

    def build_shell(self, page: ft.Page):
        app = self.app
        page.title = "相识北洋"
        page.theme_mode = ft.ThemeMode.SYSTEM

        app.profile_file_picker = ft.FilePicker()
        app.chat_file_picker = ft.FilePicker()
        app.receive_dir_picker = ft.FilePicker()
        app.moment_image_picker = ft.FilePicker()
        page.services.append(app.profile_file_picker)
        page.services.append(app.chat_file_picker)
        page.services.append(app.receive_dir_picker)
        page.services.append(app.moment_image_picker)

        page.fonts = {"Noto Sans SC": app.paths.font_asset}
        page.theme = ft.Theme(
            color_scheme_seed=ft.Colors.DEEP_PURPLE,
            visual_density=ft.VisualDensity.COMFORTABLE,
            font_family="Noto Sans SC",
        )

        is_mobile = str(page.platform).lower() in (
            "android",
            "ios",
            "pageplatform.android",
            "pageplatform.ios",
        )
        if is_mobile:
            page.padding = ft.Padding.only(top=40, left=0, right=0, bottom=0)
        else:
            page.padding = 0
            page.window_width = 460
            page.window_height = 820
            page.window_min_width = 380
            page.window_min_height = 640

        if not is_mobile:
            icon_path = app.paths.assets_dir / "app_icon.ico"
            if icon_path.exists():
                page.window.icon = str(icon_path.resolve())

        app.udp_status_dot = ft.Container(
            width=8,
            height=8,
            border_radius=4,
            bgcolor=ft.Colors.RED_400,
            tooltip="UDP 广播: 关闭",
            shadow=ft.BoxShadow(
                blur_radius=4,
                color=ft.Colors.with_opacity(0.3, ft.Colors.RED_500),
            ),
        )
        app.tcp_status_dot = ft.Container(
            width=8,
            height=8,
            border_radius=4,
            bgcolor=ft.Colors.RED_400,
            tooltip="TCP 监听: 关闭",
            shadow=ft.BoxShadow(
                blur_radius=4,
                color=ft.Colors.with_opacity(0.3, ft.Colors.RED_500),
            ),
        )

        app.top_header = ft.Container(
            content=ft.Row(
                [
                    ft.Row(
                        [
                            ft.Text(
                                "相识",
                                size=18,
                                weight=ft.FontWeight.W_900,
                                color=ft.Colors.DEEP_PURPLE_400,
                            ),
                            ft.Text("北洋", size=18, weight=ft.FontWeight.W_900),
                        ],
                        spacing=0,
                    ),
                    ft.Row(
                        [
                            ft.Row(
                                [
                                    app.udp_status_dot,
                                    ft.Text(
                                        "UDP广播",
                                        size=10,
                                        weight=ft.FontWeight.BOLD,
                                        color=ft.Colors.ON_SURFACE_VARIANT,
                                    ),
                                ],
                                spacing=4,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            ft.Row(
                                [
                                    app.tcp_status_dot,
                                    ft.Text(
                                        "TCP连线",
                                        size=10,
                                        weight=ft.FontWeight.BOLD,
                                        color=ft.Colors.ON_SURFACE_VARIANT,
                                    ),
                                ],
                                spacing=4,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                        ],
                        spacing=10,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=T.pad_symmetric(horizontal=T.SP_LG, vertical=T.SP_MD),
            border=ft.Border(
                bottom=ft.BorderSide(
                    1,
                    ft.Colors.with_opacity(0.06, ft.Colors.ON_SURFACE),
                )
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        )

        app.views = {
            "discover": DiscoverView(app),
            "friends": FriendsView(app),
            "chat": ChatView(app),
            "moments": MomentsView(app),
            "profile": ProfileView(app),
        }

        # Intercept Android system back button and convert it to app-level
        # navigation back. Without this, the back button closes the app
        # immediately instead of returning to the previous view.
        if is_mobile:
            def _on_keyboard(e: ft.KeyboardEvent):
                if e.key in ("Back", "Escape", "GoBack"):
                    if app._pop_nav():
                        page.update()
            page.on_keyboard_event = _on_keyboard

        app.nav = self.nav_class(tabs=T.TABS, on_change=app._on_nav_change)
        app._stack = ft.Stack(expand=True)
        app.root_bg = ft.Image(
            src="placeholder",
            fit=ft.BoxFit.COVER,
            opacity=0.08,
            expand=True,
            visible=False,
        )
        app.root_container = ft.Container(
            content=ft.Column(
                [
                    app.top_header,
                    ft.Container(
                        content=app._stack,
                        expand=True,
                        padding=T.pad_only(
                            left=8 if is_mobile else T.SP_LG,
                            right=8 if is_mobile else T.SP_LG,
                            top=8 if is_mobile else T.SP_LG,
                        ),
                    ),
                    app.nav,
                ],
                spacing=0,
                expand=True,
            ),
            expand=True,
        )
        page.add(
            ft.Stack(
                [
                    app.root_bg,
                    app.root_container,
                ],
                expand=True,
            )
        )
