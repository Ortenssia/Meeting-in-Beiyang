"""
挑战 3 - 社交运行时编排测试
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from code_share.services import social_runtime
from code_share.services.social_runtime import RuntimeConfig, SocialRuntime


class ImmediateThread:
    def __init__(self, target, args=(), daemon=None, **_kwargs):
        self.target = target
        self.args = args
        self.daemon = daemon

    def start(self):
        self.target(*self.args)


class DummyDevice:
    device_name = "Alice"
    ip = "127.0.0.1"
    tcp_port = 7780
    user_id = "user_alice"
    device_id = "device_alice"
    last_seen = time.time()

    def is_online(self):
        return True


def test_runtime_initializes_identity_and_health(tmp_path):
    runtime = SocialRuntime(
        RuntimeConfig(
            tcp_port=7779,
            udp_port=8890,
            db_path=str(tmp_path / "alice.db"),
            name_override="Alice",
        )
    ).initialize()

    try:
        health = runtime.get_health()
        assert health["name"] == "Alice"
        assert health["tcp_port"] == 7779
        assert health["udp_port"] == 8890
        assert health["udp_running"] is False
        assert health["tcp_running"] is False
        assert health["user_id"].startswith("user_")
        assert health["device_id"].startswith("device_")
    finally:
        runtime.stop()


def test_runtime_updates_known_friend_endpoint_and_reconnects(tmp_path, monkeypatch):
    monkeypatch.setattr(social_runtime.threading, "Thread", ImmediateThread)
    runtime = SocialRuntime(
        RuntimeConfig(
            tcp_port=7779,
            udp_port=8890,
            db_path=str(tmp_path / "alice.db"),
            name_override="Me",
        )
    ).initialize()

    try:
        runtime.friend_db.add_friend(
            "Alice",
            "192.168.1.10",
            7779,
            ["kivy"],
            "bio",
            user_id="user_alice",
        )
        connect_calls = []
        runtime.connection_manager.is_connected = lambda ip, port=0: False
        runtime.connection_manager.connect_to_friend = (
            lambda ip, port, name: connect_calls.append((ip, port, name)) or True
        )

        runtime._handle_device_found(DummyDevice())

        friend = runtime.friend_db.get_friend_by_user_id("user_alice")
        assert friend["ip"] == "127.0.0.1"
        assert friend["port"] == 7780
        assert connect_calls == [("127.0.0.1", 7780, "Alice")]
    finally:
        runtime.stop()
