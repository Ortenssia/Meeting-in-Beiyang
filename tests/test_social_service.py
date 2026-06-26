"""
挑战 3 - 社交门面服务测试
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from code_share.services.friend_db import FriendDB
from code_share.services.social_service import SocialService


class DummyConnection:
    def __init__(self, online=None):
        self.online = set(online or [])

    def is_friend_online(self, name):
        return name in self.online


class DummyDevice:
    def __init__(self, name, ip, port, user_id):
        self.device_name = name
        self.ip = ip
        self.tcp_port = port
        self.user_id = user_id
        self.device_id = f"device_{user_id}"
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


def test_social_service_friend_cards_are_accepted_only(tmp_path):
    db = FriendDB(str(tmp_path / "social.db"))
    db.add_friend("Alice", "172.30.0.1", 7779, [], "bio", user_id="user_alice")
    db.add_friend("Eve", "172.30.0.3", 7779, [], "bio", user_id="user_eve", status="pending")

    service = SocialService(db, DummyConnection(["Alice"]), DummyUDP([]))
    cards = service.get_friend_cards()

    assert len(cards) == 1
    assert cards[0]["name"] == "Alice"
    assert cards[0]["online"] is True
