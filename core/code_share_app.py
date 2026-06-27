"""
相识北洋 - 校园社交应用主 App 控制器 (Challenge 3)
"""
import os
import sys
import threading
from kivy.app import App
from kivy.uix.screenmanager import ScreenManager
from kivy.clock import Clock, mainthread

# 确保能导入同包下的模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from screens.discover_screen import DiscoverScreen
from screens.friends_screen import FriendsScreen
from screens.chat_screen import ChatScreen
from screens.profile_screen import ProfileScreen
from screens.settings_screen import SettingsScreen

from core.services.social_runtime import RuntimeConfig, SocialRuntime

from core.utils.helpers import Helpers
from core.utils.protocol import Protocol
from kivy.core.text import LabelBase


def register_chinese_font():
    """动态搜索系统中的中文字体并注册为 Kivy 默认字体，防止中文乱码显示为豆腐块"""
    import os
    local_font = os.path.join(os.path.dirname(__file__), 'fonts', 'simhei.ttf')
    candidates = [
        # Windows (Preferred Modern Font)
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        # macOS
        "/System/Library/Fonts/PingFang.ttc",
        # Android
        "/system/fonts/NotoSansCJK-Regular.ttc",
        "/system/fonts/NotoSansSC-Regular.ttf",
        # Fallbacks
        r"C:\Windows\Fonts\simsun.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        "/system/fonts/DroidSansFallback.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        local_font,
    ]
    selected_font = None
    for path in candidates:
        if os.path.exists(path):
            selected_font = path
            break
    if selected_font:
        LabelBase.register(
            name='app_chinese_font',
            fn_regular=selected_font,
            fn_bold=selected_font,
            fn_italic=selected_font,
            fn_bolditalic=selected_font
        )
        # Apply font globally to all text widgets using Builder
        from kivy.lang import Builder
        Builder.load_string('''
<Label>:
    font_name: 'app_chinese_font'
<Button>:
    font_name: 'app_chinese_font'
<TextInput>:
    font_name: 'app_chinese_font'

<ModernLabel@Label>:
    font_name: 'app_chinese_font'
    color: 0.95, 0.95, 0.95, 1

<ModernButton@Button>:
    font_name: 'app_chinese_font'
    background_normal: ''
    background_down: ''
    background_color: 0, 0, 0, 0
    color: 0.9, 0.9, 0.9, 1
    font_size: '14sp'
    canvas.before:
        Color:
            rgba: (0.17, 0.17, 0.18, 1) if not self.disabled else (0.1, 0.1, 0.1, 1)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(8)]

<ModernButtonAccent@Button>:
    font_name: 'app_chinese_font'
    background_normal: ''
    background_down: ''
    background_color: 0, 0, 0, 0
    color: 1, 1, 1, 1
    font_size: '14sp'
    canvas.before:
        Color:
            rgba: (0.0, 0.6, 1.0, 1) if self.state == 'normal' else (0.0, 0.5, 0.8, 1)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(8)]

<ModernButtonDanger@Button>:
    font_name: 'app_chinese_font'
    background_normal: ''
    background_down: ''
    background_color: 0, 0, 0, 0
    color: 1, 1, 1, 1
    font_size: '14sp'
    canvas.before:
        Color:
            rgba: (0.9, 0.25, 0.3, 1) if self.state == 'normal' else (0.7, 0.15, 0.2, 1)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(8)]

<ModernButtonSecondary@Button>:
    font_name: 'app_chinese_font'
    background_normal: ''
    background_down: ''
    background_color: 0, 0, 0, 0
    color: 0.6, 0.6, 0.65, 1
    font_size: '14sp'
    canvas.before:
        Color:
            rgba: (0.12, 0.12, 0.13, 1) if self.state == 'normal' else (0.08, 0.08, 0.09, 1)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(8)]

<ModernTextInput@TextInput>:
    font_name: 'app_chinese_font'
    foreground_color: 0.95, 0.95, 0.95, 1
    background_color: 0, 0, 0, 0
    cursor_color: 0.0, 0.6, 1.0, 1
    padding: [dp(12), dp(10), dp(12), dp(10)]
    use_bubble: True
    canvas.before:
        Color:
            rgba: (0.17, 0.17, 0.18, 1)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(8)]
        Color:
            rgba: (0.0, 0.6, 1.0, 1) if self.focus else (0, 0, 0, 0)
        Line:
            rounded_rectangle: (self.x, self.y, self.width, self.height, dp(8))
            width: dp(1)
''')
        print(f"[FontManager] 已成功注册中文字体: {selected_font}")
    else:
        print("[FontManager] 警告: 未在系统中找到合适的中文默认字体，中文可能显示为乱码！")


# 立即执行中文字体注册
register_chinese_font()


# ================================================================== #
#  UI 重构全局组件：动态多彩头像与矢量图标导航键
# ================================================================== #
import hashlib
import math
from kivy.properties import StringProperty, BooleanProperty, NumericProperty
from kivy.uix.widget import Widget
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.metrics import dp
from kivy.graphics import Color, Ellipse, Line, RoundedRectangle, Rectangle
from kivy.factory import Factory
from kivy.clock import Clock


class SolidColorBackground(Widget):
    """纯色平铺背景 (支持自定义本地背景图)"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self._redraw, size=self._redraw)
        Clock.schedule_once(self._bind_to_app, 0)
        
    def _bind_to_app(self, dt):
        from kivy.app import App
        app = App.get_running_app()
        if app and hasattr(app, "custom_background"):
            app.bind(custom_background=self._redraw)
            self._redraw()

    def _redraw(self, *args):
        self.canvas.clear()
        if self.width <= 1 or self.height <= 1:
            return
            
        from kivy.app import App
        import os
        app = App.get_running_app()
        bg_source = getattr(app, "custom_background", "") if app else ""

        with self.canvas:
            if bg_source and os.path.exists(bg_source):
                Color(1, 1, 1, 1.0)
                Rectangle(pos=self.pos, size=self.size, source=bg_source)
            else:
                Color(0.07, 0.07, 0.07, 1.0) # Solid dark `#121212` background
                Rectangle(pos=self.pos, size=self.size)

Factory.register('SolidColorBackground', cls=SolidColorBackground)


class LetterAvatar(Widget):
    """动态哈希多彩圆形文字头像组件，右上角可选在线状态点，支持自定义头像"""
    text = StringProperty("")
    name_key = StringProperty("")
    is_online = BooleanProperty(False)
    avatar_size = NumericProperty(dp(40))
    avatar_source = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (None, None)
        self.size = (self.avatar_size, self.avatar_size)
        
        self.lbl = Label(
            text="",
            font_size="15sp",
            bold=True,
            color=(1, 1, 1, 1),
            font_name='app_chinese_font',
            halign="center",
            valign="middle"
        )
        self.add_widget(self.lbl)
        
        self.bind(pos=self._redraw, size=self._redraw, name_key=self._redraw, is_online=self._redraw, text=self._redraw)

    def _redraw(self, *args):
        self.size = (self.avatar_size, self.avatar_size)
        self.lbl.size = self.size
        self.lbl.pos = self.pos
        self.lbl.font_size = f"{max(9, int(self.avatar_size * 0.42))}sp"
        
        display_char = self.text.strip()
        if display_char:
            self.lbl.text = display_char[0].upper()
        else:
            self.lbl.text = "?"

        self.canvas.before.clear()
        self.canvas.after.clear()
        
        from kivy.app import App
        import os
        app = App.get_running_app()

        custom_avatar = self.avatar_source
        if not custom_avatar and app and self.name_key == getattr(app, 'device_name', ''):
            custom_avatar = getattr(app, 'custom_avatar', '')

        with self.canvas.before:
            if custom_avatar and os.path.exists(custom_avatar):
                Color(1, 1, 1, 1)
                Ellipse(pos=self.pos, size=self.size, source=custom_avatar)
                self.lbl.text = "" # Hide the letter if avatar is shown
            else:
                bg_rgba = self._get_color_by_name(self.name_key)
                Color(*bg_rgba)
                Ellipse(pos=self.pos, size=self.size)

        if self.is_online:
            with self.canvas.after:
                Color(0.04, 0.04, 0.06, 1)
                Ellipse(pos=(self.x + self.width - dp(12), self.y), size=(dp(12), dp(12)))
                Color(0.0, 0.9, 0.46, 1)
                Ellipse(pos=(self.x + self.width - dp(10), self.y + dp(2)), size=(dp(8), dp(8)))

    def _get_color_by_name(self, name):
        if not name:
            return (0.44, 0.32, 1.0, 1)
        colors = [
            (0.53, 0.33, 0.82, 1),  # Purple
            (0.04, 0.24, 0.38, 1),  # Cyan
            (0.13, 0.75, 0.42, 1),  # Green
            (0.92, 0.23, 0.35, 1),  # Red
            (0.98, 0.51, 0.19, 1),  # Orange
            (0.18, 0.60, 0.85, 1)   # Blue
        ]
        try:
            h = hashlib.md5(name.encode('utf-8', errors='ignore')).hexdigest()
            val = int(h, 16)
            return colors[val % len(colors)]
        except Exception:
            return (0.44, 0.32, 1.0, 1)


class IconTabButton(Button):
    """手绘矢量图标底栏导航按键 (Minimalist)"""
    tab_name = StringProperty("")
    is_active = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ''
        self.background_down = ''
        self.background_color = (0, 0, 0, 0)
        self.color = (0, 0, 0, 0)
        
        self.text_label = Label(
            text="",
            font_name="app_chinese_font",
            font_size="10sp",
            color=(0.5, 0.55, 0.65, 1),
            halign="center",
            valign="middle"
        )
        self.add_widget(self.text_label)
        self.bind(pos=self.redraw, size=self.redraw, is_active=self.redraw, text=self.redraw)

    def redraw(self, *args):
        self.canvas.before.clear()
        self.canvas.after.clear()
        
        # Color palette for active / inactive
        active_color = (0.0, 0.6, 1.0, 1) # QQ Blue
        inactive_color = (0.6, 0.6, 0.65, 1)
        
        self.text_label.text = self.text
        self.text_label.color = active_color if self.is_active else inactive_color
        self.text_label.bold = False
        self.text_label.size = (self.width, dp(18))
        self.text_label.pos = (self.x, self.y + dp(4))
        self.text_label.text_size = (self.width, None)

        cx = self.x + self.width / 2
        cy = self.y + self.height - dp(21)
        size = dp(20)

        with self.canvas.before:
            pass # No glowing dots

        with self.canvas.after:
            Color(*(active_color if self.is_active else inactive_color))

            # Refined minimalist vector icons
            if self.tab_name == "discover":
                Line(ellipse=(cx - size/2, cy - size/2, size, size), width=dp(1.2))
                Line(points=[cx - size/4, cy + size/4, cx + size/4, cy - size/4], width=dp(1.2))
                Ellipse(pos=(cx - dp(2), cy - dp(2)), size=(dp(4), dp(4)))
                
            elif self.tab_name == "friends":
                Ellipse(pos=(cx - dp(4), cy), size=(dp(8), dp(8)))
                Line(bezier=[cx - dp(8), cy - dp(6), cx - dp(7), cy - dp(2), cx + dp(7), cy - dp(2), cx + dp(8), cy - dp(6)], width=dp(1.2))
                
            elif self.tab_name == "chat":
                Line(rounded_rectangle=(cx - dp(8), cy - dp(5), dp(16), dp(12), dp(4)), width=dp(1.2))
                Line(points=[cx - dp(4), cy - dp(5), cx - dp(7), cy - dp(9), cx - dp(6), cy - dp(5)], width=dp(1.2))
                Line(points=[cx - dp(3), cy + dp(1), cx + dp(3), cy + dp(1)], width=dp(1))
                
            elif self.tab_name == "profile":
                Line(circle=(cx, cy, dp(7)), width=dp(1.2))
                Ellipse(pos=(cx - dp(2.5), cy + dp(1)), size=(dp(5), dp(5)))
                Line(bezier=[cx - dp(5), cy - dp(5), cx - dp(3), cy - dp(2), cx + dp(3), cy - dp(2), cx + dp(5), cy - dp(5)], width=dp(1.2))

            elif self.tab_name == "settings":
                Line(circle=(cx, cy, dp(4)), width=dp(1.2))
                import math
                for angle in range(0, 360, 60):
                    rad = math.radians(angle)
                    x1 = cx + math.cos(rad) * dp(4)
                    y1 = cy + math.sin(rad) * dp(4)
                    x2 = cx + math.cos(rad) * dp(7)
                    y2 = cy + math.sin(rad) * dp(7)
                    Line(points=[x1, y1, x2, y2], width=dp(1.2))


Factory.register('LetterAvatar', cls=LetterAvatar)
Factory.register('IconTabButton', cls=IconTabButton)


class CodeShareApp(App):
    """相识北洋主应用"""
    custom_background = StringProperty("")
    custom_avatar = StringProperty("")

    def __init__(self, tcp_port=Protocol.DEFAULT_TCP_PORT, udp_port=Protocol.DEFAULT_UDP_PORT, db_path="assets/data/friends.db", name_override="", **kwargs):
        super().__init__(**kwargs)
        self.tcp_port = tcp_port
        self.udp_port = udp_port
        self.db_path = db_path
        self.name_override = (name_override or "").strip()
        self.device_name = name_override or Helpers.get_hostname()

        self.friend_db = None
        self.connection_manager = None
        self.udp_service = None
        self.message_service = None
        self.social_service = None
        self.runtime = None

    def build(self):
        self.title = "相识北洋"
        self._init_services()

        from kivy.uix.screenmanager import SlideTransition
        sm = ScreenManager(transition=SlideTransition(duration=0.2))
        sm.add_widget(DiscoverScreen(name='discover'))
        sm.add_widget(FriendsScreen(name='friends'))
        sm.add_widget(ChatScreen(name='chat'))
        sm.add_widget(ProfileScreen(name='profile'))
        sm.add_widget(SettingsScreen(name='settings'))
        
        # 默认跳到发现页面
        sm.current = 'discover'
        return sm

    def _init_services(self):
        self.runtime = SocialRuntime(
            RuntimeConfig(
                tcp_port=self.tcp_port,
                udp_port=self.udp_port,
                db_path=self.db_path,
                name_override=self.name_override,
                receive_dir="assets/received_files",
            )
        ).initialize()
        self.runtime.on_discovery_changed = self._on_device_found
        self.runtime.on_online_changed = self._on_online_changed
        self.runtime.on_friends_changed = self._on_friends_changed
        self.runtime.on_message_received = self._on_service_message_received
        self.runtime.on_friend_request = self._on_service_friend_request
        self.runtime.on_friend_accepted = self._on_service_friend_accepted
        self.runtime.on_error = self._on_error
        self._mirror_runtime_state()

    def _mirror_runtime_state(self):
        self.device_name = self.runtime.device_name
        self.user_id = self.runtime.user_id
        self.device_id = self.runtime.device_id
        self.custom_background = self.runtime.custom_background
        self.custom_avatar = self.runtime.custom_avatar
        self.friend_db = self.runtime.friend_db
        self.connection_manager = self.runtime.connection_manager
        self.udp_service = self.runtime.udp_service
        self.message_service = self.runtime.message_service
        self.social_service = self.runtime.social_service

    def on_start(self):
        if self.runtime:
            self.runtime.start()

    def on_stop(self):
        if self.runtime:
            self.runtime.stop()

    # ================================================================== #
    #  服务层回调处理
    # ================================================================== #

    @mainthread
    def _on_device_found(self):
        discover = self.root.get_screen('discover')
        if discover:
            discover._refresh_discovered()

    @mainthread
    def _on_device_offline(self, ip):
        discover = self.root.get_screen('discover')
        if discover:
            discover._refresh_discovered()

    @mainthread
    def _on_online_changed(self):
        discover = self.root.get_screen('discover')
        if discover:
            discover._refresh_online_friends()

    @mainthread
    def _on_friends_changed(self):
        friends = self.root.get_screen('friends')
        if friends:
            friends.refresh()

    @mainthread
    def _on_friend_disconnected(self, ip):
        self._on_online_changed()
        self._on_friends_changed()

    def _on_message_received(self, ip, data):
        # 将接收到的原始网络包传递给消息服务进一步解析
        if self.message_service:
            self.message_service.handle_message(ip, data)

    def _on_error(self, msg):
        print(f"[BeiyangSocialApp Error] {msg}")

    @mainthread
    def _on_service_message_received(self, friend_name, content, timestamp):
        chat = self.root.get_screen('chat')
        if chat:
            chat.on_new_message(friend_name, content, timestamp)

    def _on_service_friend_request(self, profile, is_match, from_ip=None):
        profile = dict(profile or {})
        if from_ip:
            profile["ip"] = from_ip
        Clock.schedule_once(
            lambda _dt: self._show_friend_request_popup(profile, is_match),
            0
        )

    def _show_friend_request_popup(self, profile, is_match):
        """Show a conservative friend-request dialog on the Kivy main thread."""
        try:
            from kivy.uix.popup import Popup
            from kivy.uix.boxlayout import BoxLayout
            from kivy.uix.label import Label
            from kivy.uix.button import Button
            from kivy.metrics import dp

            sender_name = profile.get("name", "Unknown")
            bio = profile.get("bio", "这个用户很懒，什么都没写")
            tags = profile.get("tags", [])
            sender_ip = profile.get("ip", "0.0.0.0")
            match_text = "符合你的交友条件" if is_match else "未完全符合你的交友条件"

            layout = BoxLayout(
                orientation='vertical',
                padding=[dp(16), dp(14), dp(16), dp(12)],
                spacing=dp(10)
            )
            message = (
                "收到好友申请\n\n"
                f"{sender_name} 想添加你为好友\n"
                f"IP: {sender_ip}\n"
                f"状态: {match_text}\n"
                f"标签: {', '.join(tags) if tags else '无'}\n\n"
                f"{bio}"
            )
            info_label = Label(
                text=message,
                font_size='14sp',
                halign='left',
                valign='top'
            )
            info_label.bind(size=info_label.setter("text_size"))
            layout.add_widget(info_label)

            btn_row = BoxLayout(
                orientation='horizontal',
                size_hint_y=None,
                height=dp(42),
                spacing=dp(10)
            )
            accept_btn = Button(text="同意并添加", font_size='14sp')
            ignore_btn = Button(text="忽略", font_size='14sp')
            btn_row.add_widget(accept_btn)
            btn_row.add_widget(ignore_btn)
            layout.add_widget(btn_row)

            popup = Popup(
                title="",
                title_size=0,
                content=layout,
                size_hint=(0.86, 0.52),
                auto_dismiss=False
            )

            def on_accept(_btn):
                import threading
                self.friend_db.add_friend(
                    name=sender_name,
                    ip=sender_ip,
                    port=int(profile.get("tcp_port", Protocol.DEFAULT_TCP_PORT) or Protocol.DEFAULT_TCP_PORT),
                    tags=tags,
                    bio=bio,
                    category="朋友",
                    user_id=profile.get("user_id", ""),
                    status="accepted",
                )
                self.friend_db.set_friend_request_status(
                    "accepted",
                    user_id=profile.get("user_id", ""),
                    name=sender_name,
                    ip=sender_ip,
                    port=int(profile.get("tcp_port", Protocol.DEFAULT_TCP_PORT) or Protocol.DEFAULT_TCP_PORT),
                )
                threading.Thread(
                    target=self.message_service.send_friend_accept,
                    args=(sender_name, sender_ip),
                    daemon=True,
                ).start()
                friends = self.root.get_screen('friends')
                if friends:
                    friends.refresh()
                discover = self.root.get_screen('discover')
                if discover:
                    discover._refresh_online_friends()
                popup.dismiss()

            accept_btn.bind(on_press=on_accept)
            def on_ignore(_btn):
                self.friend_db.set_friend_request_status(
                    "rejected",
                    user_id=profile.get("user_id", ""),
                    name=sender_name,
                    ip=sender_ip,
                    port=int(profile.get("tcp_port", Protocol.DEFAULT_TCP_PORT) or Protocol.DEFAULT_TCP_PORT),
                )
                popup.dismiss()

            ignore_btn.bind(on_press=on_ignore)
            popup.open()
        except Exception as e:
            print(f"[BeiyangSocialApp Error] Failed to show friend request popup: {e}")

    @mainthread
    def _on_service_friend_accepted(self, friend_name, friend_ip):
        discover = self.root.get_screen('discover')
        if discover:
            discover._refresh_online_friends()
        friends = self.root.get_screen('friends')
        if friends:
            friends.refresh()

    # ================================================================== #
    #  UI 层调用 API 接口
    # ================================================================== #

    def get_local_device_info(self):
        return {
            'name': self.device_name,
            'ip': Helpers.get_default_ip()
        }

    def set_tcp_port(self, port):
        self.tcp_port = port
        if self.runtime:
            self.runtime.set_tcp_port(port)
            self._mirror_runtime_state()

    def get_my_profile(self):
        p = self.friend_db.get_my_profile()
        p["ip"] = Helpers.get_default_ip()
        if self.device_name:
            p["name"] = self.device_name
        return p

    def save_profile(self, profile):
        if self.runtime:
            self.runtime.save_profile(profile)
            self._mirror_runtime_state()

    def scan_for_people(self):
        if self.runtime:
            self.runtime.scan_for_people()

    def get_discovered_people(self):
        return self.runtime.get_discovered_people() if self.runtime else []

    def send_friend_request(self, name, ip, port=Protocol.DEFAULT_TCP_PORT, user_id=""):
        if self.is_existing_friend(name, ip, port, user_id):
            return False
        if self.message_service:
            return self.message_service.send_friend_request(name, ip, port, user_id)
        return False

    def is_existing_friend(self, name="", ip="", port=0, user_id=""):
        if not self.friend_db:
            return False
        return self.friend_db.get_relationship_status(
            user_id=user_id,
            name=name,
            ip=ip,
            port=port,
        ) in ("pending_sent", "pending_received", "accepted")

    def get_relationship_status(self, name="", ip="", port=0, user_id=""):
        if not self.friend_db:
            return "none"
        return self.friend_db.get_relationship_status(
            user_id=user_id,
            name=name,
            ip=ip,
            port=port,
        )

    def get_all_friends(self):
        return self.runtime.get_all_friends() if self.runtime else []

    def get_online_friends(self):
        return self.runtime.get_online_friends() if self.runtime else []

    def delete_friend(self, name):
        friend = self.friend_db.get_friend(name)
        if friend:
            ip = friend.get("ip")
            port = friend.get("port")
            if ip and self.connection_manager:
                endpoint = f"{ip}:{port}" if port else ip
                self.connection_manager.disconnect_friend(endpoint)
            self.friend_db.remove_friend(name)
            # 刷新 UI
            friends = self.root.get_screen('friends')
            if friends:
                friends.refresh()
            discover = self.root.get_screen('discover')
            if discover:
                discover._refresh_online_friends()

    def set_friend_category(self, name, category):
        if self.friend_db:
            self.friend_db.set_friend_category(name, category)
            # 刷新 UI
            friends = self.root.get_screen('friends')
            if friends:
                friends.refresh()

    def open_chat_with(self, name):
        self.root.current = 'chat'
        chat_screen = self.root.get_screen('chat')
        if chat_screen:
            chat_screen.show_window_view(name)

    def send_chat_message(self, friend_name, *args):
        # 支持 (friend_name, text) 和 (friend_name, friend_ip, text)
        if len(args) == 1:
            text = args[0]
        elif len(args) == 2:
            text = args[1]
        else:
            return False

        if self.message_service:
            return self.message_service.send_message(friend_name, text)
        return False

    def send_file_to_friend(self, friend_name, file_path):
        if self.message_service:
            return self.message_service.send_file(friend_name, file_path)
        return False

    def get_chat_history(self, friend_name):
        if self.friend_db:
            return self.friend_db.get_chat_history(friend_name, limit=100)
        return []

    def clear_chat_history(self, friend_name):
        if self.friend_db:
            self.friend_db.clear_chat_history(friend_name)
            # 刷新聊天窗口
            chat_screen = self.root.get_screen('chat')
            if chat_screen and chat_screen._current_view == 'window':
                chat_screen.chat_window_view.clear_messages()

    def get_chat_list(self):
        try:
            return self.runtime.get_chat_list() if self.runtime else []
        except Exception as e:
            print(f"获取聊天列表失败: {e}")
            return []

    def get_runtime_health(self):
        return self.runtime.get_health() if self.runtime else {}

    def clear_pending_messages(self, friend_name):
        if self.friend_db:
            self.friend_db.clear_pending_messages(friend_name)

    def get_pending_message_count(self, for_friend=None):
        if self.social_service:
            return self.social_service.get_pending_message_count(for_friend or "")
        return 0
