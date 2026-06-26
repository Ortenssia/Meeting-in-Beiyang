"""
好友管理界面 (Challenge 3 - 相识北洋)

展示好友列表，支持分类筛选、搜索和交互操作：
  - 分类标签栏：全部 / 同学 / 朋友 / 自定义
  - 好友列表：RecycleView，每行显示名称、在线状态圆点、最后活跃时间
  - 搜索栏：按名称过滤好友
  - 点击好友进入聊天，长按弹出操作菜单（删除、更改分类）
  - 底部导航栏
"""

from kivy.app import App
from kivy.clock import mainthread, Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.uix.recycleview import RecycleView
from kivy.uix.screenmanager import Screen
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.graphics import Color, Ellipse, Rectangle, RoundedRectangle, Line
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
# 好友行 - RecycleView 条目
# ---------------------------------------------------------------------------
class FriendItem(BoxLayout):
    """好友列表中的单行：头像 + 名称 + 最后活跃时间。

    支持点击进入聊天、长按弹出操作菜单。
    """

    # 长按判定时间（秒）
    LONG_PRESS_DURATION = 0.6

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "horizontal"
        self.size_hint_y = None
        self.height = dp(60)
        self.padding = [dp(14), dp(6)]
        self.spacing = dp(12)

        # 绘制卡片背景与圆角边框
        with self.canvas.before:
            Color(1, 1, 1, 0.03)  # 磨砂玻璃背景
            self._bg = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[dp(12)]
            )
            Color(1, 1, 1, 0.12)  # 高光边框色
            self._border = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, dp(12)),
                width=dp(1)
            )
        self.bind(
            pos=self._update_rect,
            size=self._update_rect
        )

        self._data = {}
        self._long_press_event = None

        # -- 头像 --
        self.avatar = Factory.LetterAvatar(avatar_size=dp(42))

        # -- 名称 --
        self.name_label = Label(
            text="",
            font_size="16sp",
            bold=True,
            halign="left",
            valign="middle",
            size_hint_x=0.55,
            color=(1, 1, 1, 1),
        )
        self.name_label.bind(size=self.name_label.setter("text_size"))

        # -- 最后活跃时间 --
        self.last_seen_label = Label(
            text="",
            font_size="12sp",
            halign="right",
            valign="middle",
            size_hint_x=0.3,
            color=(0.63, 0.65, 0.75, 1),
        )
        self.last_seen_label.bind(size=self.last_seen_label.setter("text_size"))

        self.add_widget(self.avatar)
        self.add_widget(self.name_label)
        self.add_widget(self.last_seen_label)

        # 绑定触摸事件（点击 / 长按 / 滑动）
        self.bind(
            on_touch_down=self._on_touch_down,
            on_touch_move=self._on_touch_move,
            on_touch_up=self._on_touch_up,
        )

    def _update_rect(self, instance, value):
        self._bg.pos = self.pos
        self._bg.size = self.size
        self._border.rounded_rectangle = (self.x, self.y, self.width, self.height, dp(12))

    def refresh_view_attrs(self, rv, index, data):
        """由 RecycleView 适配器调用，填充行数据。"""
        self._data = data
        name = data.get("name", "未知")
        self.name_label.text = name
        self.last_seen_label.text = data.get("last_seen", "")

        is_online = data.get("online", False)
        self.avatar.text = name
        self.avatar.name_key = name
        self.avatar.is_online = is_online

        return super().refresh_view_attrs(rv, index, data)

    # ---- 触摸事件（点击 + 长按） ----

    def _on_touch_down(self, touch, *args):
        if not self.collide_point(*touch.pos):
            return False
        self._touch_start_pos = touch.pos
        # 启动长按计时器
        self._long_press_event = Clock.schedule_once(
            self._on_long_press, self.LONG_PRESS_DURATION
        )
        return False

    def _on_touch_move(self, touch, *args):
        if not self.collide_point(*touch.pos):
            # 划出去了，取消长按判定
            if self._long_press_event:
                self._long_press_event.cancel()
                self._long_press_event = None
            return False
            
        if hasattr(self, '_touch_start_pos') and self._touch_start_pos:
            import math
            dist = math.sqrt((touch.x - self._touch_start_pos[0])**2 + (touch.y - self._touch_start_pos[1])**2)
            if dist > dp(10):
                # 滑动距离过大，说明是列表滚动，取消长按判定
                if self._long_press_event:
                    self._long_press_event.cancel()
                    self._long_press_event = None
        return False

    def _on_touch_up(self, touch, *args):
        if not self.collide_point(*touch.pos):
            if self._long_press_event:
                self._long_press_event.cancel()
                self._long_press_event = None
            if hasattr(self, '_touch_start_pos'):
                self._touch_start_pos = None
            return False
            
        # 取消长按（如果尚未触发）
        if self._long_press_event:
            self._long_press_event.cancel()
            self._long_press_event = None
            
            # 判断移动距离，防止滚动时误触发短按
            if hasattr(self, '_touch_start_pos') and self._touch_start_pos:
                import math
                dist = math.sqrt((touch.x - self._touch_start_pos[0])**2 + (touch.y - self._touch_start_pos[1])**2)
                if dist <= dp(10):
                    self._on_click()
                    
        if hasattr(self, '_touch_start_pos'):
            self._touch_start_pos = None
        return False

    def _on_click(self):
        """短按好友：跳转到聊天界面。"""
        name = self._data.get("name", "")
        if not name:
            return
        app = get_root_app()
        if hasattr(app, "open_chat_with"):
            app.open_chat_with(name)
        # 切换到聊天界面
        if hasattr(app, "root") and hasattr(app.root, "current"):
            app.root.current = "chat"

    def _on_long_press(self, _dt):
        """长按好友：弹出操作菜单。"""
        self._long_press_event = None
        name = self._data.get("name", "")
        if not name:
            return
        self._show_options_popup(name)

    def _show_options_popup(self, friend_name):
        """弹出好友操作菜单（删除、更改分类）。"""
        content = BoxLayout(orientation="vertical", spacing=dp(10), padding=[dp(16), dp(16)])
        _add_background(content, (0.09, 0.10, 0.14, 1))

        # 标题
        title_label = Label(
            text=friend_name,
            font_size="18sp",
            bold=True,
            size_hint_y=None,
            height=dp(36),
            color=(1, 1, 1, 1),
        )
        content.add_widget(title_label)

        # 更改分类按钮
        category_btn = Factory.ModernButtonAccent(
            text="更改分类",
            size_hint_y=None,
            height=dp(42),
        )
        category_btn.bind(on_press=lambda _b: self._on_change_category(friend_name, popup))
        content.add_widget(category_btn)

        # 删除好友按钮
        delete_btn = Factory.ModernButtonDanger(
            text="删除好友",
            size_hint_y=None,
            height=dp(42),
        )
        delete_btn.bind(on_press=lambda _b: self._on_delete_friend(friend_name, popup))
        content.add_widget(delete_btn)

        # 取消按钮
        cancel_btn = Factory.ModernButtonSecondary(
            text="取消",
            size_hint_y=None,
            height=dp(42),
        )
        cancel_btn.bind(on_press=lambda _b: popup.dismiss())
        content.add_widget(cancel_btn)

        popup = Popup(
            title="好友操作",
            content=content,
            size_hint=(0.8, 0.48),
            background_color=(0.04, 0.04, 0.06, 0.95),
            title_align="center"
        )
        popup.open()

    def _on_change_category(self, friend_name, popup):
        """弹出分类选择对话框。"""
        popup.dismiss()

        content = BoxLayout(orientation="vertical", spacing=dp(12), padding=[dp(16), dp(16)])
        _add_background(content, (0.09, 0.10, 0.14, 1))

        categories = ["同学", "朋友", "自定义"]
        btn_row = BoxLayout(orientation="horizontal", spacing=dp(8), size_hint_y=None, height=dp(44))

        def _select(cat):
            app = get_root_app()
            if hasattr(app, "set_friend_category"):
                app.set_friend_category(friend_name, cat)
            cat_popup.dismiss()

        for cat in categories:
            btn = Factory.ModernButton(
                text=cat,
                font_size="14sp",
            )
            btn.bind(on_press=lambda _b, c=cat: _select(c))
            btn_row.add_widget(btn)

        content.add_widget(Label(
            text="选择分类:",
            font_size="16sp",
            size_hint_y=None,
            height=dp(30),
            color=(1, 1, 1, 1),
            bold=True
        ))
        content.add_widget(btn_row)

        cat_popup = Popup(
            title="更改分类",
            content=content,
            size_hint=(0.8, 0.32),
            background_color=(0.04, 0.04, 0.06, 0.95),
            title_align="center"
        )
        cat_popup.open()

    def _on_delete_friend(self, friend_name, popup):
        """删除好友。"""
        popup.dismiss()
        app = get_root_app()
        if hasattr(app, "delete_friend"):
            app.delete_friend(friend_name)


# ---------------------------------------------------------------------------
# 好友列表 RecycleView
# ---------------------------------------------------------------------------
class FriendList(RecycleView):
    """可滚动的好友列表。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.viewclass = FriendItem
        layout = RecycleBoxLayout(
            default_size=(None, dp(60)),
            default_size_hint=(1, None),
            size_hint_y=None,
            orientation="vertical",
            spacing=dp(6),
        )
        layout.bind(minimum_height=layout.setter("height"))
        self.add_widget(layout)
        self.data = []


# ---------------------------------------------------------------------------
# GlassSearchInput - 毛玻璃药丸风格搜索框，左侧手绘放大镜矢量图标
# ---------------------------------------------------------------------------
class GlassSearchInput(TextInput):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.font_name = 'app_chinese_font'
        self.foreground_color = (1, 1, 1, 1)
        self.background_color = (0, 0, 0, 0)
        self.cursor_color = (0.44, 0.32, 1.0, 1)
        self.padding = [dp(36), dp(10), dp(12), dp(10)]
        self.use_bubble = True
        self.bind(pos=self._redraw, size=self._redraw, focus=self._redraw)

    def _redraw(self, *args):
        self.padding = [dp(36), max(0, (self.height - self.line_height) / 2.0), dp(12), 0]
        self.canvas.before.clear()
        with self.canvas.before:
            # 磨砂背景
            if self.focus:
                Color(1, 1, 1, 0.08)
            else:
                Color(1, 1, 1, 0.04)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(18)])

            # 边框发光
            if self.focus:
                Color(0.44, 0.32, 1.0, 0.8)
            else:
                Color(1, 1, 1, 0.12)
            Line(rounded_rectangle=(self.x, self.y, self.width, self.height, dp(18)), width=dp(1))
            
            # 聚焦时外发光
            if self.focus:
                Color(0.44, 0.32, 1.0, 0.25)
                Line(rounded_rectangle=(self.x - dp(1), self.y - dp(1), self.width + dp(2), self.height + dp(2), dp(18)), width=dp(1.5))

            # 放大镜矢量图
            cx = self.x + dp(20)
            cy = self.y + self.height / 2
            Color(0.44, 0.32, 1.0, 0.9) if self.focus else Color(0.55, 0.57, 0.68, 1)
            Line(circle=(cx, cy + dp(2), dp(4.5)), width=dp(1.2))
            Line(points=[cx + dp(3), cy - dp(1.5), cx + dp(7.5), cy - dp(6)], width=dp(1.5))


# ---------------------------------------------------------------------------
# FriendsScreen - 好友管理界面
# ---------------------------------------------------------------------------
class FriendsScreen(Screen):
    """好友管理界面：分类筛选、搜索、聊天入口、好友操作。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "friends"
        self._all_friends = []          # 完整好友数据缓存
        self._current_category = "全部"  # 当前筛选分类
        self._search_text = ""          # 当前搜索文本
        self._category_buttons = {}     # 分类按钮引用
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
            text="好友",
            font_size="22sp",
            bold=True,
            size_hint_y=None,
            height=dp(48),
            color=(1, 1, 1, 1),
            halign="center"
        )
        root.add_widget(title)

        # -- 搜索与分类聚合卡片 (合并为一个悬浮卡片区块) --
        header_card = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(100),
            spacing=dp(10),
            padding=[dp(10), dp(10), dp(10), dp(10)],
        )
        with header_card.canvas.before:
            Color(0.12, 0.12, 0.13, 1)  # Solid flat card
            self._header_bg = RoundedRectangle(pos=header_card.pos, size=header_card.size, radius=[dp(12)])
            
        def update_header_bg(w, v):
            self._header_bg.pos = header_card.pos
            self._header_bg.size = header_card.size
        header_card.bind(pos=update_header_bg, size=update_header_bg)

        # 1. 搜索行
        search_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(36),
            spacing=dp(6),
        )

        self.search_input = GlassSearchInput(
            hint_text="搜索好友...",
            multiline=False,
            size_hint_x=0.85,
        )
        self.search_input.bind(text=self._on_search_text_changed)

        # 迷你圆形清除按键
        clear_btn = Button(
            text="×",
            font_size="16sp",
            bold=True,
            size_hint_x=0.15,
            background_normal='',
            background_down='',
            background_color=(0, 0, 0, 0),
            color=(0.55, 0.57, 0.68, 0.7)
        )
        with clear_btn.canvas.before:
            Color(0.17, 0.17, 0.18, 1)
            self._clear_bg = RoundedRectangle(pos=clear_btn.pos, size=clear_btn.size, radius=[dp(8)])
            
        def update_clear_btn(b, v):
            self._clear_bg.pos = b.pos
            self._clear_bg.size = b.size
        clear_btn.bind(pos=update_clear_btn, size=update_clear_btn)
        clear_btn.bind(on_press=self._on_clear_search)

        search_row.add_widget(self.search_input)
        search_row.add_widget(clear_btn)
        header_card.add_widget(search_row)

        # 2. 分类标签行
        category_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(32),
            spacing=dp(6),
        )

        categories = ["全部", "同学", "朋友", "自定义"]
        for cat in categories:
            is_active = (cat == self._current_category)
            btn = Button(
                text=cat,
                background_normal='',
                background_down='',
                background_color=(0, 0, 0, 0),
                color=(1, 1, 1, 1) if is_active else (0.63, 0.65, 0.75, 1),
                font_name='app_chinese_font',
                font_size="13sp",
                bold=is_active
            )
            
            with btn.canvas.before:
                btn_color_inst = Color(0.0, 0.6, 1.0, 0.2) if is_active else Color(0, 0, 0, 0)
                btn_bg = RoundedRectangle(pos=btn.pos, size=btn.size, radius=[dp(8)])
            
            def update_btn_bg(b, v, bg=btn_bg):
                bg.pos = b.pos
                bg.size = b.size
            btn.bind(pos=update_btn_bg, size=update_btn_bg)
            
            # 存下颜色引用以动态切换
            btn.bind(on_press=lambda _b, c=cat: self._on_category_selected(c))
            self._category_buttons[cat] = (btn, btn_color_inst)
            category_row.add_widget(btn)

        header_card.add_widget(category_row)
        root.add_widget(header_card)

        # -- 好友列表 --
        self.friend_list = FriendList(size_hint_y=1)
        root.add_widget(self.friend_list)

        # -- 好友计数标签 --
        self.count_label = Label(
            text="共 0 位好友",
            font_size="13sp",
            size_hint_y=None,
            height=dp(24),
            halign="center",
            color=(0.63, 0.65, 0.75, 1),
        )
        root.add_widget(self.count_label)

        # -- 底部导航栏 --
        nav_bar = self._build_modern_nav_bar("friends")
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

    # ---- 生命周期 --------------------------------------------------------

    def on_enter(self, *args):
        """进入界面时刷新好友列表。"""
        self._load_friends()

    # ---- 公共 API --------------------------------------------------------

    @mainthread
    def update_friend_list(self, friends):
        """
        更新好友列表显示。

        Args:
            friends: list[dict]，每个 dict 包含:
                - name: str 好友名称
                - online: bool 是否在线
                - last_seen: str 最后活跃时间
                - category: str 分类
        """
        self._all_friends = friends
        self._apply_filter()

    @mainthread
    def refresh(self):
        """重新从 App 加载好友数据并刷新。"""
        self._load_friends()

    # ---- 事件处理 --------------------------------------------------------

    def _on_category_selected(self, category):
        """分类标签点击事件。"""
        self._current_category = category
        # 更新按钮外观
        for cat, (btn, color_inst) in self._category_buttons.items():
            if cat == category:
                btn.color = (1, 1, 1, 1)
                btn.bold = True
                color_inst.rgba = (0.44, 0.32, 1.0, 0.45) # 玻璃半透明紫色
            else:
                btn.color = (0.63, 0.65, 0.75, 1)
                btn.bold = False
                color_inst.rgba = (0, 0, 0, 0)
        self._apply_filter()

    def _on_search_text_changed(self, instance, text):
        """搜索框文本变化事件。"""
        self._search_text = text.strip().lower()
        self._apply_filter()

    def _on_clear_search(self, _btn):
        """清除搜索框。"""
        self.search_input.text = ""
        self._search_text = ""
        self._apply_filter()

    # ---- 内部方法 --------------------------------------------------------

    def _load_friends(self):
        """从 App 加载好友数据。"""
        app = get_root_app()
        if hasattr(app, "get_all_friends"):
            friends = app.get_all_friends()
            if friends is not None:
                self.update_friend_list(friends)

    def _apply_filter(self):
        """根据当前分类和搜索文本过滤好友列表。"""
        filtered = self._all_friends

        # 分类过滤
        if self._current_category != "全部":
            filtered = [
                f for f in filtered
                if f.get("category", "朋友") == self._current_category
            ]

        # 搜索过滤
        if self._search_text:
            filtered = [
                f for f in filtered
                if self._search_text in f.get("name", "").lower()
            ]

        # 在线排序：在线好友靠前
        filtered.sort(key=lambda f: (not f.get("online", False), f.get("name", "")))

        # 更新 RecycleView
        self.friend_list.data = [
            {
                "name": f.get("name", "未知"),
                "online": f.get("online", False),
                "last_seen": f.get("last_seen", ""),
            }
            for f in filtered
        ]

        self.count_label.text = f"共 {len(filtered)} 位好友"

    def _navigate(self, screen_name):
        """通过 ScreenManager 切换界面，使用无延迟切换避免动画卡顿。"""
        app = get_root_app()
        if hasattr(app, "root") and hasattr(app.root, "current"):
            if app.root.current == screen_name:
                return
            from kivy.uix.screenmanager import NoTransition
            app.root.transition = NoTransition()
            app.root.current = screen_name

