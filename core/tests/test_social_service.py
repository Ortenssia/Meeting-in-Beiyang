"""
挑战 3 - 社交门面服务测试
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.backend.services.friend_db import FriendDB
from core.backend.services.social_service import SocialService


class DummyConnection:
    def __init__(self, online=None):
        self.online = set(online or [])

    def is_friend_online(self, name):
        return name in self.online


class DummyDevice:
    def __init__(self, name, ip, port, user_id, device_id=None):
        self.device_name = name
        self.ip = ip
        self.tcp_port = port
        self.user_id = user_id
        self.device_id = device_id if device_id is not None else f"device_{user_id}"
        self.last_seen = time.time()

    def is_online(self):
        return True


class DummyUDP:
    def __init__(self, devices):
        import threading
        self.devices = {device.user_id: device for device in devices}
        self._devices_lock = threading.Lock()


def test_social_service_hides_existing_friends_from_discovery(tmp_path):
    db = FriendDB(str(tmp_path / "social.db"))
    db.add_friend("Alice", "172.30.0.1", 7779, [], "bio", user_id="user_alice")
    udp = DummyUDP([
        DummyDevice("Alice", "172.30.0.1", 7779, "user_alice"),
        DummyDevice("Bob", "172.30.0.2", 7780, "user_bob"),
    ])

    service = SocialService(db, DummyConnection(["Alice"]), udp)
    cards = service.get_discovered_cards(my_user_id="user_me", my_name="Me")

    assert [card["name"] for card in cards] == ["Bob"]
    assert cards[0]["status"] == "none"


def test_social_service_does_not_hide_same_user_different_device(tmp_path):
    db = FriendDB(str(tmp_path / "social.db"))
    udp = DummyUDP([
        DummyDevice("Bob", "127.0.0.1", 7780, "user_shared", "device_bob"),
    ])

    service = SocialService(db, DummyConnection([]), udp)
    cards = service.get_discovered_cards(
        my_user_id="user_shared",
        my_name="Alice",
        my_device_id="device_alice",
        my_tcp_port=7779,
    )

    assert [card["name"] for card in cards] == ["Bob"]


def test_social_service_hides_same_device_only(tmp_path):
    db = FriendDB(str(tmp_path / "social.db"))
    udp = DummyUDP([
        DummyDevice("Alice", "127.0.0.1", 7779, "user_alice", "device_alice"),
    ])

    service = SocialService(db, DummyConnection([]), udp)
    cards = service.get_discovered_cards(
        my_user_id="user_alice",
        my_name="Alice",
        my_device_id="device_alice",
        my_tcp_port=7779,
    )

    assert cards == []


def test_social_service_friend_cards_are_accepted_only(tmp_path):
    db = FriendDB(str(tmp_path / "social.db"))
    db.add_friend("Alice", "172.30.0.1", 7779, [], "bio", user_id="user_alice")
    db.add_friend("Eve", "172.30.0.3", 7779, [], "bio", user_id="user_eve", status="pending")

    service = SocialService(db, DummyConnection(["Alice"]), DummyUDP([]))
    cards = service.get_friend_cards()

    assert len(cards) == 1
    assert cards[0]["name"] == "Alice"
    assert cards[0]["online"] is True
