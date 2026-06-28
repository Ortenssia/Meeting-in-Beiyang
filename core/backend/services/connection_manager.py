"""
连接池管理模块 (Challenge 3 - 相识北洋)

管理多个同时存在的好友 TCP 连接，提供：
  - TCP 服务端：监听并接受入站连接，每个连接启动独立接收线程
  - 连接池：维护 friend_ip -> {socket, name, connected_at} 映射
  - 主动连接：connect_to_friend() 向好友发起 TCP 连接
  - 消息收发：send_to_friend() / broadcast_to_friends()
  - 心跳线程：每 30 秒向所有好友广播 HEARTBEAT 消息
  - IP 变更检测：监控本机默认 IP，变化时通知所有好友
  - 线程安全：所有连接池操作均在互斥锁保护下进行

TCP 端口：7779
"""

import logging
import socket
import threading
import time
from typing import Callable, Dict, List, Optional

from core.backend.shared.helpers import Helpers
from core.backend.shared.protocol import Protocol

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    好友连接池管理器。

    负责维护与所有已添加好友之间的 TCP 长连接，包括入站（好友连我）
    和出站（我连好友）两个方向的连接。

    上层通过设置回调函数响应连接事件：
      - on_friend_connected(name, ip)
      - on_friend_disconnected(ip)
      - on_message_received(ip, data)
      - on_error(msg)
    """

    def __init__(
        self,
        my_name: str = "",
        tcp_port: int = Protocol.DEFAULT_TCP_PORT,
        my_user_id: str = "",
        my_device_id: str = "",
    ):
        """
        Args:
            my_name:  本机用户名 / 昵称，用于心跳和身份宣告。
            tcp_port: 本机 TCP 监听端口，默认 7779。
        """
        self.my_name = my_name or Helpers.get_hostname()
        self.tcp_port = tcp_port
        self.my_user_id = my_user_id
        self.my_device_id = my_device_id

        # ------------------------------------------------------------------ #
        #  连接池：endpoint -> {"socket", "name", "ip", "port", "connected_at"}
        # endpoint is normally "ip:port" when the peer advertises a TCP port.
        # ------------------------------------------------------------------ #
        self.connections: Dict[str, Dict] = {}
        self._lock = threading.Lock()

        # 服务端 socket
        self._server_socket: Optional[socket.socket] = None
        self._running = False

        # 记录上一次检测到的本机 IP（用于 IP 变更检测）
        self._last_known_ip: str = Helpers.get_default_ip()

        # 后台线程引用
        self._server_thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._ip_monitor_thread: Optional[threading.Thread] = None

        # ------------------------------------------------------------------ #
        #  回调函数（由上层设置）
        # ------------------------------------------------------------------ #
        self.on_friend_connected: Optional[Callable[[str, str], None]] = None
        self.on_friend_disconnected: Optional[Callable[[str], None]] = None
        self.on_message_received: Optional[Callable[[str, dict], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None

    # ================================================================== #
    #  生命周期
    # ================================================================== #

    def start_server(self, port: int = 0):
        """
        启动 TCP 服务端，开始监听入站连接。

        为每个新连接启动一个独立的接收线程，并启动心跳线程和 IP 监控线程。

        Args:
            port: 监听端口，传入 0 或不传则使用构造时指定的 tcp_port。
        """
        if self._running:
            return

        listen_port = port if port > 0 else self.tcp_port

        try:
            self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_socket.bind(("0.0.0.0", listen_port))
            self._server_socket.listen(20)
            self._server_socket.settimeout(1.0)  # 1 秒超时以便检查 running 标志

            self.tcp_port = listen_port
            self._running = True

            # 接受连接线程
            self._server_thread = threading.Thread(
                target=self._accept_worker, daemon=True, name="TCP-Accept"
            )
            self._server_thread.start()

            # 心跳线程：每 30 秒广播 HEARTBEAT
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_worker, daemon=True, name="TCP-Heartbeat"
            )
            self._heartbeat_thread.start()

            # IP 变更监控线程：每 15 秒检测本机 IP 是否变化
            self._ip_monitor_thread = threading.Thread(
                target=self._ip_monitor_worker, daemon=True, name="TCP-IPMonitor"
            )
            self._ip_monitor_thread.start()

            logger.info("TCP 服务端已启动，监听端口 %d", listen_port)

        except Exception as e:
            self._running = False
            error_msg = f"TCP 服务端启动失败: {e}"
            logger.error(error_msg)
            if self.on_error:
                self.on_error(error_msg)

    def stop(self):
        """
        停止所有服务：关闭服务端 socket，断开所有好友连接，终止后台线程。
        """
        self._running = False

        # 关闭服务端 socket
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
            self._server_socket = None

        # 断开所有好友连接
        with self._lock:
            for endpoint in list(self.connections.keys()):
                self._disconnect_friend_unlocked(endpoint)

        logger.info("TCP 服务端已停止")

    # ================================================================== #
    #  入站连接（服务端 accept）
    # ================================================================== #

    def _accept_worker(self):
        """
        接受连接线程：循环 accept()，为每个新连接启动接收线程。

        如果已有到该 IP 的已命名连接，直接关闭新连接。
        TCP 双向通道只需一条，多余的入站连接是网络波动或双方同时
        重连导致的重复握手。
        """
        while self._running:
            try:
                client_sock, addr = self._server_socket.accept()
                client_ip = addr[0]
                client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

                # 已有到该 IP 的已命名连接 → 关闭重复入站连接
                dup = False
                with self._lock:
                    for info in self.connections.values():
                        if info.get("ip") == client_ip and not self._looks_like_ip(
                            info.get("name", "")
                        ):
                            dup = True
                            break
                if dup:
                    logger.debug("已有到 %s 的连接，关闭重复入站连接", client_ip)
                    try:
                        client_sock.close()
                    except Exception:
                        pass
                    continue

                logger.info("收到入站连接: %s", client_ip)

                recv_thread = threading.Thread(
                    target=self._receive_worker,
                    args=(client_sock, client_ip),
                    daemon=True,
                    name=f"Recv-{client_ip}",
                )
                recv_thread.start()

            except socket.timeout:
                continue
            except OSError:
                break
            except Exception as e:
                if self._running:
                    logger.error("接受连接异常: %s", e)
                time.sleep(0.1)

    # ================================================================== #
    #  接收线程（每个连接一个）
    # ================================================================== #

    def _receive_worker(self, sock: socket.socket, friend_ip: str):
        """
        连接接收线程：循环读取消息并触发回调。

        当连接断开或读取出错时，自动清理连接池并触发 on_friend_disconnected。

        Args:
            sock:      该好友连接的 socket。
            friend_ip: 好友 IP 地址。
        """
        connection_key = friend_ip
        while self._running:
            try:
                success, data = Protocol.unpack_with_header(sock)
                if not success:
                    # 连接已断开
                    break

                message = Protocol.parse_message(data)
                if not message:
                    continue

                msg_type = message.get("type", "")

                # 特殊处理：入站连接时第一条消息可能是 PROFILE_EXCHANGE，
                # 从中提取好友名字并注册到连接池
                if msg_type == Protocol.PROFILE_EXCHANGE:
                    friend_name = message.get("name", "Unknown")
                    tcp_port = int(message.get("tcp_port", 0) or 0)
                    connection_key = self._register_connection(
                        sock, friend_ip, friend_name, tcp_port
                    )

                # 特殊处理：HEARTBEAT 消息可能带来名字更新
                elif msg_type == Protocol.HEARTBEAT:
                    friend_name = message.get("name", "")
                    if friend_name:
                        tcp_port = int(message.get("port", 0) or 0)
                        connection_key = self._register_connection(
                            sock, friend_ip, friend_name, tcp_port
                        )

                # FRIEND_REQUEST / FRIEND_ACCEPT both carry a profile. Register
                # the inbound socket as soon as we learn the peer name so replies
                # can be sent back over the same connection.
                elif msg_type in (Protocol.FRIEND_REQUEST, Protocol.FRIEND_ACCEPT):
                    profile = message.get("profile", {}) or {}
                    friend_name = profile.get("name", "")
                    if friend_name:
                        tcp_port = int(profile.get("tcp_port", 0) or 0)
                        connection_key = self._register_connection(
                            sock, friend_ip, friend_name, tcp_port
                        )

                # 将消息传递给上层
                if self.on_message_received:
                    self.on_message_received(friend_ip, message)

            except Exception as e:
                logger.debug("接收线程异常 [%s]: %s", friend_ip, e)
                break

        # 连接断开，清理
        self._handle_disconnect(connection_key, sock)
        try:
            sock.close()
        except Exception:
            pass

    def _handle_disconnect(self, endpoint: str, disconnected_socket=None):
        """
        处理好友连接断开事件。

        从连接池移除该 IP，并触发 on_friend_disconnected 回调。

        Args:
            endpoint: 断开的连接 key（通常为 ip:port）。
        """
        friend_name = ""
        friend_ip = endpoint
        with self._lock:
            key = self._find_connection_key(endpoint)
            if key:
                info = self.connections[key]
                if disconnected_socket is not None and info.get("socket") is not disconnected_socket:
                    return
                friend_name = info.get("name", "")
                friend_ip = info.get("ip", endpoint)
                del self.connections[key]

        if friend_ip and self.on_friend_disconnected:
            self.on_friend_disconnected(friend_ip)

        if friend_name:
            logger.info("好友断开: %s (%s)", friend_name, friend_ip)

    # ================================================================== #
    #  出站连接（主动连接好友）
    # ================================================================== #

    def connect_to_friend(self, ip: str, port: int = 0,
                          name: str = "") -> bool:
        """
        主动向好友发起 TCP 连接，并加入连接池。

        若已有到该 IP:port 的已命名连接，直接返回 True 而不创建新连接。
        TCP 是双向的，一个连接足够双方收发。

        Returns:
            True 表示连接成功（或已存在），False 表示失败。
        """
        friend_port = port if port > 0 else Protocol.DEFAULT_TCP_PORT
        if not self._running:
            return False

        # 已有到该 IP:port 的已命名连接 → 不需要重复建连
        if self.is_connected(ip, friend_port):
            with self._lock:
                key = self._endpoint_key(ip, friend_port)
                existing = self.connections.get(key)
                existing_name = existing.get("name", "") if existing else ""
            if existing_name and not self._looks_like_ip(existing_name):
                return True

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)  # 5 秒连接超时
            sock.connect((ip, friend_port))
            if not self._running:
                sock.close()
                return False
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(None)  # 连接成功后恢复阻塞模式

            key = self._register_connection(sock, ip, name or ip, friend_port)

            # _register_connection may have closed *sock* when the endpoint
            # already had an alive connection (duplicate-connection guard).
            # In that case the profile-exchange was already sent by the
            # existing connection — just report success.
            try:
                sock.getpeername()
            except OSError:
                # sock was closed → connection already existed.
                logger.info(
                    "已连接到好友（复用已有连接）: %s (%s:%d)",
                    name, ip, friend_port,
                )
                return True

            # 主动连接后立即交换身份，避免入站侧只能靠后续业务消息猜名字。
            profile_msg = Protocol.create_profile_exchange(
                self.my_name,
                [],
                "",
                self.tcp_port,
                self.my_user_id,
                self.my_device_id,
            )
            sock.sendall(profile_msg)

            logger.info("已连接到好友: %s (%s:%d)", name, ip, friend_port)

            # 通知上层
            if self.on_friend_connected:
                self.on_friend_connected(name or ip, ip)

            # 启动接收线程
            recv_thread = threading.Thread(
                target=self._receive_worker,
                args=(sock, ip),
                daemon=True,
                name=f"Recv-{key}",
            )
            recv_thread.start()

            return True

        except Exception as e:
            if not self._running:
                return False
            error_msg = f"连接好友失败 [{ip}]: {e}"
            logger.error(error_msg)
            if self.on_error:
                self.on_error(error_msg)
            return False

    # ================================================================== #
    #  连接管理
    # ================================================================== #

    def disconnect_friend(self, ip: str):
        """
        主动断开与指定好友的连接。

        Args:
            ip: 好友 IP 地址。
        """
        with self._lock:
            key = self._find_connection_key(ip)
            if key:
                self._disconnect_friend_unlocked(key)

        if self.on_friend_disconnected:
            self.on_friend_disconnected(ip)

        logger.info("已断开好友连接: %s", ip)

    def _disconnect_friend_unlocked(self, endpoint: str):
        """
        断开好友连接的内部实现（调用时须持有 _lock）。

        Args:
            endpoint: 连接 key、IP、或好友名。
        """
        key = self._find_connection_key(endpoint)
        if key:
            sock = self.connections[key].get("socket")
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
            del self.connections[key]

    def send_to_friend(self, ip_or_name: str, data: bytes) -> bool:
        """
        向指定好友发送数据（带 4 字节长度头）。

        如果传入的是已经通过 Protocol.create_message() 等方法
        打包好的完整数据（含长度头），则直接发送；
        否则自动添加长度头。

        Args:
            ip_or_name: 好友 IP 地址或好友名字。
            data: 待发送的字节串（已打包或未打包均可）。

        Returns:
            True 表示发送成功，False 表示失败。
        """
        with self._lock:
            key = self._find_connection_key(ip_or_name)
            if not key:
                error_msg = f"好友 {ip_or_name} 不在连接池中"
                logger.warning(error_msg)
                if self.on_error:
                    self.on_error(error_msg)
                return False
            info = self.connections[key]
            sock = info["socket"]
            send_lock = info.setdefault("send_lock", threading.Lock())

        try:
            with send_lock:
                sock.sendall(data)
            return True
        except Exception as e:
            error_msg = f"发送消息给 {ip_or_name} 失败: {e}"
            logger.error(error_msg)
            self._handle_disconnect(key, sock)
            return False

    def broadcast_to_friends(self, data: bytes):
        """
        向所有已连接好友广播数据。

        Args:
            data: 待发送 of 字节串（已打包的完整消息）。
        """
        with self._lock:
            endpoint_list = list(self.connections.keys())

        failed_ips: List[str] = []
        for endpoint in endpoint_list:
            if not self.send_to_friend(endpoint, data):
                failed_ips.append(endpoint)

        if failed_ips:
            logger.warning("广播失败的好友: %s", failed_ips)

    # ================================================================== #
    #  状态查询
    # ================================================================== #

    def get_online_friends(self) -> List[Dict]:
        """
        获取当前所有在线好友列表。

        Returns:
            列表，每项为字典 {"ip": str, "name": str, "connected_at": str}。
        """
        with self._lock:
            deduped = {}
            for key, info in self.connections.items():
                name = info.get("name", "")
                ip = info.get("ip", key)
                port = int(info.get("port", 0) or 0)
                dedupe_key = name or self._endpoint_key(ip, port)
                current = deduped.get(dedupe_key)
                if current and int(current.get("port", 0) or 0) and not port:
                    continue
                deduped[dedupe_key] = {
                    "ip": ip,
                    "port": port,
                    "name": name,
                    "connected_at": info["connected_at"],
                }
            return list(deduped.values())

    def is_friend_online(self, name: str) -> bool:
        """
        检查指定名字的好友是否在线。

        Args:
            name: 好友姓名。

        Returns:
            True 表示在线。
        """
        with self._lock:
            return any(info.get("name") == name for info in self.connections.values())

    def get_friend_ip(self, name: str) -> str:
        """
        获取指定好友的在线 IP。

        Args:
            name: 好友姓名。

        Returns:
            在线 IP，未找到则返回空字符串。
        """
        with self._lock:
            for _key, info in self.connections.items():
                if info.get("name") == name:
                    port = int(info.get("port", 0) or 0)
                    return self._endpoint_key(info.get("ip", ""), port)
        return ""

    def is_connected(self, ip: str, port: int = 0) -> bool:
        """
        检查指定 IP 的好友是否已连接。

        Args:
            ip: 好友 IP 地址。
            port: TCP 端口；为 0 时匹配任意同 IP 连接。

        Returns:
            True 表示已连接，False 表示未连接。
        """
        with self._lock:
            if port:
                return self._endpoint_key(ip, port) in self.connections
            return any(info.get("ip") == ip for info in self.connections.values())

    def get_friend_name(self, ip: str) -> str:
        """
        获取指定 IP 好友的名字。

        Args:
            ip: 好友 IP 地址。

        Returns:
            好友名字；若未连接则返回空字符串。
        """
        with self._lock:
            key = self._find_connection_key(ip)
            if key:
                return self.connections[key].get("name", "")
            return ""

    def update_friend_name(self, ip: str, name: str):
        """
        更新连接池中好友的名字。

        Args:
            ip:   好友 IP 地址。
            name: 新名字。
        """
        with self._lock:
            key = self._find_connection_key(ip)
            if key:
                self.connections[key]["name"] = name

    def get_connection_count(self) -> int:
        """
        获取当前在线好友连接数。

        Returns:
            连接数。
        """
        with self._lock:
            return len(self.connections)

    @staticmethod
    def _endpoint_key(ip: str, port: int = 0) -> str:
        try:
            port = int(port or 0)
        except (TypeError, ValueError):
            port = 0
        return f"{ip}:{port}" if port > 0 else ip

    def _find_connection_key(self, ip_or_name: str) -> Optional[str]:
        # 1) exact key match
        if ip_or_name in self.connections:
            return ip_or_name
        # 2) match by registered name
        for key, info in self.connections.items():
            if info.get("name") == ip_or_name:
                return key
        # 3) match by IP only (handles bare IP and "ip:port" strings)
        candidate_ip = ip_or_name
        if ":" in ip_or_name:
            candidate_ip = ip_or_name.rsplit(":", 1)[0]
        for key, info in self.connections.items():
            if info.get("ip") == candidate_ip:
                return key
        # 4) match by original string as IP
        for key, info in self.connections.items():
            if info.get("ip") == ip_or_name:
                return key
        return None

    @staticmethod
    def _socket_alive(sock: Optional[socket.socket]) -> bool:
        """Return True if *sock* appears to still be a usable TCP connection."""
        if sock is None:
            return False
        try:
            # getpeername succeeds for connected sockets and raises for
            # sockets that have been closed or lost the peer.
            sock.getpeername()
            return True
        except OSError:
            return False

    @staticmethod
    def _looks_like_ip(value: str) -> bool:
        """Return True when *value* is a bare IP address rather than a nickname."""
        if not value:
            return True
        parts = value.split(".")
        if len(parts) != 4:
            return False
        return all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)

    def _register_connection(
        self,
        sock: socket.socket,
        ip: str,
        name: str,
        port: int = 0,
    ) -> str:
        """Register (or update) a TCP connection in the pool.

        Duplicate connections to the same endpoint are prevented upstream by
        ``_accept_worker`` and ``connect_to_friend``.  When a key collision
        does occur (rare race), the *new* duplicate socket is closed and
        the existing entry is kept.
        """
        key = self._endpoint_key(ip, port)
        should_notify = False
        with self._lock:
            # Remove any port-less stub that references the same socket.
            for existing_key, info in list(self.connections.items()):
                if info.get("socket") is sock and existing_key != key:
                    del self.connections[existing_key]
                elif (
                    port
                    and existing_key != key
                    and info.get("ip") == ip
                    and info.get("name") == (name or ip)
                    and not int(info.get("port", 0) or 0)
                ):
                    # Port-less entry for same IP+name — discard it.
                    try:
                        old = info.get("socket")
                        if old and old is not sock:
                            old.close()
                    except Exception:
                        pass
                    del self.connections[existing_key]

            old_name = ""
            if key not in self.connections:
                should_notify = True
            else:
                existing = self.connections[key]
                old_name = existing.get("name", "")
                old_sock = existing.get("socket")
                if old_sock and old_sock is not sock:
                    # Duplicate — close the new socket, keep the existing one.
                    try:
                        sock.close()
                    except Exception:
                        pass
                    # Still upgrade the name if this was an IP→name transition.
                    new_name = name or ip
                    if new_name and new_name != old_name and self._looks_like_ip(old_name):
                        existing["name"] = new_name
                        if self.on_friend_connected:
                            should_notify = True
                    if not should_notify:
                        return key

            existing_lock = self.connections.get(key, {}).get("send_lock")
            self.connections[key] = {
                "socket": sock,
                "name": name or ip,
                "ip": ip,
                "port": int(port or 0),
                "connected_at": self.connections.get(key, {}).get(
                    "connected_at", Helpers.get_timestamp()
                ),
                "send_lock": existing_lock or threading.Lock(),
            }

        if should_notify and self.on_friend_connected:
            self.on_friend_connected(name or ip, ip)
        return key

    # ================================================================== #
    #  心跳线程
    # ================================================================== #

    def _heartbeat_worker(self):
        """
        心跳线程：每 30 秒向所有好友广播 HEARTBEAT 消息。

        用于维持连接活跃、宣告本机当前 IP，并让好友检测 IP 变更。
        """
        while self._running:
            time.sleep(30)
            if not self._running:
                break

            try:
                current_ip = Helpers.get_default_ip()
                heartbeat_data = Protocol.create_heartbeat(
                    name=self.my_name,
                    ip=current_ip,
                    port=self.tcp_port,
                )
                self.broadcast_to_friends(heartbeat_data)
            except Exception as e:
                logger.debug("心跳广播异常: %s", e)

    # ================================================================== #
    #  IP 变更检测线程
    # ================================================================== #

    def _ip_monitor_worker(self):
        """
        IP 变更监控线程：每 15 秒检测本机默认 IP 是否变化。

        若检测到 IP 变更，立即向所有好友发送 HEARTBEAT 消息
        携带新的 IP 地址，以便好友更新地址簿中的记录。
        """
        while self._running:
            time.sleep(15)
            if not self._running:
                break

            try:
                current_ip = Helpers.get_default_ip()

                if current_ip != self._last_known_ip:
                    old_ip = self._last_known_ip
                    self._last_known_ip = current_ip

                    logger.info(
                        "检测到 IP 变更: %s -> %s，通知所有好友", old_ip, current_ip
                    )

                    # 立即广播 HEARTBEAT 告知好友
                    heartbeat_data = Protocol.create_heartbeat(
                        name=self.my_name,
                        ip=current_ip,
                        port=self.tcp_port,
                    )
                    self.broadcast_to_friends(heartbeat_data)

            except Exception as e:
                logger.debug("IP 监控异常: %s", e)
