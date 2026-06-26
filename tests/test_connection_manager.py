"""
挑战 3 - 连接池状态单元测试
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from code_share.services.connection_manager import ConnectionManager


class DummySocket:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


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
