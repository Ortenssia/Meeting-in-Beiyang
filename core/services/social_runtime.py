"""
P2P social runtime orchestration.

This module owns the service lifecycle and cross-service reactions. Screens and
the Kivy App should not need to know how UDP discovery, TCP connections,
relationship storage, message relay, and file transfer are wired together.
"""

from dataclasses import dataclass
import threading
from typing import Callable, Optional

try:
    from .connection_manager import ConnectionManager
    from .friend_db import FriendDB
    from .message_service import MessageService
    from .social_service import SocialService
    from .udp_service import UDPService
    from ..utils.helpers import Helpers
    from ..utils.protocol import Protocol
except ImportError:
    from services.connection_manager import ConnectionManager
    from services.friend_db import FriendDB
    from services.message_service import MessageService
    from services.social_service import SocialService
    from services.udp_service import UDPService
    from utils.helpers import Helpers
    from utils.protocol import Protocol


@dataclass
class RuntimeConfig:
    tcp_port: int = Protocol.DEFAULT_TCP_PORT
    udp_port: int = Protocol.DEFAULT_UDP_PORT
    db_path: str = "assets/data/friends.db"
    name_override: str = ""
    receive_dir: str = "assets/received_files"


class SocialRuntime:
    """Coordinates identity, discovery, relationships, messaging, and files."""

    def __init__(self, config: RuntimeConfig):
        self.config = config
        self.device_name = (config.name_override or "").strip() or Helpers.get_hostname()
        self.user_id = ""
        self.device_id = ""
        self.custom_background = ""
        self.custom_avatar = ""

        self.friend_db: Optional[FriendDB] = None
        self.connection_manager: Optional[ConnectionManager] = None
        self.udp_service: Optional[UDPService] = None
        self.message_service: Optional[MessageService] = None
        self.social_service: Optional[SocialService] = None

        self.on_discovery_changed: Optional[Callable[[], None]] = None
        self.on_online_changed: Optional[Callable[[], None]] = None
        self.on_friends_changed: Optional[Callable[[], None]] = None
        self.on_message_received: Optional[Callable[[str, str, str], None]] = None
        self.on_friend_request: Optional[Callable[..., None]] = None
        self.on_friend_accepted: Optional[Callable[[str, str], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None

    def initialize(self):
        self.friend_db = FriendDB(self.config.db_path)
        profile = self.friend_db.get_my_profile()
        if self.config.name_override:
            profile["name"] = self.config.name_override
            self.friend_db.save_profile(profile)
            self.device_name = self.config.name_override
        elif profile.get("name"):
            self.device_name = profile["name"]

        self.custom_background = profile.get("background", "")
        self.custom_avatar = profile.get("avatar", "")
        self.user_id = profile.get("user_id", "")
        self.device_id = profile.get("device_id", "")

        self.connection_manager = ConnectionManager(
            my_name=self.device_name,
            tcp_port=self.config.tcp_port,
            my_user_id=self.user_id,
            my_device_id=self.device_id,
        )
        self.udp_service = UDPService(
            port=self.config.udp_port,
            device_name=self.device_name,
            tcp_port=self.config.tcp_port,
            user_id=self.user_id,
            device_id=self.device_id,
        )
        self.message_service = MessageService(
            connection_manager=self.connection_manager,
            friend_db=self.friend_db,
            receive_dir=self.config.receive_dir,
        )
        self.social_service = SocialService(
            friend_db=self.friend_db,
            connection_manager=self.connection_manager,
            udp_service=self.udp_service,
        )
        self._bind_internal_callbacks()
        return self

    def start(self):
        if self.udp_service:
            self.udp_service.start()
        if self.connection_manager:
            self.connection_manager.start_server()
        if self.message_service:
            self.message_service.start()

    def stop(self):
        if self.udp_service:
            self.udp_service.stop()
        if self.connection_manager:
            self.connection_manager.stop()
        if self.message_service:
            self.message_service.stop()
        if self.friend_db:
            self.friend_db.close()

    def save_profile(self, profile: dict):
        if not self.friend_db:
            return
        self.friend_db.save_profile(profile)
        saved = self.friend_db.get_my_profile()
        self.device_name = profile.get("name", self.device_name)
        self.user_id = saved.get("user_id", "")
        self.device_id = saved.get("device_id", "")
        self.custom_background = profile.get("background", self.custom_background)
        self.custom_avatar = profile.get("avatar", self.custom_avatar)
        if self.udp_service:
            self.udp_service.device_name = self.device_name
            self.udp_service.user_id = self.user_id
            self.udp_service.device_id = self.device_id
        if self.connection_manager:
            self.connection_manager.my_name = self.device_name
            self.connection_manager.my_user_id = self.user_id
            self.connection_manager.my_device_id = self.device_id

    def set_tcp_port(self, port: int):
        self.config.tcp_port = port
        if self.connection_manager:
            self.connection_manager.tcp_port = port
        if self.udp_service:
            self.udp_service.tcp_port = port

    def get_health(self) -> dict:
        return {
            "name": self.device_name,
            "user_id": self.user_id,
            "device_id": self.device_id,
            "tcp_port": self.config.tcp_port,
            "udp_port": self.config.udp_port,
            "udp_running": bool(self.udp_service and self.udp_service.running),
            "tcp_running": bool(
                self.connection_manager and self.connection_manager._running
            ),
            "discovered_count": len(self.get_discovered_people()),
            "online_count": len(self.get_online_friends()),
            "friend_count": len(self.get_all_friends()),
        }

    def get_network_diagnostics(self) -> dict:
        udp_diag = self.udp_service.get_diagnostics() if self.udp_service else {}
        health = self.get_health()
        return {
            **udp_diag,
            "name": self.device_name,
            "user_id": self.user_id,
            "device_id": self.device_id,
            "tcp_running": health["tcp_running"],
            "discovered_count": health["discovered_count"],
            "online_count": health["online_count"],
            "friend_count": health["friend_count"],
        }

    def scan_for_people(self):
        if self.udp_service:
            self.udp_service.manual_scan()

    def probe_peer(self, ip: str, tcp_port: int = Protocol.DEFAULT_TCP_PORT,
                   display_name: str = "") -> dict:
        """Try multiple app-level paths to reach one peer."""
        result = {
            "ip": ip,
            "tcp_port": int(tcp_port or Protocol.DEFAULT_TCP_PORT),
            "display_name": display_name or ip,
            "udp_probe": {},
            "tcp_connected": False,
        }
        if self.udp_service:
            result["udp_probe"] = self.udp_service.probe_host(ip)
        if self.connection_manager:
            result["tcp_connected"] = self.connection_manager.connect_to_friend(
                ip, result["tcp_port"], result["display_name"]
            )
        if result["tcp_connected"] and self.udp_service:
            self.udp_service._add_device(
                ip,
                result["display_name"],
                result["tcp_port"],
            )
        return result

    def get_discovered_people(self):
        if self.social_service:
            return self.social_service.get_discovered_cards(self.user_id, self.device_name)
        return []

    def get_all_friends(self):
        return self.social_service.get_friend_cards() if self.social_service else []

    def get_online_friends(self):
        return self.social_service.get_online_friend_cards() if self.social_service else []

    def get_chat_list(self):
        return self.social_service.get_chat_list() if self.social_service else []

    def _bind_internal_callbacks(self):
        self.udp_service.on_device_found = self._handle_device_found
        self.udp_service.on_device_offline = self._handle_device_offline
        self.connection_manager.on_friend_connected = self._handle_friend_connected
        self.connection_manager.on_friend_disconnected = self._handle_friend_disconnected
        self.connection_manager.on_message_received = self._handle_wire_message
        self.connection_manager.on_error = self._handle_error
        self.message_service.on_message_received = self._handle_message_received
        self.message_service.on_friend_request = self._handle_friend_request
        self.message_service.on_friend_accepted = self._handle_friend_accepted

    def _handle_device_found(self, device_info):
        self._sync_known_friend_endpoint(device_info)
        if self.on_discovery_changed:
            self.on_discovery_changed()

    def _handle_device_offline(self, _ip):
        if self.on_discovery_changed:
            self.on_discovery_changed()

    def _handle_friend_connected(self, name, _ip):
        if self.on_online_changed:
            self.on_online_changed()
        if self.on_friends_changed:
            self.on_friends_changed()
        if self.message_service:
            threading.Thread(
                target=self.message_service.flush_pending_messages,
                args=(name,),
                daemon=True,
            ).start()

    def _handle_friend_disconnected(self, _ip):
        if self.on_online_changed:
            self.on_online_changed()
        if self.on_friends_changed:
            self.on_friends_changed()

    def _handle_wire_message(self, ip, data):
        if self.message_service:
            self.message_service.handle_message(ip, data)

    def _handle_message_received(self, friend_name, content, timestamp):
        if self.on_message_received:
            self.on_message_received(friend_name, content, timestamp)

    def _handle_friend_request(self, profile, is_match, from_ip=None):
        if self.on_friend_request:
            self.on_friend_request(profile, is_match, from_ip)

    def _handle_friend_accepted(self, friend_name, friend_ip):
        if self.on_online_changed:
            self.on_online_changed()
        if self.on_friends_changed:
            self.on_friends_changed()
        if self.on_friend_accepted:
            self.on_friend_accepted(friend_name, friend_ip)

    def _handle_error(self, message: str):
        if self.on_error:
            self.on_error(message)

    def _sync_known_friend_endpoint(self, device_info):
        if not (self.friend_db and self.connection_manager):
            return
        name = device_info.device_name
        ip = device_info.ip
        port = int(device_info.tcp_port or Protocol.DEFAULT_TCP_PORT)
        friend = (
            self.friend_db.get_friend_by_user_id(getattr(device_info, "user_id", ""))
            or self.friend_db.get_friend(name)
        )
        if not friend:
            return

        old_ip = friend.get("ip", "")
        old_port = int(friend.get("port", Protocol.DEFAULT_TCP_PORT) or Protocol.DEFAULT_TCP_PORT)
        if old_ip != ip or old_port != port:
            self.friend_db.add_friend(
                name=friend.get("name", name),
                ip=ip,
                port=port,
                tags=friend.get("tags", []),
                bio=friend.get("bio", ""),
                category=friend.get("category", "朋友"),
                user_id=friend.get("user_id", ""),
                status=friend.get("status", "accepted"),
            )
        if not self.connection_manager.is_connected(ip, port):
            threading.Thread(
                target=self.connection_manager.connect_to_friend,
                args=(ip, port, friend.get("name", name)),
                daemon=True,
            ).start()
