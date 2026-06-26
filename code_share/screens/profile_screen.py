"""
个人主页界面 (Challenge 3 - 相识北洋)

展示和编辑个人资料与好友匹配条件：
  - 名称输入框
  - 标签输入（逗号分隔，显示为 chip 样式）
  - 个人简介（多行文本）
  - 好友条件设置：
    - 必选标签输入
    - 可选标签输入
    - 最低匹配数量 Spinner
    - 自动接受好友请求开关 (Switch)
  - 保存按钮
  - 底部导航栏
"""

from kivy.app import App
from kivy.clock import mainthread
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.screenmanager import Screen
from kivy.uix.spinner import Spinner
from kivy.uix.switch import Switch
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.graphics import Color, RoundedRectangle, Rectangle, Line
from kivy.factory import Factory


def get_root_app():
    """返回当前运行的 Kivy App 实例。"""
    return App.get_running_app()


# ---------------------------------------------------------------------------
# 背景绘制辅助
# ---------------------------------------------------------------------------
def _add_background(widget, rgba):
    """为 widget 绑定彩色矩形背景。"""
    with widget.canvas.before:
        Color(*rgba)
        rect = Rectangle(pos=widget.pos, size=widget.size)
    widget.bind(
        pos=lambda w, v: setattr(rect, "pos", v),
        size=lambda w, v: setattr(rect, "size", v),
    )
    return rect


# ---------------------------------------------------------------------------
# TagChip - 单个标签芯片
# ---------------------------------------------------------------------------
class TagChip(BoxLayout):
    """单个标签芯片，带删除按钮。"""

    def __init__(self, text="", on_remove=None, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "horizontal"
        self.size_hint_x = None
        self.size_hint_y = None
        self.height = dp(32)
        self.spacing = dp(4)
        self.padding = [dp(10), dp(2)]

        self.tag_text = text
        self._on_remove = on_remove

        # 圆角背景与边框
        with self.canvas.before:
            Color(0.17, 0.17, 0.18, 1)  # Flat dark grey background
            self._bg = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[dp(16)],
            )
            # No borders in flat design
            Color(0, 0, 0, 0)
            self._border = Line(width=0)
        self.bind(
            pos=self._update_rect,
            size=self._update_rect,
        )

        # 标签文本
        lbl = Label(
            text=text,
            font_size="13sp",
            color=(1, 1, 1, 1),
            size_hint_x=None,
        )
        lbl.bind(
            texture_size=lambda inst, val: setattr(inst, "width", val[0] + dp(4)),
        )
        self.add_widget(lbl)

        # 删除按钮 (x)
        remove_btn = Button(
            text="x",
            font_size="14sp",
            size_hint_x=None,
            width=dp(20),
            background_normal='',
            background_down='',
            background_color=(0, 0, 0, 0),
            color=(0.9, 0.3, 0.35, 0.8), # Refined subtle red
        )
        remove_btn.bind(on_press=self._remove_self)
        self.add_widget(remove_btn)

        # 绑定宽度自适应
        self.bind(minimum_width=self.setter("width"))

    def _update_rect(self, instance, value):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def _remove_self(self, _btn):
        """从父容器中移除自身并回调。"""
        parent = self.parent
        if parent:
            parent.remove_widget(self)
        if self._on_remove:
            self._on_remove(self.tag_text)


# ---------------------------------------------------------------------------
# TagInput - 标签输入区域（输入框 + chip 展示）
# ---------------------------------------------------------------------------
class TagInput(BoxLayout):
    """标签输入组件：TextInput + 回车添加 chip + FlowRow 展示。"""

    def __init__(self, hint_text="输入标签，逗号分隔后回车", **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.size_hint_y = None
        self.bind(minimum_height=self.setter("height"))
        self.spacing = dp(6)

        self._tags = []

        # 输入行
        input_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(38),
            spacing=dp(8),
        )

        self.text_input = Factory.ModernTextInput(
            hint_text=hint_text,
            multiline=False,
            size_hint_x=0.8,
        )
        self.text_input.bind(on_text_validate=self._on_add_tags)

        add_btn = Factory.ModernButtonAccent(
            text="添加",
            size_hint_x=0.2,
        )
        add_btn.bind(on_press=self._on_add_tags)

        input_row.add_widget(self.text_input)
        input_row.add_widget(add_btn)
        self.add_widget(input_row)

        # Chip 展示区 (ScrollView + 水平 wrap 布局)
        self.chip_scroll = ScrollView(
            size_hint_y=None,
            height=dp(42),
            scroll_y=0,
        )
        self.chip_container = BoxLayout(
            orientation="horizontal",
            size_hint_x=None,
            size_hint_y=None,
            height=dp(36),
            spacing=dp(6),
            padding=[dp(2), dp(2)],
        )
        self.chip_container.bind(minimum_width=self.chip_container.setter("width"))
        self.chip_scroll.add_widget(self.chip_container)
        self.add_widget(self.chip_scroll)

    def _on_add_tags(self, *_args):
        """解析输入框文本，按逗号分割后添加 chip。"""
        raw = self.text_input.text.strip()
        if not raw:
            return
        # 支持中英文逗号
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if not parts or len(parts) == 1 and parts[0] == raw:
            parts = [p.strip() for p in raw.split("\uff0c") if p.strip()]
        if not parts:
            parts = [raw]
            
        for tag in parts:
            if tag and tag not in self._tags:
                self._tags.append(tag)
                chip = TagChip(text=tag, on_remove=self._on_remove_tag)
                self.chip_container.add_widget(chip)
        self.text_input.text = ""

    def _on_remove_tag(self, tag_text):
        """移除指定标签。"""
        if tag_text in self._tags:
            self._tags.remove(tag_text)

    def get_tags(self):
        """返回当前所有标签列表。"""
        return list(self._tags)

    def set_tags(self, tags):
        """设置标签列表（清空后重新添加）。"""
        self._tags = []
        self.chip_container.clear_widgets()
        for tag in tags:
            tag = tag.strip()
            if tag and tag not in self._tags:
                self._tags.append(tag)
                chip = TagChip(text=tag, on_remove=self._on_remove_tag)
                self.chip_container.add_widget(chip)


# ---------------------------------------------------------------------------
# ProfileScreen - 个人主页界面
# ---------------------------------------------------------------------------
class ProfileScreen(Screen):
    """个人主页：编辑个人资料与好友匹配条件。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "profile"
        self._build_ui()

    # ---- UI 构造 ---------------------------------------------------------

    def _build_ui(self):
        # 1. 挂载纯色背景
        self.background = Factory.SolidColorBackground()
        self.add_widget(self.background)

        # 2. 内容层容器
        root = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))

        # -- 标题栏 --
        title = Label(
            text="我的主页",
            font_size="22sp",
            bold=True,
            size_hint_y=None,
            height=dp(48),
            color=(1, 1, 1, 1),
            halign="center"
        )
        root.add_widget(title)

        # -- 滚动区域 --
        scroll = ScrollView(size_hint_y=1)
        form = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(16),  # 卡片之间的间距
            padding=[dp(6), dp(6), dp(6), dp(16)],
        )
        form.bind(minimum_height=form.setter("height"))

        # ==== 头像预览 ====
        from kivy.uix.anchorlayout import AnchorLayout
        avatar_card = AnchorLayout(anchor_x='center', anchor_y='center', size_hint_y=None, height=dp(96))
        self.avatar_preview = Factory.LetterAvatar(avatar_size=dp(80))
        avatar_card.add_widget(self.avatar_preview)
        form.add_widget(avatar_card)

        # 卡片容器构造辅助函数 (Flat Design)
        def make_flat_card(spacing=dp(10), padding=dp(16)):
            card = BoxLayout(orientation="vertical", spacing=spacing, padding=padding, size_hint_y=None)
            with card.canvas.before:
                # Main card background (Solid dark)
                Color(0.12, 0.12, 0.13, 1)
                bg = RoundedRectangle(pos=card.pos, size=card.size, radius=[dp(12)])
            def _up(w, v):
                bg.pos = w.pos
                bg.size = w.size
            card.bind(pos=_up, size=_up)
            card.bind(minimum_height=card.setter("height"))
            return card

        # ==== Card 1: 个人基本信息 ====
        card_basic = make_flat_card(spacing=dp(8))
        card_basic.add_widget(self._make_section_label("基本资料"))

        # -- 名称输入 --
        name_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(38),
            spacing=dp(10),
        )
        name_row.add_widget(self._make_field_label("我的昵称", size_hint_x=0.22))
        self.name_input = Factory.ModernTextInput(
            hint_text="输入你的名称",
            multiline=False,
            size_hint_x=0.78,
        )
        self.name_input.bind(text=self._on_name_changed)
        name_row.add_widget(self.name_input)
        card_basic.add_widget(name_row)

        # -- 自定义头像 --
        avatar_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(38), spacing=dp(10))
        avatar_row.add_widget(self._make_field_label("自定义头像", size_hint_x=0.22))
        self.avatar_input = Factory.ModernTextInput(hint_text="本地图片路径", multiline=False, size_hint_x=0.55)
        avatar_row.add_widget(self.avatar_input)
        avatar_btn = Factory.ModernButtonSecondary(text="浏览", size_hint_x=0.23)
        avatar_btn.bind(on_press=lambda x: self._browse_file(self.avatar_input))
        avatar_row.add_widget(avatar_btn)
        card_basic.add_widget(avatar_row)

        # -- 自定义背景 --
        bg_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(38), spacing=dp(10))
        bg_row.add_widget(self._make_field_label("自定义背景", size_hint_x=0.22))
        self.bg_input = Factory.ModernTextInput(hint_text="本地图片路径", multiline=False, size_hint_x=0.55)
        bg_row.add_widget(self.bg_input)
        bg_btn = Factory.ModernButtonSecondary(text="浏览", size_hint_x=0.23)
        bg_btn.bind(on_press=lambda x: self._browse_file(self.bg_input))
        bg_row.add_widget(bg_btn)
        card_basic.add_widget(bg_row)

        # -- 标签输入 --
        card_basic.add_widget(self._make_field_label("兴趣标签（展示给其他人）"))
        self.tags_input = TagInput(hint_text="输入后回车，例如：编程、篮球、游戏")
        card_basic.add_widget(self.tags_input)

        # -- 个人简介 --
        card_basic.add_widget(self._make_field_label("个人简介"))
        self.bio_input = Factory.ModernTextInput(
            hint_text="介绍一下自己吧...",
            multiline=True,
            size_hint_y=None,
            height=dp(86),
        )
        card_basic.add_widget(self.bio_input)
        form.add_widget(card_basic)

        # ==== Card 2: 好友匹配条件 ====
        card_conditions = make_flat_card(spacing=dp(8))
        card_conditions.add_widget(self._make_section_label("自动同意匹配条件"))

        # -- 必选标签 --
        card_conditions.add_widget(self._make_field_label("必选标签（对方必须拥有）"))
        self.required_tags_input = TagInput(hint_text="如：北洋、计算机")
        card_conditions.add_widget(self.required_tags_input)

        # -- 可选标签 --
        card_conditions.add_widget(self._make_field_label("可选标签（对方拥有其一即可）"))
        self.optional_tags_input = TagInput(hint_text="如：唱歌、跳舞、画画")
        card_conditions.add_widget(self.optional_tags_input)

        # -- 最低匹配数量 --
        min_match_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(38),
            spacing=dp(10),
        )
        min_match_row.add_widget(self._make_field_label("最低匹配标签数", size_hint_x=0.45))
        
        self.min_match_spinner = Spinner(
            text="1",
            values=[str(i) for i in range(1, 11)],
            size_hint_x=0.35,
            background_normal='',
            background_down='',
            background_color=(0, 0, 0, 0),
            color=(1, 1, 1, 1),
            font_name='app_chinese_font',
            font_size="14sp",
        )
        with self.min_match_spinner.canvas.before:
            # Clean flat background like ModernTextInput
            Color(0.17, 0.17, 0.18, 1)
            self._spin_bg = RoundedRectangle(
                pos=self.min_match_spinner.pos,
                size=self.min_match_spinner.size,
                radius=[dp(8)]
            )
            
        def update_spin_canvas(w, v):
            self._spin_bg.pos = w.pos
            self._spin_bg.size = w.size
            
        self.min_match_spinner.bind(pos=update_spin_canvas, size=update_spin_canvas)
        min_match_row.add_widget(self.min_match_spinner)
        min_match_row.add_widget(Widget(size_hint_x=0.2))
        card_conditions.add_widget(min_match_row)

        # -- 自动接受开关 --
        auto_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(40),
            spacing=dp(10),
        )
        auto_row.add_widget(self._make_field_label("符合条件自动同意申请", size_hint_x=0.7))
        self.auto_accept_switch = Switch(
            active=False,
            size_hint_x=None,
            width=dp(60),
        )
        auto_row.add_widget(self.auto_accept_switch)
        auto_row.add_widget(Widget(size_hint_x=0.1))
        card_conditions.add_widget(auto_row)
        form.add_widget(card_conditions)

        # -- 保存按钮 --
        save_btn = Factory.ModernButtonAccent(
            text="保存配置",
            size_hint_y=None,
            height=dp(44),
        )
        save_btn.bind(on_press=self._on_save)
        form.add_widget(save_btn)

        # -- 保存状态提示 --
        self.save_status = Label(
            text="",
            font_size="13sp",
            bold=True,
            size_hint_y=None,
            height=dp(24),
            color=(0.0, 0.9, 0.46, 1),
        )
        form.add_widget(self.save_status)

        scroll.add_widget(form)
        root.add_widget(scroll)

        # -- 底部导航栏 --
        nav_bar = self._build_modern_nav_bar("profile")
        root.add_widget(nav_bar)

        self.add_widget(root)
    def _build_modern_nav_bar(self, active_tab_name):
        # 底部标准 Tab Bar
        nav_wrapper = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(56),
        )
        
        nav_container = BoxLayout(
            orientation="horizontal",
            spacing=0,
        )
        with nav_container.canvas.before:
            # Solid Tab Bar Background
            Color(0.1, 0.1, 0.1, 1)
            self._nav_bg = Rectangle(
                pos=nav_container.pos,
                size=nav_container.size
            )
            # Top separator line
            Color(0.2, 0.2, 0.2, 1)
            self._nav_border = Line(
                points=[nav_container.x, nav_container.y + nav_container.height, nav_container.x + nav_container.width, nav_container.y + nav_container.height],
                width=dp(1)
            )
        
        def update_nav_bg(w, v):
            self._nav_bg.pos = nav_container.pos
            self._nav_bg.size = nav_container.size
            self._nav_border.points = [nav_container.x, nav_container.y + nav_container.height, nav_container.x + nav_container.width, nav_container.y + nav_container.height]
        nav_container.bind(pos=update_nav_bg, size=update_nav_bg)

        nav_items = [

            ("发现", "discover"),
            ("好友", "friends"),
            ("聊天", "chat"),
            ("我的", "profile"),
            ("设置", "settings"),
        ]
        
        for text, sn in nav_items:
            is_active = (sn == active_tab_name)
            btn = Factory.IconTabButton(
                text=text,
                tab_name=sn,
                is_active=is_active
            )
            btn.bind(on_press=lambda _b, name=sn: self._navigate(name))
            nav_container.add_widget(btn)
            
        nav_wrapper.add_widget(nav_container)
        return nav_wrapper

    def _browse_file(self, target_input):
        import threading
        def _pick():
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                file_path = filedialog.askopenfilename(filetypes=[("Image files", "*.png;*.jpg;*.jpeg;*.bmp")])
                root.destroy()
                if file_path:
                    from kivy.clock import Clock
                    Clock.schedule_once(lambda dt: setattr(target_input, 'text', file_path), 0)
            except Exception as e:
                print("Browse file failed:", e)
        threading.Thread(target=_pick, daemon=True).start()

    # ---- 逻辑处理 --------------------------------------------------------

    def on_enter(self, *args):
        """进入界面时从 App 加载已保存的资料。"""
        self._load_profile()

    # ---- 公共 API --------------------------------------------------------

    @mainthread
    def set_profile(self, profile):
        """
        设置界面显示的个人资料。

        Args:
            profile: dict，包含 name, tags, bio 等字段。
        """
        if not profile:
            return
        
        # 1. 顶部大头像及名称更新
        if profile.get("name"):
            self.avatar_preview.text = profile["name"]
            self.avatar_preview.name_key = profile["name"]
        
        if profile.get("avatar"):
            self.avatar_preview.avatar_source = profile["avatar"]

        # 2. 表单区基本信息
        self.name_input.text = profile.get("name", "")
        self.bio_input.text = profile.get("bio", "")
        self.avatar_input.text = profile.get("avatar", "")
        self.bg_input.text = profile.get("background", "")

        self.tags_input.set_tags(profile.get("tags", []))

        conditions = profile.get("conditions", {})
        self.required_tags_input.set_tags(conditions.get("required_tags", []))
        self.optional_tags_input.set_tags(conditions.get("optional_tags", []))
        self.min_match_spinner.text = str(conditions.get("min_match_count", 1))
        self.auto_accept_switch.active = conditions.get("auto_accept", False)

    @mainthread
    def show_save_status(self, text, is_error=False):
        """显示保存操作的状态提示。"""
        self.save_status.text = text
        self.save_status.color = (1.0, 0.23, 0.19, 1) if is_error else (0.0, 0.9, 0.46, 1)

    # ---- 事件处理 --------------------------------------------------------

    def _on_name_changed(self, instance, text):
        self.avatar_preview.text = text
        self.avatar_preview.name_key = text

    def _on_save(self, _btn):
        """保存按钮点击事件。"""
        name = self.name_input.text.strip()
        if not name:
            self.show_save_status("名称不能为空", is_error=True)
            return

        bio = self.bio_input.text.strip()
        tags = self.tags_input.get_tags()

        avatar_path = self.avatar_input.text.strip()
        bg_path = self.bg_input.text.strip()

        conditions = {
            "required_tags": self.required_tags_input.get_tags(),
            "optional_tags": self.optional_tags_input.get_tags(),
            "min_match_count": int(self.min_match_spinner.text),
            "auto_accept": self.auto_accept_switch.active
        }

        profile = {
            "name": name,
            "tags": tags,
            "bio": bio,
            "avatar": avatar_path,
            "background": bg_path,
            "conditions": conditions
        }

        app = get_root_app()
        if hasattr(app, "save_profile"):
            try:
                app.save_profile(profile)
                self.show_save_status("保存成功")
            except Exception as e:
                self.show_save_status(f"保存失败: {e}", is_error=True)
        else:
            self.show_save_status("保存成功（本地）")

    # ---- 内部方法 --------------------------------------------------------

    def _load_profile(self):
        """从 App 加载已保存的个人资料。"""
        app = get_root_app()
        if hasattr(app, "get_my_profile"):
            profile = app.get_my_profile()
            if profile:
                self.set_profile(profile)

    def _make_section_label(self, text):
        """创建分组标题标签。"""
        lbl = Label(
            text=text,
            font_size="16sp",
            bold=True,
            size_hint_y=None,
            height=dp(36),
            halign="left",
            valign="bottom",
            color=(0.5, 0.5, 0.55, 1), # Flat grey section title
        )
        lbl.bind(size=lbl.setter("text_size"))
        return lbl

    def _make_field_label(self, text, size_hint_x=1.0):
        """创建字段名称标签。"""
        lbl = Label(
            text=text,
            font_size="14sp",
            size_hint_x=size_hint_x,
            size_hint_y=None,
            height=dp(24),
            halign="left",
            valign="middle",
            color=(0.63, 0.65, 0.75, 1),
        )
        lbl.bind(size=lbl.setter("text_size"))
        return lbl

    def _navigate(self, screen_name):
        """通过 ScreenManager 切换界面，使用无延迟切换避免动画卡顿。"""
        app = get_root_app()
        if hasattr(app, "root") and hasattr(app.root, "current"):
            if app.root.current == screen_name:
                return
            from kivy.uix.screenmanager import NoTransition
            app.root.transition = NoTransition()
            app.root.current = screen_name

