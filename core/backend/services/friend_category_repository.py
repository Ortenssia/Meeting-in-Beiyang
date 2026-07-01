"""Friend category persistence for FriendDB."""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List


logger = logging.getLogger(__name__)


class FriendCategoryRepository:
    """Manage local friend category records."""

    def __init__(self, owner):
        self.owner = owner

    @property
    def conn(self):
        return self.owner.conn

    @property
    def _lock(self):
        return self.owner._lock

    def migrate_friend_categories(self) -> None:
        """Seed the category table from defaults and legacy JSON settings."""
        try:
            cursor = self.conn.cursor()
            existing = cursor.execute("SELECT COUNT(*) AS count FROM friend_categories").fetchone()
            if existing and int(existing["count"] or 0) > 0:
                return

            categories = ["同学", "朋友"]
            legacy = cursor.execute(
                "SELECT value FROM app_settings WHERE key = ?",
                ("custom_friend_categories",),
            ).fetchone()
            if legacy:
                try:
                    parsed = json.loads(legacy["value"] or "[]")
                    if isinstance(parsed, list) and parsed:
                        categories = [str(item).strip() for item in parsed if str(item).strip()]
                except Exception:
                    pass
            if "朋友" not in categories:
                categories.append("朋友")

            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for index, category in enumerate(dict.fromkeys(categories)):
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO friend_categories
                    (name, sort_order, color, icon, created_at)
                    VALUES (?, ?, '', '', ?)
                    """,
                    (category, index, now),
                )
            self.conn.commit()
        except Exception as exc:
            logger.error("迁移好友分组失败: %s", exc)

    def set_friend_category(self, name: str, category: str) -> bool:
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute("UPDATE friends SET category = ? WHERE name = ?", (category, name))
                self.conn.commit()
            return True
        except Exception as exc:
            logger.error("设置好友分类失败 [%s -> %s]: %s", name, category, exc)
            return False

    def add_friend_category(self, name: str, color: str = "", icon: str = "") -> bool:
        category = (name or "").strip()
        if not category or category == "全部":
            return False
        try:
            with self._lock:
                cursor = self.conn.cursor()
                row = cursor.execute("SELECT MAX(sort_order) AS max_order FROM friend_categories").fetchone()
                sort_order = int(row["max_order"] if row and row["max_order"] is not None else -1) + 1
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO friend_categories
                    (name, sort_order, color, icon, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (category, sort_order, color or "", icon or "", now),
                )
                self.conn.commit()
                return cursor.rowcount > 0
        except Exception as exc:
            logger.error("添加好友分组失败 [%s]: %s", name, exc)
            return False

    def delete_friend_category(self, name: str, fallback: str = "朋友") -> bool:
        category = (name or "").strip()
        fallback_category = (fallback or "朋友").strip()
        if not category or category == fallback_category:
            return False
        try:
            with self._lock:
                cursor = self.conn.cursor()
                fallback_row = cursor.execute(
                    "SELECT name FROM friend_categories WHERE name = ?",
                    (fallback_category,),
                ).fetchone()
                if not fallback_row:
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    cursor.execute(
                        """
                        INSERT OR IGNORE INTO friend_categories
                        (name, sort_order, color, icon, created_at)
                        VALUES (?, 0, '', '', ?)
                        """,
                        (fallback_category, now),
                    )
                cursor.execute(
                    "UPDATE friends SET category = ? WHERE category = ?",
                    (fallback_category, category),
                )
                cursor.execute("DELETE FROM friend_categories WHERE name = ?", (category,))
                deleted = cursor.rowcount > 0
                self.conn.commit()
                return deleted
        except Exception as exc:
            logger.error("删除好友分组失败 [%s]: %s", name, exc)
            return False

    def get_friend_category_records(self) -> List[Dict[str, Any]]:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT name, sort_order, color, icon, created_at
                FROM friend_categories
                ORDER BY sort_order ASC, name ASC
                """
            )
            return [
                {
                    "name": row["name"],
                    "sort_order": row["sort_order"],
                    "color": row["color"] or "",
                    "icon": row["icon"] or "",
                    "created_at": row["created_at"],
                }
                for row in cursor.fetchall()
            ]
        except Exception as exc:
            logger.error("获取好友分组记录失败: %s", exc)
            return []

    def get_friend_categories(self) -> List[str]:
        try:
            cursor = self.conn.cursor()
            configured = [
                row["name"]
                for row in cursor.execute(
                    """
                    SELECT name FROM friend_categories
                    ORDER BY sort_order ASC, name ASC
                    """
                ).fetchall()
            ]
            used = [
                row["category"]
                for row in cursor.execute(
                    """
                    SELECT DISTINCT category
                    FROM friends
                    WHERE category IS NOT NULL AND TRIM(category) != ''
                    ORDER BY category
                    """
                ).fetchall()
            ]
            return list(dict.fromkeys(configured + used))
        except Exception as exc:
            logger.error("获取好友分类失败: %s", exc)
            return []
