"""Group chat dialogs and actions for ChatView."""

import flet as ft

from .. import theme as T


class ChatGroupController:
    """Handle group info, creation, and settings dialogs."""

    def __init__(self, owner):
        self.owner = owner
        self.app = owner.app

    @property
    def page(self):
        return self.owner.page

    def show_group_info(self, group_id):
        group = self.app.friend_db.get_group(group_id)
        if not group or not self.page:
            return

        name = group.get("group_name", "")
        members = group.get("members", [])

        members_chips = []
        for member in members:
            is_me = member == self.app.device_name
            chip_color = ft.Colors.DEEP_PURPLE_400 if is_me else ft.Colors.ON_SURFACE_VARIANT
            members_chips.append(
                ft.Container(
                    content=ft.Row(
                        [
                            T.avatar_circle(
                                self.app.get_avatar_for_name(member) if not is_me else member,
                                20,
                            ),
                            ft.Text(
                                member,
                                size=11,
                                color=chip_color,
                                weight=ft.FontWeight.BOLD if is_me else ft.FontWeight.NORMAL,
                            ),
                        ],
                        spacing=4,
                        tight=True,
                    ),
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                    padding=T.pad_symmetric(horizontal=8, vertical=4),
                    border_radius=8,
                )
            )

        def close_dlg(_e):
            dlg.open = False
            self.page.update()
            try:
                self.page.overlay.remove(dlg)
            except Exception:
                pass

        dlg = ft.AlertDialog(
            title=ft.Row(
                [
                    T.avatar_circle("group", 44),
                    ft.Column(
                        [
                            ft.Text(name, size=T.FS_TITLE, weight=ft.FontWeight.BOLD),
                            ft.Text(
                                f"群组 ID: {group_id[:8]}",
                                size=T.FS_CAPTION,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                            ),
                        ],
                        spacing=2,
                    ),
                ],
                spacing=T.SP_SM,
            ),
            content=ft.Column(
                [
                    T.section_title("群成员列表"),
                    ft.Row(members_chips, wrap=True),
                ],
                spacing=T.SP_SM,
                tight=True,
                width=300,
            ),
            actions=[ft.TextButton("关闭", on_click=close_dlg)],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()

    def create_group(self, _e):
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
            elif name in selected_friends:
                selected_friends.remove(name)

        checkboxes = []
        for friend in friends:
            name = friend.get("name", "")
            checkboxes.append(
                ft.Checkbox(
                    label=name,
                    value=False,
                    on_change=lambda e, n=name: on_checkbox_change(e, n),
                )
            )

        def close_dialog(_e):
            dlg.open = False
            if self.page:
                self.page.update()

        def do_create(_e):
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
                ft.Button(
                    "创建",
                    on_click=do_create,
                    bgcolor=ft.Colors.DEEP_PURPLE_500,
                    color=ft.Colors.WHITE,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()

    def show_group_settings(self, group_id):
        group = self.app.friend_db.get_group(group_id)
        if not group or not self.page:
            return

        name = group.get("group_name", "")
        members = group.get("members", [])
        owner = group.get("owner", "")
        only_owner_manage = int(group.get("only_owner_manage", 0) or 0)

        is_owner = self.app.device_name == owner or not owner
        can_manage = not only_owner_manage or is_owner

        group_name_input = ft.TextField(
            value=name,
            hint_text="修改群聊名称...",
            border_radius=8,
            disabled=not can_manage,
        )
        permission_switch = ft.Switch(
            label="仅群主可编辑名称及邀请成员",
            value=bool(only_owner_manage),
            disabled=not is_owner,
            label_position=ft.LabelPosition.RIGHT,
        )

        all_friends = self.app.get_all_friends() or []
        invite_candidates = [friend for friend in all_friends if friend.get("name") not in members]
        selected_invitees = []

        def on_invitee_change(e, member_name):
            if e.control.value:
                if member_name not in selected_invitees:
                    selected_invitees.append(member_name)
            elif member_name in selected_invitees:
                selected_invitees.remove(member_name)

        checkboxes = []
        for candidate in invite_candidates:
            candidate_name = candidate.get("name", "")
            checkboxes.append(
                ft.Checkbox(
                    label=candidate_name,
                    value=False,
                    disabled=not can_manage,
                    on_change=lambda e, cn=candidate_name: on_invitee_change(e, cn),
                )
            )

        def close_dialog(_e):
            dlg.open = False
            self.page.update()

        def do_save(_e):
            new_name = (group_name_input.value or "").strip()
            if not new_name:
                self.app.show_toast("群聊名称不能为空")
                return

            updated_members = list(members)
            for invitee in selected_invitees:
                if invitee not in updated_members:
                    updated_members.append(invitee)

            new_owner = owner if owner else self.app.device_name
            new_only_owner_manage = 1 if permission_switch.value else 0
            self.app.update_group_info(
                group_id,
                new_name,
                updated_members,
                owner=new_owner,
                only_owner_manage=new_only_owner_manage,
            )
            close_dialog(None)
            self.app.show_toast("群信息设置已保存并同步 👥")

            self.owner.current_friend = new_name
            self.owner.refresh_header()

        content_items = [
            ft.Text("群聊名称", size=T.FS_CAPTION, weight=ft.FontWeight.BOLD),
            group_name_input,
            ft.Text(
                f"群主: {owner if owner else self.app.device_name}",
                size=T.FS_CAPTION,
                color=ft.Colors.ON_SURFACE_VARIANT,
            ),
            permission_switch,
        ]

        if not can_manage:
            content_items.append(
                ft.Text(
                    f"🔒 仅群主 {owner} 可管理该群",
                    color=ft.Colors.RED_300,
                    size=T.FS_CAPTION,
                    weight=ft.FontWeight.BOLD,
                )
            )
        else:
            content_items.append(
                ft.Text("邀请好友加入", size=T.FS_CAPTION, weight=ft.FontWeight.BOLD)
                if checkboxes
                else ft.Container()
            )
            if checkboxes:
                content_items.append(ft.Column(checkboxes, scroll=ft.ScrollMode.AUTO, height=120))
            else:
                content_items.append(
                    ft.Text("暂无可邀请的好友", size=T.FS_CAPTION, color=ft.Colors.ON_SURFACE_VARIANT)
                )

        dlg = ft.AlertDialog(
            title=ft.Text("群聊设置 ⚙️", weight=ft.FontWeight.BOLD),
            content=ft.Column(
                content_items,
                spacing=T.SP_SM,
                tight=True,
                width=300,
            ),
            actions=[
                ft.TextButton("取消", on_click=close_dialog),
                ft.Button(
                    "保存",
                    on_click=do_save,
                    bgcolor=ft.Colors.DEEP_PURPLE_500,
                    color=ft.Colors.WHITE,
                    disabled=not can_manage,
                ),
            ]
            if can_manage
            else [ft.TextButton("关闭", on_click=close_dialog)],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()
