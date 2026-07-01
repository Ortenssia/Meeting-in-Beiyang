"""Profile persistence and matching logic for FriendDB."""

import json
import logging
import socket
from typing import Any, Dict


logger = logging.getLogger(__name__)


class ProfileRepository:
    """Store the local profile and friend-matching conditions."""

    def __init__(self, db):
        self.db = db

    def get_my_profile(self) -> Dict[str, Any]:
        """Return the local profile, creating a default row when needed."""
        try:
            cursor = self.db.conn.cursor()
            cursor.execute("SELECT * FROM my_profile ORDER BY id ASC LIMIT 1")
            row = cursor.fetchone()

            if row:
                user_id = row["user_id"] if "user_id" in row.keys() else ""
                device_id = row["device_id"] if "device_id" in row.keys() else ""
                name = row["name"]
                tags = json.loads(row["tags"] or "[]")
                bio = row["bio"]
                avatar = row["avatar"] if "avatar" in row.keys() else ""
                background = row["background"] if "background" in row.keys() else ""
                card_bg = row["card_bg"] if "card_bg" in row.keys() else ""
                with self.db._lock:
                    cursor.execute("DELETE FROM my_profile WHERE id != ?", (row["id"],))
                    if not user_id or not device_id:
                        user_id = user_id or self.db._new_id("user")
                        device_id = device_id or self.db._new_id("device")
                        cursor.execute(
                            "UPDATE my_profile SET user_id = ?, device_id = ? WHERE id = ?",
                            (user_id, device_id, row["id"]),
                        )
                    self.db.conn.commit()
            else:
                user_id = self.db._new_id("user")
                device_id = self.db._new_id("device")
                name = socket.gethostname()
                tags = []
                bio = ""
                avatar = ""
                background = ""
                card_bg = ""
                with self.db._lock:
                    cursor.execute(
                        "INSERT INTO my_profile (user_id, device_id, name, tags, bio, avatar, background, card_bg) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (user_id, device_id, name, "[]", "", "", "", ""),
                    )
                    self.db.conn.commit()

            return {
                "user_id": user_id,
                "device_id": device_id,
                "name": name,
                "tags": tags,
                "bio": bio,
                "avatar": avatar,
                "background": background,
                "card_bg": card_bg,
                "conditions": self.db.get_conditions(),
            }
        except Exception as exc:
            logger.error("获取个人资料失败: %s", exc)
            return {
                "user_id": "",
                "device_id": "",
                "name": socket.gethostname(),
                "tags": [],
                "bio": "",
                "avatar": "",
                "background": "",
                "card_bg": "",
                "conditions": {},
            }

    def save_profile(self, profile: Dict[str, Any]) -> bool:
        """Save local profile and friend-matching conditions atomically."""
        try:
            required_tags = profile.get("conditions", {}).get("required_tags", [])
            optional_tags = profile.get("conditions", {}).get("optional_tags", [])
            min_match = profile.get("conditions", {}).get("min_match_count", 1)
            auto_accept = profile.get("conditions", {}).get("auto_accept", False)

            with self.db._lock:
                cursor = self.db.conn.cursor()
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
                user_id = profile.get("user_id") or existing_user_id or self.db._new_id("user")
                device_id = profile.get("device_id") or existing_device_id or self.db._new_id("device")
                name = profile.get("name", "Unknown")
                tags = profile.get("tags", [])
                bio = profile.get("bio", "")
                avatar = profile.get("avatar", "")
                background = profile.get("background", "")
                card_bg = profile.get("card_bg", "")

                cursor.execute("DELETE FROM my_profile")
                cursor.execute(
                    "INSERT INTO my_profile (user_id, device_id, name, tags,"
                    " bio, avatar, background, card_bg) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        user_id,
                        device_id,
                        name,
                        json.dumps(tags, ensure_ascii=False),
                        bio,
                        avatar,
                        background,
                        card_bg,
                    ),
                )

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
                self.db.conn.commit()

            return True
        except Exception as exc:
            logger.error("保存个人资料失败: %s", exc)
            return False

    def check_conditions_match(self, profile: Dict[str, Any]) -> bool:
        """Return whether a remote profile satisfies my friend conditions."""
        try:
            my_cond = self.db.get_conditions()
            if not my_cond:
                return True

            required_tags = my_cond.get("required_tags", [])
            optional_tags = my_cond.get("optional_tags", [])
            min_match = my_cond.get("min_match_count", 1)
            friend_tags = profile.get("tags", [])

            for tag in required_tags:
                if tag not in friend_tags:
                    return False

            all_cond_tags = set(required_tags + optional_tags)
            matched = [tag for tag in friend_tags if tag in all_cond_tags]
            return len(matched) >= min_match
        except Exception as exc:
            logger.error("条件匹配检查失败: %s", exc)
            return False
