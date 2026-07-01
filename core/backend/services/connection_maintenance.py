"""Background maintenance loops for TCP connections."""

import logging
import time

from core.backend.shared.helpers import Helpers
from core.backend.shared.protocol import Protocol

logger = logging.getLogger(__name__)


class ConnectionMaintenance:
    """Heartbeat broadcast and local-IP change notification."""

    def __init__(self, manager):
        self.manager = manager

    def heartbeat_worker(self):
        manager = self.manager
        while manager._running:
            time.sleep(manager.network_policy.tcp_heartbeat_interval)
            if not manager._running:
                break
            try:
                manager.broadcast_to_friends(self._heartbeat_payload())
            except Exception as exc:
                logger.debug("心跳广播异常: %s", exc)

    def ip_monitor_worker(self):
        manager = self.manager
        while manager._running:
            time.sleep(manager.network_policy.ip_monitor_interval)
            if not manager._running:
                break
            try:
                current_ip = Helpers.get_default_ip()
                if current_ip == manager._last_known_ip:
                    continue
                old_ip = manager._last_known_ip
                manager._last_known_ip = current_ip
                logger.info("检测到 IP 变更: %s -> %s，通知所有好友", old_ip, current_ip)
                manager.broadcast_to_friends(self._heartbeat_payload(current_ip))
            except Exception as exc:
                logger.debug("IP 监控异常: %s", exc)

    def _heartbeat_payload(self, current_ip: str = "") -> bytes:
        manager = self.manager
        return Protocol.create_heartbeat(
            name=manager.my_name,
            ip=current_ip or Helpers.get_default_ip(),
            port=manager.tcp_port,
        )
