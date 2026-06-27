"""
社交应用门面服务。

这个服务把 UI 需要的社交状态整理成稳定的卡片数据，避免各个 Screen
直接读数据库、连接池和发现服务后各自推断关系。
"""

from typing import Any, Dict, List

try:
    from ..utils.protocol import Protocol
except ImportError:
    from utils.protocol import Protocol


class SocialService:
    """统一组织发现、好友、在线状态和聊天列表的读取逻辑。"""

    def __init__(self, friend_db, connection_manager, udp_service):
        self.friend_db = friend_db
        self.connection_manager = connection_manager
        self.udp_service = udp_service

    def get_discovered_cards(self, my_user_id: str = "", my_name: str = "") -> List[Dict[str, Any]]:
        if not self.udp_service:
            return []

        cards = []
        with self.udp_service._devices_lock:
            devices = list(self.udp_service.devices.values())

        for dev in devices:
            if not dev.is_online():
                continue

            user_id = getattr(dev, "user_id", "")
            if (user_id and user_id == my_user_id) or (not user_id and dev.device_name == my_name):
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
                "device_id": getattr(dev, "device_id", ""),
                "name": dev.device_name,
                "ip": dev.ip,
                "tcp_port": dev.tcp_port,
                "status": status,
                "status_label": self._relationship_label(status),
                "can_request": status in ("none", "rejected"),
                "can_chat": False,
            })

        return sorted(cards, key=lambda item: (item["status"] != "none", item["name"]))

    def get_friend_cards(self) -> List[Dict[str, Any]]:
        friends = self.friend_db.get_friends() if self.friend_db else []
        cards = []
        for friend in friends:
            if friend.get("status", "accepted") != "accepted":
                continue
            name = friend.get("name", "")
            online = self.connection_manager.is_friend_online(name) if self.connection_manager else False
            cards.append({
                "user_id": friend.get("user_id", ""),
                "name": name,
                "ip": friend.get("ip", ""),
                "port": int(friend.get("port", Protocol.DEFAULT_TCP_PORT) or Protocol.DEFAULT_TCP_PORT),
                "tags": friend.get("tags", []),
                "bio": friend.get("bio", ""),
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
                "last_message": row["content"],
                "time": row["timestamp"][-8:] if len(row["timestamp"]) >= 8 else row["timestamp"],
                "unread": self.get_pending_message_count(name),
            })
        for name, friend in friend_cards.items():
            if name in seen:
                continue
            chat_list.append({
                "user_id": friend.get("user_id", ""),
                "name": name,
                "online": friend.get("online", False),
                "last_message": "可以开始聊天",
                "time": "",
                "unread": self.get_pending_message_count(name),
            })
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
