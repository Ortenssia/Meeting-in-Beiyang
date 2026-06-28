"""
好友数据库模块 (Challenge 3 - 相识北洋)

使用 SQLite 存储好友信息、地址簿、好友匹配条件和待转发消息。

管理四张表：
  - friends:            好友地址簿（名字、IP、标签、简介、分类）
  - friend_conditions:  好友匹配条件（必须标签、可选标签、最低匹配数）
  - pending_messages:   待转发消息（离线消息洪泛中继暂存）
  - chat_history:       聊天记录（发送/接收方向、消息正文、时间戳）

线程安全：使用 check_same_thread=False 配合内部 _lock 保护所有写操作。
"""

import json
import logging
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.config import get_app_paths

logger = logging.getLogger(__name__)


class FriendDB:
    """
    好友数据库管理类。

    提供好友管理、匹配条件存储、待转发消息队列和聊天记录持久化等功能。
    所有数据库操作均通过内部互斥锁保证线程安全。
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Args:
            db_path: SQLite 数据库文件路径。普通文件名会被解析到应用数据目录。
        """
        resolved = get_app_paths().resolve_db_path(db_path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(resolved)
        self.conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        """初始化数据库，创建所有表结构。"""
        try:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            cursor = self.conn.cursor()

            # ---- 好友地址簿表 ---- #
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS friends (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     TEXT    DEFAULT '',
                    name        TEXT    NOT NULL,
                    ip          TEXT    NOT NULL,
                    port        INTEGER DEFAULT 7779,
                    tags        TEXT    DEFAULT '[]',     -- JSON 数组
                    bio         TEXT    DEFAULT '',
                    avatar      TEXT    DEFAULT '',
                    background  TEXT    DEFAULT '',
                    category    TEXT    DEFAULT '朋友',
                    status      TEXT    DEFAULT 'accepted',
                    added_at    TEXT    NOT NULL,
                    last_seen   TEXT    NOT NULL
                )
            """)

            # ---- 好友匹配条件表（仅一行配置） ---- #
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS friend_conditions (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    required_tags   TEXT    DEFAULT '[]',     -- JSON 数组
                    optional_tags   TEXT    DEFAULT '[]',     -- JSON 数组
                    min_match_count INTEGER DEFAULT 1,
                    auto_accept     INTEGER DEFAULT 0         -- 0 = 手动, 1 = 自动
                )
            """)

            # ---- 待转发消息表（离线消息洪泛中继暂存） ---- #
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pending_messages (
                    msg_id      TEXT    PRIMARY KEY,
                    from_name   TEXT    NOT NULL,
                    from_ip     TEXT    NOT NULL,
                    to_name     TEXT    NOT NULL,
                    content     TEXT    NOT NULL,
                    timestamp   TEXT    NOT NULL,
                    relay_path  TEXT    DEFAULT '[]'          -- JSON 数组
                )
            """)

            # ---- 聊天记录表 ---- #
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    friend_name TEXT    NOT NULL,
                    friend_ip   TEXT    NOT NULL,
                    direction   TEXT    NOT NULL,              -- 'send' or 'receive'
                    content     TEXT    NOT NULL,
                    timestamp   TEXT    NOT NULL,
                    msg_id      TEXT    NOT NULL
                )
            """)

            # ---- 本机应用设置表 ---- #
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    key         TEXT    PRIMARY KEY,
                    value       TEXT    NOT NULL
                )
            """)

            # ---- 个人资料表 ---- #
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS my_profile (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     TEXT    DEFAULT '',
                    device_id   TEXT    DEFAULT '',
                    name        TEXT    NOT NULL,
                    tags        TEXT    DEFAULT '[]',     -- JSON 数组
                    bio         TEXT    DEFAULT ''
                )
            """)
            
            # 兼容老版本，动态添加新增字段
            try:
                cursor.execute("ALTER TABLE my_profile ADD COLUMN avatar TEXT DEFAULT ''")
            except Exception:
                pass
            try:
                cursor.execute("ALTER TABLE my_profile ADD COLUMN background TEXT DEFAULT ''")
            except Exception:
                pass
            try:
                cursor.execute("ALTER TABLE my_profile ADD COLUMN user_id TEXT DEFAULT ''")
            except Exception:
                pass
            try:
                cursor.execute("ALTER TABLE my_profile ADD COLUMN device_id TEXT DEFAULT ''")
            except Exception:
                pass
            try:
                cursor.execute("ALTER TABLE friends ADD COLUMN user_id TEXT DEFAULT ''")
            except Exception:
                pass
            try:
                cursor.execute("ALTER TABLE friends ADD COLUMN status TEXT DEFAULT 'accepted'")
            except Exception:
                pass
            try:
                cursor.execute("ALTER TABLE friends ADD COLUMN avatar TEXT DEFAULT ''")
            except Exception:
                pass
            try:
                cursor.execute("ALTER TABLE friends ADD COLUMN background TEXT DEFAULT ''")
            except Exception:
                pass

            # ---- 好友请求状态表 ---- #
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS friend_requests (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     TEXT    DEFAULT '',
                    name        TEXT    NOT NULL,
                    ip          TEXT    NOT NULL,
                    port        INTEGER DEFAULT 7779,
                    tags        TEXT    DEFAULT '[]',
                    bio         TEXT    DEFAULT '',
                    direction   TEXT    NOT NULL,          -- incoming / outgoing
                    status      TEXT    NOT NULL,          -- pending / accepted / rejected
                    msg_id      TEXT    DEFAULT '',
                    updated_at  TEXT    NOT NULL
                )
            """)

            # ---- 中继消息去重表 ---- #
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS received_msg_ids (
                    msg_id      TEXT    PRIMARY KEY,
                    received_at TEXT    NOT NULL
                )
            """)

            # ---- 群组表 ---- #
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS groups (
                    group_id    TEXT    PRIMARY KEY,
                    group_name  TEXT    NOT NULL,
                    members     TEXT    DEFAULT '[]',     -- JSON 数组，包含成员名字
                    created_at  TEXT    NOT NULL,
                    owner       TEXT    DEFAULT '',
                    only_owner_manage INTEGER DEFAULT 0
                )
            """)
            try:
                cursor.execute("ALTER TABLE groups ADD COLUMN owner TEXT DEFAULT ''")
            except Exception:
                pass
            try:
                cursor.execute("ALTER TABLE groups ADD COLUMN only_owner_manage INTEGER DEFAULT 0")
            except Exception:
                pass

            # ---- 群聊历史记录表 ---- #
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS group_chat_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    msg_id      TEXT    NOT NULL,
                    group_id    TEXT    NOT NULL,
                    sender      TEXT    NOT NULL,
                    content     TEXT    NOT NULL,
                    timestamp   TEXT    NOT NULL
                )
            """)

            # ---- 朋友圈/空间动态表 ---- #
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS moments (
                    post_id     TEXT    PRIMARY KEY,
                    author      TEXT    NOT NULL,
                    content     TEXT    NOT NULL,
                    media_path  TEXT    DEFAULT '',
                    timestamp   TEXT    NOT NULL,
                    created_at  TEXT    NOT NULL
                )
            """)

            self.conn.commit()
            self._repair_blank_friend_names()
            logger.info("好友数据库初始化完成: %s", self.db_path)

        except Exception as e:
            logger.error("好友数据库初始化失败: %s", e)

    def close(self):
        """关闭数据库连接。"""
        if self.conn:
            try:
                self.conn.close()
                self.conn = None
            except Exception:
                pass

    # ================================================================== #
    #  好友管理
    # ================================================================== #

    def add_friend(self, name: str, ip: str, port: int = 7779,
                   tags: List[str] = None, bio: str = "",
                   category: str = "朋友", user_id: str = "",
                   status: str = "accepted", avatar: str = "",
                   background: str = "") -> bool:
        """
        添加好友到地址簿。

        若同名好友已存在则更新其信息而非重复插入。

        Args:
            name:     好友名字 / 昵称。
            ip:       好友 IP 地址。
            port:     好友 TCP 端口。
            tags:     兴趣标签列表，如 ["摄影", "编程"]。
            bio:      个人简介。
            category: 好友分类，默认 "朋友"。

        Returns:
            True 表示操作成功。
        """
        if status is None:
            status = "accepted"
        if category is None:
            category = "朋友"
        if bio is None:
            bio = ""
        if avatar is None:
            avatar = ""
        if background is None:
            background = ""
        if user_id is None:
            user_id = ""

        try:
            with self._lock:
                cursor = self.conn.cursor()
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                tags_json = json.dumps(tags or [], ensure_ascii=False)

                # 优先按稳定 user_id 更新；兼容旧数据时回退到 name。
                if user_id:
                    cursor.execute(
                        """
                        SELECT id, user_id, avatar, background
                        FROM friends
                        WHERE user_id = ? OR name = ?
                        """,
                        (user_id, name),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT id, user_id, avatar, background
                        FROM friends
                        WHERE name = ?
                        """,
                        (name,),
                    )
                existing = cursor.fetchone()

                if existing:
                    stored_user_id = user_id or existing["user_id"] or ""
                    # 更新已有好友信息
                    existing_avatar = existing["avatar"] if "avatar" in existing.keys() else ""
                    existing_background = existing["background"] if "background" in existing.keys() else ""
                    cursor.execute("""
                        UPDATE friends
                        SET user_id = ?, name = ?, ip = ?, port = ?, tags = ?,
                            bio = ?, avatar = ?, background = ?, category = ?,
                            status = ?, last_seen = ?
                        WHERE id = ?
                    """, (
                        stored_user_id, name, ip, port, tags_json, bio,
                        avatar or existing_avatar, background or existing_background,
                        category, status, now, existing["id"],
                    ))
                else:
                    # 插入新好友
                    cursor.execute("""
                        INSERT INTO friends
                        (user_id, name, ip, port, tags, bio, avatar, background,
                         category, status, added_at, last_seen)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        user_id, name, ip, port, tags_json, bio, avatar,
                        background, category, status, now, now,
                    ))

                if user_id:
                    cursor.execute("""
                        UPDATE friend_requests
                        SET status = 'accepted', updated_at = ?
                        WHERE user_id = ? OR name = ?
                    """, (now, user_id, name))
                self.conn.commit()
            return True

        except Exception as e:
            logger.error("添加好友失败 [%s]: %s", name, e)
            return False

    def _repair_blank_friend_names(self) -> None:
        """Repair legacy friend rows that were accepted with an empty name."""
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute("""
                    SELECT id, user_id, ip, port
                    FROM friends
                    WHERE (name IS NULL OR TRIM(name) = '')
                """)
                rows = cursor.fetchall()
                for row in rows:
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
                        cursor.execute(
                            "UPDATE friends SET name = ? WHERE id = ?",
                            (repair_name, row["id"]),
                        )
                    elif not row["user_id"]:
                        cursor.execute("DELETE FROM friends WHERE id = ?", (row["id"],))
                self.conn.commit()
        except Exception as e:
            logger.error("修复空好友名称失败: %s", e)

    def update_friend_avatar(
        self,
        name: str = "",
        avatar: str = "",
        user_id: str = "",
    ) -> bool:
        """Update a friend's locally cached avatar path."""
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
                    cursor.execute(
                        "UPDATE friends SET avatar = ? WHERE name = ?",
                        (avatar, name),
                    )
                self.conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error("更新好友头像失败 [%s/%s]: %s", name, user_id, e)
            return False

    def remove_friend(self, name: str) -> bool:
        """
        从地址簿中移除好友。

        同时删除该好友的所有聊天记录。

        Args:
            name: 好友名字。

        Returns:
            True 表示删除成功。
        """
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute("DELETE FROM friends WHERE name = ?", (name,))
                cursor.execute(
                    "DELETE FROM chat_history WHERE friend_name = ?", (name,)
                )
                self.conn.commit()
            return True

        except Exception as e:
            logger.error("删除好友失败 [%s]: %s", name, e)
            return False

    def get_friends(self) -> List[Dict[str, Any]]:
        """
        获取所有好友列表。

        Returns:
            好友字典列表，每项包含 name, ip, port, tags, bio, category,
            added_at, last_seen 等字段。tags 为已解析的列表。
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM friends ORDER BY added_at DESC")
            rows = cursor.fetchall()
            return [self._row_to_friend_dict(row) for row in rows]

        except Exception as e:
            logger.error("获取好友列表失败: %s", e)
            return []

    def get_friend_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """
        根据名字查找好友。

        Args:
            name: 好友名字。

        Returns:
            好友字典，未找到返回 None。
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM friends WHERE name = ?", (name,))
            row = cursor.fetchone()
            return self._row_to_friend_dict(row) if row else None

        except Exception as e:
            logger.error("查找好友失败 [%s]: %s", name, e)
            return None

    def get_friend_by_ip(self, ip: str) -> Optional[Dict[str, Any]]:
        """
        根据 IP 查找好友。

        Args:
            ip: 好友 IP 地址。

        Returns:
            好友字典，未找到返回 None。
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM friends WHERE ip = ?", (ip,))
            row = cursor.fetchone()
            return self._row_to_friend_dict(row) if row else None

        except Exception as e:
            logger.error("按 IP 查找好友失败 [%s]: %s", ip, e)
            return None

    def get_friend_by_user_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """根据稳定 user_id 查找好友。"""
        if not user_id:
            return None
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM friends WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return self._row_to_friend_dict(row) if row else None

        except Exception as e:
            logger.error("按 user_id 查找好友失败 [%s]: %s", user_id, e)
            return None

    def get_friend_by_endpoint(self, ip: str, port: int) -> Optional[Dict[str, Any]]:
        """根据当前连接地址查找好友，用于兼容尚未携带 user_id 的旧协议。"""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT * FROM friends WHERE ip = ? AND port = ?",
                (ip, int(port or 0)),
            )
            row = cursor.fetchone()
            return self._row_to_friend_dict(row) if row else None

        except Exception as e:
            logger.error("按 endpoint 查找好友失败 [%s:%s]: %s", ip, port, e)
            return None

    def update_friend_ip(self, name: str, new_ip: str) -> bool:
        """
        更新好友的 IP 地址（IP 变更时使用）。

        Args:
            name:   好友名字。
            new_ip: 新的 IP 地址。

        Returns:
            True 表示更新成功。
        """
        try:
            with self._lock:
                cursor = self.conn.cursor()
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute("""
                    UPDATE friends
                    SET ip = ?, last_seen = ?
                    WHERE name = ?
                """, (new_ip, now, name))
                self.conn.commit()
            return True

        except Exception as e:
            logger.error("更新好友 IP 失败 [%s -> %s]: %s", name, new_ip, e)
            return False

    def set_friend_category(self, name: str, category: str) -> bool:
        """
        设置好友分类。

        Args:
            name:     好友名字。
            category: 分类名称，如 "同学", "朋友", "社团"。

        Returns:
            True 表示设置成功。
        """
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute("""
                    UPDATE friends SET category = ? WHERE name = ?
                """, (category, name))
                self.conn.commit()
            return True

        except Exception as e:
            logger.error("设置好友分类失败 [%s -> %s]: %s", name, category, e)
            return False

    def get_friend_categories(self) -> List[str]:
        """
        获取所有好友分类（去重）。

        Returns:
            唯一分类名称列表。
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT DISTINCT category FROM friends ORDER BY category"
            )
            return [row["category"] for row in cursor.fetchall()]

        except Exception as e:
            logger.error("获取好友分类失败: %s", e)
            return []

    def update_friend_last_seen(self, name: str) -> bool:
        """
        更新好友最后在线时间。

        Args:
            name: 好友名字。

        Returns:
            True 表示更新成功。
        """
        try:
            with self._lock:
                cursor = self.conn.cursor()
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute("""
                    UPDATE friends SET last_seen = ? WHERE name = ?
                """, (now, name))
                self.conn.commit()
            return True

        except Exception as e:
            logger.error("更新好友在线时间失败 [%s]: %s", name, e)
            return False

    # ================================================================== #
    #  好友请求状态
    # ================================================================== #

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
        """新增或更新一条好友请求状态。"""
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            tags_json = json.dumps(tags or [], ensure_ascii=False)
            with self._lock:
                cursor = self.conn.cursor()
                if user_id:
                    cursor.execute(
                        "SELECT id FROM friend_requests WHERE user_id = ?",
                        (user_id,),
                    )
                else:
                    cursor.execute(
                        "SELECT id FROM friend_requests WHERE name = ? AND ip = ? AND port = ?",
                        (name, ip, int(port or 0)),
                    )
                existing = cursor.fetchone()
                if existing:
                    cursor.execute("""
                        UPDATE friend_requests
                        SET user_id = ?, name = ?, ip = ?, port = ?, tags = ?,
                            bio = ?, direction = ?, status = ?, msg_id = ?,
                            updated_at = ?
                        WHERE id = ?
                    """, (
                        user_id, name, ip, int(port or 0), tags_json, bio,
                        direction, status, msg_id, now, existing["id"],
                    ))
                else:
                    cursor.execute("""
                        INSERT INTO friend_requests
                        (user_id, name, ip, port, tags, bio, direction, status,
                         msg_id, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        user_id, name, ip, int(port or 0), tags_json, bio,
                        direction, status, msg_id, now,
                    ))
                self.conn.commit()
            return True
        except Exception as e:
            logger.error("保存好友请求失败 [%s]: %s", name, e)
            return False

    def get_friend_request(
        self,
        user_id: str = "",
        name: str = "",
        ip: str = "",
        port: int = 0,
    ) -> Optional[Dict[str, Any]]:
        """查找一条好友请求状态。"""
        try:
            cursor = self.conn.cursor()
            if user_id:
                cursor.execute(
                    "SELECT * FROM friend_requests WHERE user_id = ? ORDER BY updated_at DESC LIMIT 1",
                    (user_id,),
                )
            elif ip and port:
                cursor.execute("""
                    SELECT * FROM friend_requests
                    WHERE name = ? AND ip = ? AND port = ?
                    ORDER BY updated_at DESC LIMIT 1
                """, (name, ip, int(port or 0)))
            else:
                cursor.execute(
                    "SELECT * FROM friend_requests WHERE name = ? ORDER BY updated_at DESC LIMIT 1",
                    (name,),
                )
            row = cursor.fetchone()
            return self._row_to_request_dict(row) if row else None
        except Exception as e:
            logger.error("查找好友请求失败: %s", e)
            return None

    def set_friend_request_status(
        self,
        status: str,
        user_id: str = "",
        name: str = "",
        ip: str = "",
        port: int = 0,
    ) -> bool:
        """更新好友请求状态。"""
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with self._lock:
                cursor = self.conn.cursor()
                if user_id:
                    cursor.execute("""
                        UPDATE friend_requests
                        SET status = ?, updated_at = ?
                        WHERE user_id = ?
                    """, (status, now, user_id))
                elif ip and port:
                    cursor.execute("""
                        UPDATE friend_requests
                        SET status = ?, updated_at = ?
                        WHERE name = ? AND ip = ? AND port = ?
                    """, (status, now, name, ip, int(port or 0)))
                else:
                    cursor.execute("""
                        UPDATE friend_requests
                        SET status = ?, updated_at = ?
                        WHERE name = ?
                    """, (status, now, name))
                self.conn.commit()
            return True
        except Exception as e:
            logger.error("更新好友请求状态失败: %s", e)
            return False

    def get_relationship_status(
        self,
        user_id: str = "",
        name: str = "",
        ip: str = "",
        port: int = 0,
    ) -> str:
        """返回 none / pending_sent / pending_received / accepted / rejected。"""
        friend = self.get_friend_by_user_id(user_id) if user_id else None
        if not friend and name:
            friend = self.get_friend_by_name(name)
        if not friend and ip and port:
            friend = self.get_friend_by_endpoint(ip, port)
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

    # ================================================================== #
    #  好友匹配条件
    # ================================================================== #

    def save_conditions(self, required_tags: List[str],
                        optional_tags: List[str],
                        min_match: int = 1,
                        auto_accept: bool = False) -> bool:
        """
        保存好友匹配条件（仅保留一份配置，每次调用覆盖）。

        Args:
            required_tags: 必须匹配的标签列表。
            optional_tags: 可选匹配的标签列表。
            min_match:     最少匹配标签总数。
            auto_accept:   匹配时是否自动接受好友请求。

        Returns:
            True 表示保存成功。
        """
        try:
            with self._lock:
                cursor = self.conn.cursor()

                # 清空旧条件，只保留一条配置
                cursor.execute("DELETE FROM friend_conditions")

                cursor.execute("""
                    INSERT INTO friend_conditions
                    (required_tags, optional_tags, min_match_count, auto_accept)
                    VALUES (?, ?, ?, ?)
                """, (
                    json.dumps(required_tags, ensure_ascii=False),
                    json.dumps(optional_tags, ensure_ascii=False),
                    min_match,
                    1 if auto_accept else 0,
                ))

                self.conn.commit()
            return True

        except Exception as e:
            logger.error("保存匹配条件失败: %s", e)
            return False

    def get_conditions(self) -> Dict[str, Any]:
        """
        获取当前好友匹配条件。

        Returns:
            条件字典，包含 required_tags, optional_tags,
            min_match_count, auto_accept；未配置时返回空字典。
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM friend_conditions LIMIT 1")
            row = cursor.fetchone()

            if not row:
                return {}

            return {
                "required_tags": json.loads(row["required_tags"]),
                "optional_tags": json.loads(row["optional_tags"]),
                "min_match_count": row["min_match_count"],
                "auto_accept": bool(row["auto_accept"]),
            }

        except Exception as e:
            logger.error("获取匹配条件失败: %s", e)
            return {}

    # ================================================================== #
    #  待转发消息（离线消息洪泛中继暂存）
    # ================================================================== #

    def add_pending_message(self, *args, **kwargs) -> bool:
        """
        添加一条待转发消息到暂存队列。支持多种调用签名：
        1. add_pending_message(self, msg_id, from_name, from_ip, to_name, content, timestamp, relay_path)
        2. add_pending_message(self, to_name, data_json)  -- 适配 MessageService
        """
        # 1. 检查是否为 data_json 命名参数调用
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
                # 如果是中继包裹包，展开提取原消息内容
                if msg.get("type") == "RELAY_MESSAGE":
                    orig = msg.get("original_message", msg.get("original_msg", {}))
                    msg_id = orig.get("msg_id", msg_id)
                    from_name = orig.get("from_name", from_name)
                    content = orig.get("content", content)
                    timestamp = orig.get("timestamp", timestamp)
                    relay_path = msg.get("relay_path", [])
            except Exception:
                return False
        # 2. 检查是否为 (to_name, data_json) 位置参数调用
        elif len(args) >= 2 and isinstance(args[1], str) and (args[1].startswith("{") or "type" in args[1]):
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
        # 3. 传统的详细参数调用
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
                cursor.execute("""
                    INSERT OR REPLACE INTO pending_messages
                    (msg_id, from_name, from_ip, to_name, content,
                     timestamp, relay_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    msg_id, from_name, from_ip, to_name, content,
                    timestamp, json.dumps(relay_path or [], ensure_ascii=False),
                ))
                self.conn.commit()
            return True
        except Exception as e:
            logger.error("添加待转发消息失败 [%s]: %s", msg_id, e)
            return False

    def get_pending_messages_for(self, name: str) -> List[Dict[str, Any]]:
        """
        获取发给指定好友的所有待转发消息。

        Args:
            name: 接收方用户名。

        Returns:
            待转发消息字典列表，按时间戳升序排列。
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT * FROM pending_messages
                WHERE to_name = ?
                ORDER BY timestamp ASC
            """, (name,))

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

        except Exception as e:
            logger.error("获取待转发消息失败 [%s]: %s", name, e)
            return []

    def remove_pending_message(self, msg_id: str) -> bool:
        """
        删除指定待转发消息（已成功转发后调用）。

        Args:
            msg_id: 消息唯一标识。

        Returns:
            True 表示删除成功。
        """
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute(
                    "DELETE FROM pending_messages WHERE msg_id = ?", (msg_id,)
                )
                self.conn.commit()
            return True

        except Exception as e:
            logger.error("删除待转发消息失败 [%s]: %s", msg_id, e)
            return False

    def clear_pending_messages(self) -> bool:
        """
        清空所有待转发消息。

        Returns:
            True 表示清空成功。
        """
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute("DELETE FROM pending_messages")
                self.conn.commit()
            return True

        except Exception as e:
            logger.error("清空待转发消息失败: %s", e)
            return False

    # ================================================================== #
    #  聊天记录
    # ================================================================== #

    def add_chat_message(self, friend_name: str, friend_ip: str,
                         direction: str, content: str,
                         timestamp: str, msg_id: str) -> bool:
        """
        添加一条聊天记录。

        Args:
            friend_name: 好友名字。
            friend_ip:   好友 IP 地址。
            direction:   消息方向，"send"（我发出的）或 "receive"（收到的）。
            content:     消息正文。
            timestamp:   消息时间戳。
            msg_id:      消息唯一标识。

        Returns:
            True 表示添加成功。
        """
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute("""
                    INSERT INTO chat_history
                    (friend_name, friend_ip, direction, content,
                     timestamp, msg_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (friend_name, friend_ip, direction, content,
                      timestamp, msg_id))
                self.conn.commit()
            return True

        except Exception as e:
            logger.error("添加聊天记录失败: %s", e)
            return False

    def get_chat_history(self, friend_name: str,
                         limit: int = 100) -> List[Dict[str, Any]]:
        """
        获取与指定好友的聊天记录。

        Args:
            friend_name: 好友名字。
            limit:       返回最大条数，默认 100。

        Returns:
            聊天记录字典列表，按时间戳升序排列（最早的在前）。
            每条包含 friend_name, friend_ip, direction, content,
            timestamp, msg_id 等字段。
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT * FROM chat_history
                WHERE friend_name = ?
                ORDER BY timestamp ASC
                LIMIT ?
            """, (friend_name, limit))

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

        except Exception as e:
            logger.error("获取聊天记录失败 [%s]: %s", friend_name, e)
            return []

    def clear_chat_history(self, friend_name: str) -> bool:
        """
        清空与指定好友的所有聊天记录。

        Args:
            friend_name: 好友名字。

        Returns:
            True 表示清空成功。
        """
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute("""
                    DELETE FROM chat_history WHERE friend_name = ?
                """, (friend_name,))
                self.conn.commit()
            return True

        except Exception as e:
            logger.error("清空聊天记录失败 [%s]: %s", friend_name, e)
            return False

    # ================================================================== #
    #  内部辅助方法
    # ================================================================== #

    @staticmethod
    def _row_to_friend_dict(row) -> Dict[str, Any]:
        """
        将数据库行转换为好友字典。

        自动将 tags 字段从 JSON 字符串解析为列表。

        Args:
            row: sqlite3.Row 对象。

        Returns:
            好友信息字典。
        """
        try:
            tags = json.loads(row["tags"])
        except (json.JSONDecodeError, TypeError):
            tags = []

        return {
            "id": row["id"],
            "user_id": (row["user_id"] if "user_id" in row.keys() else "") or "",
            "name": row["name"],
            "ip": row["ip"],
            "port": row["port"],
            "tags": tags,
            "bio": row["bio"] or "",
            "avatar": (row["avatar"] if "avatar" in row.keys() else "") or "",
            "background": (row["background"] if "background" in row.keys() else "") or "",
            "category": row["category"] or "朋友",
            "status": (row["status"] if "status" in row.keys() else "accepted") or "accepted",
            "added_at": row["added_at"],
            "last_seen": row["last_seen"],
        }

    @staticmethod
    def _row_to_request_dict(row) -> Dict[str, Any]:
        try:
            tags = json.loads(row["tags"])
        except (json.JSONDecodeError, TypeError):
            tags = []
        return {
            "id": row["id"],
            "user_id": row["user_id"] or "",
            "name": row["name"],
            "ip": row["ip"],
            "port": row["port"],
            "tags": tags,
            "bio": row["bio"] or "",
            "direction": row["direction"],
            "status": row["status"],
            "msg_id": row["msg_id"] or "",
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    # ================================================================== #
    #  个人资料管理与别名适配
    # ================================================================== #

    def get_my_profile(self) -> Dict[str, Any]:
        """
        获取本机的个人资料（包括基本资料和好友匹配条件）。
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM my_profile LIMIT 1")
            row = cursor.fetchone()

            if row:
                user_id = row["user_id"] if "user_id" in row.keys() else ""
                device_id = row["device_id"] if "device_id" in row.keys() else ""
                name = row["name"]
                tags = json.loads(row["tags"])
                bio = row["bio"]
                avatar = row["avatar"] if "avatar" in row.keys() else ""
                background = row["background"] if "background" in row.keys() else ""
                if not user_id or not device_id:
                    user_id = user_id or self._new_id("user")
                    device_id = device_id or self._new_id("device")
                    with self._lock:
                        cursor.execute(
                            "UPDATE my_profile SET user_id = ?, device_id = ? WHERE id = ?",
                            (user_id, device_id, row["id"]),
                        )
                        self.conn.commit()
            else:
                import socket
                user_id = self._new_id("user")
                device_id = self._new_id("device")
                name = socket.gethostname()
                tags = []
                bio = ""
                avatar = ""
                background = ""
                with self._lock:
                    cursor.execute(
                        "INSERT INTO my_profile (user_id, device_id, name, tags, bio, avatar, background) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (user_id, device_id, name, "[]", "", "", ""),
                    )
                    self.conn.commit()

            conditions = self.get_conditions()
            return {
                "user_id": user_id,
                "device_id": device_id,
                "name": name,
                "tags": tags,
                "bio": bio,
                "avatar": avatar,
                "background": background,
                "conditions": conditions,
            }
        except Exception as e:
            logger.error("获取个人资料失败: %s", e)
            import socket
            return {
                "user_id": "",
                "device_id": "",
                "name": socket.gethostname(),
                "tags": [],
                "bio": "",
                "avatar": "",
                "background": "",
                "conditions": {},
            }

    def save_profile(self, profile: Dict[str, Any]) -> bool:
        """
        保存本机个人资料及好友条件。

        整个写入过程（读取已有数据 → 写入新数据 → 保存条件）在同一把锁
        内完成，避免并发 save_profile 造成数据覆盖或条件与资料不一致。
        """
        try:
            required_tags = profile.get("conditions", {}).get("required_tags", [])
            optional_tags = profile.get("conditions", {}).get("optional_tags", [])
            min_match = profile.get("conditions", {}).get("min_match_count", 1)
            auto_accept = profile.get("conditions", {}).get("auto_accept", False)

            with self._lock:
                cursor = self.conn.cursor()

                # 读取已存在的 user_id / device_id（避免每次保存都重新生成）
                cursor.execute("SELECT * FROM my_profile LIMIT 1")
                existing = cursor.fetchone()
                existing_user_id = (
                    existing["user_id"]
                    if existing and "user_id" in existing.keys()
                    else ""
                )
                existing_device_id = (
                    existing["device_id"]
                    if existing and "device_id" in existing.keys()
                    else ""
                )
                user_id = (
                    profile.get("user_id")
                    or existing_user_id
                    or self._new_id("user")
                )
                device_id = (
                    profile.get("device_id")
                    or existing_device_id
                    or self._new_id("device")
                )
                name = profile.get("name", "Unknown")
                tags = profile.get("tags", [])
                bio = profile.get("bio", "")
                avatar = profile.get("avatar", "")
                background = profile.get("background", "")

                # 更新个人资料（单行 —— DELETE + INSERT）
                cursor.execute("DELETE FROM my_profile")
                cursor.execute(
                    "INSERT INTO my_profile (user_id, device_id, name, tags,"
                    " bio, avatar, background) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        user_id,
                        device_id,
                        name,
                        json.dumps(tags, ensure_ascii=False),
                        bio,
                        avatar,
                        background,
                    ),
                )

                # ---- 好友匹配条件（在同一事务中保存，保证原子性）---- #
                cursor.execute("DELETE FROM friend_conditions")
                cursor.execute(
                    "INSERT INTO friend_conditions"
                    " (required_tags, optional_tags, min_match_count, auto_accept)"
                    " VALUES (?, ?, ?, ?)",
                    (
                        json.dumps(required_tags, ensure_ascii=False),
                        json.dumps(optional_tags, ensure_ascii=False),
                        min_match,
                        1 if auto_accept else 0,
                    ),
                )

                self.conn.commit()

            return True
        except Exception as e:
            logger.error("保存个人资料失败: %s", e)
            return False

    def get_friend(self, name: str) -> Optional[Dict[str, Any]]:
        """别名：根据名字查找好友。"""
        return self.get_friend_by_name(name)

    def get_friend_conditions(self) -> Dict[str, Any]:
        """别名：获取好友匹配条件。"""
        return self.get_conditions()

    def get_pending_messages(self, name: str) -> List[Dict[str, Any]]:
        """别名：获取指定好友的待转发消息。"""
        return self.get_pending_messages_for(name)

    def clear_pending_messages(self, name: Optional[str] = None) -> bool:
        """
        清除待转发消息。如果指定了名字，则只清除发给该好友的消息，否则清除全部。
        """
        try:
            with self._lock:
                cursor = self.conn.cursor()
                if name:
                    cursor.execute("DELETE FROM pending_messages WHERE to_name = ?", (name,))
                else:
                    cursor.execute("DELETE FROM pending_messages")
                self.conn.commit()
            return True
        except Exception as e:
            logger.error("清除待转发消息失败: %s", e)
            return False

    def get_app_setting(self, key: str, default: str = "") -> str:
        """读取本机应用设置。"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else default
        except Exception as e:
            logger.error("读取应用设置失败 [%s]: %s", key, e)
            return default

    def set_app_setting(self, key: str, value: str) -> bool:
        """保存本机应用设置。"""
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO app_settings (key, value)
                    VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (key, value),
                )
                self.conn.commit()
            return True
        except Exception as e:
            logger.error("保存应用设置失败 [%s]: %s", key, e)
            return False

    def save_chat_message(self, from_name: str, to_name: str,
                          content: str, timestamp: str, msg_id: str) -> bool:
        """
        保存聊天消息。自动判断收发方向并解析对端 IP。
        """
        try:
            my_profile = self.get_my_profile()
            my_name = my_profile.get("name", "")

            if to_name == my_name:
                friend_name = from_name
                direction = "receive"
            else:
                friend_name = to_name
                direction = "send"

            friend = self.get_friend(friend_name)
            friend_ip = friend.get("ip", "") if friend else ""

            return self.add_chat_message(
                friend_name=friend_name,
                friend_ip=friend_ip,
                direction=direction,
                content=content,
                timestamp=timestamp,
                msg_id=msg_id,
            )
        except Exception as e:
            logger.error("保存聊天消息失败: %s", e)
            return False

    def check_msg_id(self, msg_id: str) -> bool:
        """
        检查指定 msg_id 是否已处理过。
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT 1 FROM received_msg_ids WHERE msg_id = ?", (msg_id,))
            return cursor.fetchone() is not None
        except Exception as e:
            logger.error("检查 msg_id 失败: %s", e)
            return False

    def record_msg_id(self, msg_id: str) -> bool:
        """
        记录已处理的 msg_id。
        """
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
        except Exception as e:
            logger.error("记录 msg_id 失败: %s", e)
            return False

    def check_conditions_match(self, profile: Dict[str, Any]) -> bool:
        """
        检查给定的用户资料是否满足我方好友匹配条件。
        """
        try:
            my_cond = self.get_conditions()
            if not my_cond:
                return True  # 无条件则默认匹配

            required_tags = my_cond.get("required_tags", [])
            optional_tags = my_cond.get("optional_tags", [])
            min_match = my_cond.get("min_match_count", 1)

            friend_tags = profile.get("tags", [])

            # 1. 必须匹配的标签检查
            for tag in required_tags:
                if tag not in friend_tags:
                    return False

            # 2. 计算总匹配标签数（包括必选 and 可选）
            all_cond_tags = set(required_tags + optional_tags)
            matched = [tag for tag in friend_tags if tag in all_cond_tags]

            return len(matched) >= min_match
        except Exception as e:
            logger.error("条件匹配检查失败: %s", e)
            return False

    # ================================================================== #
    #  群组与群聊管理
    # ================================================================== #

    def save_group(self, group_id: str, group_name: str, members: List[str], owner: str = "", only_owner_manage: int = 0) -> bool:
        """保存或更新群组。"""
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
        except Exception as e:
            logger.error("保存群组失败: %s", e)
            return False

    def get_group(self, group_id: str) -> Optional[Dict[str, Any]]:
        """获取群组详情。"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM groups WHERE group_id = ?", (group_id,))
            row = cursor.fetchone()
            if row:
                res = dict(row)
                try:
                    res["members"] = json.loads(res["members"])
                except Exception:
                    res["members"] = []
                return res
            return None
        except Exception as e:
            logger.error("获取群组失败: %s", e)
            return None

    def get_all_groups(self) -> List[Dict[str, Any]]:
        """获取所有群组。"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM groups ORDER BY created_at DESC")
            rows = cursor.fetchall()
            results = []
            for r in rows:
                res = dict(r)
                try:
                    res["members"] = json.loads(res["members"])
                except Exception:
                    res["members"] = []
                results.append(res)
            return results
        except Exception as e:
            logger.error("获取所有群组失败: %s", e)
            return []

    def save_group_chat_message(self, msg_id: str, group_id: str, sender: str, content: str, timestamp: str) -> bool:
        """保存群聊消息。"""
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
        except Exception as e:
            logger.error("保存群消息失败: %s", e)
            return False

    def get_group_chat_history(self, group_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """获取群聊历史记录。"""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT * FROM group_chat_history WHERE group_id = ? ORDER BY timestamp ASC",
                (group_id,),
            )
            rows = cursor.fetchall()
            results = [dict(r) for r in rows]
            if len(results) > limit:
                results = results[-limit:]
            return results
        except Exception as e:
            logger.error("获取群消息历史失败: %s", e)
            return []

    def has_group_message(self, msg_id: str) -> bool:
        """检查是否已经接收过该群消息。"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT 1 FROM group_chat_history WHERE msg_id = ?", (msg_id,))
            return cursor.fetchone() is not None
        except Exception as e:
            logger.error("检查群消息ID失败: %s", e)
            return False

    # ================================================================== #
    #  空间发帖管理
    # ================================================================== #

    def save_moment(self, post_id: str, author: str, content: str, media_path: str, timestamp: str) -> bool:
        """保存或更新空间发帖。"""
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
        except Exception as e:
            logger.error("保存空间发帖失败: %s", e)
            return False

    def get_moments(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取所有的空间发帖，按时间倒序排列。"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM moments ORDER BY timestamp DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error("获取空间发帖失败: %s", e)
            return []

    def has_moment(self, post_id: str) -> bool:
        """检查本地是否已存在该空间发帖。"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT 1 FROM moments WHERE post_id = ?", (post_id,))
            return cursor.fetchone() is not None
        except Exception as e:
            logger.error("检查空间发帖ID失败: %s", e)
            return False
