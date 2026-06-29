"""
社交应用门面服务。

这个服务把 UI 需要的社交状态整理成稳定的卡片数据，避免各个 Screen
直接读数据库、连接池和发现服务后各自推断关系。
"""

from typing import Any, Dict, List

from core.backend.shared.protocol import Protocol


class SocialService:
    """统一组织发现、好友、在线状态和聊天列表的读取逻辑。"""

    def __init__(self, friend_db, connection_manager, udp_service):
        self.friend_db = friend_db
        self.connection_manager = connection_manager
        self.udp_service = udp_service

    def get_discovered_cards(
        self,
        my_user_id: str = "",
        my_name: str = "",
        my_device_id: str = "",
        my_tcp_port: int = Protocol.DEFAULT_TCP_PORT,
    ) -> List[Dict[str, Any]]:
        if not self.udp_service:
            return []

        cards = []
        with self.udp_service._devices_lock:
            devices = list(self.udp_service.devices.values())

        for dev in devices:
            if not dev.is_online():
                continue

            user_id = getattr(dev, "user_id", "")
            device_id = getattr(dev, "device_id", "")
            if device_id and my_device_id and device_id == my_device_id:
                continue
            if (
                not device_id
                and dev.device_name == my_name
                and int(dev.tcp_port or Protocol.DEFAULT_TCP_PORT) == int(my_tcp_port or Protocol.DEFAULT_TCP_PORT)
            ):
                continue

            status = self.friend_db.get_relationship_status(
                user_id=user_id,
                name=dev.device_name,
                ip=dev.ip,
                port=dev.tcp_port,
            )
            if status == "accepted":
                continue

            cards.append({
                "user_id": user_id,
                "device_id": device_id,
                "name": dev.device_name,
                "ip": dev.ip,
                "tcp_port": dev.tcp_port,
                "candidate_ips": getattr(dev, "candidate_ips", []),
                "status": status,
                "status_label": self._relationship_label(status),
                "can_request": status in ("none", "rejected"),
                "can_chat": False,
            })

        # Deduplicate by stable identity (user_id/device_id) or name, merging
        # duplicates that may be in transition (e.g. empty user_id vs filled).
        deduped: List[Dict[str, Any]] = []
        for card in cards:
            matched_index = -1
            for idx, existing in enumerate(deduped):
                if card.get("user_id") and existing.get("user_id") and card["user_id"] == existing["user_id"]:
                    matched_index = idx
                    break
                if card.get("device_id") and existing.get("device_id") and card["device_id"] == existing["device_id"]:
                    matched_index = idx
                    break
                # Only match by name if there is no conflict in IDs or endpoints (different ports on same IP)
                if card["name"] == existing["name"]:
                    card_uid = card.get("user_id")
                    exist_uid = existing.get("user_id")
                    card_did = card.get("device_id")
                    exist_did = existing.get("device_id")
                    
                    has_id_conflict = (
                        (card_uid and exist_uid and card_uid != exist_uid) or
                        (card_did and exist_did and card_did != exist_did)
                    )
                    has_endpoint_conflict = (
                        card.get("ip") == existing.get("ip") and
                        card.get("tcp_port") != existing.get("tcp_port")
                    )
                    
                    if not has_id_conflict and not has_endpoint_conflict:
                        # For different IPs, only merge if at least one lacks IDs (fallback transition card)
                        if card.get("ip") == existing.get("ip") or not (card_uid or card_did) or not (exist_uid or exist_did):
                            matched_index = idx
                            break

            if matched_index == -1:
                deduped.append(card)
            else:
                existing = deduped[matched_index]
                existing_has_id = bool(existing.get("user_id") or existing.get("device_id"))
                card_has_id = bool(card.get("user_id") or card.get("device_id"))

                replace = False
                if card_has_id and not existing_has_id:
                    replace = True
                elif existing_has_id and not card_has_id:
                    replace = False
                elif card.get("ip") == "127.0.0.1" and existing.get("ip") != "127.0.0.1":
                    replace = True

                if replace:
                    deduped[matched_index] = card
        cards = deduped

        return sorted(cards, key=lambda item: (item["status"] != "none", item["name"]))

    def get_friend_cards(self) -> List[Dict[str, Any]]:
        friends = self.friend_db.get_friends() if self.friend_db else []
        cards = []
        seen_names = set()
        for friend in friends:
            status = friend.get("status", "accepted") or "accepted"
            if status != "accepted":
                continue
            name = friend.get("name", "")
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            port = int(friend.get("port", Protocol.DEFAULT_TCP_PORT) or Protocol.DEFAULT_TCP_PORT)
            endpoint = f"{friend.get('ip', '')}:{port}" if friend.get("ip") else ""
            online = False
            if self.connection_manager:
                online = self.connection_manager.is_friend_online(name)
                if not online and endpoint:
                    online = self.connection_manager.is_connected(friend.get("ip", ""), port)
            cards.append({
                "user_id": friend.get("user_id", ""),
                "name": name,
                "ip": friend.get("ip", ""),
                "port": port,
                "tags": friend.get("tags", []),
                "bio": friend.get("bio", ""),
                "avatar": friend.get("avatar", ""),
                "background": friend.get("background", ""),
                "category": friend.get("category", "朋友"),
                "last_seen": friend.get("last_seen", ""),
                "online": online,
                "status": "accepted",
                "can_chat": True,
            })
        return sorted(cards, key=lambda item: (not item["online"], item["name"]))

    def get_online_friend_cards(self) -> List[Dict[str, Any]]:
        return [friend for friend in self.get_friend_cards() if friend.get("online")]

    def get_chat_list(self) -> List[Dict[str, Any]]:
        if not self.friend_db:
            return []
        cursor = self.friend_db.conn.cursor()
        cursor.execute("""
            SELECT friend_name, content, timestamp
            FROM chat_history
            WHERE id IN (
                SELECT MAX(id)
                FROM chat_history
                GROUP BY friend_name
            )
            ORDER BY timestamp DESC
        """)
        rows = cursor.fetchall()

        friend_cards = {friend["name"]: friend for friend in self.get_friend_cards()}
        seen = set()
        chat_list = []
        for row in rows:
            name = row["friend_name"]
            seen.add(name)
            friend = friend_cards.get(name, {})
            chat_list.append({
                "user_id": friend.get("user_id", ""),
                "name": name,
                "online": friend.get("online", False),
                "avatar": friend.get("avatar", ""),
                "last_message": row["content"],
                "time": row["timestamp"][-8:] if len(row["timestamp"]) >= 8 else row["timestamp"],
                "unread": self.get_pending_message_count(name),
                "raw_time": row["timestamp"],
            })
        for name, friend in friend_cards.items():
            if name in seen:
                continue
            chat_list.append({
                "user_id": friend.get("user_id", ""),
                "name": name,
                "online": friend.get("online", False),
                "avatar": friend.get("avatar", ""),
                "last_message": "可以开始聊天",
                "time": "",
                "unread": self.get_pending_message_count(name),
                "raw_time": "1970-01-01 00:00:00",
            })

        # Query all groups and add them
        try:
            cursor.execute("SELECT * FROM groups")
            group_rows = cursor.fetchall()
            for g_row in group_rows:
                group_id = g_row["group_id"]
                group_name = g_row["group_name"]

                cursor.execute("""
                    SELECT sender, content, timestamp FROM group_chat_history
                    WHERE group_id = ? ORDER BY timestamp DESC LIMIT 1
                """, (group_id,))
                msg_row = cursor.fetchone()

                if msg_row:
                    last_message = f"{msg_row['sender']}: {msg_row['content']}"
                    raw_time = msg_row["timestamp"]
                    last_time = raw_time[-8:] if len(raw_time) >= 8 else raw_time
                else:
                    last_message = "群聊已创建"
                    raw_time = g_row["created_at"]
                    last_time = ""

                chat_list.append({
                    "user_id": group_id,
                    "name": group_name,
                    "is_group": True,
                    "group_id": group_id,
                    "online": True,
                    "avatar": "group",
                    "last_message": last_message,
                    "time": last_time,
                    "raw_time": raw_time,
                    "unread": 0,
                })
        except Exception:
            pass

        chat_list.sort(key=lambda x: x.get("raw_time", ""), reverse=True)
        return chat_list

    def get_pending_message_count(self, friend_name: str = "") -> int:
        try:
            cursor = self.friend_db.conn.cursor()
            if friend_name:
                cursor.execute("SELECT COUNT(*) FROM pending_messages WHERE to_name = ?", (friend_name,))
            else:
                cursor.execute("SELECT COUNT(*) FROM pending_messages")
            row = cursor.fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    @staticmethod
    def _relationship_label(status: str) -> str:
        return {
            "none": "可添加",
            "pending_sent": "已发送",
            "pending_received": "待处理",
            "accepted": "已是好友",
            "rejected": "可重试",
        }.get(status, "可添加")
