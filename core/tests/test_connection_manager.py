"""
挑战 3 - 连接池状态单元测试
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.backend.services.connection_manager import ConnectionManager


class DummySocket:
    def __init__(self):
        self.closed = False
        self.sent = []
        self.options = []

    def close(self):
        self.closed = True

    def sendall(self, data):
        self.sent.append(data)

    def getpeername(self):
        if self.closed:
            raise OSError("closed")
        return ("172.30.0.1", 7780)

    def setsockopt(self, *args):
        self.options.append(args)


def test_register_connection_dedupes_temporary_ip_entry():
    manager = ConnectionManager(my_name="Me", tcp_port=7779)
    sock = DummySocket()

    manager._register_connection(sock, "172.30.0.1", "Alice", 0)
    manager._register_connection(sock, "172.30.0.1", "Alice", 7780)

    online = manager.get_online_friends()

    assert len(online) == 1
    assert online[0]["name"] == "Alice"
    assert online[0]["ip"] == "172.30.0.1"
    assert online[0]["port"] == 7780


def test_get_online_friends_prefers_port_entry_for_same_name():
    manager = ConnectionManager(my_name="Me", tcp_port=7779)

    manager._register_connection(DummySocket(), "172.30.0.1", "Alice", 0)
    manager._register_connection(DummySocket(), "172.30.0.1", "Alice", 7780)

    online = manager.get_online_friends()

    assert len(online) == 1
    assert online[0]["port"] == 7780


def test_duplicate_connection_keeps_existing_socket():
    manager = ConnectionManager(my_name="Me", tcp_port=7779)
    old_socket = DummySocket()
    new_socket = DummySocket()

    key = manager._register_connection(old_socket, "172.30.0.1", "Alice", 7780)
    manager._register_connection(new_socket, "172.30.0.1", "Alice", 7780)
    manager._handle_disconnect(key, new_socket)

    assert new_socket.closed is True
    assert old_socket.closed is False
    assert manager.connections[key]["socket"] is old_socket
    assert manager.is_friend_online("Alice") is True


def test_registered_connection_has_send_lock_and_sends_through_it():
    manager = ConnectionManager(my_name="Me", tcp_port=7779)
    sock = DummySocket()

    key = manager._register_connection(sock, "172.30.0.1", "Alice", 7780)
    ok = manager.send_to_friend("Alice", b"payload")

    assert ok is True
    assert sock.sent == [b"payload"]
    assert "send_lock" in manager.connections[key]


def test_online_queries_prune_closed_socket_entries():
    manager = ConnectionManager(my_name="Me", tcp_port=7779)
    sock = DummySocket()

    manager._register_connection(sock, "172.30.0.1", "Alice", 7780)
    sock.close()

    assert manager.is_friend_online("Alice") is False
    assert manager.get_online_friends() == []
    assert manager.get_connection_count() == 0
