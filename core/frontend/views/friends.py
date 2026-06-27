"""Friends view: search, category filter, friend cards, manage dialog."""
import flet as ft

from .. import theme as T

CATEGORIES = ["全部", "同学", "朋友", "自定义"]


class FriendsView:
    def __init__(self, app):
        self.app = app
        self.page = app.page
        self.search = ft.TextField(
            label="搜索好友", 
            prefix_icon=ft.Icons.SEARCH_ROUNDED,
            on_change=self._on_search, 
            border_radius=14,
            border_color=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            content_padding=12,
        )
        self.count = ft.Text("0 位好友", size=T.FS_BODY, weight=ft.FontWeight.BOLD, color=ft.Colors.DEEP_PURPLE_400)
        self._category = "全部"
        self._query = ""
        self.chip_row = ft.Row(
            [
                T.FilterChip(label=c, selected=(c == "全部"),
                              on_select=lambda chip, c=c: self._set_category(c, chip))
                for c in CATEGORIES
            ],
            spacing=T.SP_SM,
            scroll=ft.ScrollMode.AUTO,
        )
        self.list_col = ft.Column(spacing=T.SP_SM, expand=True, scroll=ft.ScrollMode.AUTO)

    def build(self):
        return ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("我的好友", size=T.FS_HEADER, weight=ft.FontWeight.W_800),
                        ft.Row(
                            [
                                ft.IconButton(
                                    icon=ft.Icons.GROUP_ADD_ROUNDED,
                                    icon_color=ft.Colors.DEEP_PURPLE_400,
                                    tooltip="发起群聊",
                                    on_click=self._on_create_group,
                                ),
                                self.count,
                            ],
                            spacing=4,
                        )
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                ),
                self.search,
                ft.Container(
                    content=self.chip_row,
                    padding=T.pad_symmetric(vertical=4),
                ),
                self.list_col,
            ],
            spacing=T.SP_SM, expand=True,
        )

    def on_enter(self):
        self.refresh()

    # -- refresh -----------------------------------------------------------

    def refresh(self):
        friends = self.app.get_all_friends() if self.app.runtime else []
        items = list(friends)
        if self._category != "全部":
            items = [i for i in items if i.get("category", "朋友") == self._category]
        if self._query:
            items = [i for i in items if self._query in i.get("name", "").lower()]

        self.list_col.controls.clear()
        for f in items:
            self.list_col.controls.append(self._friend_card(f))
        if not items:
            self.list_col.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(ft.Icons.PEOPLE_OUTLINE_ROUNDED, size=40, color=ft.Colors.ON_SURFACE_VARIANT, opacity=0.4),
                            ft.Text(
                                "暂无好友\n去「发现」发送好友申请",
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
                    alignment=ft.Alignment.CENTER, 
                    expand=True,
                )
            )
        self.count.value = f"{len(items)} 位好友"
        if self.page:
            self.page.update()

    # -- builders ----------------------------------------------------------

    def _friend_card(self, data):
        name = data.get("name", "未知")
        online = data.get("online", False)
        avatar = data.get("avatar") or name
        tags = data.get("tags") or []
        category = data.get("category") or "朋友"
        unread = self.app.has_unread_chat(name)
        
        endpoint = f"{data.get('ip', '')}:{data.get('port', '')}".strip(":")
        sub = f"IP: {endpoint}" if endpoint else "离线缓存状态"

        # Build list of beautiful tags
        tags_row = ft.Row(spacing=4, wrap=True)
        # Always add the category as the first custom colored tag
        tags_row.controls.append(
            ft.Container(
                content=ft.Text(category, size=10, weight=ft.FontWeight.BOLD, color=ft.Colors.DEEP_PURPLE_200),
                bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.DEEP_PURPLE),
                padding=T.pad_symmetric(horizontal=6, vertical=2),
                border_radius=4,
            )
        )
        # Add interest tags
        for t in tags[:2]:  # Limit to 2 tags to avoid overflow
            tags_row.controls.append(
                ft.Container(
                    content=ft.Text(t, size=10, weight=ft.FontWeight.W_500, color=ft.Colors.ON_SURFACE_VARIANT),
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                    padding=T.pad_symmetric(horizontal=6, vertical=2),
                    border_radius=4,
                )
            )

        status_badge = ft.Container(
            content=ft.Row(
                [
                    ft.Container(width=6, height=6, border_radius=3, bgcolor=ft.Colors.GREEN_400 if online else ft.Colors.ON_SURFACE_VARIANT),
                    ft.Text(
                        "在线" if online else "离线",
                        size=T.FS_CAPTION, 
                        color=ft.Colors.GREEN_400 if online else ft.Colors.ON_SURFACE_VARIANT,
                        weight=ft.FontWeight.BOLD if online else ft.FontWeight.NORMAL,
                    ),
                ],
                spacing=4,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            padding=T.pad_symmetric(horizontal=8, vertical=4),
            bgcolor=ft.Colors.with_opacity(0.1, ft.Colors.GREEN) if online else ft.Colors.with_opacity(0.06, ft.Colors.ON_SURFACE),
            border_radius=99,
        )

        return ft.GestureDetector(
            mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=lambda _e, n=name: self.app.open_chat_with(n),
            content=ft.Container(
                content=ft.Row(
                    [
                        ft.GestureDetector(
                            mouse_cursor=ft.MouseCursor.CLICK,
                            on_tap=lambda _e, n=name: self.app.show_friend_profile(n),
                            content=T.avatar_circle(
                                avatar,
                                T.AVATAR_MD,
                                online=online,
                                unread=unread,
                            ),
                        ),
                        ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Text(name, size=T.FS_TEXT, weight=ft.FontWeight.BOLD),
                                        ft.Container(width=4),
                                        status_badge,
                                    ],
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                ft.Text(sub, size=T.FS_CAPTION, color=ft.Colors.ON_SURFACE_VARIANT, weight=ft.FontWeight.W_500),
                                tags_row,
                            ],
                            spacing=4, expand=True,
                        ),
                        ft.PopupMenuButton(
                            icon=ft.Icons.MORE_VERT_ROUNDED,
                            items=[
                                ft.PopupMenuItem(
                                    content=ft.Text("发起聊天"),
                                    icon=ft.Icons.CHAT_ROUNDED,
                                    on_click=lambda _e, n=name: self.app.open_chat_with(n)
                                ),
                                ft.PopupMenuItem(
                                    content=ft.Text("管理分类"),
                                    icon=ft.Icons.CATEGORY_ROUNDED,
                                    on_click=lambda _e, d=data: self._manage(d)
                                ),
                                ft.PopupMenuItem(),
                                ft.PopupMenuItem(
                                    content=ft.Text("删除好友"),
                                    icon=ft.Icons.DELETE_OUTLINE_ROUNDED,
                                    on_click=lambda _e, n=name: self._confirm_delete(n)
                                ),
                            ],
                        ),
                    ],
                ),
                padding=T.SP_MD,
                border_radius=T.R_MD,
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
                border=T.border_all(1, ft.Colors.with_opacity(0.06, ft.Colors.ON_SURFACE)),
                shadow=T.SHADOW_CARD,
            )
        )

    # -- events ------------------------------------------------------------

    def _on_search(self, e):
        self._query = (e.control.value or "").strip().lower()
        self.refresh()

    def _set_category(self, category, _chip):
        self._category = category
        for c in self.chip_row.controls:
            c.selected = (c.label == category)
        self.refresh()

    def _manage(self, data):
        name = data.get("name", "")
        current = data.get("category", "朋友")
        
        seg = ft.SegmentedButton(
            selected=[current] if current in ["同学", "朋友", "自定义"] else ["朋友"],
            segments=[
                ft.Segment(label=ft.Text("同学", weight=ft.FontWeight.W_600), value="同学"),
                ft.Segment(label=ft.Text("朋友", weight=ft.FontWeight.W_600), value="朋友"),
                ft.Segment(label=ft.Text("自定义", weight=ft.FontWeight.W_600), value="自定义"),
            ],
            allow_multiple_selection=False, 
            allow_empty_selection=False,
        )

        def on_save(_e):
            new_cat = seg.selected[0] if seg.selected else "朋友"
            self.app.set_friend_category(name, new_cat)
            dlg.open = False
            self.page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"修改「{name}」的分类", weight=ft.FontWeight.BOLD),
            content=ft.Column(
                [
                    ft.Text("选择好友的分组类别：", size=T.FS_BODY, color=ft.Colors.ON_SURFACE_VARIANT),
                    seg
                ], 
                spacing=T.SP_SM, tight=True, width=320
            ),
            actions=[
                ft.TextButton("取消", on_click=lambda _e: self._close(dlg)),
                ft.ElevatedButton("保存", on_click=on_save, bgcolor=ft.Colors.DEEP_PURPLE_500, color=ft.Colors.WHITE),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()

    def _confirm_delete(self, name):
        def do_delete(_e):
            dlg.open = False
            self.app.delete_friend(name)
            self.page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("确认删除好友 ⚠️", weight=ft.FontWeight.BOLD),
            content=ft.Text(f"确定删除好友「{name}」吗？\n删除后连接将断开，但聊天历史记录仍保留。"),
            actions=[
                ft.TextButton("取消", on_click=lambda _e: self._close(dlg)),
                ft.ElevatedButton(
                    "删除好友", 
                    on_click=do_delete,
                    bgcolor=ft.Colors.RED_600, 
                    color=ft.Colors.WHITE
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()

    def _close(self, dlg):
        dlg.open = False
        self.page.update()

    def _on_create_group(self, _e):
        friends = self.app.get_all_friends() or []
        if not friends:
            self.app.show_toast("暂无好友，无法发起群聊哦~")
            return

        selected_friends = []
        
        group_name_input = ft.TextField(
            hint_text="输入群聊名称...",
            border_radius=8,
            autofocus=True,
        )

        def on_checkbox_change(e, name):
            if e.control.value:
                if name not in selected_friends:
                    selected_friends.append(name)
            else:
                if name in selected_friends:
                    selected_friends.remove(name)

        checkboxes = []
        for f in friends:
            name = f.get("name", "")
            checkboxes.append(
                ft.Checkbox(
                    label=name,
                    value=False,
                    on_change=lambda e, n=name: on_checkbox_change(e, n)
                )
            )

        def close_dialog(e):
            dlg.open = False
            if self.page:
                self.page.update()

        def do_create(e):
            group_name = (group_name_input.value or "").strip()
            if not group_name:
                self.app.show_toast("请输入群聊名称")
                return
            if not selected_friends:
                self.app.show_toast("请选择群成员")
                return
            
            group_id = self.app.create_group(group_name, selected_friends)
            close_dialog(None)
            self.app.show_toast(f"群聊「{group_name}」创建成功！")
            self.app.open_chat_with(group_name, is_group=True, group_id=group_id)

        dlg = ft.AlertDialog(
            title=ft.Text("发起群聊 👥", weight=ft.FontWeight.BOLD),
            content=ft.Column(
                [
                    ft.Text("群聊名称", size=T.FS_CAPTION, weight=ft.FontWeight.BOLD),
                    group_name_input,
                    ft.Text("选择群成员", size=T.FS_CAPTION, weight=ft.FontWeight.BOLD),
                    ft.Column(checkboxes, scroll=ft.ScrollMode.AUTO, height=200),
                ],
                spacing=T.SP_SM,
                tight=True,
                width=300,
            ),
            actions=[
                ft.TextButton("取消", on_click=close_dialog),
                ft.ElevatedButton("创建", on_click=do_create, bgcolor=ft.Colors.DEEP_PURPLE_500, color=ft.Colors.WHITE),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()
