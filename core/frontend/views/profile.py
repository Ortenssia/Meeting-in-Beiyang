"""Profile view: avatar, basic info, tags, bio, matching conditions."""
import threading
import time

import flet as ft

from .. import theme as T


class TagInput(ft.Column):
    """Reusable tag input: TextField + add button + horizontally scrolling chips."""

    def __init__(self, hint="输入后回车，例如：编程、篮球"):
        super().__init__(spacing=T.SP_SM)
        self._tags = []
        self.hint = hint
        
        self.input = ft.TextField(
            label=hint, 
            expand=True, 
            on_submit=self._add,
            border_radius=12,
            border_color=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
            content_padding=10,
            prefix_icon=ft.Icons.TAG_ROUNDED,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        )
        self.add_btn = ft.IconButton(
            icon=ft.Icons.ADD_CIRCLE_ROUNDED,
            icon_color=ft.Colors.DEEP_PURPLE_400,
            icon_size=28,
            on_click=self._add,
            tooltip="添加标签"
        )
        self.chips = ft.Row(spacing=T.SP_SM, scroll=ft.ScrollMode.AUTO)
        self.controls = [
            ft.Row([self.input, self.add_btn], spacing=T.SP_SM, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            self.chips,
        ]

    def _add(self, _e=None):
        raw = (self.input.value or "").strip()
        if not raw:
            return
        parts = [p.strip() for p in raw.replace("，", ",").split(",") if p.strip()]
        for tag in parts:
            if tag and tag not in self._tags:
                self._tags.append(tag)
                self.chips.controls.append(
                    ft.Chip(
                        label=ft.Text(tag, weight=ft.FontWeight.W_600),
                        on_delete=self._make_remove(tag),
                        delete_icon=ft.Icons.CLOSE_ROUNDED,
                        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                        border_side=ft.BorderSide(1, ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE)),
                    )
                )
        self.input.value = ""
        self.update()

    def _make_remove(self, tag):
        def _remove(e):
            if tag in self._tags:
                self._tags.remove(tag)
            for c in list(self.chips.controls):
                if isinstance(c, ft.Chip) and c.label.value == tag:
                    self.chips.controls.remove(c)
            self.update()
        return _remove

    def get_tags(self):
        return list(self._tags)

    def set_tags(self, tags):
        self._tags = []
        self.chips.controls.clear()
        for tag in (tags or []):
            tag = tag.strip()
            if tag and tag not in self._tags:
                self._tags.append(tag)
                self.chips.controls.append(
                    ft.Chip(
                        label=ft.Text(tag, weight=ft.FontWeight.W_600), 
                        on_delete=self._make_remove(tag),
                        delete_icon=ft.Icons.CLOSE_ROUNDED,
                        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                        border_side=ft.BorderSide(1, ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE)),
                    )
                )
        try:
            self.update()
        except Exception:
            pass


class ProfileView:
    def __init__(self, app):
        self.app = app
        self.page = app.page
        
        self.name_in = ft.TextField(
            label="我的昵称", 
            on_change=self._on_name,
            border_radius=12,
            border_color=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        )
        self.avatar_in = ft.TextField(
            label="自定义头像路径",
            border_radius=12,
            border_color=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        )
        self.bg_in = ft.TextField(
            label="自定义背景路径",
            border_radius=12,
            border_color=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        )
        self.bio_in = ft.TextField(
            label="个人简介", 
            multiline=True, 
            min_lines=3, 
            max_lines=5,
            border_radius=12,
            border_color=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            hint_text="向大家介绍一下你自己吧…"
        )
        
        self.tags_input = TagInput("输入兴趣，逗号或回车分割")
        self.req_input = TagInput("必选兴趣（如：计算机）")
        self.opt_input = TagInput("可选兴趣（如：唱歌）")
        
        self.min_match = ft.Dropdown(
            label="最低匹配标签数", 
            value="1",
            border_radius=12,
            border_color=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            options=[ft.dropdown.Option(str(i)) for i in range(1, 11)],
        )
        
        self.auto_accept = ft.Switch(
            label="满足标签条件时自动同意好友申请",
            active_color=ft.Colors.DEEP_PURPLE_500,
        )
        
        self.status = ft.Text("", size=T.FS_BODY, weight=ft.FontWeight.BOLD)
        self._avatar_name = ""
        
        # Dedicated avatar holder for dynamic updates
        self.avatar_holder = ft.Container(
            content=T.avatar_circle("", T.AVATAR_LG),
            width=T.AVATAR_LG,
            height=T.AVATAR_LG,
        )

        self.file_picker = getattr(app, "profile_file_picker", None) or ft.FilePicker()
        
        self.DEFAULT_AVATARS = list(app.paths.default_avatar_assets)
        self.default_avatars_row = ft.Row(spacing=T.SP_MD, alignment=ft.MainAxisAlignment.START, height=48)

    def build(self):
        # Twitter-style profile cover stack
        header_stack = ft.Stack(
            [
                # Cover Card with primary gradient
                ft.Container(
                    height=100,
                    border_radius=T.R_LG,
                    gradient=T.GRADIENT_PRIMARY,
                    border=T.border_all(1, ft.Colors.with_opacity(0.1, ft.Colors.WHITE)),
                ),
                # Avatar overlapping the cover card
                ft.Container(
                    content=self.avatar_holder,
                    top=50,
                    left=0,
                    right=0,
                    alignment=ft.alignment.Alignment.CENTER,
                )
            ],
            height=136,
        )

        save_btn = ft.GestureDetector(
            mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=self._save,
            content=ft.Container(
                content=ft.Text("保存配置", color=ft.Colors.WHITE, size=T.FS_TEXT, weight=ft.FontWeight.BOLD),
                height=46,
                border_radius=23,
                gradient=T.GRADIENT_PRIMARY,
                shadow=T.SHADOW_GLOW,
                alignment=ft.alignment.Alignment.CENTER,
            )
        )

        return ft.Column(
            [
                ft.Text("个人资料", size=T.FS_HEADER, weight=ft.FontWeight.W_800),
                ft.Column(
                    [
                        header_stack,
                        ft.Container(height=4),
                        
                        T.surface_card(
                            T.section_title("基本资料"),
                            self.name_in,
                            self._path_row("头像", self.avatar_in, "图片"),
                            self.default_avatars_row,
                            self._path_row("背景", self.bg_in, "图片"),
                            ft.Text("我的兴趣标签", size=T.FS_BODY, weight=ft.FontWeight.BOLD, color=ft.Colors.DEEP_PURPLE_400),
                            self.tags_input,
                            self.bio_in,
                        ),
                        
                        T.surface_card(
                            T.section_title("自动同意匹配条件"),
                            ft.Text("配置必选与可选交友标签以开启自动匹配通过：", size=T.FS_CAPTION, color=ft.Colors.ON_SURFACE_VARIANT),
                            self.req_input,
                            self.opt_input,
                            self.min_match,
                            self.auto_accept,
                        ),
                        
                        save_btn,
                        ft.Container(content=self.status, alignment=ft.alignment.Alignment.CENTER),
                    ],
                    spacing=T.SP_MD, expand=True, scroll=ft.ScrollMode.AUTO,
                ),
            ],
            spacing=T.SP_SM, expand=True,
        )

    def _path_row(self, label, control, pick_label):
        btn = ft.OutlinedButton(
            pick_label, 
            on_click=lambda _e, c=control: self._browse(c),
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=10),
            )
        )
        control.expand = True
        return ft.Row(
            [control, btn],
            spacing=T.SP_SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _browse(self, target):
        import threading
        def _do_pick():
            import tkinter as tk
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
                target.value = file_path
                if target == self.avatar_in:
                    self._avatar_name = file_path
                    self.avatar_holder.content = T.avatar_circle(
                        self.app.paths.asset_src(self._avatar_name),
                        T.AVATAR_LG,
                    )
                    self._build_default_avatars()
                if self.page:
                    self.page.update()
        threading.Thread(target=_do_pick, daemon=True).start()

    def _build_default_avatars(self):
        self.default_avatars_row.controls.clear()
        selected_path = (self.avatar_in.value or "").strip()
        for name, path in self.DEFAULT_AVATARS:
            selected_asset = self.app.paths.asset_src(selected_path)
            is_selected = (selected_asset == path or selected_path.endswith(name))
            avatar_btn = ft.GestureDetector(
                mouse_cursor=ft.MouseCursor.CLICK,
                on_tap=lambda _e, p=path: self._select_default_avatar(p),
                content=ft.Container(
                    content=T.avatar_circle(self.app.paths.asset_src(path), 40),
                    padding=2,
                    border_radius=24,
                    border=T.border_all(2, ft.Colors.DEEP_PURPLE_400) if is_selected else T.border_all(2, ft.Colors.TRANSPARENT),
                    animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
                )
            )
            self.default_avatars_row.controls.append(avatar_btn)

    def _select_default_avatar(self, path):
        self.avatar_in.value = path
        self._avatar_name = path
        self.avatar_holder.content = T.avatar_circle(self.app.paths.asset_src(path), T.AVATAR_LG)
        self._build_default_avatars()
        if self.page:
            self.page.update()

    # -- lifecycle ---------------------------------------------------------

    def on_enter(self):
        self._load()

    def _load(self):
        profile = self.app.get_my_profile()
        if not profile:
            return
        self._avatar_name = profile.get("name", "")
        if profile.get("avatar"):
            self.avatar_in.value = profile.get("avatar", "")
            self._avatar_name = profile.get("avatar", "")
        self.name_in.value = profile.get("name", "")
        self.bio_in.value = profile.get("bio", "")
        self.bg_in.value = profile.get("background", "")
        self.tags_input.set_tags(profile.get("tags", []))
        cond = profile.get("conditions", {})
        self.req_input.set_tags(cond.get("required_tags", []))
        self.opt_input.set_tags(cond.get("optional_tags", []))
        self.min_match.value = str(cond.get("min_match_count", 1))
        self.auto_accept.value = cond.get("auto_accept", False)
        
        self._build_default_avatars()
        
        # Redraw avatar circle with loaded name/avatar path
        self.avatar_holder.content = T.avatar_circle(self.app.paths.asset_src(self._avatar_name), T.AVATAR_LG)
        if self.page:
            self.page.update()

    # -- events ------------------------------------------------------------

    def _on_name(self, e):
        avatar_path = (self.avatar_in.value or "").strip()
        self._avatar_name = avatar_path if avatar_path.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp")) else (e.control.value or "")
        # Dynamically redraw avatar in real-time as name changes
        self.avatar_holder.content = T.avatar_circle(self.app.paths.asset_src(self._avatar_name), T.AVATAR_LG)
        if self.page:
            self.page.update()

    def _save(self, _e):
        name = (self.name_in.value or "").strip()
        if not name:
            self.status.value = "❌ 昵称不能为空"
            self.status.color = ft.Colors.RED_400
            self.page.update()
            return
        
        profile = {
            "name": name,
            "tags": self.tags_input.get_tags(),
            "bio": (self.bio_in.value or "").strip(),
            "avatar": (self.avatar_in.value or "").strip(),
            "background": (self.bg_in.value or "").strip(),
            "conditions": {
                "required_tags": self.req_input.get_tags(),
                "optional_tags": self.opt_input.get_tags(),
                "min_match_count": int(self.min_match.value or "1"),
                "auto_accept": self.auto_accept.value,
            },
        }
        try:
            if not self.app.save_profile(profile):
                raise RuntimeError("运行时未初始化")
            self.status.value = "✨ 配置保存成功"
            self.status.color = ft.Colors.GREEN_400
        except Exception as e:
            self.status.value = f"❌ 保存失败: {e}"
            self.status.color = ft.Colors.RED_400
        self.page.update()

        def _clear():
            time.sleep(3)
            self.status.value = ""
            try:
                self.page.update()
            except Exception:
                pass
        threading.Thread(target=_clear, daemon=True).start()
