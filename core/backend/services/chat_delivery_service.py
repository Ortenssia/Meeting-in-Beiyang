"""Direct chat-message delivery and receive handling for MessageService."""

import json
import logging
import time
import uuid
from typing import Any, Dict

from core.backend.shared.protocol import Protocol


logger = logging.getLogger(__name__)


class ChatDeliveryService:
    """Send and handle CHAT_MESSAGE packets."""

    def __init__(self, owner):
        self.owner = owner

    def send_message(self, to_name: str, content: str, msg_id: str = "") -> bool:
        owner = self.owner
        my_profile = owner.friend_db.get_my_profile()
        my_name = my_profile.get("name", "Unknown")
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        msg_id = msg_id or str(uuid.uuid4())

        chat_msg = {
            "type": owner.CHAT_MESSAGE,
            "msg_id": msg_id,
            "from_name": my_name,
            "to_name": to_name,
            "content": content,
            "timestamp": timestamp,
        }
        owner.friend_db.save_chat_message(
            from_name=my_name,
            to_name=to_name,
            content=content,
            timestamp=timestamp,
            msg_id=msg_id,
        )

        if not owner.connection_manager.is_friend_online(to_name):
            record = owner.friend_db.get_friend(to_name) if owner.friend_db else None
            if record and record.get("ip"):
                ip = record["ip"]
                port = int(record.get("port") or Protocol.DEFAULT_TCP_PORT)
                logger.info("[MessageService] 尝试主动重连以发送消息 -> %s (%s:%s)", to_name, ip, port)
                owner.connection_manager.connect_to_friend(ip, port, to_name)

        if owner.connection_manager.is_friend_online(to_name):
            success = owner._send_data_to_friend(to_name, chat_msg)
            if success:
                logger.info("[MessageService] 直连发送 -> %s: %s", to_name, content[:50])
                return True
            logger.warning("[MessageService] 直连发送失败 -> %s，降级为中继", to_name)

        owner.friend_db.add_pending_message(
            to_name=to_name,
            data_json=json.dumps(chat_msg, ensure_ascii=False),
        )
        relay_msg = {
            "type": owner.RELAY_MESSAGE,
            "relay_hops": 0,
            "original_message": chat_msg,
        }
        relayed = owner._flood_relay(relay_msg, exclude_name=to_name)
        logger.info(
            "[MessageService] 消息已缓存 + 中继给 %s 个在线好友 (目标 %s 离线)",
            relayed,
            to_name,
        )
        return True

    def handle_chat_message(self, from_ip: str, data: Dict[str, Any]):
        owner = self.owner
        my_profile = owner.friend_db.get_my_profile()
        my_name = my_profile.get("name", "")
        to_name = data.get("to_name", "")
        from_name = data.get("from_name", "")
        content = data.get("content", "")
        timestamp = data.get("timestamp", "")
        msg_id = data.get("msg_id", "")

        if msg_id and owner.friend_db.check_msg_id(msg_id):
            logger.debug("[MessageService] 重复消息 %s，忽略", msg_id)
            return
        if msg_id:
            owner.friend_db.record_msg_id(msg_id)

        if to_name == my_name:
            owner.friend_db.save_chat_message(
                from_name=from_name,
                to_name=my_name,
                content=content,
                timestamp=timestamp,
                msg_id=msg_id,
            )
            logger.info("[MessageService] 收到消息 %s: %s", from_name, content[:50])
            if owner.on_message_received:
                try:
                    owner.on_message_received(from_name, content, timestamp, msg_id)
                except Exception as exc:
                    logger.error("[MessageService] on_message_received 回调异常: %s", exc)
            return

        logger.info("[MessageService] 中继消息 %s -> %s（经过本机）", from_name, to_name)
        if owner.connection_manager.is_friend_online(to_name):
            owner._relay_chat_to_others(data, exclude_ip=from_ip, exclude_name=from_name)
        else:
            owner.friend_db.add_pending_message(
                to_name=to_name,
                data_json=json.dumps(data, ensure_ascii=False),
            )
            owner._relay_chat_to_others(data, exclude_ip=from_ip, exclude_name=from_name)
