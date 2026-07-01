"""Thread-safe state used by UDP discovery."""

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple


@dataclass
class DeviceInfo:
    """A discovered peer and its latest reachable addresses."""

    ip: str
    device_name: str
    tcp_port: int
    last_seen: float
    user_id: str = ""
    device_id: str = ""
    candidate_ips: List[str] = field(default_factory=list)

    def is_online(self, timeout: int = 15) -> bool:
        return (time.time() - self.last_seen) < timeout


class DeviceRegistry:
    """Owns identity deduplication and online/offline state."""

    def __init__(self):
        self.devices: Dict[str, DeviceInfo] = {}
        self.lock = threading.Lock()

    def upsert(
        self,
        ip: str,
        device_name: str,
        tcp_port: int,
        user_id: str = "",
        device_id: str = "",
        candidate_ips: Optional[List[str]] = None,
    ) -> Tuple[DeviceInfo, bool]:
        now = time.time()
        candidates = clean_candidate_ips(ip, candidate_ips or [])
        canonical = device_id or user_id
        key = canonical or f"{device_name}@{ip}:{int(tcp_port or 0)}"

        with self.lock:
            if canonical:
                self._merge_fallback_entry(key, device_name, tcp_port, user_id, device_id)

            existing = self.devices.get(key)
            changed = existing is None
            if existing is None:
                existing = DeviceInfo(
                    ip, device_name, tcp_port, now, user_id, device_id, candidates
                )
                self.devices[key] = existing
            else:
                changed = changed or any(
                    (
                        existing.ip != ip,
                        existing.tcp_port != tcp_port,
                        existing.device_name != device_name,
                        existing.candidate_ips != candidates,
                    )
                )
                existing.ip = ip
                existing.device_name = device_name
                existing.tcp_port = tcp_port
                existing.last_seen = now
                existing.user_id = user_id
                existing.device_id = device_id
                existing.candidate_ips = candidates
            return existing, changed

    def _merge_fallback_entry(
        self,
        key: str,
        device_name: str,
        tcp_port: int,
        user_id: str,
        device_id: str,
    ):
        for existing_key, existing in list(self.devices.items()):
            if existing_key == key:
                continue
            if (
                existing.device_name == device_name
                and int(existing.tcp_port or 0) == int(tcp_port or 0)
                and not (existing.device_id or existing.user_id)
            ):
                self.devices[key] = existing
                existing.user_id = user_id
                existing.device_id = device_id
                del self.devices[existing_key]
                return

    def remove_offline(self, timeout: int = 15) -> List[str]:
        with self.lock:
            offline = [
                (key, device.ip)
                for key, device in self.devices.items()
                if not device.is_online(timeout)
            ]
            for key, _ip in offline:
                del self.devices[key]
        return [ip for _key, ip in offline]

    def online(self) -> List[DeviceInfo]:
        with self.lock:
            return [device for device in self.devices.values() if device.is_online()]


class UDPDiagnostics:
    """Small synchronized counter/snapshot object for discovery diagnostics."""

    def __init__(self):
        self._lock = threading.Lock()
        self._values = {
            "started_at": None,
            "last_scan_at": None,
            "last_receive_at": None,
            "last_device_at": None,
            "last_error": "",
            "last_targets": 0,
            "last_probe_ports": [],
            "send_attempts": 0,
            "send_success": 0,
            "send_errors": 0,
            "receive_packets": 0,
            "receive_ping": 0,
            "receive_pong": 0,
            "receive_friend_request": 0,
            "receive_resets_ignored": 0,
        }

    def update(self, **values):
        with self._lock:
            self._values.update(values)

    def bump(self, key: str, amount: int = 1):
        with self._lock:
            self._values[key] = int(self._values.get(key, 0) or 0) + amount

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._values)


def clean_candidate_ips(primary_ip: str, values: List[str]) -> List[str]:
    seen = set()
    cleaned = []
    for value in [primary_ip, *values]:
        if not value or value.startswith("127."):
            continue
        parts = value.split(".")
        if len(parts) != 4 or not all(
            part.isdigit() and 0 <= int(part) <= 255 for part in parts
        ):
            continue
        if value not in seen:
            seen.add(value)
            cleaned.append(value)
    return cleaned
