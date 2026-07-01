"""Reusable tag input controls for profile editing."""

import flet as ft

from .. import theme as T


class TagInput(ft.Column):
    """QQ-style personality tag bubbles with an inline add composer."""

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
        self.on_changed = None

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
