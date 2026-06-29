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
        self.connect_success = True
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
        if not self.connect_success:
            return False
        actual_name = name if name else (port if isinstance(port, str) else "")
        if actual_name:
            self.online_friends[actual_name] = ip
        return True


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

        success = msg_service.send_message("Alice", "Hi Alice!", msg_id="ui-msg-1")
        assert success is True

        # 验证消息直接通过 TCP 送达了
        assert len(conn_mgr.sent_messages) == 1
        target, data = conn_mgr.sent_messages[0]
        assert target == "Alice"
        assert data["type"] == MessageService.CHAT_MESSAGE
        assert data["msg_id"] == "ui-msg-1"
        assert data["content"] == "Hi Alice!"

        # 检查是否同时记入了聊天历史
        history = db.get_chat_history("Alice")
        assert len(history) == 1
        assert history[0]["content"] == "Hi Alice!"
        assert history[0]["direction"] == "send"
        assert history[0]["msg_id"] == "ui-msg-1"

    def test_receive_message_callback_includes_msg_id(self, social_env):
        db, conn_mgr, msg_service = social_env
        received = []
        msg_service.on_message_received = (
            lambda name, content, timestamp, msg_id:
            received.append((name, content, timestamp, msg_id))
        )

        msg_service.handle_message(
            "192.168.1.5",
            {
                "type": MessageService.CHAT_MESSAGE,
                "msg_id": "incoming-msg-1",
                "from_name": "Alice",
                "to_name": "Me",
                "content": "Hi Me!",
                "timestamp": "2026-06-29 00:30:00",
            },
        )

        assert received == [
            ("Alice", "Hi Me!", "2026-06-29 00:30:00", "incoming-msg-1")
        ]
        history = db.get_chat_history("Alice")
        assert len(history) == 1
        assert history[0]["direction"] == "receive"
        assert history[0]["msg_id"] == "incoming-msg-1"

    def test_send_message_offline_relay(self, social_env):
        db, conn_mgr, msg_service = social_env

        # 离线的目标好友
        db.add_friend("Bob", "192.168.1.6", 7779, ["kivy"], "Bob Bio")
        # 在线的其他好友（作为中继节点）
        db.add_friend("Charlie", "192.168.1.7", 7779, ["kivy"], "Charlie Bio")
        conn_mgr.online_friends["Charlie"] = "192.168.1.7"
        conn_mgr.connect_success = False

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
        conn_mgr.connect_success = False

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

    def test_file_resume_response_falls_back_to_source_ip(self, tmp_path):
        class FallbackConnectionManager:
            tcp_port = 7779

            def __init__(self):
                self.sent = []

            def is_friend_online(self, _name):
                return True

            def get_online_friends(self):
                return []

            def send_to_friend(self, target, packed):
                size = struct.unpack("!I", packed[:4])[0]
                message = Protocol.parse_message(packed[4:4 + size])
                self.sent.append((target, message))
                return target == "192.168.1.5"

        db = FriendDB(str(tmp_path / "receiver.db"))
        db.save_profile({"name": "Bob"})
        conn = FallbackConnectionManager()
        service = MessageService(
            conn,
            db,
            receive_dir=str(tmp_path / "received"),
            avatar_dir=str(tmp_path / "avatars"),
        )
        try:
            service._handle_file_offer(
                "192.168.1.5",
                {
                    "type": MessageService.FILE_OFFER,
                    "file_id": "resume-fallback",
                    "from_name": "Alice",
                    "to_name": "Bob",
                    "filename": "photo.png",
                    "size": 1024,
                    "chunk_size": 1024,
                    "chunk_count": 1,
                    "sha256": "",
                },
            )
            service._handle_file_resume_req(
                "192.168.1.5",
                {
                    "type": service.FILE_RESUME_REQ,
                    "file_id": "resume-fallback",
                    "filename": "photo.png",
                    "sha256": "",
                },
            )

            assert conn.sent[-1][0] == "192.168.1.5"
            assert conn.sent[-1][1]["type"] == service.FILE_RESUME_RESP
        finally:
            db.close()

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

    def test_delete_friend_clears_requests(self, social_env):
        db, _conn_mgr, _msg_service = social_env
        db.add_friend("Alice", "192.168.1.5", 7779, ["kivy"], "Alice Bio", user_id="user_alice")
        # Prepopulate friend_requests with accepted request
        db.upsert_friend_request(
            user_id="user_alice",
            name="Alice",
            ip="192.168.1.5",
            port=7779,
            direction="incoming",
            status="accepted"
        )
        assert db.get_relationship_status(user_id="user_alice") == "accepted"

        # Remove friend
        db.remove_friend("Alice")
        assert db.get_friend("Alice") is None
        assert db.get_relationship_status(user_id="user_alice") == "none"

    def test_handle_friend_accept_ignores_non_pending(self, social_env):
        db, _conn_mgr, msg_service = social_env

        # Scenario 1: Receive FRIEND_ACCEPT when status is "none" (not pending_sent). Should ignore.
        accept_data = {
            "type": MessageService.FRIEND_ACCEPT,
            "msg_id": "accept_msg_none",
            "profile": {
                "user_id": "user_alice",
                "name": "Alice",
                "tags": ["kivy"],
                "bio": "Alice Bio",
                "tcp_port": 7779,
            }
        }
        msg_service.handle_message("192.168.1.5", accept_data)
        assert db.get_friend("Alice") is None

        # Scenario 2: Relationship status is "pending_sent". Should accept.
        db.upsert_friend_request(
            user_id="user_alice",
            name="Alice",
            ip="192.168.1.5",
            port=7779,
            direction="outgoing",
            status="pending"
        )
        assert db.get_relationship_status(user_id="user_alice") == "pending_sent"

        accept_data_2 = dict(accept_data)
        accept_data_2["msg_id"] = "accept_msg_pending"
        msg_service.handle_message("192.168.1.5", accept_data_2)
        friend = db.get_friend("Alice")
        assert friend is not None
        assert friend["status"] == "accepted"

    def test_handle_friend_delete_removes_friend_from_db(self, social_env):
        db, _conn_mgr, msg_service = social_env

        deleted_names = []
        msg_service.on_friend_deleted = lambda name: deleted_names.append(name)

        db.add_friend("Alice", "192.168.1.5", 7779, ["kivy"], "Alice Bio", user_id="user_alice")
        db.upsert_friend_request(
            user_id="user_alice",
            name="Alice",
            ip="192.168.1.5",
            port=7779,
            direction="incoming",
            status="accepted"
        )
        assert db.get_friend("Alice") is not None
        assert db.get_relationship_status(user_id="user_alice") == "accepted"

        delete_data = {
            "type": Protocol.FRIEND_DELETE,
            "msg_id": "delete_msg_1",
            "profile": {
                "user_id": "user_alice",
                "name": "Alice",
            }
        }
        msg_service.handle_message("192.168.1.5", delete_data)

        # Verify Alice is completely removed from DB
        assert db.get_friend("Alice") is None
        assert db.get_relationship_status(user_id="user_alice") == "none"

        # Verify callback was triggered
        assert deleted_names == ["Alice"]

    def test_system_notifications(self, social_env):
        db, _conn_mgr, msg_service = social_env

        # Track notifications callback
        changed_notifs_calls = 0
        def on_changed():
            nonlocal changed_notifs_calls
            changed_notifs_calls += 1

        msg_service.on_notifications_changed = on_changed

        # 1. Test database helpers via message service
        assert len(db.get_system_notifications()) == 0
        msg_service.add_system_notification("Title 1", "Content 1", "info")
        assert changed_notifs_calls == 1

        notifs = db.get_system_notifications()
        assert len(notifs) == 1
        assert notifs[0]["title"] == "Title 1"
        assert notifs[0]["content"] == "Content 1"
        assert notifs[0]["is_read"] == 0

        # 2. Test callback on incoming FRIEND_DELETE
        db.add_friend("Bob", "192.168.1.6", 7779, [], "Bob Bio", user_id="user_bob")
        delete_data = {
            "type": Protocol.FRIEND_DELETE,
            "msg_id": "delete_msg_notif",
            "profile": {
                "user_id": "user_bob",
                "name": "Bob",
            }
        }
        msg_service.handle_message("192.168.1.6", delete_data)

        # Verify Bob is removed
        assert db.get_friend("Bob") is None
        # Verify on_notifications_changed callback was triggered for deletion notification
        assert changed_notifs_calls == 2

        # Verify notification entry is saved
        notifs = db.get_system_notifications()
        assert len(notifs) == 2
        assert any("Bob" in n["content"] for n in notifs)

        # 3. Test mark all read
        db.mark_all_notifications_read()
        notifs = db.get_system_notifications()
        assert all(n["is_read"] == 1 for n in notifs)

        # 4. Test clear
        db.clear_system_notifications()
        assert len(db.get_system_notifications()) == 0

    def test_file_offer_system_notifications(self, social_env):
        db, _conn_mgr, msg_service = social_env

        # Track notifications callback
        changed_notifs_calls = 0
        def on_changed():
            nonlocal changed_notifs_calls
            changed_notifs_calls += 1

        msg_service.on_notifications_changed = on_changed
        db.add_friend("Charlie", "192.168.1.7", 7779, [], "Charlie Bio", user_id="user_charlie")
        my_name = db.get_my_profile().get("name", "")

        offer_data = {
            "type": msg_service.FILE_OFFER,
            "file_id": "test_file_id_123",
            "from_name": "Charlie",
            "to_name": my_name,
            "filename": "hello.zip",
            "size": 1024 * 1024,
            "chunk_size": 256 * 1024,
            "chunk_count": 4,
            "sha256": "abcdef",
            "timestamp": "2026-06-29 03:00:00",
            "purpose": "chat_file",
        }

        # Handle the offer message
        msg_service.handle_message("192.168.1.7", offer_data)

        # Verify notifications changed callback was triggered
        assert changed_notifs_calls == 1

        # Verify notification entry is saved in DB with correct category and formatted size
        notifs = db.get_system_notifications()
        assert len(notifs) == 1
        assert notifs[0]["category"] == "file_offer"
        assert "Charlie" in notifs[0]["content"]
        assert "hello.zip" in notifs[0]["content"]
        assert "1.0 MiB" in notifs[0]["content"]
        assert "test_file_id_123" in notifs[0]["content"]

    def test_file_offer_deduplication(self, social_env):
        db, _conn_mgr, msg_service = social_env
        db.add_friend("Charlie", "192.168.1.7", 7779, [], "Charlie Bio", user_id="user_charlie")
        my_name = db.get_my_profile().get("name", "")

        offer_data = {
            "type": msg_service.FILE_OFFER,
            "file_id": "duplicate_file_id_999",
            "from_name": "Charlie",
            "to_name": my_name,
            "filename": "duplicate_test.zip",
            "size": 1024 * 1024,
            "chunk_size": 256 * 1024,
            "chunk_count": 4,
            "sha256": "abcdef",
            "timestamp": "2026-06-29 03:00:00",
            "purpose": "chat_file",
        }

        # Handle the offer message first time
        msg_service.handle_message("192.168.1.7", offer_data)

        # Handle the duplicate offer message
        msg_service.handle_message("192.168.1.7", offer_data)

        # Verify only 1 notification is recorded (it filtered out the duplicate!)
        notifs = db.get_system_notifications()
        count = sum(1 for n in notifs if "duplicate_file_id_999" in n["content"])
        assert count == 1

    def test_moment_deletion_sync(self, social_env):
        db, conn_mgr, msg_service = social_env
        db.add_friend("Charlie", "192.168.1.7", 7779, [], "Charlie Bio", user_id="user_charlie")

        # Save a moment from Charlie
        db.save_moment("char-post-1", "Charlie", "Dynamic content 1", "", "2026-06-29 03:00:00")
        db.save_moment("char-post-2", "Charlie", "Dynamic content 2", "", "2026-06-29 03:01:00")
        assert db.has_moment("char-post-1") is True
        assert db.has_moment("char-post-2") is True

        # 1. Test real-time MOMENT_DELETE handling
        delete_data = {
            "type": "MOMENT_DELETE",
            "post_id": "char-post-1",
        }
        msg_service.handle_message("192.168.1.7", delete_data)
        assert db.has_moment("char-post-1") is False
        assert db.has_moment("char-post-2") is True

        # 2. Test fallback synchronization deletion:
        # Charlie sends MOMENTS_SYNC_RESP containing only char-post-3
        sync_resp_data = {
            "type": "MOMENTS_SYNC_RESP",
            "posts": [
                {
                    "post_id": "char-post-3",
                    "author": "Charlie",
                    "content": "Dynamic content 3",
                    "media_name": "",
                    "media_data": "",
                    "timestamp": "2026-06-29 03:02:00",
                }
            ],
            "comments": [],
            "sender_name": "Charlie",
        }
        msg_service.handle_message("192.168.1.7", sync_resp_data)

        # char-post-2 (which was not in sync list) should be deleted!
        assert db.has_moment("char-post-2") is False
        # char-post-3 should be added!
        assert db.has_moment("char-post-3") is True
