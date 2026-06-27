"""
挑战 3 - UDP 发现服务测试
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.services import udp_service
from core.services.udp_service import UDPService


def test_broadcast_targets_include_loopback_and_local_ip(monkeypatch):
    monkeypatch.setattr(
        udp_service.Helpers,
        "_detect_interfaces",
        lambda: [
            {
                "ip": "192.168.56.10",
                "mask": "255.255.255.0",
                "broadcast": "192.168.56.255",
            }
        ],
    )

    service = UDPService(port=8890, device_name="Alice", tcp_port=7779)

    targets = set(service._get_broadcast_targets())

    assert "127.0.0.1" in targets
    assert "192.168.56.10" in targets
    assert "192.168.56.255" in targets
    assert "192.168.56.11" in targets
