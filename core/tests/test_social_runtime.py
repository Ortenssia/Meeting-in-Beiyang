"""
挑战 3 - 社交运行时编排测试
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.backend.services import social_runtime
from core.backend.services.network_policy import NetworkPolicy
from core.backend.services.social_runtime import RuntimeConfig, SocialRuntime


class ImmediateThread:
    def __init__(self, target, args=(), daemon=None, **_kwargs):
        self.target = target
        self.args = args
        self.daemon = daemon

    def start(self):
        self.target(*self.args)


class DeferredThread(ImmediateThread):
    instances = []

    def __init__(self, target, args=(), daemon=None, **kwargs):
        super().__init__(target, args, daemon, **kwargs)
        self.__class__.instances.append(self)

    def start(self):
        pass


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


def test_runtime_passes_network_policy_to_services(tmp_path):
    policy = NetworkPolicy(
        tcp_connect_timeout=1.5,
        udp_active_scan_interval=9.0,
        message_heartbeat_interval=4.0,
        file_chunk_size=64 * 1024,
    )
    runtime = SocialRuntime(
        RuntimeConfig(
            tcp_port=7779,
            udp_port=8890,
            db_path=str(tmp_path / "alice.db"),
            name_override="Alice",
            network_policy=policy,
        )
    ).initialize()

    try:
        assert runtime.network_policy is policy
        assert runtime.connection_manager.network_policy is policy
        assert runtime.udp_service.network_policy is policy
        assert runtime.message_service.network_policy is policy
        assert runtime.message_service.FILE_CHUNK_SIZE == 64 * 1024
        assert runtime.message_service.HEARTBEAT_INTERVAL == 4.0
    finally:
        runtime.stop()


def test_runtime_can_change_receive_dir_and_persist_setting(tmp_path):
    db_path = tmp_path / "alice.db"
    chosen_dir = tmp_path / "chosen_inbox"
    runtime = SocialRuntime(
        RuntimeConfig(
            db_path=str(db_path),
            name_override="Alice",
        )
    ).initialize()

    try:
        resolved = runtime.set_receive_dir(str(chosen_dir))
        assert resolved == str(chosen_dir)
        assert runtime.get_receive_dir() == str(chosen_dir)
        assert runtime.message_service.receive_dir == str(chosen_dir)
        assert chosen_dir.is_dir()
    finally:
        runtime.stop()

    restarted = SocialRuntime(
        RuntimeConfig(
            db_path=str(db_path),
            name_override="Alice",
        )
    ).initialize()
    try:
        assert restarted.get_receive_dir() == str(chosen_dir)
    finally:
        restarted.stop()


def test_runtime_name_override_rotates_identity_when_reusing_db_for_new_name(tmp_path):
    db_path = tmp_path / "shared.db"
    alice = SocialRuntime(
        RuntimeConfig(db_path=str(db_path), name_override="Alice")
    ).initialize()
    try:
        alice_user_id = alice.user_id
        alice_device_id = alice.device_id
    finally:
        alice.stop()

    bob = SocialRuntime(
        RuntimeConfig(db_path=str(db_path), name_override="Bob")
    ).initialize()
    try:
        assert bob.device_name == "Bob"
        assert bob.user_id != alice_user_id
        assert bob.device_id != alice_device_id
    finally:
        bob.stop()


def test_runtime_reasserts_launch_name_for_same_name_override(tmp_path):
    db_path = tmp_path / "alice.db"
    runtime = SocialRuntime(
        RuntimeConfig(db_path=str(db_path), name_override="Alice")
    ).initialize()
    try:
        runtime.save_profile({
            "name": "Alice 自定义",
            "tags": ["编程", "摄影"],
            "bio": "Keep profile",
            "conditions": {
                "required_tags": ["编程"],
                "optional_tags": ["音乐"],
                "min_match_count": 2,
                "auto_accept": True,
            },
        })
        saved_user_id = runtime.user_id
        saved_device_id = runtime.device_id
    finally:
        runtime.stop()

    restarted = SocialRuntime(
        RuntimeConfig(db_path=str(db_path), name_override="Alice")
    ).initialize()
    try:
        profile = restarted.friend_db.get_my_profile()
        assert restarted.device_name == "Alice"
        assert profile["name"] == "Alice"
        assert profile["tags"] == ["编程", "摄影"]
        assert profile["bio"] == "Keep profile"
        assert profile["conditions"]["required_tags"] == ["编程"]
        assert profile["conditions"]["optional_tags"] == ["音乐"]
        assert profile["conditions"]["min_match_count"] == 2
        assert profile["conditions"]["auto_accept"] is True
        assert restarted.user_id == saved_user_id
        assert restarted.device_id == saved_device_id
    finally:
        restarted.stop()


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


def test_runtime_deduplicates_pending_reconnects(tmp_path, monkeypatch):
    DeferredThread.instances.clear()
    monkeypatch.setattr(social_runtime.threading, "Thread", DeferredThread)
    runtime = SocialRuntime(
        RuntimeConfig(
            db_path=str(tmp_path / "alice.db"),
            name_override="Me",
        )
    ).initialize()

    try:
        runtime.connection_manager.is_connected = lambda _ip, _port=0: False
        runtime.connection_manager.connect_to_friend = lambda *_args: True

        runtime._schedule_friend_connection("127.0.0.1", 7780, "Alice")
        runtime._schedule_friend_connection("127.0.0.1", 7780, "Alice")

        assert len(DeferredThread.instances) == 1
        DeferredThread.instances[0].target()
        assert runtime._connecting_endpoints == set()
    finally:
        runtime.stop()


def test_runtime_does_not_schedule_reconnect_while_stopping(tmp_path, monkeypatch):
    DeferredThread.instances.clear()
    monkeypatch.setattr(social_runtime.threading, "Thread", DeferredThread)
    runtime = SocialRuntime(
        RuntimeConfig(db_path=str(tmp_path / "alice.db"), name_override="Me")
    ).initialize()

    try:
        runtime._stopping = True
        runtime._schedule_friend_connection("127.0.0.1", 7780, "Alice")

        assert DeferredThread.instances == []
        assert runtime._connecting_endpoints == set()
    finally:
        runtime.stop()
