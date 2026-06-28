"""
挑战 3 - 消息服务与社交业务流单元测试
"""
import pytest
import sys
import os
import json
import struct
import base64
import tempfile
import uuid

# 将项目根目录添加到路径中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.backend.services.message_service import MessageService
from core.backend.services.friend_db import FriendDB
from core.backend.shared.protocol import Protocol


class MockConnectionManager:
    """Mock Connection Manager to track offline caching and relays"""
    def __init__(self):
        self.online_friends = {}  # name -> ip
        self.sent_messages = []   # list of (name, msg_dict)
        self.connect_calls = []
        self.tcp_port = 7788

    def is_friend_online(self, name):
        return name in self.online_friends

    def get_friend_ip(self, name):
        return self.online_friends.get(name, "")

    def get_online_friends(self):
        return list(self.online_friends.keys())

    def send_to_friend(self, name, data_bytes):
        # 解析长度前缀 + 协议消息（JSON 或二进制文件块）
        header_len = 4
        if len(data_bytes) >= header_len:
            length = struct.unpack('!I', data_bytes[:header_len])[0]
            self.sent_messages.append(
                (name, Protocol.parse_message(data_bytes[header_len:header_len+length]))
            )
            return True
        return False

    def connect_to_friend(self, ip, port=0, name=""):
        self.connect_calls.append((ip, port, name))
        actual_name = name if name else (port if isinstance(port, str) else "")
        if actual_name:
            self.online_friends[actual_name] = ip


@pytest.fixture
def social_env(tmp_path):
    # Setup database
    db_path = tmp_path / "test_social_flow.db"
    
    db = FriendDB(str(db_path))
    # Configure user profile
    db.save_profile({
        "name": "Me",
        "tags": ["python"],
        "bio": "Developer",
        "conditions": {
            "required_tags": ["kivy"],
            "optional_tags": ["sqlite"],
            "min_match_count": 1,
            "auto_accept": True
        }
    })

    conn_mgr = MockConnectionManager()
    msg_service = MessageService(
        connection_manager=conn_mgr,
        friend_db=db,
        receive_dir=str(tmp_path / "received_files"),
        avatar_dir=str(tmp_path / "received_avatars"),
    )
    
    yield db, conn_mgr, msg_service
    
    db.close()


class TestSocialFlow:
    """社交消息中继及核心业务流测试"""

    def test_send_message_online(self, social_env):
        db, conn_mgr, msg_service = social_env
        
        # 加好友
        db.add_friend("Alice", "192.168.1.5", 7779, ["kivy"], "Alice Bio")
        # Alice 在线
        conn_mgr.online_friends["Alice"] = "192.168.1.5"

        success = msg_service.send_message("Alice", "Hi Alice!")
        assert success is True
        
        # 验证消息直接通过 TCP 送达了
        assert len(conn_mgr.sent_messages) == 1
        target, data = conn_mgr.sent_messages[0]
        assert target == "Alice"
        assert data["type"] == MessageService.CHAT_MESSAGE
        assert data["content"] == "Hi Alice!"

        # 检查是否同时记入了聊天历史
        history = db.get_chat_history("Alice")
        assert len(history) == 1
        assert history[0]["content"] == "Hi Alice!"
        assert history[0]["direction"] == "send"

    def test_send_message_offline_relay(self, social_env):
        db, conn_mgr, msg_service = social_env
        
        # 离线的目标好友
        db.add_friend("Bob", "192.168.1.6", 7779, ["kivy"], "Bob Bio")
        # 在线的其他好友（作为中继节点）
        db.add_friend("Charlie", "192.168.1.7", 7779, ["kivy"], "Charlie Bio")
        conn_mgr.online_friends["Charlie"] = "192.168.1.7"

        # 发消息给离线的 Bob
        success = msg_service.send_message("Bob", "Hi Bob (offline)")
        assert success is True

        # 1. 验证 Bob 离线时，消息进入了待发 (pending) 缓存
        pending = db.get_pending_messages("Bob")
        assert len(pending) == 1
        assert pending[0]["content"] == "Hi Bob (offline)"

        # 2. 验证消息同时洪泛发送给在线互友 Charlie
        assert len(conn_mgr.sent_messages) == 1
        target, data = conn_mgr.sent_messages[0]
        assert target == "Charlie"
        assert data["type"] == MessageService.RELAY_MESSAGE
        assert data["original_message"]["content"] == "Hi Bob (offline)"
        assert data["original_message"]["to_name"] == "Bob"

    def test_flood_relay_returns_sent_count(self, social_env):
        db, conn_mgr, msg_service = social_env
        db.add_friend("Charlie", "192.168.1.7", 7779, ["kivy"], "Charlie Bio")
        db.add_friend("Dana", "192.168.1.8", 7779, ["kivy"], "Dana Bio")
        conn_mgr.online_friends["Charlie"] = "192.168.1.7"
        conn_mgr.online_friends["Dana"] = "192.168.1.8"

        count = msg_service._flood_relay(
            {"type": MessageService.RELAY_MESSAGE},
            exclude_name="Dana",
        )

        assert count == 1
        assert conn_mgr.sent_messages[0][0] == "Charlie"

    def test_send_friend_request_uses_discovered_port(self, social_env):
        db, conn_mgr, msg_service = social_env

        success = msg_service.send_friend_request("Alice", "172.30.0.1", 7780, "user_alice")

        assert success is True
        assert conn_mgr.connect_calls == [("172.30.0.1", 7780, "Alice")]
        target, data = conn_mgr.sent_messages[0]
        assert target == "Alice"
        assert data["type"] == MessageService.FRIEND_REQUEST
        assert data["profile"]["tcp_port"] == 7788
        assert data["profile"]["user_id"].startswith("user_")
        assert db.get_relationship_status(user_id="user_alice") == "pending_sent"

    def test_send_friend_request_sends_local_avatar_file(self, social_env, tmp_path):
        db, conn_mgr, msg_service = social_env
        avatar = tmp_path / "me.png"
        avatar.write_bytes(b"avatar bytes")
        profile = db.get_my_profile()
        profile["avatar"] = str(avatar)
        db.save_profile(profile)

        success = msg_service.send_friend_request("Alice", "172.30.0.1", 7780, "user_alice")

        assert success is True
        messages = [data for _target, data in conn_mgr.sent_messages]
        assert messages[0]["type"] == MessageService.FRIEND_REQUEST
        assert messages[0]["profile"]["avatar"] == ""
        assert messages[1]["type"] == MessageService.FILE_OFFER
        assert messages[1]["purpose"] == "avatar"
        assert messages[1]["avatar_owner"] == "Me"
        assert messages[-1]["type"] == MessageService.FILE_COMPLETE
        assert messages[-1]["purpose"] == "avatar"

    def test_send_friend_request_skips_existing_friend(self, social_env):
        db, conn_mgr, msg_service = social_env
        db.add_friend("Alice", "172.30.0.1", 7780, ["kivy"], "Alice Bio")

        success = msg_service.send_friend_request("Alice", "172.30.0.1", 7780)

        assert success is False
        assert conn_mgr.connect_calls == []
        assert conn_mgr.sent_messages == []

    def test_receive_friend_request_auto_accept(self, social_env):
        db, conn_mgr, msg_service = social_env

        # 外部设备发送的 FRIEND_REQUEST
        # 标签 ["kivy"] 契合我们的要求
        sender_profile = {"name": "Dave", "tags": ["kivy"], "bio": "Dave Bio"}
        req_data = {
            "type": MessageService.FRIEND_REQUEST,
            "msg_id": "req_uuid_1",
            "profile": sender_profile,
            "conditions": {"required_tags": [], "min_match_count": 0}
        }

        # 消息服务开始处理
        msg_service.handle_message("192.168.1.8", req_data)

        # 验证是否触发自动接受好友，并添加至好友列表
        friend = db.get_friend("Dave")
        assert friend is not None
        assert friend["ip"] == "192.168.1.8"
        assert friend["bio"] == "Dave Bio"

        # 验证是否自动发回了 ACCEPT 消息给 Dave
        assert len(conn_mgr.sent_messages) == 1
        target, data = conn_mgr.sent_messages[0]
        assert target == "Dave"
        assert data["type"] == "FRIEND_ACCEPT"

    def test_existing_friend_request_resends_accept(self, social_env):
        db, conn_mgr, msg_service = social_env
        db.add_friend("Dave", "172.30.0.1", 7779, ["old"], "Old Bio")
        conn_mgr.online_friends["Dave"] = "172.30.0.1"

        req_data = {
            "type": MessageService.FRIEND_REQUEST,
            "msg_id": "req_existing_1",
            "profile": {
                "user_id": "user_dave",
                "name": "Dave",
                "tags": ["kivy"],
                "bio": "Dave Bio",
                "tcp_port": 7780,
            },
            "conditions": {"required_tags": [], "min_match_count": 0},
        }

        msg_service.handle_message("172.30.0.1", req_data)

        friend = db.get_friend("Dave")
        assert friend["port"] == 7780
        assert friend["user_id"] == "user_dave"
        assert friend["bio"] == "Dave Bio"
        assert len(conn_mgr.sent_messages) == 1
        target, data = conn_mgr.sent_messages[0]
        assert target == "Dave"
        assert data["type"] == "FRIEND_ACCEPT"
        assert data["profile"]["tcp_port"] == 7788

    def test_receive_friend_request_manual_audit(self, social_env):
        db, conn_mgr, msg_service = social_env

        # 外部设备发送的 FRIEND_REQUEST
        # 标签 ["sports"] 不契合我们的要求 ( required_tags 是 ["kivy"] )
        sender_profile = {"name": "Eve", "tags": ["sports"], "bio": "Eve Bio"}
        req_data = {
            "type": MessageService.FRIEND_REQUEST,
            "msg_id": "req_uuid_2",
            "profile": sender_profile,
            "conditions": {"required_tags": [], "min_match_count": 0}
        }

        # 绑定审核回调
        callback_triggered = []
        def my_request_callback(profile, is_match):
            callback_triggered.append((profile, is_match))
        msg_service.on_friend_request = my_request_callback

        # 消息服务开始处理
        msg_service.handle_message("192.168.1.9", req_data)

        # 1. 验证不符合条件时未被自动添加为好友
        assert db.get_friend("Eve") is None

        # 2. 验证是否成功触发人工审核回调
        assert len(callback_triggered) == 1
        prof, is_match = callback_triggered[0]
        assert prof["name"] == "Eve"
        assert is_match is False

    def test_friend_request_callback_receives_source_ip(self, social_env):
        db, conn_mgr, msg_service = social_env

        sender_profile = {"name": "Frank", "tags": ["sports"], "bio": "Frank Bio"}
        req_data = {
            "type": MessageService.FRIEND_REQUEST,
            "msg_id": "req_uuid_3",
            "profile": sender_profile,
            "conditions": {"required_tags": [], "min_match_count": 0}
        }

        callback_triggered = []

        def my_request_callback(profile, is_match, from_ip):
            callback_triggered.append((profile, is_match, from_ip))

        msg_service.on_friend_request = my_request_callback
        msg_service.handle_message("192.168.1.10", req_data)

        assert len(callback_triggered) == 1
        prof, is_match, from_ip = callback_triggered[0]
        assert prof["name"] == "Frank"
        assert prof["ip"] == "192.168.1.10"
        assert from_ip == "192.168.1.10"
        assert is_match is False

    def test_flush_pending_messages(self, social_env):
        db, conn_mgr, msg_service = social_env
        
        # 离线的目标好友
        db.add_friend("Bob", "192.168.1.6", 7779, ["kivy"], "Bob Bio")
        
        # 发送离线消息给 Bob，进入 pending 队列
        msg_service.send_message("Bob", "Hello Bob offline!")
        pending = db.get_pending_messages("Bob")
        assert len(pending) == 1
        assert pending[0]["content"] == "Hello Bob offline!"
        
        # 模拟 Bob 连接上线
        conn_mgr.online_friends["Bob"] = "192.168.1.6"
        
        # 触发 flush_pending_messages
        msg_service.flush_pending_messages("Bob")
        
        # 验证消息已从数据库清除
        assert len(db.get_pending_messages("Bob")) == 0
        
        # 验证消息通过 TCP 发送了出去，并且内容是原本的 CHAT_MESSAGE 格式（非 RELAY）
        assert len(conn_mgr.sent_messages) == 1
        target, data = conn_mgr.sent_messages[0]
        assert target == "Bob"
        assert data["type"] == MessageService.CHAT_MESSAGE
        assert data["content"] == "Hello Bob offline!"

    def test_send_file_online_friend(self, social_env, tmp_path):
        db, conn_mgr, msg_service = social_env
        sample = tmp_path / "sample.txt"
        sample.write_text("hello file transfer", encoding="utf-8")
        db.add_friend("Alice", "192.168.1.5", 7779, ["kivy"], "Alice Bio")
        conn_mgr.online_friends["Alice"] = "192.168.1.5"

        success = msg_service.send_file("Alice", str(sample))

        assert success is True
        types = [msg["type"] for _target, msg in conn_mgr.sent_messages]
        assert types[0] == MessageService.FILE_OFFER
        assert MessageService.FILE_CHUNK in types
        assert types[-1] == MessageService.FILE_COMPLETE
        content = db.get_chat_history("Alice")[0]["content"]
        assert content.startswith("[文件] ")
        payload = json.loads(content.split("] ", 1)[1])
        assert payload["filename"] == "sample.txt"
        assert payload["path"] == str(sample)

    def test_large_file_resumes_after_transient_disconnect(self, tmp_path):
        class LoopbackConnectionManager:
            def __init__(self, drop_chunk=None):
                self.peer_service = None
                self.online = True
                self.drop_chunk = drop_chunk
                self.dropped = False
                self.reconnect_calls = 0
                self.tcp_port = 7779
                self.sent_types = []

            def is_friend_online(self, _name):
                return self.online

            def get_online_friends(self):
                return []

            def send_to_friend(self, _name, packed):
                if not self.online:
                    return False
                size = struct.unpack("!I", packed[:4])[0]
                message = Protocol.parse_message(packed[4:4 + size])
                self.sent_types.append(
                    (
                        message.get("type"),
                        message.get("chunk_index"),
                        message.get("next_chunk"),
                        bool(message.get("binary", False)),
                    )
                )
                if (
                    message.get("type") == MessageService.FILE_CHUNK
                    and message.get("chunk_index") == self.drop_chunk
                    and not self.dropped
                ):
                    self.dropped = True
                    self.online = False
                    return False
                self.peer_service.handle_message("127.0.0.1", message)
                return True

            def connect_to_friend(self, _ip, _port=0, _name=""):
                self.reconnect_calls += 1
                self.online = True
                return True

        sender_db = FriendDB(str(tmp_path / "sender.db"))
        receiver_db = FriendDB(str(tmp_path / "receiver.db"))
        sender_db.save_profile({"name": "Alice"})
        receiver_db.save_profile({"name": "Bob"})
        sender_db.add_friend("Bob", "127.0.0.1", 7779, [], "")
        receiver_db.add_friend("Alice", "127.0.0.1", 7779, [], "")

        sender_conn = LoopbackConnectionManager(drop_chunk=5)
        receiver_conn = LoopbackConnectionManager()
        sender = MessageService(
            sender_conn,
            sender_db,
            receive_dir=str(tmp_path / "sender_files"),
            avatar_dir=str(tmp_path / "sender_avatars"),
        )
        receiver_dir = tmp_path / "receiver_files"
        receiver = MessageService(
            receiver_conn,
            receiver_db,
            receive_dir=str(receiver_dir),
            avatar_dir=str(tmp_path / "receiver_avatars"),
        )
        sender_conn.peer_service = receiver
        receiver_conn.peer_service = sender
        receiver.on_file_offer_received = (
            lambda _name, _filename, _size, file_id: receiver.accept_file_offer(file_id)
        )
        sender.FILE_ACK_TIMEOUT = 0.2
        progress_updates = []
        sender.on_file_progress = (
            lambda *args, **_kwargs: progress_updates.append(args)
        )

        payload = bytes(range(256)) * (12 * 1024)  # 3 MiB, several ACK windows
        source = tmp_path / "large.bin"
        source.write_bytes(payload)
        transfer_id = f"large-transfer-{uuid.uuid4().hex}"
        try:
            result = sender.send_file(
                "Bob", str(source), file_id=transfer_id
            )
            assert result is True, (sender_conn.sent_types, receiver_conn.sent_types)
            assert sender_conn.dropped is True
            assert sender_conn.reconnect_calls == 1
            assert any(
                item[0] == MessageService.FILE_CHUNK and item[3] is True
                for item in sender_conn.sent_types
            )
            assert (receiver_dir / "large.bin").read_bytes() == payload
            assert progress_updates[-1] == (
                transfer_id,
                "Bob",
                "large.bin",
                len(payload),
                len(payload),
                True,
            )
            assert [item[3] for item in progress_updates] == sorted(
                item[3] for item in progress_updates
            )
        finally:
            sender_db.close()
            receiver_db.close()

    def test_receive_file_writes_to_receive_dir(self, social_env):
        db, _conn_mgr, msg_service = social_env
        callbacks = []
        msg_service.on_file_received = lambda name, path, ts: callbacks.append((name, path, ts))

        payload = b"beiyang file payload"
        file_id = "file-1"
        offer = {
            "type": MessageService.FILE_OFFER,
            "file_id": file_id,
            "from_name": "Alice",
            "to_name": "Me",
            "filename": "note.txt",
            "size": len(payload),
            "chunk_size": 1024,
            "chunk_count": 1,
            "sha256": msg_service._sha256_bytes(payload),
            "timestamp": "2026-06-26 12:00:00",
        }
        chunk = {
            "type": MessageService.FILE_CHUNK,
            "file_id": file_id,
            "chunk_index": 0,
            "data_b64": base64.b64encode(payload).decode("ascii"),
        }
        complete = {
            "type": MessageService.FILE_COMPLETE,
            "file_id": file_id,
            "from_name": "Alice",
            "to_name": "Me",
            "filename": "note.txt",
            "size": len(payload),
            "sha256": msg_service._sha256_bytes(payload),
            "timestamp": "2026-06-26 12:00:00",
        }

        msg_service.handle_message("192.168.1.5", offer)
        msg_service.handle_message("192.168.1.5", chunk)
        msg_service.handle_message("192.168.1.5", complete)
        assert msg_service.accept_file_offer(file_id) is True

        assert len(callbacks) == 1
        _, saved_path, _ = callbacks[0]
        assert os.path.dirname(saved_path) == msg_service.receive_dir
        with open(saved_path, "rb") as f:
            assert f.read() == payload
        history = db.get_chat_history("Alice")
        content = history[0]["content"]
        assert content.startswith("[文件] ")
        file_payload = json.loads(content.split("] ", 1)[1])
        assert file_payload["filename"] == "note.txt"
        assert file_payload["path"] == saved_path

    def test_receive_file_writes_to_custom_receive_dir(self, social_env, tmp_path):
        db, _conn_mgr, msg_service = social_env
        custom_dir = tmp_path / "chosen_inbox"
        msg_service.set_receive_dir(str(custom_dir))

        payload = b"custom inbox payload"
        file_id = "file-custom-dir"
        offer = {
            "type": MessageService.FILE_OFFER,
            "file_id": file_id,
            "from_name": "Alice",
            "to_name": "Me",
            "filename": "custom.txt",
            "size": len(payload),
            "chunk_size": 1024,
            "chunk_count": 1,
            "sha256": msg_service._sha256_bytes(payload),
            "timestamp": "2026-06-26 12:00:00",
        }
        chunk = {
            "type": MessageService.FILE_CHUNK,
            "file_id": file_id,
            "chunk_index": 0,
            "data_b64": base64.b64encode(payload).decode("ascii"),
        }
        complete = {
            "type": MessageService.FILE_COMPLETE,
            "file_id": file_id,
            "from_name": "Alice",
            "to_name": "Me",
            "filename": "custom.txt",
            "size": len(payload),
            "sha256": msg_service._sha256_bytes(payload),
            "timestamp": "2026-06-26 12:00:00",
        }

        msg_service.handle_message("192.168.1.5", offer)
        msg_service.handle_message("192.168.1.5", chunk)
        msg_service.handle_message("192.168.1.5", complete)
        assert msg_service.accept_file_offer(file_id) is True

        saved_path = custom_dir / "custom.txt"
        assert saved_path.read_bytes() == payload
        history = db.get_chat_history("Alice")
        file_payload = json.loads(history[0]["content"].split("] ", 1)[1])
        assert file_payload["path"] == str(saved_path)

    def test_file_resume_uses_offer_part_path_when_name_conflicts(self, social_env, tmp_path):
        _db, conn_mgr, msg_service = social_env
        msg_service.set_receive_dir(str(tmp_path))
        (tmp_path / "note.txt").write_text("existing finished file", encoding="utf-8")

        payload = b"x" * (msg_service.FILE_CHUNK_SIZE + 10)
        offer = {
            "type": MessageService.FILE_OFFER,
            "file_id": "resume-conflict",
            "from_name": "Alice",
            "to_name": "Me",
            "filename": "note.txt",
            "size": len(payload),
            "chunk_size": msg_service.FILE_CHUNK_SIZE,
            "chunk_count": 2,
            "sha256": msg_service._sha256_bytes(payload),
            "timestamp": "2026-06-26 12:00:00",
        }

        msg_service.handle_message("192.168.1.5", offer)
        with msg_service._file_lock:
            state = msg_service._incoming_files["resume-conflict"]
        assert os.path.basename(state["part_path"]) == (
            "meeting_in_beiyang_resume-conflict_note.txt.part"
        )
        assert os.path.dirname(state["part_path"]) == tempfile.gettempdir()
        with open(state["part_path"], "wb") as f:
            f.write(payload[:msg_service.FILE_CHUNK_SIZE])

        conn_mgr.online_friends["Alice"] = "192.168.1.5"
        msg_service.handle_message(
            "192.168.1.5",
            {
                "type": msg_service.FILE_RESUME_REQ,
                "file_id": "resume-conflict",
                "filename": "../note.txt",
                "sha256": msg_service._sha256_bytes(payload),
            },
        )

        target, data = conn_mgr.sent_messages[-1]
        assert target == "Alice"
        assert data["type"] == msg_service.FILE_RESUME_RESP
        assert data["completed_chunks"] == 1

    def test_receive_avatar_file_updates_friend_avatar(self, social_env):
        db, _conn_mgr, msg_service = social_env
        callbacks = []
        msg_service.on_file_received = lambda name, path, ts: callbacks.append((name, path, ts))
        db.add_friend("Alice", "192.168.1.5", 7779, ["kivy"], "Alice Bio", user_id="user_alice")

        payload = b"fake png avatar payload"
        file_id = "avatar-file-1"
        offer = {
            "type": MessageService.FILE_OFFER,
            "file_id": file_id,
            "from_name": "Alice",
            "to_name": "Me",
            "filename": "alice.png",
            "size": len(payload),
            "chunk_size": 1024,
            "chunk_count": 1,
            "sha256": msg_service._sha256_bytes(payload),
            "timestamp": "2026-06-26 12:00:00",
            "purpose": "avatar",
            "avatar_owner": "Alice",
            "avatar_user_id": "user_alice",
        }
        chunk = {
            "type": MessageService.FILE_CHUNK,
            "file_id": file_id,
            "chunk_index": 0,
            "data_b64": base64.b64encode(payload).decode("ascii"),
        }
        complete = {
            "type": MessageService.FILE_COMPLETE,
            "file_id": file_id,
            "from_name": "Alice",
            "to_name": "Me",
            "filename": "alice.png",
            "size": len(payload),
            "sha256": msg_service._sha256_bytes(payload),
            "timestamp": "2026-06-26 12:00:00",
            "purpose": "avatar",
            "avatar_owner": "Alice",
            "avatar_user_id": "user_alice",
        }

        msg_service.handle_message("192.168.1.5", offer)
        msg_service.handle_message("192.168.1.5", chunk)
        msg_service.handle_message("192.168.1.5", complete)

        friend = db.get_friend_by_user_id("user_alice")
        assert friend["avatar"].endswith(".png")
        with open(friend["avatar"], "rb") as f:
            assert f.read() == payload
        assert db.get_chat_history("Alice") == []
        assert callbacks[0][0] == "Alice"
