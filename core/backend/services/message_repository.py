"""SQLite repository for direct chat and pending relay messages."""

import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MessageRepository:
    """Persistence operations for pending messages and direct chat history."""

    def __init__(self, owner):
        self.owner = owner

    @property
    def conn(self):
        return self.owner.conn

    @property
    def _lock(self):
        return self.owner._lock

    def add_pending_message(self, *args, **kwargs) -> bool:
        if "data_json" in kwargs:
            to_name = kwargs["to_name"]
            data_json = kwargs["data_json"]
            try:
                msg = json.loads(data_json)
                msg_id = msg.get("msg_id", "")
                from_name = msg.get("from_name", "")
                content = msg.get("content", "")
                timestamp = msg.get("timestamp", "")
                from_ip = ""
                relay_path = []
                if msg.get("type") == "RELAY_MESSAGE":
                    original = msg.get("original_message", msg.get("original_msg", {}))
                    msg_id = original.get("msg_id", msg_id)
                    from_name = original.get("from_name", from_name)
                    content = original.get("content", content)
                    timestamp = original.get("timestamp", timestamp)
                    relay_path = msg.get("relay_path", [])
            except Exception:
                return False
        elif len(args) >= 2 and isinstance(args[1], str) and (
            args[1].startswith("{") or "type" in args[1]
        ):
            to_name = args[0]
            try:
                msg = json.loads(args[1])
                msg_id = msg.get("msg_id", "")
                from_name = msg.get("from_name", "")
                content = msg.get("content", "")
                timestamp = msg.get("timestamp", "")
                from_ip = ""
                relay_path = []
            except Exception:
                return False
        else:
            msg_id = kwargs.get("msg_id") or (args[0] if len(args) > 0 else "")
            from_name = kwargs.get("from_name") or (args[1] if len(args) > 1 else "")
            from_ip = kwargs.get("from_ip") or (args[2] if len(args) > 2 else "")
            to_name = kwargs.get("to_name") or (args[3] if len(args) > 3 else "")
            content = kwargs.get("content") or (args[4] if len(args) > 4 else "")
            timestamp = kwargs.get("timestamp") or (args[5] if len(args) > 5 else "")
            relay_path = kwargs.get("relay_path") or (args[6] if len(args) > 6 else [])

        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO pending_messages
                    (msg_id, from_name, from_ip, to_name, content,
                     timestamp, relay_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        msg_id,
                        from_name,
                        from_ip,
                        to_name,
                        content,
                        timestamp,
                        json.dumps(relay_path or [], ensure_ascii=False),
                    ),
                )
                self.conn.commit()
            return True
        except Exception as exc:
            logger.error("添加待转发消息失败 [%s]: %s", msg_id, exc)
            return False

    def get_pending_messages_for(self, name: str) -> List[Dict[str, Any]]:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT * FROM pending_messages
                WHERE to_name = ?
                ORDER BY timestamp ASC
                """,
                (name,),
            )

            results = []
            for row in cursor.fetchall():
                results.append({
                    "msg_id": row["msg_id"],
                    "from_name": row["from_name"],
                    "from_ip": row["from_ip"],
                    "to_name": row["to_name"],
                    "content": row["content"],
                    "timestamp": row["timestamp"],
                    "relay_path": json.loads(row["relay_path"]),
                })
            return results
        except Exception as exc:
            logger.error("获取待转发消息失败 [%s]: %s", name, exc)
            return []

    def remove_pending_message(self, msg_id: str) -> bool:
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute("DELETE FROM pending_messages WHERE msg_id = ?", (msg_id,))
                self.conn.commit()
            return True
        except Exception as exc:
            logger.error("删除待转发消息失败 [%s]: %s", msg_id, exc)
            return False

    def clear_pending_messages(self, name: Optional[str] = None) -> bool:
        try:
            with self._lock:
                cursor = self.conn.cursor()
                if name:
                    cursor.execute("DELETE FROM pending_messages WHERE to_name = ?", (name,))
                else:
                    cursor.execute("DELETE FROM pending_messages")
                self.conn.commit()
            return True
        except Exception as exc:
            logger.error("清除待转发消息失败: %s", exc)
            return False

    def add_chat_message(
        self,
        friend_name: str,
        friend_ip: str,
        direction: str,
        content: str,
        timestamp: str,
        msg_id: str,
    ) -> bool:
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO chat_history
                    (friend_name, friend_ip, direction, content,
                     timestamp, msg_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (friend_name, friend_ip, direction, content, timestamp, msg_id),
                )
                self.conn.commit()
            return True
        except Exception as exc:
            logger.error("添加聊天记录失败: %s", exc)
            return False

    def get_chat_history(
        self,
        friend_name: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT * FROM chat_history
                WHERE friend_name = ?
                ORDER BY timestamp ASC
                LIMIT ?
                """,
                (friend_name, limit),
            )

            results = []
            for row in cursor.fetchall():
                results.append({
                    "id": row["id"],
                    "friend_name": row["friend_name"],
                    "friend_ip": row["friend_ip"],
                    "direction": row["direction"],
                    "content": row["content"],
                    "timestamp": row["timestamp"],
                    "msg_id": row["msg_id"],
                })
            return results
        except Exception as exc:
            logger.error("获取聊天记录失败 [%s]: %s", friend_name, exc)
            return []

    def clear_chat_history(self, friend_name: str) -> bool:
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute("DELETE FROM chat_history WHERE friend_name = ?", (friend_name,))
                self.conn.commit()
            return True
        except Exception as exc:
            logger.error("清空聊天记录失败 [%s]: %s", friend_name, exc)
            return False

    def delete_chat_message(self, msg_id: str) -> bool:
        if not msg_id:
            return False
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute("DELETE FROM chat_history WHERE msg_id = ?", (msg_id,))
                self.conn.commit()
                return cursor.rowcount > 0
        except Exception as exc:
            logger.error("删除聊天记录失败 [%s]: %s", msg_id, exc)
            return False

    def get_chat_message_content(self, msg_id: str) -> Optional[str]:
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute("SELECT content FROM chat_history WHERE msg_id = ?", (msg_id,))
                row = cursor.fetchone()
                return row[0] if row else None
        except Exception:
            return None

    def update_chat_message_content(self, msg_id: str, new_content: str) -> bool:
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute(
                    """
                    UPDATE chat_history
                    SET content = ?
                    WHERE msg_id = ?
                    """,
                    (new_content, msg_id),
                )
                self.conn.commit()
            return True
        except Exception as exc:
            logger.error("更新聊天记录失败: %s", exc)
            return False

    def delete_group_chat_message(self, msg_id: str) -> bool:
        if not msg_id:
            return False
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute("DELETE FROM group_chat_history WHERE msg_id = ?", (msg_id,))
                self.conn.commit()
                return cursor.rowcount > 0
        except Exception as exc:
            logger.error("删除群聊记录失败 [%s]: %s", msg_id, exc)
            return False

    def check_msg_id(self, msg_id: str) -> bool:
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT 1 FROM received_msg_ids WHERE msg_id = ?", (msg_id,))
            return cursor.fetchone() is not None
        except Exception as exc:
            logger.error("检查 msg_id 失败: %s", exc)
            return False

    def record_msg_id(self, msg_id: str) -> bool:
        try:
            with self._lock:
                cursor = self.conn.cursor()
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                cursor.execute(
                    "INSERT OR IGNORE INTO received_msg_ids (msg_id, received_at) VALUES (?, ?)",
                    (msg_id, timestamp),
                )
                self.conn.commit()
            return True
        except Exception as exc:
            logger.error("记录 msg_id 失败: %s", exc)
            return False
