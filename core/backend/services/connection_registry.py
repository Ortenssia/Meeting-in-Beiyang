"""Thread-safe TCP connection registry."""

import socket
import threading
from typing import Callable, Dict, List, Optional

from core.backend.shared.helpers import Helpers


class ConnectionRegistry:
    """Indexes live sockets by endpoint while preserving peer identity."""

    def __init__(self, on_connected: Callable[[str, str], None] = None):
        self.connections: Dict[str, Dict] = {}
        self.lock = threading.Lock()
        self.on_connected = on_connected

    @staticmethod
    def endpoint_key(ip: str, port: int = 0) -> str:
        try:
            port = int(port or 0)
        except (TypeError, ValueError):
            port = 0
        return f"{ip}:{port}" if port > 0 else ip

    def find_key_unlocked(self, ip_or_name: str) -> Optional[str]:
        if ip_or_name in self.connections:
            return ip_or_name
        for key, info in self.connections.items():
            if info.get("name") == ip_or_name:
                return key
        if ":" in ip_or_name:
            candidate_ip, candidate_port = ip_or_name.rsplit(":", 1)
            try:
                candidate_port = int(candidate_port)
            except ValueError:
                candidate_port = 0
            for key, info in self.connections.items():
                if (
                    info.get("ip") == candidate_ip
                    and int(info.get("port", 0) or 0) == candidate_port
                ):
                    return key
            return None
        for key, info in self.connections.items():
            if info.get("ip") == ip_or_name:
                return key
        return None

    def register(self, sock: socket.socket, ip: str, name: str, port: int = 0) -> str:
        key = self.endpoint_key(ip, port)
        should_notify = False
        with self.lock:
            self._remove_aliases_unlocked(sock, ip, name, port, key)
            existing = self.connections.get(key)
            if existing is None:
                should_notify = True
            else:
                old_sock = existing.get("socket")
                if old_sock and old_sock is not sock:
                    self._close_socket(old_sock)
                    should_notify = True

            existing_lock = (existing or {}).get("send_lock")
            self.connections[key] = {
                "socket": sock,
                "name": name or ip,
                "ip": ip,
                "port": int(port or 0),
                "connected_at": (existing or {}).get(
                    "connected_at", Helpers.get_timestamp()
                ),
                "send_lock": existing_lock or threading.Lock(),
            }

        if should_notify and self.on_connected:
            self.on_connected(name or ip, ip)
        return key

    def _remove_aliases_unlocked(self, sock, ip, name, port, key):
        for existing_key, info in list(self.connections.items()):
            if info.get("socket") is sock and existing_key != key:
                del self.connections[existing_key]
            elif (
                port
                and existing_key != key
                and info.get("ip") == ip
                and info.get("name") == (name or ip)
                and not int(info.get("port", 0) or 0)
            ):
                self._close_socket(info.get("socket"))
                del self.connections[existing_key]

    def remove(self, endpoint: str, expected_socket=None) -> Optional[Dict]:
        with self.lock:
            key = self.find_key_unlocked(endpoint)
            if not key:
                return None
            info = self.connections[key]
            if expected_socket is not None and info.get("socket") is not expected_socket:
                return None
            return self.connections.pop(key)

    def disconnect(self, endpoint: str) -> Optional[Dict]:
        info = self.remove(endpoint)
        if info:
            self._close_socket(info.get("socket"))
        return info

    def prune_unlocked(self):
        for key, info in list(self.connections.items()):
            if self.socket_alive(info.get("socket")):
                continue
            self._close_socket(info.get("socket"))
            del self.connections[key]

    def online(self) -> List[Dict]:
        with self.lock:
            self.prune_unlocked()
            deduped = {}
            for key, info in self.connections.items():
                name = info.get("name", "")
                ip = info.get("ip", key)
                port = int(info.get("port", 0) or 0)
                identity = name or self.endpoint_key(ip, port)
                current = deduped.get(identity)
                if current and int(current.get("port", 0) or 0) and not port:
                    continue
                deduped[identity] = {
                    "ip": ip,
                    "port": port,
                    "name": name,
                    "connected_at": info["connected_at"],
                }
            return list(deduped.values())

    @staticmethod
    def socket_alive(sock: Optional[socket.socket]) -> bool:
        if sock is None:
            return False
        try:
            sock.getpeername()
            return True
        except OSError:
            return False

    @staticmethod
    def _close_socket(sock):
        try:
            if sock:
                sock.close()
        except Exception:
            pass


def peer_identity_from_message(message: dict):
    """Return ``(name, tcp_port)`` when a message identifies its sender."""
    from core.backend.shared.protocol import Protocol

    msg_type = message.get("type", "")
    if msg_type == Protocol.PROFILE_EXCHANGE:
        return message.get("name", "Unknown"), int(message.get("tcp_port", 0) or 0)
    if msg_type == Protocol.HEARTBEAT:
        return message.get("name", ""), int(message.get("port", 0) or 0)
    if msg_type in (Protocol.FRIEND_REQUEST, Protocol.FRIEND_ACCEPT):
        profile = message.get("profile", {}) or {}
        return profile.get("name", ""), int(profile.get("tcp_port", 0) or 0)
    return "", 0
