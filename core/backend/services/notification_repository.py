"""SQLite repository for system notifications."""

import logging
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class NotificationRepository:
    """Persistence operations for system notification rows."""

    def __init__(self, owner):
        self.owner = owner

    @property
    def conn(self):
        return self.owner.conn

    @property
    def _lock(self):
        return self.owner._lock

    def add_system_notification(
        self,
        title: str,
        content: str,
        category: str = "info",
    ) -> bool:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO system_notifications (title, content, category, timestamp)
                    VALUES (?, ?, ?, ?)
                    """,
                    (title, content, category, now),
                )
                self.conn.commit()
            return True
        except Exception as exc:
            logger.error("添加系统通知失败: %s", exc)
            return False

    def get_system_notifications(self, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT * FROM system_notifications
                ORDER BY timestamp DESC LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.error("获取系统通知失败: %s", exc)
            return []

    def clear_system_notifications(self) -> bool:
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute("DELETE FROM system_notifications")
                self.conn.commit()
            return True
        except Exception as exc:
            logger.error("清空系统通知失败: %s", exc)
            return False

    def mark_all_notifications_read(self) -> bool:
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute("UPDATE system_notifications SET is_read = 1")
                self.conn.commit()
            return True
        except Exception as exc:
            logger.error("标记通知已读失败: %s", exc)
            return False

    def mark_notification_read(self, notif_id: int) -> bool:
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute(
                    "UPDATE system_notifications SET is_read = 1 WHERE id = ?",
                    (notif_id,),
                )
                self.conn.commit()
            return True
        except Exception as exc:
            logger.error("标记通知已读失败: %s", exc)
            return False
