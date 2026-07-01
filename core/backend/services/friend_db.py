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
from core.backend.services.friend_category_repository import FriendCategoryRepository
from core.backend.services.friend_repository import FriendRepository
from core.backend.services.friend_request_repository import FriendRequestRepository
from core.backend.services.message_repository import MessageRepository
from core.backend.services.notification_repository import NotificationRepository
from core.backend.services.profile_repository import ProfileRepository
from core.backend.services.social_repository import SocialRepository

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
        self.friends = FriendRepository(self)
        self.friend_categories = FriendCategoryRepository(self)
        self.friend_requests = FriendRequestRepository(self)
        self.messages = MessageRepository(self)
        self.notifications = NotificationRepository(self)
        self.profile = ProfileRepository(self)
        self.social = SocialRepository(self)
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

            # ---- 好友分组表 ---- #
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS friend_categories (
                    name        TEXT    PRIMARY KEY,
                    sort_order  INTEGER DEFAULT 0,
                    color       TEXT    DEFAULT '',
                    icon        TEXT    DEFAULT '',
                    created_at  TEXT    NOT NULL
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
            try:
                cursor.execute("ALTER TABLE my_profile ADD COLUMN card_bg TEXT DEFAULT ''")
            except Exception:
                pass
            try:
                cursor.execute("ALTER TABLE friends ADD COLUMN card_bg TEXT DEFAULT ''")
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
            # ---- 空间动态评论表 ---- #
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS moment_comments (
                    comment_id  TEXT    PRIMARY KEY,
                    post_id     TEXT    NOT NULL,
                    author      TEXT    NOT NULL,
                    content     TEXT    NOT NULL,
                    timestamp   TEXT    NOT NULL,
                    created_at  TEXT    NOT NULL,
                    FOREIGN KEY(post_id) REFERENCES moments(post_id) ON DELETE CASCADE
                )
            """)
            # ---- 系统通知表 ---- #
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS system_notifications (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    title       TEXT    NOT NULL,
                    content     TEXT    NOT NULL,
                    category    TEXT    DEFAULT 'info',
                    timestamp   TEXT    NOT NULL,
                    is_read     INTEGER DEFAULT 0
                )
            """)

            self.conn.commit()
            self._migrate_friend_categories()
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
                   background: str = "", card_bg: str = "") -> bool:
        return self.friends.add_friend(
            name, ip, port, tags, bio, category, user_id, status, avatar, background, card_bg
        )

    def _repair_blank_friend_names(self) -> None:
        self.friends.repair_blank_friend_names()

    def _migrate_friend_categories(self) -> None:
        self.friend_categories.migrate_friend_categories()

    def update_friend_avatar(
        self,
        name: str = "",
        avatar: str = "",
        user_id: str = "",
    ) -> bool:
        return self.friends.update_friend_avatar(name=name, avatar=avatar, user_id=user_id)

    def update_friend_card_bg(
        self,
        name: str = "",
        card_bg: str = "",
        user_id: str = "",
    ) -> bool:
        return self.friends.update_friend_card_bg(name=name, card_bg=card_bg, user_id=user_id)

    def remove_friend(self, name: str) -> bool:
        return self.friends.remove_friend(name)

    def get_friends(self) -> List[Dict[str, Any]]:
        return self.friends.get_friends()

    def get_friend_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        return self.friends.get_friend_by_name(name)

    def get_friend_by_ip(self, ip: str) -> Optional[Dict[str, Any]]:
        return self.friends.get_friend_by_ip(ip)

    def get_friend_by_user_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        return self.friends.get_friend_by_user_id(user_id)

    def get_friend_by_endpoint(self, ip: str, port: int) -> Optional[Dict[str, Any]]:
        return self.friends.get_friend_by_endpoint(ip, port)

    def update_friend_ip(self, name: str, new_ip: str) -> bool:
        return self.friends.update_friend_ip(name, new_ip)

    def set_friend_category(self, name: str, category: str) -> bool:
        return self.friend_categories.set_friend_category(name, category)

    def add_friend_category(
        self,
        name: str,
        color: str = "",
        icon: str = "",
    ) -> bool:
        return self.friend_categories.add_friend_category(name, color=color, icon=icon)

    def delete_friend_category(self, name: str, fallback: str = "朋友") -> bool:
        return self.friend_categories.delete_friend_category(name, fallback=fallback)

    def get_friend_category_records(self) -> List[Dict[str, Any]]:
        return self.friend_categories.get_friend_category_records()

    def get_friend_categories(self) -> List[str]:
        return self.friend_categories.get_friend_categories()

    def update_friend_last_seen(self, name: str) -> bool:
        return self.friends.update_friend_last_seen(name)

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
        return self.friend_requests.upsert_friend_request(
            name, ip, port, tags, bio, direction, status, user_id, msg_id
        )

    def get_friend_request(
        self,
        user_id: str = "",
        name: str = "",
        ip: str = "",
        port: int = 0,
    ) -> Optional[Dict[str, Any]]:
        return self.friend_requests.get_friend_request(user_id=user_id, name=name, ip=ip, port=port)

    def set_friend_request_status(
        self,
        status: str,
        user_id: str = "",
        name: str = "",
        ip: str = "",
        port: int = 0,
    ) -> bool:
        return self.friend_requests.set_friend_request_status(
            status, user_id=user_id, name=name, ip=ip, port=port
        )

    def get_relationship_status(
        self,
        user_id: str = "",
        name: str = "",
        ip: str = "",
        port: int = 0,
    ) -> str:
        return self.friend_requests.get_relationship_status(user_id=user_id, name=name, ip=ip, port=port)

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
        return self.messages.add_pending_message(*args, **kwargs)

    def get_pending_messages_for(self, name: str) -> List[Dict[str, Any]]:
        return self.messages.get_pending_messages_for(name)

    def remove_pending_message(self, msg_id: str) -> bool:
        return self.messages.remove_pending_message(msg_id)


    # ================================================================== #
    #  聊天记录
    # ================================================================== #

    def add_chat_message(self, friend_name: str, friend_ip: str,
                         direction: str, content: str,
                         timestamp: str, msg_id: str) -> bool:
        return self.messages.add_chat_message(
            friend_name, friend_ip, direction, content, timestamp, msg_id
        )

    def get_chat_history(self, friend_name: str,
                         limit: int = 100) -> List[Dict[str, Any]]:
        return self.messages.get_chat_history(friend_name, limit)

    def clear_chat_history(self, friend_name: str) -> bool:
        return self.messages.clear_chat_history(friend_name)

    def delete_chat_message(self, msg_id: str) -> bool:
        return self.messages.delete_chat_message(msg_id)

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
            "card_bg": (row["card_bg"] if "card_bg" in row.keys() else "") or "",
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
        return self.profile.get_my_profile()

    def save_profile(self, profile: Dict[str, Any]) -> bool:
        return self.profile.save_profile(profile)

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
        return self.messages.clear_pending_messages(name)

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
        如果已存在相同 msg_id 的消息，则直接更新其内容，避免重复插入。
        """
        try:
            existing_content = self.get_chat_message_content(msg_id)
            if existing_content is not None:
                return self.update_chat_message_content(msg_id, content)

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

    def get_chat_message_content(self, msg_id: str) -> Optional[str]:
        return self.messages.get_chat_message_content(msg_id)

    def update_chat_message_content(self, msg_id: str, new_content: str) -> bool:
        return self.messages.update_chat_message_content(msg_id, new_content)

    def delete_group_chat_message(self, msg_id: str) -> bool:
        return self.messages.delete_group_chat_message(msg_id)

    def check_msg_id(self, msg_id: str) -> bool:
        return self.messages.check_msg_id(msg_id)

    def record_msg_id(self, msg_id: str) -> bool:
        return self.messages.record_msg_id(msg_id)

    def check_conditions_match(self, profile: Dict[str, Any]) -> bool:
        return self.profile.check_conditions_match(profile)

    def save_group(self, group_id: str, group_name: str, members: List[str], owner: str = "", only_owner_manage: int = 0) -> bool:
        return self.social.save_group(group_id, group_name, members, owner, only_owner_manage)

    def get_group(self, group_id: str) -> Optional[Dict[str, Any]]:
        return self.social.get_group(group_id)

    def get_all_groups(self) -> List[Dict[str, Any]]:
        return self.social.get_all_groups()

    def save_group_chat_message(self, msg_id: str, group_id: str, sender: str, content: str, timestamp: str) -> bool:
        return self.social.save_group_chat_message(msg_id, group_id, sender, content, timestamp)

    def get_group_chat_history(self, group_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        return self.social.get_group_chat_history(group_id, limit)

    def has_group_message(self, msg_id: str) -> bool:
        return self.social.has_group_message(msg_id)

    # ================================================================== #
    #  空间发帖管理
    # ================================================================== #

    def save_moment(self, post_id: str, author: str, content: str, media_path: str, timestamp: str) -> bool:
        return self.social.save_moment(post_id, author, content, media_path, timestamp)

    def get_moments(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self.social.get_moments(limit)

    def has_moment(self, post_id: str) -> bool:
        return self.social.has_moment(post_id)

    def delete_moment(self, post_id: str) -> bool:
        return self.social.delete_moment(post_id)

    def save_moment_comment(self, comment_id: str, post_id: str, author: str, content: str, timestamp: str) -> bool:
        return self.social.save_moment_comment(comment_id, post_id, author, content, timestamp)

    def get_moment_comments(self, post_id: str) -> List[Dict[str, Any]]:
        return self.social.get_moment_comments(post_id)

    def delete_moment_comment(self, comment_id: str) -> bool:
        return self.social.delete_moment_comment(comment_id)

    # ================================================================== #
    #  系统通知管理
    # ================================================================== #

    def add_system_notification(self, title: str, content: str, category: str = "info") -> bool:
        return self.notifications.add_system_notification(title, content, category)

    def get_system_notifications(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self.notifications.get_system_notifications(limit)

    def clear_system_notifications(self) -> bool:
        return self.notifications.clear_system_notifications()

    def mark_all_notifications_read(self) -> bool:
        return self.notifications.mark_all_notifications_read()

    def mark_notification_read(self, notif_id: int) -> bool:
        return self.notifications.mark_notification_read(notif_id)
