"""
挑战 3 - 协议模块单元测试
"""
import pytest
import sys
import os
import json

# 将项目根目录添加到路径中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from code_share.utils.protocol import Protocol


class MockSocket:
    """Mock socket for testing unpack_with_header"""
    def __init__(self, data_bytes):
        self.data = data_bytes
        self.cursor = 0

    def recv(self, size):
        if self.cursor >= len(self.data):
            return b""
        chunk = self.data[self.cursor:self.cursor + size]
        self.cursor += len(chunk)
        return chunk


class TestProtocol:
    """协议层测试类"""

    def test_create_and_parse_ping(self):
        device_name = "UserA"
        tcp_port = 7779
        packet = Protocol.create_ping_packet(device_name, tcp_port)
        assert isinstance(packet, bytes)

        data = Protocol.parse_udp_packet(packet)
        assert data["type"] == Protocol.UDP_PING
        assert data["device_name"] == device_name
        assert data["tcp_port"] == tcp_port

    def test_create_and_parse_pong(self):
        device_name = "UserB"
        ip = "192.168.1.100"
        packet = Protocol.create_pong_packet(device_name, ip, 7779)
        assert isinstance(packet, bytes)

        data = Protocol.parse_udp_packet(packet)
        assert data["type"] == Protocol.UDP_PONG
        assert data["device_name"] == device_name
        assert data["ip"] == ip

    def test_pack_and_unpack_header(self):
        body = b"hello world"
        packed = Protocol.pack_with_header(body)
        assert len(packed) == len(body) + 4

        mock_sock = MockSocket(packed)
        success, unpacked_body = Protocol.unpack_with_header(mock_sock)
        assert success is True
        assert unpacked_body == body

    def test_create_message(self):
        msg = Protocol.create_message("CUSTOM_TYPE", key="val")
        data = Protocol.parse_message(msg[4:])
        assert data["type"] == "CUSTOM_TYPE"
        assert data["key"] == "val"

    def test_create_profile_exchange(self):
        packet = Protocol.create_profile_exchange("UserA", ["tag1", "tag2"], "hello")
        data = Protocol.parse_message(packet[4:])
        assert data["type"] == Protocol.PROFILE_EXCHANGE
        assert data["name"] == "UserA"
        assert data["tags"] == ["tag1", "tag2"]
        assert data["bio"] == "hello"

    def test_create_friend_request(self):
        my_profile = {"name": "UserA", "tags": ["tag1"], "bio": "hi"}
        my_conditions = {"required_tags": ["tag2"], "min_match_count": 1}
        packet = Protocol.create_friend_request("UserA", ["tag1"], "hi", my_conditions)
        
        data = Protocol.parse_message(packet[4:])
        assert data["type"] == Protocol.FRIEND_REQUEST
        assert data["profile"]["name"] == "UserA"
        assert data["conditions"] == my_conditions

    def test_create_friend_accept(self):
        packet = Protocol.create_friend_accept("UserB", ["tag2"], "hello")
        data = Protocol.parse_message(packet[4:])
        assert data["type"] == Protocol.FRIEND_ACCEPT
        assert data["name"] == "UserB"

    def test_create_friend_reject(self):
        packet = Protocol.create_friend_reject("UserB", "mismatch")
        data = Protocol.parse_message(packet[4:])
        assert data["type"] == Protocol.FRIEND_REJECT
        assert data["name"] == "UserB"
        assert data["reason"] == "mismatch"

    def test_create_chat_message(self):
        packet = Protocol.create_chat_message("id123", "UserA", "UserB", "hello world", "2026-06-13 00:00:00")
        data = Protocol.parse_message(packet[4:])
        assert data["type"] == Protocol.CHAT_MESSAGE
        assert data["msg_id"] == "id123"
        assert data["content"] == "hello world"

    def test_create_relay_message(self):
        orig = {"type": Protocol.CHAT_MESSAGE, "content": "hi"}
        packet = Protocol.create_relay_message(orig, ["UserC"])
        data = Protocol.parse_message(packet[4:])
        assert data["type"] == Protocol.RELAY_MESSAGE
        assert data["original_message"] == orig
        assert data["relay_hops"] == ["UserC"]

    def test_create_heartbeat(self):
        packet = Protocol.create_heartbeat("UserA", "192.168.1.1", 7779)
        data = Protocol.parse_message(packet[4:])
        assert data["type"] == Protocol.HEARTBEAT
        assert data["name"] == "UserA"
        assert data["ip"] == "192.168.1.1"

    def test_create_online_status(self):
        packet = Protocol.create_online_status("UserA", True)
        data = Protocol.parse_message(packet[4:])
        assert data["type"] == Protocol.ONLINE_STATUS
        assert data["name"] == "UserA"
        assert data["online"] is True
