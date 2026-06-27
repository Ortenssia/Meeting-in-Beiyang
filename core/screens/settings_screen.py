"""
设置界面 (Challenge 3 - 相识北洋)

应用配置与系统信息展示：
  - 设备名称显示（只读）
  - TCP 端口输入（可修改，重启生效）
  - UDP 端口显示（只读，默认 8890）
  - 清空聊天记录按钮
  - 待发送消息计数 + 清空按钮
  - 关于信息区（版本号、应用名）
  - 返回按钮
  - 底部导航栏
"""

from kivy.app import App
from kivy.clock import mainthread
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.graphics import Color, Rectangle, RoundedRectangle, Line
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
# ---------------------------------------------------------------------------
# ClickableSettingRow - 可点击的设置行，右侧带有 Chevron > 箭头与状态文本
# ---------------------------------------------------------------------------
class ClickableSettingRow(Button):
    def __init__(self, label_text="", status_text="", **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ''
        self.background_down = ''
        self.background_color = (0, 0, 0, 0)
        self.size_hint_y = None
        self.height = dp(46)
        self.status_val = status_text
        
        self.label = Label(
            text=label_text,
            font_name='app_chinese_font',
            font_size="14sp",
            color=(0.85, 0.85, 0.9, 1),
            halign="left",
            valign="middle"
        )
        self.status_label = Label(
            text=status_text,
            font_name='app_chinese_font',
            font_size="13sp",
            color=(0.55, 0.57, 0.68, 1),
            halign="right",
            valign="middle"
        )
        self.add_widget(self.label)
        self.add_widget(self.status_label)
        self.bind(pos=self._redraw, size=self._redraw)
        
    def _redraw(self, *args):
        self.canvas.before.clear()
        self.canvas.after.clear()
        
        with self.canvas.before:
            if self.state == 'down':
                Color(0.2, 0.2, 0.2, 1)
            else:
                Color(0.17, 0.17, 0.18, 1)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(8)])
            
        with self.canvas.after:
            Color(0.55, 0.57, 0.68, 0.8)
            cx = self.x + self.width - dp(20)
            cy = self.y + self.height / 2
            Line(points=[
                cx - dp(3), cy + dp(5),
                cx + dp(2), cy,
                cx - dp(3), cy - dp(5)
            ], width=dp(1.2))
            
        self.label.size = (self.width * 0.6, self.height)
        self.label.pos = (self.x + dp(12), self.y)
        self.label.text_size = (self.width * 0.6, None)
        
        self.status_label.text = self.status_val
        self.status_label.size = (self.width * 0.3, self.height)
        self.status_label.pos = (self.x + self.width - dp(36) - self.status_label.width, self.y)
        self.status_label.text_size = (self.status_label.width, None)


# ---------------------------------------------------------------------------
# SettingsScreen - 设置界面
# ---------------------------------------------------------------------------
class SettingsScreen(Screen):
    """设置界面：设备信息、端口配置、数据管理、关于信息。"""

    # 默认端口常量
    DEFAULT_UDP_PORT = 8890
    DEFAULT_TCP_PORT = 7779

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "settings"
        self._build_ui()

    # ---- UI 构造 ---------------------------------------------------------

    def _build_ui(self):
        # 1. 挂载纯色背景
        self.background = Factory.SolidColorBackground()
        self.add_widget(self.background)

        # 2. 内容层容器
        root = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))

        # -- 标题栏 --
        title_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(48),
            spacing=dp(6),
        )

        self.back_btn = Factory.ModernButtonSecondary(
            text="< 返回",
            size_hint_x=0.2,
            size_hint_y=0.75,
            font_size="13sp",
        )
        self.back_btn.bind(on_press=self._on_back)

        title_label = Label(
            text="设置",
            font_size="22sp",
            bold=True,
            color=(1, 1, 1, 1),
            halign="center"
        )

        title_row.add_widget(self.back_btn)
        title_row.add_widget(title_label)
        root.add_widget(title_row)

        # 卡片容器构造辅助函数 (Flat Design)
        def make_flat_card(spacing=dp(8), padding=dp(10)):
            card = BoxLayout(orientation="vertical", spacing=spacing, padding=padding, size_hint_y=None)
            with card.canvas.before:
                Color(0.12, 0.12, 0.13, 1)  # Flat dark background
                bg = RoundedRectangle(pos=card.pos, size=card.size, radius=[dp(12)])
            def _up(w, v):
                bg.pos = w.pos
                bg.size = w.size
            card.bind(pos=_up, size=_up)
            card.bind(minimum_height=card.setter("height"))
            return card

        # ---- Card 1: 设备与网络配置 ----
        card_net = make_flat_card(spacing=dp(8))
        card_net.add_widget(self._make_section_header("系统与网络配置"))

        # 设备名称（只读显示）
        device_row = self._make_setting_row("设备名称")
        self.device_name_label = Label(
            text="--",
            font_size="14sp",
            halign="right",
            valign="middle",
            color=(0.85, 0.85, 0.9, 1),
            size_hint_x=0.5,
        )
        self.device_name_label.bind(size=self.device_name_label.setter("text_size"))
        device_row.add_widget(self.device_name_label)
        card_net.add_widget(device_row)

        # TCP 端口（可修改）
        tcp_row = self._make_setting_row("TCP 监听端口")
        self.tcp_port_input = Factory.ModernTextInput(
            text=str(self.DEFAULT_TCP_PORT),
            multiline=False,
            input_filter="int",
            size_hint_x=0.3,
            halign="right",
        )
        tcp_row.add_widget(self.tcp_port_input)

        tcp_save_btn = Factory.ModernButtonAccent(
            text="应用",
            size_hint_x=0.18,
            size_hint_y=0.8,
            font_size="13sp",
        )
        tcp_save_btn.bind(on_press=self._on_save_tcp_port)
        tcp_row.add_widget(tcp_save_btn)
        card_net.add_widget(tcp_row)

        # TCP 端口修改提示
        self.tcp_port_hint = Label(
            text="",
            font_size="12sp",
            size_hint_y=None,
            height=dp(18),
            halign="left",
            color=(0.9, 0.9, 0.46, 1),
        )
        self.tcp_port_hint.bind(size=self.tcp_port_hint.setter("text_size"))
        card_net.add_widget(self.tcp_port_hint)

        # UDP 端口（只读）
        udp_row = self._make_setting_row("UDP 广播端口")
        udp_label = Label(
            text=str(self.DEFAULT_UDP_PORT),
            font_size="14sp",
            halign="right",
            valign="middle",
            color=(0.63, 0.65, 0.75, 1),
            size_hint_x=0.3,
        )
        udp_label.bind(size=udp_label.setter("text_size"))
        udp_row.add_widget(udp_label)
        card_net.add_widget(udp_row)
        
        root.add_widget(card_net)

        # ---- Card 2: 本地数据清理 ----
        card_data = make_flat_card(spacing=dp(8))
        card_data.add_widget(self._make_section_header("本地数据清理"))

        # 清空聊天记录
        self.clear_chat_row = ClickableSettingRow(label_text="清空本地所有聊天记录")
        self.clear_chat_row.bind(on_press=self._on_clear_chat)
        card_data.add_widget(self.clear_chat_row)

        # 待发送消息
        self.pending_row = ClickableSettingRow(label_text="清空待发送离线队列", status_text="0 条")
        self.pending_row.bind(on_press=self._on_clear_pending)
        card_data.add_widget(self.pending_row)
        
        root.add_widget(card_data)

        # ---- 关于信息区 ----
        root.add_widget(self._make_section_header("关于应用"))

        about_card = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(94),
            padding=[dp(16), dp(10)],
            spacing=dp(4),
        )
        
        with about_card.canvas.before:
            Color(0.12, 0.12, 0.13, 1)
            self._about_bg = RoundedRectangle(pos=about_card.pos, size=about_card.size, radius=[dp(12)])
            
        def update_about_bg(w, v):
            self._about_bg.pos = about_card.pos
            self._about_bg.size = about_card.size
        about_card.bind(pos=update_about_bg, size=update_about_bg)

        about_title = Label(
            text="相识北洋",
            font_size="18sp",
            bold=True,
            size_hint_y=0.35,
            color=(0.0, 0.6, 1.0, 1), # QQ Blue
            halign="left"
        )
        about_title.bind(size=about_title.setter("text_size"))

        about_version = Label(
            text="版本: 3.0.0",
            font_size="13sp",
            size_hint_y=0.25,
            halign="left",
            valign="middle",
            color=(0.63, 0.65, 0.75, 1),
        )
        about_version.bind(size=about_version.setter("text_size"))

        about_desc = Label(
            text="P2P 校园社交应用 | 洪泛消息中继 | 兴趣条件匹配",
            font_size="12sp",
            size_hint_y=0.2,
            halign="left",
            valign="middle",
            color=(0.55, 0.55, 0.65, 1),
        )
        about_desc.bind(size=about_desc.setter("text_size"))

        about_ports = Label(
            text=f"UDP 广播端口: {self.DEFAULT_UDP_PORT}  |  TCP 通信端口: {self.DEFAULT_TCP_PORT}",
            font_size="11sp",
            size_hint_y=0.2,
            halign="left",
            valign="middle",
            color=(0.45, 0.45, 0.55, 1),
        )
        about_ports.bind(size=about_ports.setter("text_size"))

        about_card.add_widget(about_title)
        about_card.add_widget(about_version)
        about_card.add_widget(about_desc)
        about_card.add_widget(about_ports)
        root.add_widget(about_card)

        # 填充剩余空间
        root.add_widget(Widget(size_hint_y=1))

        # -- 底部导航栏 --
        nav_bar = self._build_modern_nav_bar("settings")
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
        """进入设置界面时刷新信息。"""
        self._refresh_device_info()
        self._refresh_pending_count()
        self._refresh_tcp_port()

    # ---- 公共 API --------------------------------------------------------

    @mainthread
    def update_device_name(self, name):
        """更新设备名称显示。"""
        self.device_name_label.text = name if name else "--"
    @mainthread
    def update_pending_count(self, count):
        """更新待发送消息计数。"""
        self.pending_row.status_val = f"{count} 条"
        self.pending_row._redraw()

    @mainthread
    def set_tcp_port_display(self, port):
        """更新 TCP 端口输入框的值。"""
        self.tcp_port_input.text = str(port)

    @mainthread
    def show_status(self, text, is_error=False):
        """显示操作状态提示。"""
        self.tcp_port_hint.text = text
        self.tcp_port_hint.color = (1.0, 0.23, 0.19, 1) if is_error else (0.0, 0.9, 0.46, 1)
        # 3 秒后清除提示
        from kivy.clock import Clock
        Clock.schedule_once(lambda dt: self._clear_status(), 3)

    # ---- 事件处理 --------------------------------------------------------

    def _on_back(self, _btn):
        """返回按钮：回到上一个界面（默认回到发现界面）。"""
        app = get_root_app()
        if hasattr(app, "root") and hasattr(app.root, "current"):
            app.root.current = "discover"

    def _on_save_tcp_port(self, _btn):
        """保存 TCP 端口修改。"""
        try:
            port = int(self.tcp_port_input.text.strip())
            if port < 1024 or port > 65535:
                self.show_status("端口范围: 1024-65535", is_error=True)
                return

            app = get_root_app()
            if hasattr(app, "set_tcp_port"):
                app.set_tcp_port(port)
            self.show_status(f"TCP 端口已设置为 {port}（重启后完全生效）")
        except ValueError:
            self.show_status("请输入有效的端口号", is_error=True)

    def _on_clear_chat(self, _btn):
        """清空聊天记录（带确认对话框）。"""
        content = BoxLayout(orientation="vertical", spacing=dp(12), padding=[dp(16), dp(16)])
        _add_background(content, (0.09, 0.10, 0.14, 1))

        warning = Label(
            text="确定要清空所有聊天记录吗？\n此操作不可恢复。",
            font_size="15sp",
            color=(1, 1, 1, 1),
            halign="center",
            valign="middle"
        )
        warning.bind(size=warning.setter("text_size"))
        content.add_widget(warning)

        btn_row = BoxLayout(orientation="horizontal", spacing=dp(10), size_hint_y=None, height=dp(40))

        confirm_btn = Factory.ModernButtonDanger(
            text="确认清空",
        )

        def _do_clear(_b):
            app = get_root_app()
            if hasattr(app, "clear_chat_history"):
                # 清空所有的聊天记录
                friends = app.get_all_friends()
                for f in friends:
                    app.clear_chat_history(f.get("name", ""))
            self.show_status("聊天记录已清空")
            popup.dismiss()

        confirm_btn.bind(on_press=_do_clear)

        cancel_btn = Factory.ModernButtonSecondary(
            text="取消",
        )
        cancel_btn.bind(on_press=lambda _b: popup.dismiss())

        btn_row.add_widget(confirm_btn)
        btn_row.add_widget(cancel_btn)
        content.add_widget(btn_row)

        popup = Popup(
            title="清空聊天记录",
            content=content,
            size_hint=(0.8, 0.36),
            background_color=(0.04, 0.04, 0.06, 0.95),
            title_align="center"
        )
        popup.open()

    def _on_clear_pending(self, _btn):
        """清空待发送消息（带确认对话框）。"""
        content = BoxLayout(orientation="vertical", spacing=dp(12), padding=[dp(16), dp(16)])
        _add_background(content, (0.09, 0.10, 0.14, 1))

        warning = Label(
            text="确定要清空所有待发送消息吗？\n离线好友将不会收到这些消息。",
            font_size="15sp",
            color=(1, 1, 1, 1),
            halign="center",
            valign="middle"
        )
        warning.bind(size=warning.setter("text_size"))
        content.add_widget(warning)

        btn_row = BoxLayout(orientation="horizontal", spacing=dp(10), size_hint_y=None, height=dp(40))

        confirm_btn = Factory.ModernButtonDanger(
            text="确认清空",
        )

        def _do_clear(_b):
            app = get_root_app()
            if hasattr(app, "clear_pending_messages"):
                # 清空所有的待发送消息
                friends = app.get_all_friends()
                for f in friends:
                    app.clear_pending_messages(f.get("name", ""))
            self.update_pending_count(0)
            self.show_status("待发送消息已清空")
            popup.dismiss()

        confirm_btn.bind(on_press=_do_clear)

        cancel_btn = Factory.ModernButtonSecondary(
            text="取消",
        )
        cancel_btn.bind(on_press=lambda _b: popup.dismiss())

        btn_row.add_widget(confirm_btn)
        btn_row.add_widget(cancel_btn)
        content.add_widget(btn_row)

        popup = Popup(
            title="清空待发送消息",
            content=content,
            size_hint=(0.8, 0.36),
            background_color=(0.04, 0.04, 0.06, 0.95),
            title_align="center"
        )
        popup.open()

    # ---- 内部方法 --------------------------------------------------------

    def _refresh_device_info(self):
        """从 App 获取设备名称。"""
        app = get_root_app()
        if hasattr(app, "device_name"):
            self.update_device_name(app.device_name)
        elif hasattr(app, "get_local_device_info"):
            info = app.get_local_device_info()
            if info:
                self.update_device_name(info.get("name", "--"))

    def _refresh_pending_count(self):
        """从 App 获取待发送消息数。"""
        app = get_root_app()
        if hasattr(app, "get_pending_message_count"):
            count = app.get_pending_message_count()
            self.update_pending_count(count if count else 0)

    def _refresh_tcp_port(self):
        """从 App 获取当前 TCP 端口。"""
        app = get_root_app()
        if hasattr(app, "tcp_port"):
            self.set_tcp_port_display(app.tcp_port)

    def _clear_status(self):
        """清除操作状态提示。"""
        self.tcp_port_hint.text = ""

    def _make_section_header(self, text):
        """创建分组标题。"""
        lbl = Label(
            text=text,
            font_size="15sp",
            bold=True,
            size_hint_y=None,
            height=dp(32),
            halign="left",
            valign="bottom",
            color=(0.5, 0.5, 0.55, 1),
        )
        lbl.bind(size=lbl.setter("text_size"))
        return lbl

    def _make_setting_row(self, label_text):
        """创建一行设置项：左侧标签 + 右侧控件容器。"""
        row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(46),
            spacing=dp(8),
            padding=[dp(12), dp(4), dp(12), dp(4)],
        )
        
        with row.canvas.before:
            Color(0.12, 0.12, 0.13, 1)  # Flat background
            row_bg = RoundedRectangle(pos=row.pos, size=row.size, radius=[dp(8)])
            
        def update_row_bg(w, v, bg=row_bg):
            bg.pos = w.pos
            bg.size = w.size
        row.bind(pos=update_row_bg, size=update_row_bg)

        label = Label(
            text=label_text,
            font_size="14sp",
            halign="left",
            valign="middle",
            size_hint_x=0.52,
            color=(0.85, 0.85, 0.9, 1),
        )
        label.bind(size=label.setter("text_size"))
        row.add_widget(label)

        return row

    def _navigate(self, screen_name):
        """通过 ScreenManager 切换界面，使用无延迟切换避免动画卡顿。"""
        app = get_root_app()
        if hasattr(app, "root") and hasattr(app.root, "current"):
            if app.root.current == screen_name:
                return
            from kivy.uix.screenmanager import NoTransition
            app.root.transition = NoTransition()
            app.root.current = screen_name

