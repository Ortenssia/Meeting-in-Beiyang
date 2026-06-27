"""
好友界面。

重构目标：好友列表只消费 App 提供的好友卡片数据，不直接推断关系；
列表使用普通 ScrollView，避免 RecycleView 复用状态导致“计数有、列表空”的问题。
"""

from kivy.app import App
from kivy.clock import mainthread
from kivy.factory import Factory
from kivy.graphics import Color, Line, Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget


def get_root_app():
    return App.get_running_app()


class SearchInput(TextInput):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.font_name = "app_chinese_font"
        self.hint_text = "搜索好友"
        self.multiline = False
        self.foreground_color = (0.95, 0.95, 0.95, 1)
        self.background_color = (0, 0, 0, 0)
        self.cursor_color = (0.0, 0.6, 1.0, 1)
        self.padding = [dp(14), dp(9), dp(14), 0]
        self.bind(pos=self._redraw, size=self._redraw, focus=self._redraw)

    def _redraw(self, *_args):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(0.14, 0.14, 0.15, 1)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(8)])
            Color(0.0, 0.6, 1.0, 0.9 if self.focus else 0.15)
            Line(rounded_rectangle=(self.x, self.y, self.width, self.height, dp(8)), width=dp(1))


class CategoryChip(Button):
    def __init__(self, label, active=False, **kwargs):
        super().__init__(**kwargs)
        self.text = label
        self.font_name = "app_chinese_font"
        self.font_size = "13sp"
        self.background_normal = ""
        self.background_down = ""
        self.background_color = (0, 0, 0, 0)
        self.size_hint_y = None
        self.height = dp(32)
        self._active = active
        self.bind(pos=self._redraw, size=self._redraw, state=self._redraw)

    def set_active(self, active):
        self._active = active
        self.color = (1, 1, 1, 1) if active else (0.62, 0.64, 0.72, 1)
        self._redraw()

    def _redraw(self, *_args):
        self.canvas.before.clear()
        with self.canvas.before:
            if self._active:
                Color(0.0, 0.6, 1.0, 1)
            else:
                Color(0.14, 0.14, 0.15, 1)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(8)])


class FriendCard(BoxLayout):
    def __init__(self, data, **kwargs):
        super().__init__(**kwargs)
        self.data = data
        self.orientation = "horizontal"
        self.size_hint_y = None
        self.height = dp(72)
        self.padding = [dp(12), dp(8), dp(12), dp(8)]
        self.spacing = dp(12)
        self.bind(pos=self._redraw, size=self._redraw)

        avatar = Factory.LetterAvatar(
            avatar_size=dp(44),
            text=data.get("name", ""),
            name_key=data.get("name", ""),
            is_online=data.get("online", False),
        )
        self.add_widget(avatar)

        info = BoxLayout(orientation="vertical", spacing=dp(2))
        title_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(26))
        name = Label(
            text=data.get("name", "未知"),
            font_size="16sp",
            bold=True,
            halign="left",
            valign="middle",
            color=(1, 1, 1, 1),
        )
        name.bind(size=name.setter("text_size"))
        status = Label(
            text="在线" if data.get("online") else "离线",
            font_size="12sp",
            halign="right",
            valign="middle",
            color=(0.0, 0.86, 0.45, 1) if data.get("online") else (0.56, 0.58, 0.66, 1),
            size_hint_x=None,
            width=dp(54),
        )
        title_row.add_widget(name)
        title_row.add_widget(status)

        meta = Label(
            text=self._subtitle(data),
            font_size="12sp",
            halign="left",
            valign="middle",
            color=(0.62, 0.64, 0.72, 1),
            shorten=True,
            shorten_from="right",
        )
        meta.bind(size=meta.setter("text_size"))

        info.add_widget(title_row)
        info.add_widget(meta)
        self.add_widget(info)

    def _subtitle(self, data):
        tags = data.get("tags") or []
        tag_text = " / ".join(tags[:3]) if tags else data.get("category", "朋友")
        endpoint = f"{data.get('ip', '')}:{data.get('port', '')}".strip(":")
        return f"{tag_text} · {endpoint}" if endpoint else tag_text

    def _redraw(self, *_args):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(0.12, 0.12, 0.13, 1)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(8)])
            Color(1, 1, 1, 0.06)
            Line(rounded_rectangle=(self.x, self.y, self.width, self.height, dp(8)), width=dp(1))

    def on_touch_up(self, touch):
        if not self.collide_point(*touch.pos):
            return super().on_touch_up(touch)
        app = get_root_app()
        if hasattr(app, "open_chat_with"):
            app.open_chat_with(self.data.get("name", ""))
            return True
        return super().on_touch_up(touch)


class FriendsScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "friends"
        self._all_friends = []
        self._category = "全部"
        self._query = ""
        self._chips = {}
        self._build_ui()

    def _build_ui(self):
        self.background = Factory.SolidColorBackground()
        self.add_widget(self.background)

        root = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
        header = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(42))
        title = Label(
            text="好友",
            font_size="22sp",
            bold=True,
            halign="left",
            valign="middle",
            color=(1, 1, 1, 1),
        )
        title.bind(size=title.setter("text_size"))
        self.count_label = Label(
            text="0 位",
            font_size="13sp",
            halign="right",
            valign="middle",
            color=(0.62, 0.64, 0.72, 1),
            size_hint_x=None,
            width=dp(88),
        )
        header.add_widget(title)
        header.add_widget(self.count_label)
        root.add_widget(header)

        self.search_input = SearchInput(size_hint_y=None, height=dp(40))
        self.search_input.bind(text=self._on_search)
        root.add_widget(self.search_input)

        chip_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(32), spacing=dp(6))
        for category in ["全部", "同学", "朋友", "自定义"]:
            chip = CategoryChip(category, active=(category == self._category))
            chip.bind(on_press=lambda _btn, c=category: self._set_category(c))
            self._chips[category] = chip
            chip_row.add_widget(chip)
        root.add_widget(chip_row)

        self.scroll = ScrollView(size_hint_y=1)
        self.container = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
        self.container.bind(minimum_height=self.container.setter("height"))
        self.scroll.add_widget(self.container)
        root.add_widget(self.scroll)

        root.add_widget(self._build_nav("friends"))
        self.add_widget(root)

    def _build_nav(self, active):
        nav = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(56))
        row = BoxLayout(orientation="horizontal")
        with row.canvas.before:
            Color(0.1, 0.1, 0.1, 1)
            bg = Rectangle(pos=row.pos, size=row.size)
            Color(0.2, 0.2, 0.2, 1)
            border = Line(points=[row.x, row.y + row.height, row.x + row.width, row.y + row.height], width=dp(1))

        def redraw(w, *_args):
            bg.pos = w.pos
            bg.size = w.size
            border.points = [w.x, w.y + w.height, w.x + w.width, w.y + w.height]
        row.bind(pos=redraw, size=redraw)

        for text, screen in [("发现", "discover"), ("好友", "friends"), ("聊天", "chat"), ("我的", "profile"), ("设置", "settings")]:
            btn = Factory.IconTabButton(text=text, tab_name=screen, is_active=(screen == active))
            btn.bind(on_press=lambda _btn, name=screen: self._navigate(name))
            row.add_widget(btn)
        nav.add_widget(row)
        return nav

    def on_enter(self, *_args):
        self.refresh()

    @mainthread
    def refresh(self):
        app = get_root_app()
        self._all_friends = app.get_all_friends() if hasattr(app, "get_all_friends") else []
        self._render()

    @mainthread
    def update_friend_list(self, friends):
        self._all_friends = friends or []
        self._render()

    def _on_search(self, _input, text):
        self._query = (text or "").strip().lower()
        self._render()

    def _set_category(self, category):
        self._category = category
        for name, chip in self._chips.items():
            chip.set_active(name == category)
        self._render()

    def _render(self):
        items = list(self._all_friends)
        if self._category != "全部":
            items = [item for item in items if item.get("category", "朋友") == self._category]
        if self._query:
            items = [item for item in items if self._query in item.get("name", "").lower()]

        self.container.clear_widgets()
        for friend in items:
            self.container.add_widget(FriendCard(friend))

        if not items:
            empty = Label(
                text="暂无好友\n去「发现」发送好友申请",
                font_size="15sp",
                halign="center",
                valign="middle",
                color=(0.56, 0.58, 0.66, 1),
                size_hint_y=None,
                height=dp(160),
            )
            empty.bind(size=empty.setter("text_size"))
            self.container.add_widget(empty)

        self.count_label.text = f"{len(items)} 位"

    def _navigate(self, screen_name):
        app = get_root_app()
        if hasattr(app, "root") and hasattr(app.root, "current"):
            app.root.current = screen_name
