"""
聊天界面 (Challenge 3 - 相识北洋)

包含两个视图，通过内部状态切换：
  1. 聊天列表视图 (ChatListView):
     - 展示有消息记录的好友列表
     - 每行显示：好友名称、最后一条消息预览、未读消息数
  2. 聊天窗口视图 (ChatWindowView):
     - 顶部：返回按钮 + 好友名称
     - 消息区域 (ScrollView)：消息气泡（左侧 = 好友，右侧 = 自己）
     - 底部：文本输入框 + 发送按钮
     - 每条消息显示时间戳

底部导航栏在两个视图中均可见。
"""

from kivy.app import App
from kivy.clock import mainthread, Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.screenmanager import Screen
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.graphics import Color, RoundedRectangle, Rectangle, Line, Ellipse
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


# =========================================================================== #
#  视图 1：聊天列表
# =========================================================================== #

class ChatListItem(BoxLayout):
    """聊天列表中的单行：头像 + 好友名称 + 最后消息预览 + 未读数。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "horizontal"
        self.size_hint_y = None
        self.height = dp(68)
        self.padding = [dp(14), dp(8)]
        self.spacing = dp(12)

        # 绘制卡片背景与圆角边框
        with self.canvas.before:
            Color(0.12, 0.12, 0.13, 1)  # Solid flat background
            self._bg = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[dp(8)]
            )
        self.bind(
            pos=self._update_rect,
            size=self._update_rect
        )

        self._data = {}

        # -- 左侧：头像 --
        self.avatar = Factory.LetterAvatar(avatar_size=dp(44))

        # -- 中间：名称 + 最后消息 --
        info_col = BoxLayout(orientation="vertical", size_hint_x=0.6)

        self.name_label = Label(
            text="",
            font_size="16sp",
            bold=True,
            halign="left",
            valign="bottom",
            size_hint_y=0.5,
            color=(1, 1, 1, 1),
        )
        self.name_label.bind(size=self.name_label.setter("text_size"))

        self.preview_label = Label(
            text="",
            font_size="13sp",
            halign="left",
            valign="top",
            size_hint_y=0.5,
            color=(0.63, 0.65, 0.75, 1),
            shorten=True,
            shorten_from="right",
        )
        self.preview_label.bind(size=self.preview_label.setter("text_size"))

        info_col.add_widget(self.name_label)
        info_col.add_widget(self.preview_label)

        # -- 右侧：未读计数 + 时间 --
        right_col = BoxLayout(
            orientation="vertical",
            size_hint_x=0.25,
            spacing=dp(2),
        )

        self.time_label = Label(
            text="",
            font_size="11sp",
            halign="right",
            valign="bottom",
            size_hint_y=0.5,
            color=(0.55, 0.55, 0.65, 1),
        )
        self.time_label.bind(size=self.time_label.setter("text_size"))

        # 带有小背景的未读红点显示
        self.unread_container = BoxLayout(size_hint_y=0.5, size_hint_x=1)
        self.unread_label = Label(
            text="",
            font_size="11sp",
            bold=True,
            halign="center",
            valign="middle",
            color=(1, 1, 1, 1),
        )
        self.unread_label.bind(size=self.unread_label.setter("text_size"))
        
        with self.unread_label.canvas.before:
            self._unread_color = Color(1.0, 0.23, 0.19, 0.0) # 默认隐藏
            self._unread_bg = Ellipse(size=(dp(16), dp(16)))
        
        def update_unread_bg(w, v):
            self._unread_bg.pos = (self.unread_label.x + self.unread_label.width - dp(18), 
                                   self.unread_label.y + (self.unread_label.height - dp(16)) / 2)
        self.unread_label.bind(pos=update_unread_bg, size=update_unread_bg)
        
        self.unread_container.add_widget(self.unread_label)

        right_col.add_widget(self.time_label)
        right_col.add_widget(self.unread_container)

        self.add_widget(self.avatar)
        self.add_widget(info_col)
        self.add_widget(right_col)

        # 绑定触控事件（分离滑动与点击）
        self.bind(
            on_touch_down=self._on_touch_down,
            on_touch_move=self._on_touch_move,
            on_touch_up=self._on_touch_up,
        )

    def _update_rect(self, instance, value):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def refresh_view_attrs(self, rv, index, data):
        """由 RecycleView 适配器调用。"""
        self._data = data
        name = data.get("name", "未知")
        self.name_label.text = name
        self.preview_label.text = data.get("last_message", "")
        self.time_label.text = data.get("time", "")

        # 设置头像信息
        self.avatar.text = name
        self.avatar.name_key = name
        
        app = get_root_app()
        is_online = False
        if hasattr(app, "get_online_friends"):
            is_online = name in [f.get("name") for f in app.get_online_friends()]
        self.avatar.is_online = is_online

        unread = data.get("unread", 0)
        if unread > 0:
            self.unread_label.text = str(unread)
            self._unread_color.rgba = (1.0, 0.23, 0.19, 1.0) # 显示醒目珊瑚红
        else:
            self.unread_label.text = ""
            self._unread_color.rgba = (0, 0, 0, 0) # 隐藏

        return super().refresh_view_attrs(rv, index, data)

    def _on_touch_down(self, touch, *args):
        if not self.collide_point(*touch.pos):
            return False
        self._touch_start_pos = touch.pos
        return False

    def _on_touch_move(self, touch, *args):
        return False

    def _on_touch_up(self, touch, *args):
        if not self.collide_point(*touch.pos):
            if hasattr(self, '_touch_start_pos'):
                self._touch_start_pos = None
            return False
        
        if hasattr(self, '_touch_start_pos') and self._touch_start_pos:
            import math
            dist = math.sqrt((touch.x - self._touch_start_pos[0])**2 + (touch.y - self._touch_start_pos[1])**2)
            if dist <= dp(10):
                name = self._data.get("name", "")
                if name:
                    app = get_root_app()
                    if hasattr(app, "open_chat_with"):
                        app.open_chat_with(name)
            self._touch_start_pos = None
        return False


class ChatListView(BoxLayout):
    """聊天列表视图：展示有消息的好友列表。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self._items = []

        self.scroll = ScrollView(size_hint_y=1)
        self.container = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(6),
            padding=[0, dp(4), 0, dp(4)]
        )
        self.container.bind(minimum_height=self.container.setter("height"))
        self.scroll.add_widget(self.container)
        self.add_widget(self.scroll)

    @mainthread
    def update(self, chat_list):
        """
        更新聊天列表。

        Args:
            chat_list: list[dict]，每个 dict 包含 name, last_message, time, unread
        """
        self.container.clear_widgets()
        self._items = []

        for entry in chat_list:
            item = ChatListItem()
            item._data = entry
            item.name_label.text = entry.get("name", "未知")
            item.preview_label.text = entry.get("last_message", "")
            item.time_label.text = entry.get("time", "")
            unread = entry.get("unread", 0)
            
            # 渲染未读数
            if unread > 0:
                item.unread_label.text = str(unread)
                item._unread_color.rgba = (1.0, 0.23, 0.19, 1.0)
            else:
                item.unread_label.text = ""
                item._unread_color.rgba = (0, 0, 0, 0)
                
            self._items.append(item)
            self.container.add_widget(item)

        if not chat_list:
            empty_label = Label(
                text="暂无聊天记录\n去「发现」界面认识新朋友吧",
                font_size="15sp",
                halign="center",
                valign="middle",
                color=(0.55, 0.55, 0.65, 1),
                size_hint_y=None,
                height=dp(120),
            )
            empty_label.bind(size=empty_label.setter("text_size"))
            self.container.add_widget(empty_label)


# =========================================================================== #
#  视图 2：聊天窗口
# =========================================================================== #

class MessageBubble(BoxLayout):
    """单条消息气泡。

    与真实社交软件类似，左侧/右侧配有用户头像，气泡圆角采用不对称设计，自己发出的使用紫色，对方发出的使用深灰色。
    """

    def __init__(self, from_name="", content="", timestamp="", is_self=False, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "horizontal"
        self.size_hint_y = None
        self.padding = [dp(10), dp(4)]
        self.spacing = dp(8)

        # 自己发出的使用纯色QQ蓝，对方发出使用灰色
        bubble_color = (0.0, 0.6, 1.0, 1.0) if is_self else (0.17, 0.17, 0.18, 1.0)
        border_color = (0, 0, 0, 0)
        # 不对称圆角半径: [top_left, top_right, bottom_right, bottom_left]
        radius = [dp(16), dp(16), dp(4), dp(16)] if is_self else [dp(16), dp(16), dp(16), dp(4)]

        # 1. 对方消息：左侧显示对方的哈希彩色头像
        if not is_self:
            avatar_container = BoxLayout(orientation="vertical", size_hint=(None, 1), width=dp(36))
            self.avatar = Factory.LetterAvatar(avatar_size=dp(36), text=from_name, name_key=from_name)
            avatar_container.add_widget(self.avatar)
            avatar_container.add_widget(Widget()) # 弹簧，推到顶部
            self.add_widget(avatar_container)
        else:
            # 自己消息：左侧留空填充
            self.add_widget(Widget(size_hint_x=0.15))

        # 2. 气泡列 (包含内容与时间)
        bubble_col = BoxLayout(
            orientation="vertical",
            size_hint_x=0.85,
            size_hint_y=None,
            spacing=dp(3),
            padding=[dp(12), dp(8)],
        )

        with bubble_col.canvas.before:
            Color(*bubble_color)
            self._bg_rect = RoundedRectangle(
                pos=bubble_col.pos,
                size=bubble_col.size,
                radius=radius
            )
            
        def update_bubble_canvas(w, v):
            self._bg_rect.pos = w.pos
            self._bg_rect.size = w.size
            
        bubble_col.bind(pos=update_bubble_canvas, size=update_bubble_canvas)

        # 发送者名称（仅对方消息显示）
        if not is_self and from_name:
            name_lbl = Label(
                text=from_name,
                font_size="11sp",
                bold=True,
                halign="left",
                valign="bottom",
                size_hint_y=None,
                height=dp(16),
                color=(0.28, 0.67, 0.96, 1), # 柔和蓝色
            )
            name_lbl.bind(size=name_lbl.setter("text_size"))
            bubble_col.add_widget(name_lbl)

        # 消息内容
        content_lbl = Label(
            text=content,
            font_size="14sp",
            halign="left",
            valign="top",
            color=(1, 1, 1, 1),
            size_hint_y=None,
        )
        content_lbl.bind(
            texture_size=content_lbl.setter("size"),
            size=content_lbl.setter("text_size"),
        )
        content_lbl.text_size = (None, None)
        bubble_col.add_widget(content_lbl)

        # 时间戳
        time_lbl = Label(
            text=timestamp,
            font_size="10sp",
            halign="right" if is_self else "left",
            valign="top",
            size_hint_y=None,
            height=dp(14),
            color=(0.85, 0.85, 0.9, 0.7) if is_self else (0.55, 0.55, 0.65, 0.7),
        )
        time_lbl.bind(size=time_lbl.setter("text_size"))
        bubble_col.add_widget(time_lbl)

        # 自适应高度
        bubble_col.bind(
            minimum_height=lambda w, h: setattr(bubble_col, "height", h),
        )
        self.add_widget(bubble_col)

        # 3. 自己消息：右侧显示本人的哈希彩色头像
        if is_self:
            avatar_container = BoxLayout(orientation="vertical", size_hint=(None, 1), width=dp(36))
            self.avatar = Factory.LetterAvatar(avatar_size=dp(36), text=from_name, name_key=from_name)
            avatar_container.add_widget(self.avatar)
            avatar_container.add_widget(Widget()) # 弹簧，推到顶部
            self.add_widget(avatar_container)
        else:
            # 对方消息：右侧留空填充
            self.add_widget(Widget(size_hint_x=0.15))

        # 绑定整个行自适应高度
        bubble_col.bind(
            height=lambda w, h: setattr(self, "height", h + dp(12)) # 给行一些 padding
        )


class ChatWindowView(BoxLayout):
    """聊天窗口视图：消息历史 + 输入框。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self._current_friend = ""
        # 增加内边距与间距，使头部与底部输入栏变成独立悬浮卡片
        self.padding = [dp(12), dp(10), dp(12), dp(12)]
        self.spacing = dp(8)

        # -- 顶部栏：返回 + 对方头像 + 好友名称 --
        top_bar = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(48),
            spacing=dp(10),
            padding=[dp(10), 0, dp(10), 0]
        )
        with top_bar.canvas.before:
            Color(0.12, 0.12, 0.13, 1)
            self._top_bg = RoundedRectangle(pos=top_bar.pos, size=top_bar.size, radius=[0])
            
        def update_top_bg(w, v):
            self._top_bg.pos = top_bar.pos
            self._top_bg.size = top_bar.size
            
        top_bar.bind(pos=update_top_bg, size=update_top_bg)

        self.back_btn = Factory.ModernButtonSecondary(
            text="< 返回",
            size_hint_x=0.22,
            size_hint_y=0.75,
            font_size="13sp",
        )
        self.back_btn.bind(on_press=self._on_back)

        # 顶部栏的好友头像
        self.header_avatar = Factory.LetterAvatar(avatar_size=dp(34))

        self.friend_name_label = Label(
            text="",
            font_size="18sp",
            bold=True,
            halign="left",
            valign="middle",
            color=(1, 1, 1, 1),
        )
        self.friend_name_label.bind(size=self.friend_name_label.setter("text_size"))

        top_bar.add_widget(self.back_btn)
        top_bar.add_widget(self.header_avatar)
        top_bar.add_widget(self.friend_name_label)
        self.add_widget(top_bar)

        # -- 消息区域 (ScrollView) --
        self.scroll = ScrollView(size_hint_y=1)
        self.message_container = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(6),
            padding=[dp(4), dp(10), dp(4), dp(10)],
        )
        self.message_container.bind(
            minimum_height=self.message_container.setter("height"),
        )
        self.scroll.add_widget(self.message_container)
        self.add_widget(self.scroll)

        # -- 底部输入栏 --
        input_bar = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(52),
            spacing=dp(8),
            padding=[dp(10), dp(6), dp(10), dp(6)],
        )
        with input_bar.canvas.before:
            Color(0.12, 0.12, 0.13, 1)
            self._input_bg = RoundedRectangle(pos=input_bar.pos, size=input_bar.size, radius=[0])
            
        def update_input_bg(w, v):
            self._input_bg.pos = input_bar.pos
            self._input_bg.size = input_bar.size
            
        input_bar.bind(pos=update_input_bg, size=update_input_bg)

        self.msg_input = Factory.ModernTextInput(
            hint_text="输入消息...",
            multiline=False,
            size_hint_x=0.85,
        )
        self.msg_input.bind(on_text_validate=self._on_send)

        # 悬浮圆形“发送”胶囊按键
        self.send_btn = Button(
            text="→",
            font_size="20sp",
            bold=True,
            size_hint_x=None,
            width=dp(38),
            size_hint_y=None,
            height=dp(38),
            background_normal='',
            background_down='',
            background_color=(0, 0, 0, 0),
            color=(1, 1, 1, 1),
            pos_hint={'center_y': 0.5}
        )
        with self.send_btn.canvas.before:
            self._send_bg_color = Color(0.0, 0.6, 1.0, 1)
            self._send_bg = Ellipse(pos=self.send_btn.pos, size=self.send_btn.size)
            
        def update_send_btn(b, v):
            self._send_bg.pos = b.pos
            self._send_bg.size = b.size
            if b.state == 'down':
                self._send_bg_color.rgba = (0.0, 0.5, 0.9, 1)
            else:
                self._send_bg_color.rgba = (0.0, 0.6, 1.0, 1)
        self.send_btn.bind(pos=update_send_btn, size=update_send_btn)
        self.send_btn.bind(on_press=self._on_send)

        input_bar.add_widget(self.msg_input)
        input_bar.add_widget(self.send_btn)
        self.add_widget(input_bar)

    # ---- 公共方法 ----

    @mainthread
    def open_chat(self, friend_name):
        """
        打开与指定好友的聊天窗口。

        Args:
            friend_name: 好友名称。
        """
        self._current_friend = friend_name
        self.friend_name_label.text = friend_name
        
        # 刷新顶部头像
        self.header_avatar.text = friend_name
        self.header_avatar.name_key = friend_name
        app = get_root_app()
        is_online = False
        if hasattr(app, "get_online_friends"):
            is_online = friend_name in [f.get("name") for f in app.get_online_friends()]
        self.header_avatar.is_online = is_online
        
        self._load_history()

    @mainthread
    def append_message(self, from_name, content, timestamp, is_self=False):
        """
        向当前聊天窗口追加一条消息气泡。

        Args:
            from_name: 发送者名称。
            content:   消息文本。
            timestamp: 时间戳字符串。
            is_self:   是否为本机发送的消息。
        """
        bubble = MessageBubble(
            from_name=from_name,
            content=content,
            timestamp=timestamp,
            is_self=is_self,
        )
        self.message_container.add_widget(bubble)
        # 自动滚动到底部
        Clock.schedule_once(lambda dt: self._scroll_to_bottom(), 0.1)

    @mainthread
    def clear_messages(self):
        """清空当前消息区域。"""
        self.message_container.clear_widgets()

    # ---- 内部方法 ----

    def _load_history(self):
        """从 App 加载与当前好友的聊天历史。"""
        self.message_container.clear_widgets()
        app = get_root_app()
        if hasattr(app, "get_chat_history"):
            history = app.get_chat_history(self._current_friend)
            if history:
                my_name = ""
                if hasattr(app, "device_name"):
                    my_name = app.device_name
                elif hasattr(app, "get_my_profile"):
                    profile = app.get_my_profile()
                    my_name = profile.get("name", "") if profile else ""

                for msg in history:
                    from_name = msg.get("from_name", "")
                    content = msg.get("content", "")
                    ts = msg.get("timestamp", "")
                    is_self = (from_name == my_name)
                    
                    # 仅保留时分秒
                    if len(ts) >= 19:  # YYYY-MM-DD HH:MM:SS
                        ts = ts[11:19]
                    
                    self.append_message(from_name, content, ts, is_self)

    def _on_send(self, *_args):
        """发送消息按钮 / 回车事件。"""
        text = self.msg_input.text.strip()
        if not text or not self._current_friend:
            return

        app = get_root_app()
        if hasattr(app, "send_chat_message"):
            import threading
            threading.Thread(
                target=app.send_chat_message,
                args=(self._current_friend, text),
                daemon=True,
            ).start()

        # 立即在本地显示（不等回执）
        import time
        ts = time.strftime("%H:%M:%S", time.localtime())
        my_name = ""
        if hasattr(app, "device_name"):
            my_name = app.device_name
        elif hasattr(app, "get_my_profile"):
            profile = app.get_my_profile()
            my_name = profile.get("name", "") if profile else ""

        self.append_message(my_name, text, ts, is_self=True)
        self.msg_input.text = ""

    def _on_back(self, _btn):
        """返回聊天列表。"""
        parent_screen = self.parent
        while parent_screen and not isinstance(parent_screen, ChatScreen):
            parent_screen = parent_screen.parent
        if parent_screen and isinstance(parent_screen, ChatScreen):
            parent_screen.show_list_view()

    def _scroll_to_bottom(self):
        """滚动到底部。"""
        self.scroll.scroll_y = 0


# =========================================================================== #
# ChatScreen - 聊天主界面（管理两个视图的切换）
# =========================================================================== #

class ChatScreen(Screen):
    """聊天界面：管理聊天列表视图和聊天窗口视图的切换。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "chat"
        self._current_view = "list"  # "list" or "window"
        self._build_ui()

    # ---- UI 构造 ---------------------------------------------------------

    def _build_ui(self):
        # 1. 挂载纯色背景
        self.background = Factory.SolidColorBackground()
        self.add_widget(self.background)

        # 2. 内容层容器
        self._root = BoxLayout(orientation="vertical")

        # -- 标题栏 --
        self._title_label = Label(
            text="聊天",
            font_size="22sp",
            bold=True,
            size_hint_y=None,
            height=dp(48),
            color=(1, 1, 1, 1),
            halign="center"
        )
        self._root.add_widget(self._title_label)

        # -- 内容容器（两个视图在此切换） --
        self._content_container = BoxLayout(
            orientation="vertical",
            size_hint_y=1,
            padding=[dp(12), 0, dp(12), 0]
        )

        # 创建两个视图
        self.chat_list_view = ChatListView()
        self.chat_window_view = ChatWindowView()

        # 默认显示列表视图
        self._content_container.add_widget(self.chat_list_view)
        self._root.add_widget(self._content_container)

        # -- 底部导航栏 --
        self._nav_bar = self._build_modern_nav_bar("chat")
        self._root.add_widget(self._nav_bar)

        self.add_widget(self._root)
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
        """进入界面时刷新聊天列表（如果当前在列表视图）。"""
        if self._current_view == "list":
            self._refresh_chat_list()

    # ---- 视图切换 --------------------------------------------------------

    @mainthread
    def show_list_view(self):
        """切换到聊天列表视图。"""
        if self._current_view == "list":
            return

        self._content_container.clear_widgets()
        self._content_container.add_widget(self.chat_list_view)
        self._current_view = "list"
        self._title_label.text = "聊天"
        self._nav_bar.opacity = 1
        self._nav_bar.disabled = False
        self._refresh_chat_list()

    @mainthread
    def show_window_view(self, friend_name):
        """
        切换到聊天窗口视图，打开与指定好友的对话。

        Args:
            friend_name: 好友名称。
        """
        self._content_container.clear_widgets()
        self._content_container.add_widget(self.chat_window_view)
        self._current_view = "window"
        self._title_label.text = ""  # 窗口视图自带顶部栏
        
        # 隐藏底栏，给聊天窗口腾出完整空间！
        self._nav_bar.opacity = 0
        self._nav_bar.disabled = True
        
        self.chat_window_view.open_chat(friend_name)

    # ---- 公共 API --------------------------------------------------------

    @mainthread
    def update_chat_list(self, chat_list):
        """
        更新聊天列表数据。

        Args:
            chat_list: list[dict]，每个 dict 包含 name, last_message, time, unread。
        """
        self.chat_list_view.update(chat_list)

    @mainthread
    def on_new_message(self, from_name, content, timestamp):
        """
        收到新消息时的处理（由 MessageService 回调触发）。

        如果当前正在与该好友聊天，追加到消息区域。
        否则更新聊天列表中的未读计数。

        Args:
            from_name: 发送者名称。
            content:   消息内容。
            timestamp: 时间戳。
        """
        # 仅保留时分秒显示
        ts_display = timestamp
        if len(timestamp) >= 19:
            ts_display = timestamp[11:19]
            
        if (
            self._current_view == "window"
            and self.chat_window_view._current_friend == from_name
        ):
            self.chat_window_view.append_message(
                from_name, content, ts_display, is_self=False
            )
        # 同时刷新列表（更新未读数和最新消息预览）
        self._refresh_chat_list()

    # ---- 内部方法 --------------------------------------------------------

    def _refresh_chat_list(self):
        """从 App 获取聊天列表数据。"""
        app = get_root_app()
        if hasattr(app, "get_chat_list"):
            chat_list = app.get_chat_list()
            if chat_list is not None:
                self.update_chat_list(chat_list)

    def _navigate(self, screen_name):
        """通过 ScreenManager 切换界面，使用无延迟切换避免动画卡顿。"""
        app = get_root_app()
        if hasattr(app, "root") and hasattr(app.root, "current"):
            if app.root.current == screen_name:
                return
            from kivy.uix.screenmanager import NoTransition
            app.root.transition = NoTransition()
            app.root.current = screen_name
