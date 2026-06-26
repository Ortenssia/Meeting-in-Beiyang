"""
挑战 3 - 数据库模块单元测试
"""
import pytest
import sys
import os

# 将项目根目录添加到路径中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from code_share.services.friend_db import FriendDB


@pytest.fixture
def db():
    db_path = "test_friends.db"
    # Ensure no leftover DB from previous runs
    if os.path.exists(db_path):
        os.remove(db_path)
    
    friend_db = FriendDB(db_path)
    yield friend_db
    
    friend_db.close()
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except PermissionError:
            pass


class TestFriendDB:
    """好友数据库单元测试"""

    def test_init_db(self, db):
        assert db.conn is not None

    def test_save_and_get_my_profile(self, db):
        profile = {
            "name": "UserA",
            "tags": ["python", "kivy"],
            "bio": "Keep coding",
            "conditions": {
                "required_tags": ["linux"],
                "optional_tags": ["git"],
                "min_match_count": 1,
                "auto_accept": True
            }
        }
        success = db.save_profile(profile)
        assert success is True

        loaded = db.get_my_profile()
        assert loaded["user_id"].startswith("user_")
        assert loaded["device_id"].startswith("device_")
        assert loaded["name"] == "UserA"
        assert loaded["tags"] == ["python", "kivy"]
        assert loaded["bio"] == "Keep coding"
        assert loaded["conditions"]["required_tags"] == ["linux"]
        assert loaded["conditions"]["auto_accept"] is True

    def test_add_and_get_friend(self, db):
        success = db.add_friend(
            name="FriendB",
            ip="192.168.1.102",
            port=7779,
            tags=["sports"],
            bio="Active person",
            category="同学"
        )
        assert success is True

        friend = db.get_friend("FriendB")
        assert friend is not None
        assert friend["ip"] == "192.168.1.102"
        assert friend["tags"] == ["sports"]
        assert friend["category"] == "同学"

        # 测试 get_friends()
        friends = db.get_friends()
        assert len(friends) == 1
        assert friends[0]["name"] == "FriendB"

        # 测试查找不存在的好友
        assert db.get_friend("Ghost") is None

    def test_user_id_updates_existing_friend(self, db):
        db.add_friend("Alice", "192.168.1.10", 7779, ["a"], "old", user_id="user_alice")
        db.add_friend("Alice New", "192.168.1.11", 7780, ["b"], "new", user_id="user_alice")

        friends = db.get_friends()
        friend = db.get_friend_by_user_id("user_alice")

        assert len(friends) == 1
        assert friend["name"] == "Alice New"
        assert friend["ip"] == "192.168.1.11"
        assert friend["port"] == 7780

    def test_friend_request_status_machine(self, db):
        db.upsert_friend_request(
            name="Alice",
            ip="192.168.1.10",
            port=7779,
            direction="outgoing",
            status="pending",
            user_id="user_alice",
        )

        assert db.get_relationship_status(user_id="user_alice") == "pending_sent"

        db.set_friend_request_status("accepted", user_id="user_alice")
        assert db.get_relationship_status(user_id="user_alice") == "accepted"

    def test_remove_friend(self, db):
        db.add_friend("FriendB", "192.168.1.102", 7779, [], "bio")
        assert db.get_friend("FriendB") is not None

        success = db.remove_friend("FriendB")
        assert success is True
        assert db.get_friend("FriendB") is None

    def test_update_friend_ip(self, db):
        db.add_friend("FriendB", "192.168.1.102", 7779, [], "bio")
        success = db.update_friend_ip("FriendB", "192.168.1.200")
        assert success is True

        friend = db.get_friend("FriendB")
        assert friend["ip"] == "192.168.1.200"

    def test_set_friend_category(self, db):
        db.add_friend("FriendB", "192.168.1.102", 7779, [], "bio", "朋友")
        success = db.set_friend_category("FriendB", "家人")
        assert success is True

        friend = db.get_friend("FriendB")
        assert friend["category"] == "家人"

    def test_msg_id_deduplication(self, db):
        msg_id = "test_msg_id_999"
        # 初始应未处理
        assert db.check_msg_id(msg_id) is False

        # 记录 msg_id
        success = db.record_msg_id(msg_id)
        assert success is True

        # 现在应该处理过
        assert db.check_msg_id(msg_id) is True

    def test_conditions_match(self, db):
        conditions = {
            "required_tags": ["python"],
            "optional_tags": ["kivy", "android"],
            "min_match_count": 2,
            "auto_accept": False
        }
        db.save_conditions(
            required_tags=conditions["required_tags"],
            optional_tags=conditions["optional_tags"],
            min_match=conditions["min_match_count"],
            auto_accept=conditions["auto_accept"]
        )

        # 案例 1: 缺少必须标签 -> 不匹配
        profile_fail1 = {"tags": ["kivy", "android"]}
        assert db.check_conditions_match(profile_fail1) is False

        # 案例 2: 包含必须标签，但总匹配数只有 1 (min_match 为 2) -> 不匹配
        profile_fail2 = {"tags": ["python"]}
        assert db.check_conditions_match(profile_fail2) is False

        # 案例 3: 包含必须标签，总匹配数达到 2 (python + kivy) -> 匹配
        profile_pass = {"tags": ["python", "kivy", "jazz"]}
        assert db.check_conditions_match(profile_pass) is True

    def test_pending_messages(self, db):
        db.add_pending_message(
            msg_id="m1", from_name="A", from_ip="192.168.1.1",
            to_name="B", content="hello", timestamp="2026-06-13 00:00:00",
            relay_path=["A"]
        )

        messages = db.get_pending_messages("B")
        assert len(messages) == 1
        assert messages[0]["content"] == "hello"

        # 清除特定好友的待发消息
        success = db.clear_pending_messages("B")
        assert success is True
        assert len(db.get_pending_messages("B")) == 0

    def test_chat_history(self, db):
        # 保存自己发送的消息
        # 我们需要在数据库里配一下本机名字，以便 save_chat_message 正确判断方向
        db.save_profile({"name": "Me", "tags": [], "bio": ""})
        db.add_friend("FriendB", "192.168.1.102", 7779, [], "bio")

        success = db.save_chat_message(
            from_name="Me", to_name="FriendB",
            content="how are you", timestamp="2026-06-13 00:00:00",
            msg_id="chat1"
        )
        assert success is True

        history = db.get_chat_history("FriendB")
        assert len(history) == 1
        assert history[0]["direction"] == "send"
        assert history[0]["content"] == "how are you"

        # 清空聊天历史
        success = db.clear_chat_history("FriendB")
        assert success is True
        assert len(db.get_chat_history("FriendB")) == 0
