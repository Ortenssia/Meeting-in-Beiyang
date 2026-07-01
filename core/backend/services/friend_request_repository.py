"""Friend request persistence for FriendDB."""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


class FriendRequestRepository:
    """Store and query friend request state."""

    def __init__(self, owner):
        self.owner = owner

    @property
    def conn(self):
        return self.owner.conn

    @property
    def _lock(self):
        return self.owner._lock

    def upsert_friend_request(
        self,
        name: str,
        ip: str,
        port: int = 7779,
        tags: List[str] = None,
        bio: str = "",
        direction: str = "outgoing",
        status: str = "pending",
        user_id: str = "",
        msg_id: str = "",
    ) -> bool:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            tags_json = json.dumps(tags or [], ensure_ascii=False)
            with self._lock:
                cursor = self.conn.cursor()
                if user_id:
                    cursor.execute("SELECT id FROM friend_requests WHERE user_id = ?", (user_id,))
                else:
                    cursor.execute(
                        "SELECT id FROM friend_requests WHERE name = ? AND ip = ? AND port = ?",
                        (name, ip, int(port or 0)),
                    )
                existing = cursor.fetchone()
                if existing:
                    cursor.execute(
                        """
                        UPDATE friend_requests
                        SET user_id = ?, name = ?, ip = ?, port = ?, tags = ?,
                            bio = ?, direction = ?, status = ?, msg_id = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            user_id,
                            name,
                            ip,
                            int(port or 0),
                            tags_json,
                            bio,
                            direction,
                            status,
                            msg_id,
                            now,
                            existing["id"],
                        ),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO friend_requests
                        (user_id, name, ip, port, tags, bio, direction, status,
                         msg_id, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            user_id,
                            name,
                            ip,
                            int(port or 0),
                            tags_json,
                            bio,
                            direction,
                            status,
                            msg_id,
                            now,
                        ),
                    )
                self.conn.commit()
            return True
        except Exception as exc:
            logger.error("保存好友请求失败 [%s]: %s", name, exc)
            return False

    def get_friend_request(
        self,
        user_id: str = "",
        name: str = "",
        ip: str = "",
        port: int = 0,
    ) -> Optional[Dict[str, Any]]:
        try:
            cursor = self.conn.cursor()
            if user_id:
                cursor.execute(
                    "SELECT * FROM friend_requests WHERE user_id = ? ORDER BY updated_at DESC LIMIT 1",
                    (user_id,),
                )
            elif ip and port:
                cursor.execute(
                    """
                    SELECT * FROM friend_requests
                    WHERE name = ? AND ip = ? AND port = ?
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (name, ip, int(port or 0)),
                )
            else:
                cursor.execute(
                    "SELECT * FROM friend_requests WHERE name = ? ORDER BY updated_at DESC LIMIT 1",
                    (name,),
                )
            row = cursor.fetchone()
            return self.owner._row_to_request_dict(row) if row else None
        except Exception as exc:
            logger.error("查找好友请求失败: %s", exc)
            return None

    def set_friend_request_status(
        self,
        status: str,
        user_id: str = "",
        name: str = "",
        ip: str = "",
        port: int = 0,
    ) -> bool:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with self._lock:
                cursor = self.conn.cursor()
                if user_id:
                    cursor.execute(
                        """
                        UPDATE friend_requests
                        SET status = ?, updated_at = ?
                        WHERE user_id = ?
                        """,
                        (status, now, user_id),
                    )
                elif ip and port:
                    cursor.execute(
                        """
                        UPDATE friend_requests
                        SET status = ?, updated_at = ?
                        WHERE name = ? AND ip = ? AND port = ?
                        """,
                        (status, now, name, ip, int(port or 0)),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE friend_requests
                        SET status = ?, updated_at = ?
                        WHERE name = ?
                        """,
                        (status, now, name),
                    )
                self.conn.commit()
            return True
        except Exception as exc:
            logger.error("更新好友请求状态失败: %s", exc)
            return False

    def get_relationship_status(
        self,
        user_id: str = "",
        name: str = "",
        ip: str = "",
        port: int = 0,
    ) -> str:
        friend = self.owner.get_friend_by_user_id(user_id) if user_id else None
        if not friend and name:
            friend = self.owner.get_friend_by_name(name)
        if not friend and ip and port:
            friend = self.owner.get_friend_by_endpoint(ip, port)
        if friend and friend.get("status", "accepted") == "accepted":
            return "accepted"

        request = self.get_friend_request(user_id=user_id, name=name, ip=ip, port=port)
        if not request:
            return "none"
        if request["status"] == "accepted":
            return "accepted"
        if request["status"] == "rejected":
            return "rejected"
        if request["direction"] == "incoming":
            return "pending_received"
        return "pending_sent"
