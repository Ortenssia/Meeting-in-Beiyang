"""Thin service facade methods for BeiyangApp."""

import time
from typing import Any, Dict, List

from core.backend.shared.protocol import Protocol


class AppServiceFacade:
    """Group service/db forwarding methods that views call through BeiyangApp."""

    def __init__(self, app):
        self.app = app

    def has_friend_profile_update(self, name):
        app = self.app
        return bool(app.message_service and app.message_service.has_pending_profile_update(name))

    def get_profile_update_mode(self) -> str:
        app = self.app
        if app.friend_db:
            mode = app.friend_db.get_app_setting("profile_update_mode", "auto")
            return mode if mode in ("auto", "manual") else "auto"
        return "auto"

    def request_friend_profile_update(self, name, silent=False):
        app = self.app
        if app.message_service:
            ok = app.message_service.request_friend_profile(name)
            if not silent:
                app.show_toast("已请求更新资料" if ok else "请求更新失败，对方可能不在线")
            return ok
        return False

    def scan_for_people(self):
        if self.app.runtime:
            self.app.runtime.scan_for_people()

    def probe_peer(self, ip, port=Protocol.DEFAULT_TCP_PORT, display_name=""):
        if self.app.runtime:
            return self.app.runtime.probe_peer(ip, port, display_name)
        return {"ip": ip, "tcp_port": port, "tcp_connected": False}

    def get_discovered_people(self):
        return self.app.runtime.get_discovered_people() if self.app.runtime else []

    def get_network_diagnostics(self):
        return self.app.runtime.get_network_diagnostics() if self.app.runtime else {}

    def send_friend_request(self, name, ip, port=Protocol.DEFAULT_TCP_PORT, user_id="", candidate_ips=None):
        app = self.app
        if app.is_existing_friend(name, ip, port, user_id):
            return False
        if app.message_service:
            return app.message_service.send_friend_request(name, ip, port, user_id, candidate_ips)
        return False

    def is_existing_friend(self, name="", ip="", port=0, user_id=""):
        app = self.app
        if not app.friend_db:
            return False
        return app.friend_db.get_relationship_status(
            user_id=user_id,
            name=name,
            ip=ip,
            port=port,
        ) in ("pending_sent", "pending_received", "accepted")

    def get_relationship_status(self, name="", ip="", port=0, user_id=""):
        app = self.app
        if not app.friend_db:
            return "none"
        return app.friend_db.get_relationship_status(
            user_id=user_id,
            name=name,
            ip=ip,
            port=port,
        )

    def get_all_friends(self):
        return self.app.runtime.get_all_friends() if self.app.runtime else []

    def get_online_friends(self):
        return self.app.runtime.get_online_friends() if self.app.runtime else []

    def delete_friend(self, name):
        app = self.app
        friend = app.friend_db.get_friend(name)
        if not friend:
            return
        ip = friend.get("ip")
        port = friend.get("port")
        if app.message_service:
            try:
                app.message_service.send_friend_delete(name)
            except Exception:
                pass
            time.sleep(0.2)
        if ip and app.connection_manager:
            endpoint = f"{ip}:{port}" if port else ip
            app.connection_manager.disconnect_friend(endpoint)
        app.friend_db.remove_friend(name)
        app._on_friends()
        app._on_online()

    def set_friend_category(self, name, category):
        app = self.app
        if app.friend_db:
            app.friend_db.set_friend_category(name, category)
            app._on_friends()

    def get_system_notifications(self):
        return self.app.friend_db.get_system_notifications() if self.app.friend_db else []

    def clear_system_notifications(self):
        app = self.app
        if app.friend_db:
            app.friend_db.clear_system_notifications()
            app._on_notifications_changed()

    def mark_all_notifications_read(self):
        app = self.app
        if app.friend_db:
            app.friend_db.mark_all_notifications_read()
            app._on_notifications_changed()

    def mark_notification_read(self, notif_id):
        app = self.app
        if app.friend_db:
            app.friend_db.mark_notification_read(notif_id)
            app._on_notifications_changed()

    def send_chat_message(self, friend_name, text, msg_id=""):
        if self.app.message_service:
            return self.app.message_service.send_message(friend_name, text, msg_id=msg_id)
        return False

    def send_file_to_friend(self, friend_name, file_path, file_id=""):
        if self.app.message_service:
            return self.app.message_service.send_file(friend_name, file_path, file_id=file_id)
        return False

    def pause_file_transfer(self, file_id):
        return bool(self.app.message_service and self.app.message_service.pause_file_transfer(file_id))

    def resume_file_transfer(self, file_id):
        return bool(self.app.message_service and self.app.message_service.resume_file_transfer(file_id))

    def cancel_file_transfer(self, file_id):
        if self.app.message_service:
            self.app.message_service.cancel_file_transfer(file_id)

    def get_chat_history(self, friend_name):
        if self.app.friend_db:
            return self.app.friend_db.get_chat_history(friend_name, limit=100)
        return []

    def clear_chat_history(self, friend_name):
        app = self.app
        if app.friend_db:
            app.friend_db.clear_chat_history(friend_name)
            app.views["chat"].reload_current()

    def delete_chat_message(self, msg_id, *, is_group=False):
        app = self.app
        if not app.friend_db or not msg_id:
            return False
        if is_group:
            return app.friend_db.delete_group_chat_message(msg_id)
        return app.friend_db.delete_chat_message(msg_id)

    def get_chat_list(self):
        app = self.app
        try:
            chat_list = app.runtime.get_chat_list() if app.runtime else []
            for entry in chat_list:
                name = entry.get("name", "")
                if app.has_unread_chat(name):
                    entry["unread"] = max(int(entry.get("unread", 0) or 0), 1)
            return chat_list
        except Exception as exc:
            print(f"获取聊天列表失败: {exc}")
            return []

    def get_runtime_health(self):
        return self.app.runtime.get_health() if self.app.runtime else {}

    def clear_pending_messages(self, friend_name):
        if self.app.friend_db:
            self.app.friend_db.clear_pending_messages(friend_name)

    def get_pending_message_count(self, for_friend=None):
        if self.app.social_service:
            return self.app.social_service.get_pending_message_count(for_friend or "")
        return 0

    def create_group(self, group_name: str, members: List[str]) -> str:
        if self.app.message_service:
            return self.app.message_service.create_group(group_name, members)
        return ""

    def update_group_info(
        self,
        group_id: str,
        group_name: str,
        members: List[str],
        owner: str = "",
        only_owner_manage: int = 0,
    ):
        app = self.app
        if app.message_service and app.friend_db:
            app.friend_db.save_group(
                group_id,
                group_name,
                members,
                owner=owner,
                only_owner_manage=only_owner_manage,
            )
            payload = {
                "type": app.message_service.GROUP_CREATE,
                "group_id": group_id,
                "group_name": group_name,
                "members": members,
                "owner": owner,
                "only_owner_manage": only_owner_manage,
            }
            for member in members:
                if member != app.device_name:
                    app.message_service._send_data_to_friend(member, payload)

    def send_group_chat_message(self, group_id: str, content: str, msg_id: str = "") -> bool:
        if self.app.message_service:
            return self.app.message_service.send_group_chat_message(group_id, content, msg_id=msg_id)
        return False

    def get_group_chat_history(self, group_id: str) -> List[Dict[str, Any]]:
        if self.app.friend_db:
            return self.app.friend_db.get_group_chat_history(group_id, limit=100)
        return []

    def get_all_groups(self) -> List[Dict[str, Any]]:
        if self.app.friend_db:
            return self.app.friend_db.get_all_groups()
        return []

    def publish_moment(self, content: str, media_path: str = "") -> bool:
        if self.app.message_service:
            return self.app.message_service.publish_moment(content, media_path)
        return False

    def get_moments(self) -> List[Dict[str, Any]]:
        if self.app.friend_db:
            return self.app.friend_db.get_moments(limit=50)
        return []

    def delete_moment(self, post_id: str) -> bool:
        app = self.app
        if app.message_service:
            return app.message_service.publish_moment_delete(post_id)
        if app.friend_db:
            ok = app.friend_db.delete_moment(post_id)
            if ok:
                app._on_moments_changed()
            return ok
        return False

    def get_moment_comments(self, post_id: str) -> List[Dict[str, Any]]:
        if self.app.friend_db:
            return self.app.friend_db.get_moment_comments(post_id)
        return []

    def delete_moment_comment(self, comment_id: str) -> bool:
        app = self.app
        if app.friend_db:
            ok = app.friend_db.delete_moment_comment(comment_id)
            if ok:
                app._on_moments_changed()
            return ok
        return False

    def publish_moment_comment(self, post_id: str, content: str) -> bool:
        if self.app.message_service:
            return self.app.message_service.publish_moment_comment(post_id, content)
        return False

    def sync_moments(self):
        app = self.app
        if app.message_service and app.connection_manager:
            for friend in app.connection_manager.get_online_friends():
                app.message_service.sync_moments_with_friend(friend["name"])
