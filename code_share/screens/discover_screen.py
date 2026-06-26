"""
发现界面 (Challenge 3 - 相识北洋)

局域网用户发现与好友在线状态展示：
  - 扫描按钮：触发 UDP 广播发现附近的人
  - 发现列表：RecycleView 展示附近用户（名称、IP、发送好友请求按钮）
  - 在线好友：当前已建立 TCP 连接的好友（绿色状态点）
  - 底部导航栏：发现 / 好友 / 聊天 / 我的 / 设置
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
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivy.graphics import Color, Ellipse, Rectangle, RoundedRectangle, Line
from kivy.factory import Factory
from kivy.properties import NumericProperty, BooleanProperty, ListProperty


def get_root_app():
    """返回当前运行 of Kivy App 实例。"""
    return App.get_running_app()


# ---------------------------------------------------------------------------
# 背景绘制辅助
# ---------------------------------------------------------------------------
def _add_background(widget, rgba):
    """为 widget 绑定彩色矩形背景，跟随 size/pos 变化。"""
    with widget.canvas.before:
        Color(*rgba)
        rect = Rectangle(pos=widget.pos, size=widget.size)
    widget.bind(
        pos=lambda w, v: setattr(rect, "pos", v),
        size=lambda w, v: setattr(rect, "size", v),
    )
    return rect


# ---------------------------------------------------------------------------
# RadarScanner - 手绘矢量雷达扫描动画组件 (Clean & Elegant)
# ---------------------------------------------------------------------------
class RadarScanner(Widget):
    angle = NumericProperty(0)
    scanning = BooleanProperty(False)
    ripples = ListProperty([])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (None, None)
        self.size = (dp(160), dp(160))
        self._anim_event = None
        self.bind(pos=self._redraw, size=self._redraw, scanning=self._on_scanning)

    def _on_scanning(self, instance, val):
        if val:
            if not self._anim_event:
                self._anim_event = Clock.schedule_interval(self._update_anim, 1.0 / 60.0)
                self.ripples = [{"radius": dp(5), "alpha": 1.0}]
        else:
            if self._anim_event:
                self._anim_event.cancel()
                self._anim_event = None
            self.ripples = []
            self.canvas.before.clear()
            self.canvas.after.clear()

    def _update_anim(self, dt):
        new_ripples = []
        for rip in self.ripples:
            r = rip["radius"] + dp(40) * dt
            a = rip["alpha"] - 0.8 * dt
            if a > 0:
                new_ripples.append({"radius": r, "alpha": max(0.0, a)})
        if not self.ripples or self.ripples[-1]["radius"] > dp(60):
            new_ripples.append({"radius": dp(5), "alpha": 1.0})
        self.ripples = new_ripples
        self._redraw()

    def _redraw(self, *args):
        self.canvas.before.clear()
        self.canvas.after.clear()
        if not self.scanning:
            return

        cx = self.x + self.width / 2
        cy = self.y + self.height / 2
        max_r = min(self.width, self.height) / 2 - dp(10)
        
        active_color = (0.0, 0.6, 1.0) # QQ Blue

        with self.canvas.before:
            Color(*active_color, 0.05)
            Ellipse(pos=(cx - max_r, cy - max_r), size=(max_r * 2, max_r * 2))

        with self.canvas.after:
            for rip in self.ripples:
                r = min(rip["radius"], max_r)
                alpha = rip["alpha"] * (1.0 - (r / max_r)**2)
                if alpha > 0:
                    Color(*active_color, alpha * 0.5)
                    Line(circle=(cx, cy, r), width=dp(2))

            Color(*active_color, 1.0)
            Ellipse(pos=(cx - dp(4), cy - dp(4)), size=(dp(8), dp(8)))

Factory.register('RadarScanner', cls=RadarScanner)



# ---------------------------------------------------------------------------
# 发现用户行 - RecycleView 条目
# ---------------------------------------------------------------------------
class DiscoveredPersonItem(BoxLayout):
    """发现列表中的单行：展示附近用户的名称、IP 及"发送好友请求"按钮。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "horizontal"
        self.size_hint_y = None
        self.height = dp(64)
        self.padding = [dp(14), dp(6)]
        self.spacing = dp(10)

        # 绘制卡片背景与圆角边框
        with self.canvas.before:
            # Main card background (Solid dark)
            Color(0.12, 0.12, 0.13, 1)
            self._bg = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[dp(12)]
            )
        self.bind(
            pos=self._update_rect,
            size=self._update_rect
        )

        self._data = {}

        # -- 头像 --
        self.avatar = Factory.LetterAvatar(avatar_size=dp(42))
        self.add_widget(self.avatar)

        # -- 信息列 (名称 + IP) --
        info = BoxLayout(orientation="vertical", size_hint_x=0.45)

        self.name_label = Label(
            text="",
            font_size="15sp",
            bold=True,
            halign="left",
            valign="bottom",
            size_hint_y=0.55,
            color=(1, 1, 1, 1),
        )
        self.name_label.bind(size=self.name_label.setter("text_size"))

        self.ip_label = Label(
            text="",
            font_size="13sp",
            halign="left",
            valign="top",
            size_hint_y=0.45,
            color=(0.63, 0.65, 0.75, 1),
        )
        self.ip_label.bind(size=self.ip_label.setter("text_size"))

        info.add_widget(self.name_label)
        info.add_widget(self.ip_label)

        # -- 发送好友请求按钮 --
        self.request_btn = Factory.ModernButtonAccent(
            text="添加好友",
            size_hint_x=0.28,
            size_hint_y=0.75,
            font_size="13sp",
        )

        self.add_widget(info)
        self.add_widget(self.request_btn)

    def _update_rect(self, instance, value):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def populate(self, data):
        """填充行数据。"""
        self._data = data
        name = data.get("name", "未知用户")
        self.name_label.text = name
        self.ip_label.text = data.get("ip", "0.0.0.0")
        
        self.avatar.text = name
        self.avatar.name_key = name
        self.avatar.is_online = False
        
        self.request_btn.unbind(on_press=self._on_send_request)
        self.request_btn.bind(on_press=self._on_send_request)
        
        # 还原状态
        self.request_btn.text = "添加好友"
        self.request_btn.disabled = False

    def _on_send_request(self, _btn):
        """发送好友请求按钮点击事件。"""
        app = get_root_app()
        name = self._data.get("name", "")
        ip = self._data.get("ip", "")
        if hasattr(app, "send_friend_request"):
            app.send_friend_request(name, ip)
            self.request_btn.text = "已发送"
            self.request_btn.disabled = True


# ---------------------------------------------------------------------------
# 发现列表 ScrollView
# ---------------------------------------------------------------------------
class DiscoveredPeopleList(ScrollView):
    """可滚动的发现用户列表。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.do_scroll_y = True
        self.do_scroll_x = False
        self.container = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(6),
        )
        self.container.bind(minimum_height=self.container.setter("height"))
        self.add_widget(self.container)

    def update_people(self, people):
        self.container.clear_widgets()
        for p in people:
            item = DiscoveredPersonItem()
            item.populate(p)
            self.container.add_widget(item)


# ---------------------------------------------------------------------------
# 在线好友气泡 - RecycleView 条目 (微信/Instagram 在线圈风格)
# ---------------------------------------------------------------------------
class OnlineFriendItem(BoxLayout):
    """在线好友列表中的圆形气泡：头像 + 居中缩略名。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.size_hint_x = None
        self.width = dp(66)
        self.spacing = dp(4)
        self.padding = [dp(2), dp(2)]

        # 1. 头像置顶并居中
        avatar_box = BoxLayout(size_hint_y=None, height=dp(42))
        self.avatar = Factory.LetterAvatar(avatar_size=dp(40), is_online=True)
        avatar_box.add_widget(Widget()) # 左侧弹簧
        avatar_box.add_widget(self.avatar)
        avatar_box.add_widget(Widget()) # 右侧弹簧
        self.add_widget(avatar_box)

        # 2. 姓名置底并居中
        self.name_label = Label(
            text="",
            font_size="10sp",
            bold=True,
            halign="center",
            valign="top",
            color=(1, 1, 1, 0.9),
            size_hint_y=None,
            height=dp(16),
            shorten=True,
            shorten_from="right",
        )
        self.name_label.bind(size=self.name_label.setter("text_size"))
        self.add_widget(self.name_label)

    def populate(self, data):
        """填充数据。"""
        name = data.get("name", "未知")
        self.name_label.text = name
        self.avatar.text = name
        self.avatar.name_key = name
        self.avatar.is_online = True


# ---------------------------------------------------------------------------
# 在线好友 ScrollView
# ---------------------------------------------------------------------------
class OnlineFriendsList(ScrollView):
    """可水平滚动的在线好友圈列表。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.do_scroll_y = False
        self.do_scroll_x = True
        self.scroll_type = ['bars', 'content']
        self.bar_width = dp(2)
        
        self.container = BoxLayout(
            orientation="horizontal",
            size_hint_x=None,
            spacing=dp(4),
            padding=[dp(4), 0, dp(4), 0]
        )
        self.container.bind(minimum_width=self.container.setter("width"))
        self.add_widget(self.container)

    def update_friends(self, friends):
        self.container.clear_widgets()
        for f in friends:
            item = OnlineFriendItem()
            item.populate(f)
            self.container.add_widget(item)


# ---------------------------------------------------------------------------
# DiscoverScreen - 发现界面
# ---------------------------------------------------------------------------
class DiscoverScreen(Screen):
    """发现界面：UDP 广播扫描附近的人 + 展示在线好友。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "discover"
        self._build_ui()

    # ---- UI 构造 ---------------------------------------------------------

    def _build_ui(self):
        # 1. 挂载纯色背景
        self.background = Factory.SolidColorBackground()
        self.add_widget(self.background)

        # 2. 内容层容器
        root = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))

        # -- 标题栏与扫描合成行 (节省纵向空间) --
        header_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(48),
            spacing=dp(6),
        )
        
        title = Label(
            text="相识北洋",
            font_size="20sp",
            bold=True,
            color=(1, 1, 1, 1),
            halign="left",
            valign="middle",
            size_hint_x=0.35,
        )
        title.bind(size=title.setter("text_size"))
        
        self.scan_status = Label(
            text="未开始扫描",
            font_size="11sp",
            halign="right",
            valign="middle",
            color=(0.55, 0.57, 0.68, 1),
            size_hint_x=0.25,
        )
        self.scan_status.bind(size=self.scan_status.setter("text_size"))
        
        self.scan_btn = Factory.ModernButtonAccent(
            text="雷达扫描",
            size_hint_x=0.2,
            size_hint_y=0.75,
            font_size="11sp",
        )
        self.scan_btn.bind(on_press=self._on_scan)
        
        self.manual_btn = Factory.ModernButton(
            text="手动添加",
            size_hint_x=0.2,
            size_hint_y=0.75,
            font_size="11sp",
        )
        self.manual_btn.bind(on_press=self._on_manual_add)
        
        header_row.add_widget(title)
        header_row.add_widget(self.scan_status)
        header_row.add_widget(self.scan_btn)
        header_row.add_widget(self.manual_btn)
        root.add_widget(header_row)

        # -- "在线好友" 标签 & 水平在线好友列表 (微信朋友圈/Instagram在线栏风格) --
        online_heading = Label(
            text="在线好友",
            font_size="14sp",
            bold=True,
            size_hint_y=None,
            height=dp(20),
            halign="left",
            valign="bottom",
            color=(0.63, 0.65, 0.75, 1),
        )
        online_heading.bind(size=online_heading.setter("text_size"))
        root.add_widget(online_heading)

        self.online_friends_list = OnlineFriendsList(
            size_hint_y=None,
            height=dp(74)
        )
        root.add_widget(self.online_friends_list)

        # -- "附近的人" 标签 --
        discovered_heading = Label(
            text="附近的人",
            font_size="14sp",
            bold=True,
            size_hint_y=None,
            height=dp(20),
            halign="left",
            valign="bottom",
            color=(0.63, 0.65, 0.75, 1),
        )
        discovered_heading.bind(size=discovered_heading.setter("text_size"))
        root.add_widget(discovered_heading)

        # -- 列表与雷达容器 (利用这个容器在扫描时动态切换，避免 Kivy 尺寸 bug) --
        self.list_container = BoxLayout(orientation="vertical", size_hint_y=1)
        root.add_widget(self.list_container)

        # -- 发现列表 --
        self.discovered_list = DiscoveredPeopleList(size_hint_y=1)
        self.list_container.add_widget(self.discovered_list)

        # -- 雷达扫描展示区 (默认不加入容器，利用占位弹簧垂直居中) --
        self.radar_box = BoxLayout(
            orientation="vertical",
            size_hint_y=1,
        )
        self.radar_box.add_widget(Widget()) # 顶部弹簧
        
        radar_center = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(160))
        self.radar_scanner = RadarScanner()
        radar_center.add_widget(Widget()) # 居中弹簧
        radar_center.add_widget(self.radar_scanner)
        radar_center.add_widget(Widget()) # 居中弹簧
        self.radar_box.add_widget(radar_center)
        
        self.radar_box.add_widget(Widget()) # 底部弹簧

        # -- 底部导航栏 --
        nav_bar = self._build_modern_nav_bar("discover")
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
        """进入界面时自动刷新发现列表和在线好友列表。"""
        self._refresh_discovered()
        self._refresh_online_friends()

    # ---- 公共 API --------------------------------------------------------

    @mainthread
    def update_discovered_people(self, people):
        """
        更新发现列表。

        Args:
            people: list[dict]，每个 dict 包含 'name' 和 'ip' 字段。
        """
        self.discovered_list.update_people(people)
        count = len(people)
        if not self.radar_scanner.scanning:
            self.scan_status.text = f"发现 {count} 人" if count else "未发现附近的人"

        # UI 诊断日志
        try:
            log_path = r"C:\Users\20476\.gemini\antigravity\brain\52596d6e-cae5-4db9-816b-d91323486126\scratch\ui_debug.log"
            import os
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                import datetime
                f.write(f"--- {datetime.datetime.now()} ---\n")
                f.write(f"people input: {people}\n")
                f.write(f"discovered_list container children count: {len(self.discovered_list.container.children)}\n")
                f.write(f"discovered_list size: {self.discovered_list.size}, height: {self.discovered_list.height}\n")
                f.write(f"list_container size: {self.list_container.size}, height: {self.list_container.height}\n")
                for child in self.discovered_list.container.children:
                    f.write(f"  - child class: {child.__class__.__name__}, name: {child.name_label.text}, ip: {child.ip_label.text}\n")
                f.write("\n")
        except Exception as e:
            print("Write debug log failed:", e)

    @mainthread
    def update_online_friends(self, friends):
        """
        更新在线好友列表。

        Args:
            friends: list[dict]，每个 dict 包含 'name' 和 'ip' 字段。
        """
        self.online_friends_list.update_friends(friends)

    @mainthread
    def set_scan_status(self, text: str):
        """设置扫描状态文本（线程安全）。"""
        self.scan_status.text = text

    # ---- 事件处理 --------------------------------------------------------

    def _on_scan(self, _btn):
        """触发 UDP 广播/单播扫描，并播放雷达扫描动画。"""
        app = get_root_app()
        if hasattr(app, "scan_for_people"):
            self.scan_status.text = "正在扫描附近的人..."
            self.scan_btn.disabled = True
            
            # 从容器中移除列表，添加雷达
            if self.discovered_list in self.list_container.children:
                self.list_container.remove_widget(self.discovered_list)
            if self.radar_box not in self.list_container.children:
                self.list_container.add_widget(self.radar_box)
            
            self.radar_scanner.scanning = True
            app.scan_for_people()
            
            # 延时恢复按钮状态
            from kivy.clock import Clock
            Clock.schedule_once(lambda dt: self._enable_scan_btn(), 5)

    def _enable_scan_btn(self):
        self.scan_btn.disabled = False
        
        # 停止雷达，从容器中移除雷达并重新添加列表
        self.radar_scanner.scanning = False
        if self.radar_box in self.list_container.children:
            self.list_container.remove_widget(self.radar_box)
        if self.discovered_list not in self.list_container.children:
            self.list_container.add_widget(self.discovered_list)
        
        self._refresh_discovered()  # 扫描完刷新列表并重置文字

    def _on_manual_add(self, _btn):
        """弹出手动添加好友对话框，直接向指定 IP 发送 TCP 好友请求。"""
        from kivy.uix.popup import Popup
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.metrics import dp
        from kivy.factory import Factory
        from kivy.graphics import Color, RoundedRectangle, Line
        
        # 容器布局
        layout = BoxLayout(orientation='vertical', padding=[dp(16), dp(16), dp(16), dp(10)], spacing=dp(12))
        with layout.canvas.before:
            Color(0.1, 0.1, 0.15, 0.9)
            layout_bg = RoundedRectangle(pos=layout.pos, size=layout.size, radius=[dp(20)])
            Color(1, 1, 1, 0.15)
            layout_border = Line(rounded_rectangle=(layout.x, layout.y, layout.width, layout.height, dp(20)), width=dp(1))
            
        def update_layout_canvas(w, v):
            layout_bg.pos = w.pos
            layout_bg.size = w.size
            layout_border.rounded_rectangle = (w.x, w.y, w.width, w.height, dp(20))
            
        layout.bind(pos=update_layout_canvas, size=update_layout_canvas)
        
        # 标题
        title_lbl = Label(
            text="手动添加好友",
            font_size='16sp',
            bold=True,
            color=(1, 1, 1, 1),
            size_hint_y=None,
            height=dp(30),
            halign="center"
        )
        title_lbl.bind(size=title_lbl.setter("text_size"))
        layout.add_widget(title_lbl)
        
        # 输入姓名
        name_box = BoxLayout(orientation='vertical', spacing=dp(4), size_hint_y=None, height=dp(64))
        name_lbl = Label(text="好友姓名:", font_size='12sp', color=(0.63, 0.65, 0.75, 1), halign="left")
        name_lbl.bind(size=name_lbl.setter("text_size"))
        name_input = Factory.ModernTextInput(hint_text="请输入好友昵称", multiline=False)
        name_box.add_widget(name_lbl)
        name_box.add_widget(name_input)
        layout.add_widget(name_box)
        
        # 输入 IP
        ip_box = BoxLayout(orientation='vertical', spacing=dp(4), size_hint_y=None, height=dp(64))
        ip_lbl = Label(text="好友 IP 地址:", font_size='12sp', color=(0.63, 0.65, 0.75, 1), halign="left")
        ip_lbl.bind(size=ip_lbl.setter("text_size"))
        ip_input = Factory.ModernTextInput(hint_text="例如 172.21.124.x", multiline=False)
        ip_box.add_widget(ip_lbl)
        ip_box.add_widget(ip_input)
        layout.add_widget(ip_box)
        
        # 错误提示Label
        err_lbl = Label(text="", font_size='11sp', color=(0.92, 0.23, 0.35, 1), size_hint_y=None, height=dp(20), halign="center")
        err_lbl.bind(size=err_lbl.setter("text_size"))
        layout.add_widget(err_lbl)
        
        # 底部按钮
        btn_row = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(38), spacing=dp(10))
        send_btn = Factory.ModernButtonAccent(text="发送申请", font_size='14sp')
        cancel_btn = Factory.ModernButtonSecondary(text="取消", font_size='14sp')
        btn_row.add_widget(send_btn)
        btn_row.add_widget(cancel_btn)
        layout.add_widget(btn_row)
        
        popup = Popup(
            title="",
            title_size=0,
            content=layout,
            size_hint=(0.84, 0.48),
            background_color=(0, 0, 0, 0),
            background="",
        )
        
        def on_send(_btn):
            name = name_input.text.strip()
            ip = ip_input.text.strip()
            if not name:
                err_lbl.text = "姓名不能为空！"
                return
            try:
                from code_share.utils.helpers import Helpers
            except ImportError:
                from utils.helpers import Helpers
            if not Helpers.validate_ip(ip):
                err_lbl.text = "IP 地址格式不合法！"
                return
            
            app = get_root_app()
            if hasattr(app, "send_friend_request"):
                # 在后台线程发送，防止主线程因 TCP 连接阻塞而卡顿
                import threading
                def task():
                    self.set_scan_status("正在发送请求...")
                    success = app.send_friend_request(name, ip)
                    if success:
                        self.set_scan_status(f"成功向 {name}({ip}) 发送申请")
                    else:
                        self.set_scan_status(f"发送申请失败，请检查网络")
                threading.Thread(target=task, daemon=True).start()
                popup.dismiss()
        
        send_btn.bind(on_press=on_send)
        cancel_btn.bind(on_press=popup.dismiss)
        popup.open()

    def _refresh_discovered(self):
        """从 App 获取已发现的用户列表并刷新。"""
        app = get_root_app()
        if hasattr(app, "get_discovered_people"):
            people = app.get_discovered_people()
            if people is not None:
                self.update_discovered_people(people)

    def _refresh_online_friends(self):
        """从 App 获取在线好友列表并刷新。"""
        app = get_root_app()
        if hasattr(app, "get_online_friends"):
            friends = app.get_online_friends()
            if friends is not None:
                self.update_online_friends(friends)

    def _navigate(self, screen_name):
        """通过 ScreenManager 切换界面，使用无延迟切换避免动画卡顿。"""
        app = get_root_app()
        if hasattr(app, "root") and hasattr(app.root, "current"):
            if app.root.current == screen_name:
                return
            from kivy.uix.screenmanager import NoTransition
            app.root.transition = NoTransition()
            app.root.current = screen_name

