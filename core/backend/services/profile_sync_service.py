"""Profile sync notice/request/response handling for MessageService."""

import logging
import os
import time
from typing import Any, Dict

from core.config import get_app_paths
from core.backend.shared.protocol import Protocol


logger = logging.getLogger(__name__)


class ProfileSyncService:
    """Coordinate friend profile version notices and profile pull sync."""

    def __init__(self, owner):
        self.owner = owner

    @staticmethod
    def profile_update_key(name: str = "", user_id: str = "") -> str:
        return user_id or name or "unknown"

    def my_profile_version(self) -> str:
        owner = self.owner
        version = owner.friend_db.get_app_setting("my_profile_updated_at", "")
        if not version:
            version = str(time.time())
            owner.friend_db.set_app_setting("my_profile_updated_at", version)
        return version

    def broadcast_profile_update_notice(self) -> int:
        owner = self.owner
        sent = 0
        for friend in owner.connection_manager.get_online_friends():
            friend_name = owner._online_friend_name(friend)
            if friend_name and self.send_profile_update_notice(friend_name):
                sent += 1
        return sent

    def send_profile_update_notice(self, friend_name: str) -> bool:
        owner = self.owner
        profile = owner.friend_db.get_my_profile()
        payload = {
            "type": owner.PROFILE_UPDATE_NOTICE,
            "from_name": profile.get("name", ""),
            "user_id": profile.get("user_id", ""),
            "version": self.my_profile_version(),
        }
        return owner._send_data_to_friend(friend_name, payload)

    def has_pending_profile_update(self, friend_name: str) -> bool:
        owner = self.owner
        friend = owner.friend_db.get_friend(friend_name) or {}
        friend_uid = friend.get("user_id", "")
        for key in (
            [self.profile_update_key(friend.get("name", friend_name), friend_uid)]
            + ([friend_name] if friend_name else [])
            + ([friend_uid] if friend_uid and friend_uid != friend_name else [])
        ):
            pending = owner.friend_db.get_app_setting(f"profile_pending:{key}", "")
            synced = owner.friend_db.get_app_setting(f"profile_synced:{key}", "")
            if pending and pending != synced:
                return True
        return False

    def request_friend_profile(self, friend_name: str) -> bool:
        owner = self.owner
        friend = owner.friend_db.get_friend(friend_name) or {}
        return owner._send_data_to_friend(
            friend_name,
            {
                "type": owner.PROFILE_SYNC_REQ,
                "from_name": owner.friend_db.get_my_profile().get("name", ""),
                "target_user_id": friend.get("user_id", ""),
            },
        )

    def handle_profile_update_notice(self, from_ip: str, data: Dict[str, Any]):
        owner = self.owner
        name = data.get("from_name", "") or owner._get_friend_name_by_ip(from_ip)
        user_id = data.get("user_id", "")
        version = str(data.get("version", "") or "")
        if not name or not version:
            return
        key = self.profile_update_key(name, user_id)
        synced = owner.friend_db.get_app_setting(f"profile_synced:{key}", "")
        if version != synced:
            owner.friend_db.set_app_setting(f"profile_pending:{key}", version)
            if user_id and name and user_id != name:
                owner.friend_db.set_app_setting(f"profile_pending:{name}", version)
                owner.friend_db.set_app_setting(f"profile_pending:{user_id}", version)
            if owner.on_friend_profile_update_available:
                owner.on_friend_profile_update_available(name)

    def handle_profile_sync_req(self, from_ip: str, data: Dict[str, Any]):
        owner = self.owner
        profile = dict(owner.friend_db.get_my_profile() or {})
        requester = owner._get_friend_name_by_ip(from_ip) or data.get("from_name", "")
        payload = {
            "type": owner.PROFILE_SYNC_RESP,
            "profile": {
                "user_id": profile.get("user_id", ""),
                "name": profile.get("name", ""),
                "tags": profile.get("tags", []),
                "bio": profile.get("bio", ""),
                "background": profile.get("background", ""),
                "card_bg": profile.get("card_bg", ""),
            },
            "version": self.my_profile_version(),
        }
        if requester:
            owner._send_data_to_friend_with_fallback(requester, payload, from_ip)
            self.send_avatar_to_friend(requester)
            self.send_card_bg_to_friend(requester)

    def handle_profile_sync_resp(self, from_ip: str, data: Dict[str, Any]):
        owner = self.owner
        profile = dict(data.get("profile") or {})
        name = profile.get("name", "") or owner._get_friend_name_by_ip(from_ip)
        if not name:
            return
        friend = owner.friend_db.get_friend(name)
        if not friend:
            logger.debug("[MessageService] 忽略未添加好友 %s 的资料同步响应", name)
            return
        owner.friend_db.add_friend(
            name=name,
            ip=friend.get("ip", from_ip) or from_ip,
            port=int(friend.get("port", Protocol.DEFAULT_TCP_PORT) or Protocol.DEFAULT_TCP_PORT),
            tags=profile.get("tags", []),
            bio=profile.get("bio", ""),
            category=friend.get("category", "朋友"),
            user_id=profile.get("user_id", friend.get("user_id", "")),
            status=friend.get("status", "accepted"),
            avatar=friend.get("avatar", ""),
            background=profile.get("background", friend.get("background", "")),
            card_bg=profile.get("card_bg", friend.get("card_bg", "")),
        )
        user_id = profile.get("user_id", "")
        key = self.profile_update_key(name, user_id)
        version = str(data.get("version", "") or "")
        if version:
            owner.friend_db.set_app_setting(f"profile_synced:{key}", version)
            owner.friend_db.set_app_setting(f"profile_pending:{key}", version)
            if user_id and name and user_id != name:
                owner.friend_db.set_app_setting(f"profile_synced:{name}", version)
                owner.friend_db.set_app_setting(f"profile_pending:{name}", version)
                owner.friend_db.set_app_setting(f"profile_synced:{user_id}", version)
                owner.friend_db.set_app_setting(f"profile_pending:{user_id}", version)
        if owner.on_friend_profile_updated:
            owner.on_friend_profile_updated(name)

    def shared_avatar_reference(self, avatar: str) -> str:
        value = (avatar or "").strip()
        if not value or os.path.isabs(value):
            return ""
        if value.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")):
            return get_app_paths().asset_src(value)
        return ""

    def send_avatar_to_friend(self, friend_name: str) -> bool:
        owner = self.owner
        profile = owner.friend_db.get_my_profile()
        avatar_path = (profile.get("avatar") or "").strip()
        if avatar_path and not os.path.isabs(avatar_path):
            candidate = get_app_paths().assets_dir / avatar_path.replace("\\", "/")
            if candidate.is_file():
                avatar_path = str(candidate)
        if not avatar_path or not os.path.isfile(avatar_path):
            return False
        if not avatar_path.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")):
            return False
        return owner.send_file(
            friend_name,
            avatar_path,
            purpose="avatar",
            avatar_owner=profile.get("name", ""),
            avatar_user_id=profile.get("user_id", ""),
            require_online=False,
        )

    def send_card_bg_to_friend(self, friend_name: str) -> bool:
        owner = self.owner
        profile = owner.friend_db.get_my_profile()
        card_bg_path = (profile.get("card_bg") or "").strip()
        if card_bg_path and not os.path.isabs(card_bg_path):
            candidate = get_app_paths().assets_dir / card_bg_path.replace("\\", "/")
            if candidate.is_file():
                card_bg_path = str(candidate)
        if not card_bg_path or not os.path.isfile(card_bg_path):
            return False
        if not card_bg_path.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")):
            return False
        return owner.send_file(
            friend_name,
            card_bg_path,
            purpose="card_bg",
            avatar_owner=profile.get("name", ""),
            avatar_user_id=profile.get("user_id", ""),
            require_online=False,
        )

    def broadcast_avatar_update(self) -> int:
        owner = self.owner
        sent = 0
        my_name = owner.friend_db.get_my_profile().get("name", "")
        for friend in owner.connection_manager.get_online_friends():
            friend_name = owner._online_friend_name(friend)
            if not friend_name or friend_name == my_name:
                continue
            if self.send_avatar_to_friend(friend_name):
                sent += 1
        return sent
