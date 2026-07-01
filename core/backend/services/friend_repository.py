"""Friend address-book persistence for FriendDB."""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


class FriendRepository:
    """CRUD operations for accepted friends."""

    def __init__(self, owner):
        self.owner = owner

    @property
    def conn(self):
        return self.owner.conn

    @property
    def _lock(self):
        return self.owner._lock

    def add_friend(
        self,
        name: str,
        ip: str,
        port: int = 7779,
        tags: List[str] = None,
        bio: str = "",
        category: str = "朋友",
        user_id: str = "",
        status: str = "accepted",
        avatar: str = "",
        background: str = "",
        card_bg: str = "",
    ) -> bool:
        status = status or "accepted"
        category = category or "朋友"
        bio = bio or ""
        avatar = avatar or ""
        background = background or ""
        card_bg = card_bg or ""
        user_id = user_id or ""

        try:
            with self._lock:
                cursor = self.conn.cursor()
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                tags_json = json.dumps(tags or [], ensure_ascii=False)
                if user_id:
                    cursor.execute(
                        """
                        SELECT id, user_id, avatar, background, card_bg
                        FROM friends
                        WHERE user_id = ? OR name = ?
                        """,
                        (user_id, name),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT id, user_id, avatar, background, card_bg
                        FROM friends
                        WHERE name = ?
                        """,
                        (name,),
                    )
                existing = cursor.fetchone()

                if existing:
                    stored_user_id = user_id or existing["user_id"] or ""
                    existing_avatar = existing["avatar"] if "avatar" in existing.keys() else ""
                    existing_background = existing["background"] if "background" in existing.keys() else ""
                    existing_card_bg = existing["card_bg"] if "card_bg" in existing.keys() else ""
                    cursor.execute(
                        """
                        UPDATE friends
                        SET user_id = ?, name = ?, ip = ?, port = ?, tags = ?,
                            bio = ?, avatar = ?, background = ?, card_bg = ?, category = ?,
                            status = ?, last_seen = ?
                        WHERE id = ?
                        """,
                        (
                            stored_user_id,
                            name,
                            ip,
                            port,
                            tags_json,
                            bio,
                            avatar or existing_avatar,
                            background or existing_background,
                            card_bg or existing_card_bg,
                            category,
                            status,
                            now,
                            existing["id"],
                        ),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO friends
                        (user_id, name, ip, port, tags, bio, avatar, background, card_bg,
                         category, status, added_at, last_seen)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            user_id,
                            name,
                            ip,
                            port,
                            tags_json,
                            bio,
                            avatar,
                            background,
                            card_bg,
                            category,
                            status,
                            now,
                            now,
                        ),
                    )

                if user_id:
                    cursor.execute(
                        """
                        UPDATE friend_requests
                        SET status = 'accepted', updated_at = ?
                        WHERE user_id = ? OR name = ?
                        """,
                        (now, user_id, name),
                    )
                self.conn.commit()
            return True
        except Exception as exc:
            logger.error("添加好友失败 [%s]: %s", name, exc)
            return False

    def repair_blank_friend_names(self) -> None:
        """Repair legacy friend rows that were accepted with an empty name."""
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute(
                    """
                    SELECT id, user_id, ip, port
                    FROM friends
                    WHERE (name IS NULL OR TRIM(name) = '')
                    """
                )
                for row in cursor.fetchall():
                    repair_name = ""
                    if row["user_id"]:
                        req = cursor.execute(
                            """
                            SELECT name FROM friend_requests
                            WHERE user_id = ? AND TRIM(name) != ''
                            ORDER BY updated_at DESC, id DESC
                            LIMIT 1
                            """,
                            (row["user_id"],),
                        ).fetchone()
                        if req:
                            repair_name = req["name"]
                    if not repair_name:
                        req = cursor.execute(
                            """
                            SELECT name FROM friend_requests
                            WHERE ip = ? AND port = ? AND TRIM(name) != ''
                            ORDER BY updated_at DESC, id DESC
                            LIMIT 1
                            """,
                            (row["ip"], row["port"]),
                        ).fetchone()
                        if req:
                            repair_name = req["name"]
                    if repair_name:
                        cursor.execute("UPDATE friends SET name = ? WHERE id = ?", (repair_name, row["id"]))
                    elif not row["user_id"]:
                        cursor.execute("DELETE FROM friends WHERE id = ?", (row["id"],))
                self.conn.commit()
        except Exception as exc:
            logger.error("修复空好友名称失败: %s", exc)

    def update_friend_avatar(self, name: str = "", avatar: str = "", user_id: str = "") -> bool:
        if not avatar or not (name or user_id):
            return False
        try:
            with self._lock:
                cursor = self.conn.cursor()
                if user_id:
                    cursor.execute(
                        "UPDATE friends SET avatar = ? WHERE user_id = ? OR name = ?",
                        (avatar, user_id, name),
                    )
                else:
                    cursor.execute("UPDATE friends SET avatar = ? WHERE name = ?", (avatar, name))
                self.conn.commit()
                return cursor.rowcount > 0
        except Exception as exc:
            logger.error("更新好友头像失败 [%s/%s]: %s", name, user_id, exc)
            return False

    def update_friend_card_bg(self, name: str = "", card_bg: str = "", user_id: str = "") -> bool:
        if not card_bg or not (name or user_id):
            return False
        try:
            with self._lock:
                cursor = self.conn.cursor()
                if user_id:
                    cursor.execute(
                        "UPDATE friends SET card_bg = ? WHERE user_id = ? OR name = ?",
                        (card_bg, user_id, name),
                    )
                else:
                    cursor.execute("UPDATE friends SET card_bg = ? WHERE name = ?", (card_bg, name))
                self.conn.commit()
                return cursor.rowcount > 0
        except Exception as exc:
            logger.error("更新好友名片背景失败 [%s/%s]: %s", name, user_id, exc)
            return False

    def remove_friend(self, name: str) -> bool:
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute("SELECT user_id FROM friends WHERE name = ?", (name,))
                row = cursor.fetchone()
                user_id = row[0] if row else None
                cursor.execute("DELETE FROM friends WHERE name = ?", (name,))
                if user_id:
                    cursor.execute("DELETE FROM friend_requests WHERE user_id = ?", (user_id,))
                else:
                    cursor.execute("DELETE FROM friend_requests WHERE name = ?", (name,))
                cursor.execute("DELETE FROM chat_history WHERE friend_name = ?", (name,))
                self.conn.commit()
            return True
        except Exception as exc:
            logger.error("删除好友失败 [%s]: %s", name, exc)
            return False

    def get_friends(self) -> List[Dict[str, Any]]:
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM friends ORDER BY added_at DESC")
            return [self.owner._row_to_friend_dict(row) for row in cursor.fetchall()]
        except Exception as exc:
            logger.error("获取好友列表失败: %s", exc)
            return []

    def get_friend_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM friends WHERE name = ?", (name,))
            row = cursor.fetchone()
            return self.owner._row_to_friend_dict(row) if row else None
        except Exception as exc:
            logger.error("查找好友失败 [%s]: %s", name, exc)
            return None

    def get_friend_by_ip(self, ip: str) -> Optional[Dict[str, Any]]:
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM friends WHERE ip = ?", (ip,))
            row = cursor.fetchone()
            return self.owner._row_to_friend_dict(row) if row else None
        except Exception as exc:
            logger.error("按 IP 查找好友失败 [%s]: %s", ip, exc)
            return None

    def get_friend_by_user_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        if not user_id:
            return None
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM friends WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return self.owner._row_to_friend_dict(row) if row else None
        except Exception as exc:
            logger.error("按 user_id 查找好友失败 [%s]: %s", user_id, exc)
            return None

    def get_friend_by_endpoint(self, ip: str, port: int) -> Optional[Dict[str, Any]]:
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM friends WHERE ip = ? AND port = ?", (ip, int(port or 0)))
            row = cursor.fetchone()
            return self.owner._row_to_friend_dict(row) if row else None
        except Exception as exc:
            logger.error("按 endpoint 查找好友失败 [%s:%s]: %s", ip, port, exc)
            return None

    def update_friend_ip(self, name: str, new_ip: str) -> bool:
        try:
            with self._lock:
                cursor = self.conn.cursor()
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute("UPDATE friends SET ip = ?, last_seen = ? WHERE name = ?", (new_ip, now, name))
                self.conn.commit()
            return True
        except Exception as exc:
            logger.error("更新好友 IP 失败 [%s -> %s]: %s", name, new_ip, exc)
            return False

    def update_friend_last_seen(self, name: str) -> bool:
        try:
            with self._lock:
                cursor = self.conn.cursor()
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute("UPDATE friends SET last_seen = ? WHERE name = ?", (now, name))
                self.conn.commit()
            return True
        except Exception as exc:
            logger.error("更新好友在线时间失败 [%s]: %s", name, exc)
            return False
