"""SQLite repository for groups and moments."""

import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SocialRepository:
    """Persistence operations for group chat and moments."""

    def __init__(self, owner):
        self.owner = owner

    @property
    def conn(self):
        return self.owner.conn

    @property
    def _lock(self):
        return self.owner._lock

    def save_group(
        self,
        group_id: str,
        group_name: str,
        members: List[str],
        owner: str = "",
        only_owner_manage: int = 0,
    ) -> bool:
        try:
            with self._lock:
                cursor = self.conn.cursor()
                created_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                members_json = json.dumps(members)
                if not owner:
                    cursor.execute("SELECT owner FROM groups WHERE group_id = ?", (group_id,))
                    row = cursor.fetchone()
                    if row and row["owner"]:
                        owner = row["owner"]
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO groups (group_id, group_name, members, created_at, owner, only_owner_manage)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (group_id, group_name, members_json, created_at, owner, only_owner_manage),
                )
                self.conn.commit()
            return True
        except Exception as exc:
            logger.error("保存群组失败: %s", exc)
            return False

    def get_group(self, group_id: str) -> Optional[Dict[str, Any]]:
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM groups WHERE group_id = ?", (group_id,))
            row = cursor.fetchone()
            if row:
                result = dict(row)
                try:
                    result["members"] = json.loads(result["members"])
                except Exception:
                    result["members"] = []
                return result
            return None
        except Exception as exc:
            logger.error("获取群组失败: %s", exc)
            return None

    def get_all_groups(self) -> List[Dict[str, Any]]:
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM groups ORDER BY created_at DESC")
            rows = cursor.fetchall()
            results = []
            for row in rows:
                result = dict(row)
                try:
                    result["members"] = json.loads(result["members"])
                except Exception:
                    result["members"] = []
                results.append(result)
            return results
        except Exception as exc:
            logger.error("获取所有群组失败: %s", exc)
            return []

    def save_group_chat_message(
        self,
        msg_id: str,
        group_id: str,
        sender: str,
        content: str,
        timestamp: str,
    ) -> bool:
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO group_chat_history (msg_id, group_id, sender, content, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (msg_id, group_id, sender, content, timestamp),
                )
                self.conn.commit()
            return True
        except Exception as exc:
            logger.error("保存群消息失败: %s", exc)
            return False

    def get_group_chat_history(
        self,
        group_id: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT * FROM group_chat_history WHERE group_id = ? ORDER BY timestamp ASC",
                (group_id,),
            )
            rows = cursor.fetchall()
            results = [dict(row) for row in rows]
            if len(results) > limit:
                results = results[-limit:]
            return results
        except Exception as exc:
            logger.error("获取群消息历史失败: %s", exc)
            return []

    def has_group_message(self, msg_id: str) -> bool:
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT 1 FROM group_chat_history WHERE msg_id = ?", (msg_id,))
            return cursor.fetchone() is not None
        except Exception as exc:
            logger.error("检查群消息ID失败: %s", exc)
            return False

    def save_moment(
        self,
        post_id: str,
        author: str,
        content: str,
        media_path: str,
        timestamp: str,
    ) -> bool:
        try:
            with self._lock:
                cursor = self.conn.cursor()
                created_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO moments (post_id, author, content, media_path, timestamp, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (post_id, author, content, media_path or "", timestamp, created_at),
                )
                self.conn.commit()
            return True
        except Exception as exc:
            logger.error("保存空间发帖失败: %s", exc)
            return False

    def get_moments(self, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM moments ORDER BY timestamp DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.error("获取空间发帖失败: %s", exc)
            return []

    def has_moment(self, post_id: str) -> bool:
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT 1 FROM moments WHERE post_id = ?", (post_id,))
            return cursor.fetchone() is not None
        except Exception as exc:
            logger.error("检查空间发帖ID失败: %s", exc)
            return False

    def delete_moment(self, post_id: str) -> bool:
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute("DELETE FROM moments WHERE post_id = ?", (post_id,))
                self.conn.commit()
            return True
        except Exception as exc:
            logger.error("删除空间发帖失败: %s", exc)
            return False

    def save_moment_comment(
        self,
        comment_id: str,
        post_id: str,
        author: str,
        content: str,
        timestamp: str,
    ) -> bool:
        try:
            with self._lock:
                cursor = self.conn.cursor()
                created_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO moment_comments (comment_id, post_id, author, content, timestamp, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (comment_id, post_id, author, content, timestamp, created_at),
                )
                self.conn.commit()
            return True
        except Exception as exc:
            logger.error("保存空间评论失败: %s", exc)
            return False

    def get_moment_comments(self, post_id: str) -> List[Dict[str, Any]]:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT * FROM moment_comments WHERE post_id = ? ORDER BY timestamp ASC",
                (post_id,),
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.error("获取空间评论失败: %s", exc)
            return []

    def delete_moment_comment(self, comment_id: str) -> bool:
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute("DELETE FROM moment_comments WHERE comment_id = ?", (comment_id,))
                self.conn.commit()
            return True
        except Exception as exc:
            logger.error("删除空间评论失败: %s", exc)
            return False
