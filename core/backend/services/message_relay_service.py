"""Heartbeat and flood-relay helpers for MessageService."""

import json
import logging
import threading
import time
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)


class MessageRelayService:
    """Manage heartbeat fanout and RELAY_MESSAGE flood routing."""

    def __init__(self, owner):
        self.owner = owner

    def start_heartbeat(self):
        owner = self.owner
        if not owner._running:
            return

        self.send_heartbeat_to_all()
        owner._heartbeat_timer = threading.Timer(owner.HEARTBEAT_INTERVAL, self.start_heartbeat)
        owner._heartbeat_timer.daemon = True
        owner._heartbeat_timer.start()

    def send_heartbeat_to_all(self):
        owner = self.owner
        my_profile = owner.friend_db.get_my_profile()
        heartbeat_msg = {
            "type": owner.HEARTBEAT,
            "name": my_profile.get("name", "Unknown"),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "avatar": owner._shared_avatar_reference(my_profile.get("avatar", "")),
            "user_id": my_profile.get("user_id", ""),
        }

        for friend in owner.connection_manager.get_online_friends():
            friend_name = self.online_friend_name(friend)
            try:
                owner._send_data_to_friend(friend_name, heartbeat_msg)
            except Exception as exc:
                logger.debug("[MessageService] 心跳发送失败 -> %s: %s", friend_name, exc)

    def handle_relay_message(self, from_ip: str, data: Dict[str, Any]):
        owner = self.owner
        original_message = data.get("original_message", {})
        relay_hops = data.get("relay_hops", 0)
        msg_id = original_message.get("msg_id", data.get("msg_id", ""))

        with owner._relay_id_lock:
            if msg_id in owner._processed_relay_ids:
                logger.debug("[MessageService] 重复中继 %s，忽略", msg_id)
                return
            owner._processed_relay_ids.add(msg_id)
            if len(owner._processed_relay_ids) > owner._MAX_RELAY_CACHE:
                excess = len(owner._processed_relay_ids) - owner._MAX_RELAY_CACHE
                for _ in range(excess):
                    owner._processed_relay_ids.pop()

        if relay_hops >= owner.MAX_RELAY_HOPS:
            logger.info("[MessageService] 中继跳数超限 (%s)，丢弃 %s", relay_hops, msg_id)
            return

        my_profile = owner.friend_db.get_my_profile()
        my_name = my_profile.get("name", "")
        to_name = original_message.get("to_name", "")

        if to_name == my_name:
            owner._handle_chat_message(from_ip, original_message)
            return

        forwarded_relay = {
            "type": owner.RELAY_MESSAGE,
            "relay_hops": relay_hops + 1,
            "original_message": original_message,
        }
        if owner.connection_manager.is_friend_online(to_name):
            self.flood_relay(
                forwarded_relay,
                exclude_ip=from_ip,
                exclude_name=original_message.get("from_name", ""),
            )
        else:
            owner.friend_db.add_pending_message(
                to_name=to_name,
                data_json=json.dumps(forwarded_relay, ensure_ascii=False),
            )
            self.flood_relay(
                forwarded_relay,
                exclude_ip=from_ip,
                exclude_name=original_message.get("from_name", ""),
            )

    def online_friend_name(self, friend: Any) -> str:
        if isinstance(friend, dict):
            return friend.get("name", "")
        return str(friend or "")

    def online_friend_ip(self, friend: Any) -> str:
        owner = self.owner
        if isinstance(friend, dict):
            return friend.get("ip", "")
        record = owner.friend_db.get_friend(str(friend or "")) if owner.friend_db else None
        return record.get("ip", "") if record else ""

    def flood_relay(
        self,
        relay_msg: Dict[str, Any],
        exclude_name: str = "",
        exclude_ip: str = "",
    ) -> int:
        owner = self.owner
        count = 0
        for friend in owner.connection_manager.get_online_friends():
            friend_name = self.online_friend_name(friend)
            if friend_name == exclude_name:
                continue
            friend_record = owner.friend_db.get_friend(friend_name)
            if friend_record and exclude_ip and friend_record.get("ip", "") == exclude_ip:
                continue
            if owner._send_data_to_friend(friend_name, relay_msg):
                count += 1
        return count

    def relay_chat_to_others(
        self,
        chat_msg: Dict[str, Any],
        exclude_ip: str = "",
        exclude_name: str = "",
    ) -> int:
        relay_msg = {
            "type": self.owner.RELAY_MESSAGE,
            "relay_hops": 1,
            "original_message": chat_msg,
        }
        return self.flood_relay(
            relay_msg,
            exclude_name=exclude_name,
            exclude_ip=exclude_ip,
        )
