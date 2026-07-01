"""
P2P social runtime orchestration.

This module owns the service lifecycle and cross-service reactions. Screens
should not need to know how UDP discovery, TCP connections,
relationship storage, message relay, and file transfer are wired together.
"""

from dataclasses import dataclass
import random
import threading
import time
from typing import Callable, Optional

from core.config import AppPaths, get_app_paths
from core.backend.services.connection_manager import ConnectionManager
from core.backend.services.friend_db import FriendDB
from core.backend.services.message_service import MessageService
from core.backend.services.network_policy import DEFAULT_NETWORK_POLICY, NetworkPolicy
from core.backend.services.social_service import SocialService
from core.backend.services.udp_service import UDPService
from core.backend.shared.helpers import Helpers
from core.backend.shared.protocol import Protocol


RECEIVE_DIR_SETTING_KEY = "receive_dir"
NAME_OVERRIDE_SETTING_KEY = "name_override"


@dataclass
class RuntimeConfig:
    tcp_port: int = Protocol.DEFAULT_TCP_PORT
    udp_port: int = Protocol.DEFAULT_UDP_PORT
    db_path: Optional[str] = None
    name_override: str = ""
    receive_dir: Optional[str] = None
    avatar_dir: Optional[str] = None
    paths: Optional[AppPaths] = None
    network_policy: NetworkPolicy = DEFAULT_NETWORK_POLICY


class SocialRuntime:
    """Coordinates identity, discovery, relationships, messaging, and files."""

    def __init__(self, config: RuntimeConfig):
        self.config = config
        self.paths = config.paths or get_app_paths()
        self.network_policy = config.network_policy
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
        self._connecting_lock = threading.Lock()
        self._connecting_endpoints = set()
        self._flush_threads_lock = threading.Lock()
        self._flush_threads = set()
        self._stopping = False

        self.on_discovery_changed: Optional[Callable[[], None]] = None
        self.on_online_changed: Optional[Callable[[], None]] = None
        self.on_friends_changed: Optional[Callable[[], None]] = None
        self.on_message_received: Optional[Callable[[str, str, str, str], None]] = None
        self.on_friend_request: Optional[Callable[..., None]] = None
        self.on_friend_accepted: Optional[Callable[[str, str], None]] = None
        self.on_friend_deleted: Optional[Callable[[str], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self.on_group_message_received: Optional[Callable[[str, str, str, str], None]] = None
        self.on_moments_changed: Optional[Callable[[], None]] = None
        self.on_notifications_changed: Optional[Callable[[], None]] = None

    def initialize(self):
        db_path = self.paths.resolve_db_path(self.config.db_path)
        self.friend_db = FriendDB(str(db_path))
        saved_receive_dir = self.friend_db.get_app_setting(RECEIVE_DIR_SETTING_KEY, "")
        receive_dir = self.paths.resolve_receive_dir(self.config.receive_dir or saved_receive_dir)
        avatar_dir = self.paths.resolve_avatar_cache_dir(self.config.avatar_dir)
        receive_dir.mkdir(parents=True, exist_ok=True)
        avatar_dir.mkdir(parents=True, exist_ok=True)
        self.config.receive_dir = str(receive_dir)
        profile = self.friend_db.get_my_profile()
        if self.config.name_override:
            override_name = self.config.name_override
            saved_override = self.friend_db.get_app_setting(NAME_OVERRIDE_SETTING_KEY, "")
            profile_name = profile.get("name", "")
            should_apply_override = False
            should_rotate_identity = False

            if saved_override and saved_override != override_name:
                should_apply_override = True
                should_rotate_identity = True
            elif not saved_override:
                should_apply_override = profile_name != override_name
                self.friend_db.set_app_setting(NAME_OVERRIDE_SETTING_KEY, override_name)
            elif saved_override == override_name and profile_name != override_name:
                should_apply_override = True

            if should_apply_override:
                if should_rotate_identity:
                    profile["user_id"] = self.friend_db._new_id("user")
                    profile["device_id"] = self.friend_db._new_id("device")
                profile["name"] = override_name
                if not self.friend_db.save_profile(profile):
                    raise RuntimeError("保存启动身份失败")
                self.friend_db.set_app_setting(NAME_OVERRIDE_SETTING_KEY, override_name)
                profile = self.friend_db.get_my_profile()

            self.device_name = profile.get("name") or override_name
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
            network_policy=self.network_policy,
        )
        self.udp_service = UDPService(
            port=self.config.udp_port,
            device_name=self.device_name,
            tcp_port=self.config.tcp_port,
            user_id=self.user_id,
            device_id=self.device_id,
            network_policy=self.network_policy,
        )
        self.message_service = MessageService(
            connection_manager=self.connection_manager,
            friend_db=self.friend_db,
            receive_dir=str(receive_dir),
            avatar_dir=str(avatar_dir),
            network_policy=self.network_policy,
        )
        self.message_service.runtime = self
        self.message_service.friend_requests.udp_friend_request_sender = (
            self._send_udp_friend_request
        )
        self.social_service = SocialService(
            friend_db=self.friend_db,
            connection_manager=self.connection_manager,
            udp_service=self.udp_service,
        )
        self._bind_internal_callbacks()
        return self

    def start(self):
        self._stopping = False
        if self.udp_service:
            self.udp_service.start()
        if self.connection_manager:
            self.connection_manager.start_server()
        if self.message_service:
            self.message_service.start()

    def stop(self):
        self._stopping = True
        if self.udp_service:
            self.udp_service.stop()
        if self.connection_manager:
            self.connection_manager.stop()
        if self.message_service:
            self.message_service.stop()
        with self._flush_threads_lock:
            flush_threads = list(self._flush_threads)
        for thread in flush_threads:
            thread.join(timeout=1.0)
        if self.friend_db:
            self.friend_db.close()

    def save_profile(self, profile: dict):
        if not self.friend_db:
            return False
        if not self.friend_db.save_profile(profile):
            return False
        saved = self.friend_db.get_my_profile()
        self.device_name = saved.get("name", self.device_name)
        self.user_id = saved.get("user_id", "")
        self.device_id = saved.get("device_id", "")
        self.custom_background = saved.get("background", self.custom_background)
        self.custom_avatar = saved.get("avatar", self.custom_avatar)
        if self.udp_service:
            self.udp_service.device_name = self.device_name
            self.udp_service.user_id = self.user_id
            self.udp_service.device_id = self.device_id
        if self.connection_manager:
            self.connection_manager.my_name = self.device_name
            self.connection_manager.my_user_id = self.user_id
            self.connection_manager.my_device_id = self.device_id

        try:
            if self.message_service and self.connection_manager:
                for friend in self.connection_manager.get_online_friends():
                    friend_name = friend.get("name")
                    if friend_name:
                        self.message_service._send_avatar_to_friend(friend_name)
                self.message_service._send_heartbeat_to_all()
        except Exception:
            pass
        return True

    def set_tcp_port(self, port: int):
        self.config.tcp_port = port
        if self.connection_manager:
            self.connection_manager.tcp_port = port
        if self.udp_service:
            self.udp_service.tcp_port = port

    def set_receive_dir(self, receive_dir: str) -> str:
        resolved = str(self.paths.resolve_receive_dir(receive_dir))
        if self.message_service:
            resolved = self.message_service.set_receive_dir(resolved)
        else:
            self.paths.resolve_receive_dir(resolved).mkdir(parents=True, exist_ok=True)
        self.config.receive_dir = resolved
        if self.friend_db:
            self.friend_db.set_app_setting(RECEIVE_DIR_SETTING_KEY, resolved)
        return resolved

    def get_receive_dir(self) -> str:
        if self.message_service:
            return self.message_service.receive_dir
        return str(self.paths.resolve_receive_dir(self.config.receive_dir))

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
            return self.social_service.get_discovered_cards(
                self.user_id,
                self.device_name,
                self.device_id,
                self.config.tcp_port,
            )
        return []

    def get_all_friends(self):
        return self.social_service.get_friend_cards() if self.social_service else []

    def get_online_friends(self):
        return self.social_service.get_online_friend_cards() if self.social_service else []

    def get_chat_list(self):
        return self.social_service.get_chat_list() if self.social_service else []

    def _bind_internal_callbacks(self):
        self.udp_service.on_device_found = self._handle_device_found
        self.udp_service.on_device_seen = self._sync_known_friend_endpoint
        self.udp_service.on_device_offline = self._handle_device_offline
        self.udp_service.on_friend_request_packet = self._handle_udp_friend_request
        self.connection_manager.on_friend_connected = self._handle_friend_connected
        self.connection_manager.on_friend_disconnected = self._handle_friend_disconnected
        self.connection_manager.on_message_received = self._handle_wire_message
        self.connection_manager.on_error = self._handle_error
        self.message_service.on_message_received = self._handle_message_received
        self.message_service.on_friend_request = self._handle_friend_request
        self.message_service.on_friend_accepted = self._handle_friend_accepted
        self.message_service.on_friend_deleted = self._handle_friend_deleted
        self.message_service.on_notifications_changed = self._handle_notifications_changed
        self.message_service.on_file_received = self._handle_file_received

    def _handle_device_found(self, device_info):
        self._sync_known_friend_endpoint(device_info)
        if self.on_discovery_changed:
            self.on_discovery_changed()

    def _handle_device_offline(self, _ip):
        if self.on_discovery_changed:
            self.on_discovery_changed()

    def _handle_friend_connected(self, name, _ip):
        if self._stopping:
            return
        if self.on_online_changed:
            self.on_online_changed()
        if self.on_friends_changed:
            self.on_friends_changed()
        # If the "name" is still a raw IP address, PROFILE_EXCHANGE hasn't
        # arrived yet.  Flushing pending messages / syncing groups with an
        # IP placeholder would only produce unnecessary failures; the real
        # sync will happen when _register_connection fires the callback
        # again after upgrading the name.
        if self.message_service and not self.connection_manager._looks_like_ip(name):
            thread = None

            def flush_pending():
                try:
                    # Self-healing reconciliation: if we have them as an accepted friend,
                    # make sure they also have us as a friend by sending them FRIEND_ACCEPT.
                    if self.friend_db:
                        friend = self.friend_db.get_friend(name)
                        if friend and friend.get("status") == "accepted":
                            self.message_service.send_friend_accept(name)

                    self.message_service.flush_pending_messages(name)
                    self.message_service.sync_groups_with_friend(name)
                    self.message_service.sync_moments_with_friend(name)
                    self.message_service.send_profile_update_notice(name)
                finally:
                    with self._flush_threads_lock:
                        self._flush_threads.discard(thread)

            thread = threading.Thread(target=flush_pending, daemon=True)
            with self._flush_threads_lock:
                self._flush_threads.add(thread)
            thread.start()

    def _handle_friend_disconnected(self, _ip):
        if self.on_online_changed:
            self.on_online_changed()
        if self.on_friends_changed:
            self.on_friends_changed()

    def _handle_wire_message(self, ip, data):
        if self.message_service:
            self.message_service.handle_message(ip, data)

    def _handle_udp_friend_request(self, ip, data):
        if self.message_service:
            self.message_service.handle_message(ip, data)

    def _send_udp_friend_request(self, hosts, payload):
        if not self.udp_service:
            return False
        return self.udp_service.send_friend_request_packet(hosts, payload)

    def _handle_message_received(self, friend_name, content, timestamp, msg_id=""):
        if self.on_message_received:
            self.on_message_received(friend_name, content, timestamp, msg_id)

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

    def _handle_friend_deleted(self, friend_name):
        if self.on_online_changed:
            self.on_online_changed()
        if self.on_friends_changed:
            self.on_friends_changed()
        if self.on_friend_deleted:
            self.on_friend_deleted(friend_name)

    def _handle_file_received(self, _friend_name, _path, _timestamp):
        if self.on_friends_changed:
            self.on_friends_changed()

    def _handle_notifications_changed(self):
        if self.on_notifications_changed:
            self.on_notifications_changed()

    def _handle_error(self, message: str):
        if self.on_error:
            self.on_error(message)

    def _sync_known_friend_endpoint(self, device_info):
        if self._stopping or not (self.friend_db and self.connection_manager):
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
                avatar=friend.get("avatar", ""),
                background=friend.get("background", ""),
            )
        if not self.connection_manager.is_connected(ip, port):
            self._schedule_friend_connection(ip, port, friend.get("name", name))

    def _schedule_friend_connection(self, ip, port, name):
        if self._stopping:
            return
        endpoint = f"{ip}:{port}"
        with self._connecting_lock:
            if endpoint in self._connecting_endpoints:
                return
            self._connecting_endpoints.add(endpoint)

        def connect():
            try:
                # Random backoff (100–800 ms) to prevent both sides from
                # reconnecting in the same instant after a network blip.
                # The side that fires first becomes the initiator; the
                # other side's _accept_worker will see the existing
                # connection and discard the duplicate accept.
                time.sleep(0.1 + random.random() * 0.7)
                if not self._stopping and not self.connection_manager.is_connected(ip, port):
                    self.connection_manager.connect_to_friend(ip, port, name)
            finally:
                with self._connecting_lock:
                    self._connecting_endpoints.discard(endpoint)

        threading.Thread(target=connect, daemon=True).start()
