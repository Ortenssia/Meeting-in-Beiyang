"""Discover view: scan, online friends, nearby people, manual add."""
import threading
import time

import flet as ft

from .. import theme as T


class DiscoverView:
    def __init__(self, app):
        self.app = app
        self.page = app.page
        self._lock = threading.Lock()

        # Scan status text with clean typography
        self.scan_status = ft.Text(
            "雷达就绪，点击开始扫描",
            size=T.FS_BODY,
            weight=ft.FontWeight.W_500,
            color=ft.Colors.ON_SURFACE_VARIANT
        )

        # Premium animated scanning progress ring
        self.scan_indicator = ft.ProgressRing(
            width=24, height=24, stroke_width=2.5,
            color=ft.Colors.DEEP_PURPLE_400,
            value=0  # Static when not scanning
        )

        # Sleek radar trigger button with primary gradient & shadow
        self.scan_btn = ft.GestureDetector(
            mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=self._on_scan,
            content=ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.RADAR_ROUNDED, color=ft.Colors.WHITE, size=20),
                        ft.Text("雷达扫描", color=ft.Colors.WHITE, size=T.FS_TEXT, weight=ft.FontWeight.BOLD),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                width=160,
                height=42,
                border_radius=21,
                gradient=T.GRADIENT_PRIMARY,
                shadow=T.SHADOW_GLOW,
                alignment=ft.alignment.Alignment.CENTER,
            )
        )

        # Elegant secondary button for manual connect
        self.manual_btn = ft.GestureDetector(
            mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=self._on_manual,
            content=ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.PERSON_ADD_ALT_1_ROUNDED, size=20),
                        ft.Text("手动连接", size=T.FS_TEXT, weight=ft.FontWeight.BOLD),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                width=140,
                height=42,
                border_radius=21,
                border=T.border_all(1.5, ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE)),
                alignment=ft.alignment.Alignment.CENTER,
            )
        )

        self.online_row = ft.Row(spacing=T.SP_MD, scroll=ft.ScrollMode.AUTO)
        self.list_col = ft.Column(spacing=T.SP_SM, expand=True, scroll=ft.ScrollMode.AUTO)

        # Diagnostics details rendered as custom status pills
        self.ip_pill = ft.Container(
            content=ft.Row(
                [ft.Icon(ft.Icons.LAN_ROUNDED, size=12, color=ft.Colors.DEEP_PURPLE_400),
                 ft.Text("IP: 未知", size=T.FS_CAPTION, weight=ft.FontWeight.BOLD)],
                spacing=4,
            ),
            bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.DEEP_PURPLE),
            padding=T.pad_symmetric(horizontal=8, vertical=4),
            border_radius=6,
        )
        self.packets_pill = ft.Container(
            content=ft.Row(
                [ft.Icon(ft.Icons.SWAP_VERT_ROUNDED, size=12, color=ft.Colors.BLUE_400),
                 ft.Text("已收: 0包", size=T.FS_CAPTION, weight=ft.FontWeight.BOLD)],
                spacing=4,
            ),
            bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.BLUE),
            padding=T.pad_symmetric(horizontal=8, vertical=4),
            border_radius=6,
        )

        self.diag_row = ft.Row(
            [self.ip_pill, self.packets_pill],
            spacing=T.SP_XS,
            wrap=True,
        )

        self._scanning = False

    def build(self):
        # Premium Radar Banner Dashboard
        radar_dashboard = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("附近搜索", size=T.FS_HEADER, weight=ft.FontWeight.W_800),
                            ft.Row([self.scan_indicator, self.scan_status], spacing=6),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Row(
                        [self.scan_btn, self.manual_btn],
                        spacing=T.SP_SM,
                        alignment=ft.MainAxisAlignment.START,
                    ),
                    ft.Container(height=4),
                    self.diag_row,
                ],
                spacing=T.SP_SM,
            ),
            padding=T.SP_LG,
            border_radius=T.R_LG,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            border=T.border_all(1, ft.Colors.with_opacity(0.06, ft.Colors.ON_SURFACE)),
        )

        return ft.Column(
            [
                radar_dashboard,
                ft.Container(height=T.SP_XS),
                # Online Friends Section
                ft.Text("在线好友", size=T.FS_TEXT, weight=ft.FontWeight.BOLD,
                        color=ft.Colors.DEEP_PURPLE_400),
                ft.Container(
                    content=self.online_row,
                    padding=T.pad_symmetric(vertical=4),
                ),
                ft.Container(height=T.SP_XS),
                # Discovered Nearby People Section
                ft.Text("附近的人", size=T.FS_TEXT, weight=ft.FontWeight.BOLD,
                        color=ft.Colors.ON_SURFACE_VARIANT),
                self.list_col,
            ],
            spacing=T.SP_SM, expand=True,
        )

    # -- lifecycle ---------------------------------------------------------

    def on_enter(self):
        self.refresh_discovered()
        self.refresh_online()
        self.refresh_diagnostics()

    # -- refreshers --------------------------------------------------------

    def refresh_discovered(self):
        with self._lock:
            people = self.app.get_discovered_people() or []
            self.list_col.controls.clear()
            for p in people:
                self.list_col.controls.append(self._person_card(p))
            if not people:
                self.list_col.controls.append(
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Icon(ft.Icons.RADAR_ROUNDED, size=40, color=ft.Colors.ON_SURFACE_VARIANT, opacity=0.4),
                                ft.Text(
                                    "附近暂无可发现的人\n点按「雷达扫描」或「手动连接」",
                                    text_align=ft.TextAlign.CENTER,
                                    size=T.FS_BODY,
                                    color=ft.Colors.ON_SURFACE_VARIANT,
                                    weight=ft.FontWeight.W_500
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.CENTER,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=T.SP_SM,
                        ),
                        padding=T.SP_2XL,
                        alignment=ft.alignment.Alignment.CENTER,
                        height=180,
                    )
                )
            if not self._scanning:
                self.scan_status.value = f"已发现 {len(people)} 人" if people else "未发现附近的人"
            self.refresh_diagnostics()
            if self.page:
                self.page.update()

    def refresh_online(self):
        with self._lock:
            friends = self.app.get_online_friends() or []
            self.online_row.controls.clear()
            for f in friends:
                name = f.get("name", "")
                self.online_row.controls.append(
                    ft.GestureDetector(
                        mouse_cursor=ft.MouseCursor.CLICK,
                        on_tap=lambda _e, n=name: self.app.open_chat_with(n),
                        content=ft.Column(
                            [
                                T.avatar_circle(self.app.get_avatar_for_name(name) if hasattr(self.app, "get_avatar_for_name") else name, T.AVATAR_MD, online=True),
                                ft.Text(name, size=T.FS_CAPTION, weight=ft.FontWeight.BOLD,
                                        max_lines=1, text_align=ft.TextAlign.CENTER, width=66),
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=4,
                        )
                    )
                )
            if not friends:
                self.online_row.controls.append(
                    ft.Container(
                        content=ft.Text("暂无在线好友", size=T.FS_CAPTION, color=ft.Colors.ON_SURFACE_VARIANT),
                        padding=T.pad_symmetric(horizontal=12, vertical=8),
                    )
                )
            if self.page:
                self.page.update()

    def refresh_diagnostics(self):
        diag = self.app.get_network_diagnostics() or {}
        if diag:
            ips = diag.get("local_ips") or []
            primary = next((ip for ip in ips if not ip.startswith("127.")),
                           ips[0] if ips else "未知")

            # Update diagnostic badges
            self.ip_pill.content.controls[1].value = f"IP: {primary}"

            packets = diag.get("receive_packets", 0)
            self.packets_pill.content.controls[1].value = f"已收: {packets}包"

            if diag.get("last_error"):
                # Dynamically append error text if something went wrong
                self.scan_status.value = f"网络错误: {diag['last_error']}"
                self.scan_status.color = ft.Colors.RED_400
        else:
            self.ip_pill.content.controls[1].value = "IP: 暂无数据"

        if self.page:
            self.page.update()

    # -- builders ----------------------------------------------------------

    def _person_card(self, p):
        name = p.get("name", "未知用户")
        port = int(p.get("tcp_port", 7779) or 7779)
        ip = p.get("ip", "0.0.0.0")
        user_id = p.get("user_id", "")
        status = p.get("status", "")
        status_label = p.get("status_label", "添加好友")
        if not status:
            status = self.app.get_relationship_status(name, ip, port, user_id)
            status_label = {
                "pending_sent": "已发送", "pending_received": "待处理",
                "accepted": "已是好友", "rejected": "可重试",
            }.get(status, "添加好友")

        # Use a standard Button here. GestureDetector/abstract Button taps can be swallowed or fail on Android.
        is_disabled = status in ("pending_sent", "pending_received", "accepted")
        btn = ft.Button(
            status_label,
            icon=ft.Icons.PERSON_ADD_ROUNDED if not is_disabled else None,
            disabled=is_disabled,
            on_click=lambda e, d=p: self._send_request(e, d),
            bgcolor=ft.Colors.DEEP_PURPLE_500 if not is_disabled else ft.Colors.SURFACE_CONTAINER_HIGHEST,
            color=ft.Colors.WHITE if not is_disabled else ft.Colors.ON_SURFACE_VARIANT,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=16),
                padding=T.pad_symmetric(horizontal=14, vertical=10),
            ),
        )

        if status == "accepted":
            btn.disabled = False
            btn.text = "发起聊天"
            btn.icon = ft.Icons.CHAT_ROUNDED
            btn.on_click = lambda _e, n=name: self.app.open_chat_with(n)
            btn.bgcolor = ft.Colors.DEEP_PURPLE_400
            btn.color = ft.Colors.WHITE

        # Glassmorphic card styling with premium layout
        return ft.Container(
            content=ft.Row(
                [
                    T.avatar_circle(self.app.get_avatar_for_name(name) if hasattr(self.app, "get_avatar_for_name") else name, T.AVATAR_MD),
                    ft.Column(
                        [
                            ft.Text(name, size=T.FS_TEXT, weight=ft.FontWeight.BOLD),
                            ft.Row(
                                [
                                    ft.Icon(ft.Icons.LAN_ROUNDED, size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                                    ft.Text(f"{ip}:{port}", size=T.FS_CAPTION,
                                            color=ft.Colors.ON_SURFACE_VARIANT, weight=ft.FontWeight.W_500),
                                ],
                                spacing=4,
                            ),
                        ],
                        spacing=2, expand=True,
                    ),
                    btn,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=T.SP_MD,
            height=76,
            border_radius=T.R_MD,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            border=T.border_all(1, ft.Colors.with_opacity(0.06, ft.Colors.ON_SURFACE)),
            shadow=T.SHADOW_CARD,
        )

    # -- events ------------------------------------------------------------

    def _on_scan(self, _e):
        if self._scanning:
            return
        self._scanning = True

        # Animate progress ring
        self.scan_indicator.value = None
        self.scan_btn.content.gradient = None
        self.scan_btn.content.bgcolor = ft.Colors.SURFACE_CONTAINER_HIGHEST
        self.scan_btn.content.shadow = None
        self.scan_status.value = "正在搜寻周围设备…"
        self.scan_status.color = ft.Colors.ON_SURFACE_VARIANT

        self.app.scan_for_people()
        if self.page:
            self.page.update()

        def _finish():
            time.sleep(4.5)
            self._scanning = False
            self.scan_indicator.value = 0
            self.scan_btn.content.gradient = T.GRADIENT_PRIMARY
            self.scan_btn.content.shadow = T.SHADOW_GLOW
            self.refresh_discovered()
            self.refresh_diagnostics()
        self.app.run_async(_finish)

    def _send_request(self, e, data):
        btn = e.control
        btn.disabled = True
        btn.text = "正在发送..."
        btn.icon = ft.Icons.HOURGLASS_EMPTY_ROUNDED
        if self.page:
            self.page.update()

        name = data.get("name", "")
        ip = data.get("ip", "")
        port = int(data.get("tcp_port", 7779) or 7779)
        user_id = data.get("user_id", "")

        def task():
            ok = self.app.send_friend_request(name, ip, port, user_id)
            if ok:
                btn.text = "已发送"
                btn.icon = None
                btn.disabled = True
                self.scan_status.value = f"已向 {name} 发起好友请求"
                self.scan_status.color = ft.Colors.GREEN_400
            else:
                btn.text = "添加好友"
                btn.icon = ft.Icons.PERSON_ADD_ROUNDED
                btn.disabled = False
                self.scan_status.value = "发送请求失败，请检查网络"
                self.scan_status.color = ft.Colors.RED_400
            self.refresh_discovered()
        self.app.run_async(task)

    def _on_manual(self, _e):
        name_in = ft.TextField(
            label="好友昵称", autofocus=True,
            border_radius=12, border_color=ft.Colors.with_opacity(0.2, ft.Colors.ON_SURFACE)
        )
        ip_in = ft.TextField(
            label="IP 地址", hint_text="例如 172.20.10.x",
            border_radius=12, border_color=ft.Colors.with_opacity(0.2, ft.Colors.ON_SURFACE)
        )
        port_in = ft.TextField(
            label="TCP 端口", value="7779", keyboard_type=ft.KeyboardType.NUMBER,
            border_radius=12, border_color=ft.Colors.with_opacity(0.2, ft.Colors.ON_SURFACE)
        )
        err = ft.Text("", size=T.FS_CAPTION, color=ft.Colors.ERROR)

        def parse():
            name = name_in.value.strip() if name_in.value else ""
            ip = ip_in.value.strip() if ip_in.value else ""
            if not name:
                err.value = "昵称不能为空"
                return None

            # Simple IP validation fallback
            parts = ip.split('.')
            if len(parts) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
                err.value = "IP 地址格式不合法"
                return None

            try:
                port = int((port_in.value or "7779").strip())
                if port < 1024 or port > 65535:
                    raise ValueError
            except ValueError:
                err.value = "端口范围应为 1024-65535"
                return None
            err.value = ""
            return name, ip, port

        def on_probe(_e):
            parsed = parse()
            if not parsed:
                self.page.update()
                return
            name, ip, port = parsed
            dlg.open = False

            def task():
                self.scan_status.value = "正在连接目标主机…"
                self.page.update()
                result = self.app.probe_peer(ip, port, name)
                if result.get("tcp_connected"):
                    msg = f"已建立 TCP 链接：{name}({ip}:{port})"
                elif result.get("udp_probe", {}).get("sent", 0):
                    msg = f"已发送 UDP 探测到 {ip}，等待对端响应"
                else:
                    msg = "无法访问目标设备，请检查 IP/端口/防火墙设置"
                self.scan_status.value = msg
                self.refresh_discovered()
                self.refresh_diagnostics()
            self.app.run_async(task)

        def on_send(_e):
            parsed = parse()
            if not parsed:
                self.page.update()
                return
            name, ip, port = parsed
            dlg.open = False

            def task():
                self.scan_status.value = "正在发送好友申请…"
                self.page.update()
                ok = self.app.send_friend_request(name, ip, port)
                self.scan_status.value = (f"已向 {name}({ip}:{port}) 发送申请" if ok
                                          else "发送失败，请检查网络")
                self.scan_status.color = ft.Colors.GREEN_400 if ok else ft.Colors.RED_400
                self.refresh_discovered()
            self.app.run_async(task)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("手动连接好友", weight=ft.FontWeight.BOLD),
            content=ft.Column(
                [name_in, ip_in, port_in, err],
                spacing=T.SP_SM, tight=True, width=320,
            ),
            actions=[
                ft.TextButton("探测连接", on_click=on_probe),
                ft.ElevatedButton("发送申请", on_click=on_send, bgcolor=ft.Colors.DEEP_PURPLE_500, color=ft.Colors.WHITE),
                ft.TextButton("取消", on_click=lambda _e: self._close_dlg(dlg)),
            ],
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()

    def _close_dlg(self, dlg):
        dlg.open = False
        self.page.update()

    # -- friend request popup ---------------------------------------------

    def show_friend_request(self, profile, is_match):
        sender_name = profile.get("name", "未知用户")
        bio = profile.get("bio", "这个用户很懒，什么都没写")
        tags = profile.get("tags", [])
        sender_ip = profile.get("ip", "0.0.0.0")
        port = int(profile.get("tcp_port", 7779) or 7779)
        match_text = "✨ 完美匹配您的交友偏好" if is_match else "标签不完全匹配，仍可加为好友"

        def on_accept(_e):
            dlg.open = False
            self.app.friend_db.add_friend(
                name=sender_name, ip=sender_ip, port=port,
                tags=tags, bio=bio, category="朋友",
                user_id=profile.get("user_id", ""), status="accepted",
                avatar=self.app.paths.asset_src(profile.get("avatar", "")),
            )
            self.app.friend_db.set_friend_request_status(
                "accepted", user_id=profile.get("user_id", ""),
                name=sender_name, ip=sender_ip, port=port,
            )
            threading.Thread(
                target=self.app.message_service.send_friend_accept,
                args=(sender_name, sender_ip), daemon=True,
            ).start()
            self.app.views["friends"].refresh()
            self.refresh_online()
            self.page.update()

        def on_ignore(_e):
            dlg.open = False
            self.app.friend_db.set_friend_request_status(
                "rejected", user_id=profile.get("user_id", ""),
                name=sender_name, ip=sender_ip, port=port,
            )
            self.page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("收到了好友申请 💬", weight=ft.FontWeight.BOLD),
            content=ft.Column(
                [
                    ft.Row([T.avatar_circle(profile.get("avatar") or sender_name, T.AVATAR_MD), ft.Text(sender_name, size=T.FS_TITLE, weight=ft.FontWeight.BOLD)], spacing=T.SP_SM),
                    ft.Text(f"IP 地址：{sender_ip}:{port}", size=T.FS_CAPTION, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Container(
                        content=ft.Text(match_text, size=T.FS_CAPTION, color=ft.Colors.DEEP_PURPLE_200 if is_match else ft.Colors.ON_SURFACE_VARIANT, weight=ft.FontWeight.BOLD),
                        bgcolor=ft.Colors.with_opacity(0.1, ft.Colors.DEEP_PURPLE) if is_match else ft.Colors.SURFACE_CONTAINER_HIGH,
                        padding=8,
                        border_radius=8,
                    ),
                    ft.Text("标签：" + (", ".join(tags) if tags else "无"), size=T.FS_CAPTION, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Container(
                        content=ft.Text(bio, size=T.FS_BODY, italic=True),
                        padding=T.pad_symmetric(vertical=4),
                    ),
                ],
                spacing=T.SP_SM, tight=True, width=320,
            ),
            actions=[
                ft.OutlinedButton("忽略", on_click=on_ignore),
                ft.ElevatedButton("同意并添加", on_click=on_accept, bgcolor=ft.Colors.DEEP_PURPLE_500, color=ft.Colors.WHITE),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.overlay.append(dlg)
        dlg.open = True
