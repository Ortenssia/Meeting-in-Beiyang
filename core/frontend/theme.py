"""
Beiyang Social — Flet UI theme tokens.

Flet handles dark/light automatically via ``page.theme_mode = SYSTEM`` so we
don't keep raw color hexes here. Instead this module exposes:

* semantic color *keys* (mapped through Flet's ``colors`` / ``Theme``)
* spacing / radius / font-size constants,
* navigation tab definitions,
* helper factories for avatar colors
* premium UI elements like glass cards, gradient buttons, and glowing badges.
"""
import os
from dataclasses import dataclass
from typing import List, Tuple

import flet as ft


# ---- Premium Gradients & Shadows ------------------------------------------ #
GRADIENT_PRIMARY = ft.LinearGradient(
    begin=ft.alignment.Alignment.TOP_LEFT,
    end=ft.alignment.Alignment.BOTTOM_RIGHT,
    colors=[ft.Colors.DEEP_PURPLE_500, ft.Colors.PINK_500],
)

THEME_COLORS = {
    "DEEP_PURPLE": {
        "seed": ft.Colors.DEEP_PURPLE,
        "gradient": [ft.Colors.DEEP_PURPLE_500, ft.Colors.PINK_500],
        "name": "经典深紫",
    },
    "PINK": {
        "seed": ft.Colors.PINK,
        "gradient": [ft.Colors.PINK_500, ft.Colors.RED_400],
        "name": "珊瑚粉黛",
    },
    "BLUE": {
        "seed": ft.Colors.BLUE,
        "gradient": [ft.Colors.BLUE_500, ft.Colors.CYAN_400],
        "name": "天空湛蓝",
    },
    "GREEN": {
        "seed": ft.Colors.GREEN,
        "gradient": [ft.Colors.GREEN_600, ft.Colors.TEAL_400],
        "name": "极光森绿",
    },
    "ORANGE": {
        "seed": ft.Colors.ORANGE,
        "gradient": [ft.Colors.ORANGE_500, ft.Colors.AMBER_400],
        "name": "活力暖橙",
    },
    "INDIGO": {
        "seed": ft.Colors.INDIGO,
        "gradient": [ft.Colors.INDIGO_500, ft.Colors.PURPLE_400],
        "name": "梦幻星空",
    },
    "TEAL": {
        "seed": ft.Colors.TEAL,
        "gradient": [ft.Colors.TEAL_600, ft.Colors.GREEN_400],
        "name": "清新雅致",
    },
    "RED": {
        "seed": ft.Colors.RED,
        "gradient": [ft.Colors.RED_500, ft.Colors.ORANGE_400],
        "name": "烈焰热情",
    },
}

GRADIENT_SECONDARY = ft.LinearGradient(
    begin=ft.alignment.Alignment.TOP_LEFT,
    end=ft.alignment.Alignment.BOTTOM_RIGHT,
    colors=[ft.Colors.BLUE_500, ft.Colors.INDIGO_600],
)

GRADIENT_SCANNER = ft.LinearGradient(
    begin=ft.alignment.Alignment.TOP_LEFT,
    end=ft.alignment.Alignment.BOTTOM_RIGHT,
    colors=[ft.Colors.CYAN_400, ft.Colors.BLUE_500, ft.Colors.PURPLE_500],
)

GRADIENT_CARD = ft.LinearGradient(
    begin=ft.alignment.Alignment.TOP_LEFT,
    end=ft.alignment.Alignment.BOTTOM_RIGHT,
    colors=[
        ft.Colors.SURFACE_CONTAINER_HIGH,
        ft.Colors.SURFACE_CONTAINER_LOW,
    ],
)

SHADOW_CARD = ft.BoxShadow(
    blur_radius=16,
    spread_radius=1,
    color=ft.Colors.with_opacity(0.05, ft.Colors.BLACK),
    offset=ft.Offset(0, 4),
)

SHADOW_GLOW = ft.BoxShadow(
    blur_radius=12,
    spread_radius=2,
    color=ft.Colors.with_opacity(0.3, ft.Colors.DEEP_PURPLE_400),
)


# ---- Avatar palette (deterministic, theme-independent) ------------------ #
AVATAR_COLORS: List[Tuple[int, int, int]] = [
    (109, 40, 217),   # Violet 700
    (16, 185, 129),   # Emerald 500
    (219, 39, 119),   # Pink 600
    (245, 158, 11),   # Amber 500
    (79, 70, 229),    # Indigo 600
    (6, 182, 212),    # Cyan 500
    (239, 68, 68),    # Red 500
    (132, 204, 22),   # Lime 500
]


def avatar_color(name: str) -> Tuple[int, int, int]:
    import hashlib
    if not name:
        return AVATAR_COLORS[0]
    try:
        h = hashlib.md5(name.encode("utf-8", errors="ignore")).hexdigest()
        return AVATAR_COLORS[int(h, 16) % len(AVATAR_COLORS)]
    except Exception:
        return AVATAR_COLORS[0]


def avatar_circle(
    name: str,
    size: int = 44,
    online: bool = False,
    unread: bool = False,
) -> ft.Control:
    """Build a deterministic colored circle avatar with online and unread dots."""
    if name == "group" or (name and name.startswith("group")):
        return ft.Container(
            width=size,
            height=size,
            border_radius=size // 2,
            bgcolor=ft.Colors.DEEP_PURPLE_500,
            alignment=ft.alignment.Alignment.CENTER,
            content=ft.Icon(ft.Icons.GROUP_ROUNDED, color=ft.Colors.WHITE, size=int(size * 0.55)),
        )

    is_image = False
    img_src = None
    if name:
        # Normalize all slashes to forward slashes first to prevent Windows path mismatch
        name = name.replace("\\", "/")
        name_lower = name.lower()
        if name_lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")):
            is_image = True
            if name.startswith("assets/"):
                img_src = name[7:]
            elif os.path.isabs(name):
                if os.path.isfile(name):
                    try:
                        with open(name, "rb") as image_file:
                            img_src = image_file.read()
                    except Exception:
                        is_image = False
                else:
                    is_image = False
            else:
                img_src = name

    r, g, b = avatar_color(name)
    initial = (name or "?").strip()[0].upper() if (name or "").strip() else "?"
    avatar_bg_color = f"#{r:02x}{g:02x}{b:02x}"
    
    image_ctrl = None
    if is_image:
        image_ctrl = ft.Image(
            src=img_src or "avatar.png",
            width=size - 3,
            height=size - 3,
            fit=ft.BoxFit.COVER,
            border_radius=(size - 3) // 2,
        )

    controls = [
        ft.Container(
            width=size,
            height=size,
            border_radius=size // 2,
            border=border_all(1.5, ft.Colors.with_opacity(0.15, ft.Colors.ON_SURFACE)),
            alignment=ft.alignment.Alignment.CENTER,
            content=ft.Container(
                width=size - 3,
                height=size - 3,
                bgcolor=ft.Colors.with_opacity(1.0, avatar_bg_color) if not is_image else None,
                border_radius=(size - 3) // 2,
                alignment=ft.alignment.Alignment.CENTER,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                content=image_ctrl if is_image else ft.Text(
                    initial,
                    color=ft.Colors.WHITE,
                    size=int(size * 0.42),
                    weight=ft.FontWeight.BOLD,
                ),
            ),
        )
    ]
    if online:
        controls.append(
            ft.Container(
                width=max(9, size // 5),
                height=max(9, size // 5),
                bgcolor=ft.Colors.with_opacity(1.0, ft.Colors.GREEN_400),
                border_radius=999,
                right=0,
                bottom=0,
                border=border_all(2, ft.Colors.SURFACE_CONTAINER_HIGH),
                shadow=ft.BoxShadow(
                    blur_radius=4,
                    color=ft.Colors.with_opacity(0.4, ft.Colors.GREEN_500),
                ),
            )
        )

    if unread:
        dot_size = max(10, size // 4)
        controls.append(
            ft.Container(
                width=dot_size,
                height=dot_size,
                bgcolor=ft.Colors.RED_500,
                border_radius=999,
                right=0,
                top=0,
                border=border_all(2, ft.Colors.SURFACE_CONTAINER_HIGH),
                shadow=ft.BoxShadow(
                    blur_radius=5,
                    color=ft.Colors.with_opacity(0.45, ft.Colors.RED_600),
                ),
            )
        )

    badge = ft.Stack(controls, width=size, height=size)
    return badge


# ---- Layout constants ---------------------------------------------------- #
SP_XS = 4
SP_SM = 8
SP_MD = 12
SP_LG = 16
SP_XL = 20
SP_2XL = 24

R_SM = 8
R_MD = 12
R_LG = 16
R_XL = 20

INPUT_HEIGHT = 46
BUTTON_HEIGHT = 44
ROW_HEIGHT = 64
NAV_HEIGHT = 64
AVATAR_SM = 36
AVATAR_MD = 44
AVATAR_LG = 72

FS_CAPTION = 11
FS_BODY = 13
FS_TEXT = 15
FS_TITLE = 17
FS_HEADER = 22

# (label, screen key, icon)
TABS: List[Tuple[str, str, str]] = [
    ("聊天", "chat", ft.Icons.CHAT_ROUNDED),
    ("联系人", "friends", ft.Icons.PEOPLE_ALT_ROUNDED),
    ("空间", "moments", ft.Icons.DASHBOARD_ROUNDED),
    ("我的", "profile", ft.Icons.ACCOUNT_CIRCLE_ROUNDED),
]


def surface_card(*content, padding=SP_LG, spacing=SP_SM) -> ft.Container:
    """A premium styled surface card with rounded corners, theme-aware bg, gradient and shadow."""
    return ft.Container(
        content=ft.Column(content, spacing=spacing),
        padding=padding,
        border_radius=R_LG,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
        border=border_all(1, ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE)),
        shadow=SHADOW_CARD,
    )


def section_title(text: str) -> ft.Text:
    return ft.Text(
        text,
        size=FS_TITLE,
        weight=ft.FontWeight.BOLD,
        color=ft.Colors.ON_SURFACE,
    )


def field_label(text: str) -> ft.Text:
    return ft.Text(text, size=FS_BODY, color=ft.Colors.ON_SURFACE_VARIANT)


def meta_text(text: str) -> ft.Text:
    return ft.Text(text, size=FS_CAPTION, color=ft.Colors.ON_SURFACE_VARIANT)


# ---- 0.85 compat helpers ------------------------------------------------- #
def pad_symmetric(horizontal: int = 0, vertical: int = 0) -> ft.Padding:
    return ft.Padding(left=horizontal, top=vertical, right=horizontal, bottom=vertical)


def pad_all(value: int = 0) -> ft.Padding:
    return ft.Padding(left=value, top=value, right=value, bottom=value)


def pad_only(top=0, left=0, bottom=0, right=0) -> ft.Padding:
    return ft.Padding(left=left, top=top, right=right, bottom=bottom)


def border_all(width: float = 1, color=None) -> ft.Border:
    side = ft.BorderSide(width=width, color=color)
    return ft.Border(top=side, bottom=side, left=side, right=side)


def radius_only(top_left=0, top_right=0, bottom_left=0, bottom_right=0) -> ft.BorderRadius:
    return ft.BorderRadius(top_left=top_left, top_right=top_right,
                           bottom_left=bottom_left, bottom_right=bottom_right)


class FilterChip(ft.Container):
    """A pill toggle. Styled container + text button. on_select receives the chip instance."""

    def __init__(self, label: str, selected: bool = False, on_select=None):
        self._label = label
        self._selected = selected
        self._on_select = on_select
        super().__init__(
            on_click=self._handle_click,
            padding=pad_symmetric(horizontal=16, vertical=8),
            border_radius=999,
            ink=True,
            animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
        )
        self._refresh()

    @property
    def label(self) -> str:
        return self._label

    @property
    def selected(self) -> bool:
        return self._selected

    @selected.setter
    def selected(self, value: bool):
        self._selected = bool(value)
        self._refresh()

    def _handle_click(self, _e):
        if self._on_select:
            self._on_select(self)

    def _refresh(self):
        if self._selected:
            self.gradient = GRADIENT_PRIMARY
            self.border = None
            self.content = ft.Text(
                self._label,
                color=ft.Colors.WHITE,
                size=FS_BODY,
                weight=ft.FontWeight.BOLD,
            )
            self.shadow = SHADOW_GLOW
        else:
            self.gradient = None
            self.bgcolor = ft.Colors.SURFACE_CONTAINER_HIGHEST
            self.border = border_all(1, ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE))
            self.content = ft.Text(
                self._label,
                color=ft.Colors.ON_SURFACE_VARIANT,
                size=FS_BODY,
                weight=ft.FontWeight.W_500,
            )
            self.shadow = None
