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


def test_network_diagnostics_explain_empty_discovery(monkeypatch):
    monkeypatch.setattr(
        udp_service.Helpers,
        "_detect_interfaces",
        lambda: [
            {
                "name": "Wi-Fi",
                "ip": "192.168.56.10",
                "mask": "255.255.255.0",
                "gateway": "192.168.56.1",
                "broadcast": "192.168.56.255",
            }
        ],
    )

    service = UDPService(port=8890, device_name="Alice", tcp_port=7779)
    service.running = True
    service.sock = object()
    service._bump_diagnostic("send_attempts", 4)
    service._bump_diagnostic("send_success", 4)

    diagnostics = service.get_diagnostics()

    assert diagnostics["udp_running"] is True
    assert diagnostics["udp_port"] == 8890
    assert diagnostics["tcp_port"] == 7779
    assert "192.168.56.10" in diagnostics["local_ips"]
    assert diagnostics["receive_packets"] == 0
    assert "防火墙" in diagnostics["hint"]


def test_probe_host_sends_udp_to_requested_host():
    class DummySocket:
        def __init__(self):
            self.sent = []

        def sendto(self, payload, addr):
            self.sent.append((payload, addr))

    sock = DummySocket()
    service = UDPService(port=8890, device_name="Alice", tcp_port=7779)
    service.sock = sock

    result = service.probe_host("192.168.56.20", [8890, 8891])

    assert result["sent"] == 2
    assert result["failed"] == 0
    assert [addr for _payload, addr in sock.sent] == [
        ("192.168.56.20", 8890),
        ("192.168.56.20", 8891),
    ]
