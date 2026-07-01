"""Offline pending-message replay for MessageService."""

import logging


logger = logging.getLogger(__name__)


class PendingMessageFlusher:
    """Flush locally cached messages when a friend comes online."""

    def __init__(self, owner):
        self.owner = owner

    def flush_pending_messages(self, friend_name: str):
        owner = self.owner
        pending = owner.friend_db.get_pending_messages(friend_name)
        if not pending:
            return

        sent_count = 0
        for record in pending:
            try:
                data = {
                    "type": owner.CHAT_MESSAGE,
                    "msg_id": record.get("msg_id", ""),
                    "from_name": record.get("from_name", ""),
                    "to_name": record.get("to_name", ""),
                    "content": record.get("content", ""),
                    "timestamp": record.get("timestamp", ""),
                }
                if owner._send_data_to_friend(friend_name, data):
                    sent_count += 1
            except Exception as exc:
                logger.error("[MessageService] 发送 pending 消息失败: %s", exc)

        owner.friend_db.clear_pending_messages(friend_name)
        logger.info(
            "[MessageService] 已向 %s 补发 %s/%s 条离线消息",
            friend_name,
            sent_count,
            len(pending),
        )
