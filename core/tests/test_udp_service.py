"""
挑战 3 - UDP 发现服务测试
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.backend.services import udp_service
from core.backend.services.udp_service import UDPService


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


def test_windows_udp_connection_reset_is_transient():
    error = OSError(10054, "connection reset")

    assert UDPService._is_transient_receive_error(error)
    assert not UDPService._is_transient_receive_error(OSError(10061, "refused"))


def test_device_seen_callback_runs_for_heartbeat_refreshes():
    service = UDPService(port=8890, device_name="Me", tcp_port=7779)
    found = []
    seen = []
    service.on_device_found = lambda device: found.append(device.device_name)
    service.on_device_seen = lambda device: seen.append(device.device_name)

    service._add_device("192.168.1.20", "Alice", 7780, "user_alice", "device_alice")
    service._add_device("192.168.1.20", "Alice", 7780, "user_alice", "device_alice")

    assert found == ["Alice"]
    assert seen == ["Alice", "Alice"]


def test_devices_with_same_user_id_keep_separate_device_entries():
    service = UDPService(port=8890, device_name="Me", tcp_port=7779)

    service._add_device("127.0.0.1", "Alice", 7779, "user_shared", "device_alice")
    service._add_device("127.0.0.1", "Bob", 7780, "user_shared", "device_bob")

    devices = service.get_online_devices()
    assert sorted(device.device_name for device in devices) == ["Alice", "Bob"]
