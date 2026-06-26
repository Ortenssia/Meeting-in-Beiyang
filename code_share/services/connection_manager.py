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

try:
    from ..utils.helpers import Helpers
    from ..utils.protocol import Protocol
except ImportError:
    from utils.helpers import Helpers
    from utils.protocol import Protocol

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

    def __init__(self, my_name: str = "", tcp_port: int = Protocol.DEFAULT_TCP_PORT):
        """
        Args:
            my_name:  本机用户名 / 昵称，用于心跳和身份宣告。
            tcp_port: 本机 TCP 监听端口，默认 7779。
        """
        self.my_name = my_name or Helpers.get_hostname()
        self.tcp_port = tcp_port

        # ------------------------------------------------------------------ #
        #  连接池：friend_ip -> {"socket", "name", "connected_at"}
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
            for ip in list(self.connections.keys()):
                self._disconnect_friend_unlocked(ip)

        logger.info("TCP 服务端已停止")

    # ================================================================== #
    #  入站连接（服务端 accept）
    # ================================================================== #

    def _accept_worker(self):
        """
        接受连接线程：循环 accept()，为每个新连接启动接收线程。
        """
        while self._running:
            try:
                client_sock, addr = self._server_socket.accept()
                client_ip = addr[0]

                logger.info("收到入站连接: %s", client_ip)

                # 如果该 IP 已有连接，先关闭旧连接
                with self._lock:
                    if client_ip in self.connections:
                        self._disconnect_friend_unlocked(client_ip)

                # 为该连接启动接收线程
                recv_thread = threading.Thread(
                    target=self._receive_worker,
                    args=(client_sock, client_ip),
                    daemon=True,
                    name=f"Recv-{client_ip}",
                )
                recv_thread.start()

            except socket.timeout:
                # accept 超时是正常的，用于检查 _running 标志
                continue
            except OSError:
                # socket 已关闭
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
                    with self._lock:
                        if friend_ip not in self.connections:
                            # 新入站连接：注册到连接池
                            self.connections[friend_ip] = {
                                "socket": sock,
                                "name": friend_name,
                                "connected_at": Helpers.get_timestamp(),
                            }
                            if self.on_friend_connected:
                                self.on_friend_connected(friend_name, friend_ip)
                        else:
                            # 更新名字
                            self.connections[friend_ip]["name"] = friend_name

                # 特殊处理：HEARTBEAT 消息可能带来名字更新
                elif msg_type == Protocol.HEARTBEAT:
                    friend_name = message.get("name", "")
                    if friend_name:
                        with self._lock:
                            if friend_ip in self.connections:
                                self.connections[friend_ip]["name"] = friend_name

                # 将消息传递给上层
                if self.on_message_received:
                    self.on_message_received(friend_ip, message)

            except Exception as e:
                logger.debug("接收线程异常 [%s]: %s", friend_ip, e)
                break

        # 连接断开，清理
        self._handle_disconnect(friend_ip)
        try:
            sock.close()
        except Exception:
            pass

    def _handle_disconnect(self, friend_ip: str):
        """
        处理好友连接断开事件。

        从连接池移除该 IP，并触发 on_friend_disconnected 回调。

        Args:
            friend_ip: 断开连接的好友 IP。
        """
        friend_name = ""
        with self._lock:
            if friend_ip in self.connections:
                friend_name = self.connections[friend_ip].get("name", "")
                del self.connections[friend_ip]

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

        连接成功后会启动接收线程，并通过 on_friend_connected 回调通知上层。

        Args:
            ip:   好友 IP 地址。
            port: 好友 TCP 端口，传入 0 或不传则使用默认端口 7779。
            name: 好友名字（可选，若已知的话）。

        Returns:
            True 表示连接成功，False 表示失败。
        """
        friend_port = port if port > 0 else Protocol.DEFAULT_TCP_PORT

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)  # 5 秒连接超时
            sock.connect((ip, friend_port))
            sock.settimeout(None)  # 连接成功后恢复阻塞模式

            # 如果该 IP 已有旧连接，先关闭
            with self._lock:
                if ip in self.connections:
                    self._disconnect_friend_unlocked(ip)

                # 注册新连接到连接池
                self.connections[ip] = {
                    "socket": sock,
                    "name": name or ip,
                    "connected_at": Helpers.get_timestamp(),
                }

            logger.info("已连接到好友: %s (%s:%d)", name, ip, friend_port)

            # 通知上层
            if self.on_friend_connected:
                self.on_friend_connected(name or ip, ip)

            # 启动接收线程
            recv_thread = threading.Thread(
                target=self._receive_worker,
                args=(sock, ip),
                daemon=True,
                name=f"Recv-{ip}",
            )
            recv_thread.start()

            return True

        except Exception as e:
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
            self._disconnect_friend_unlocked(ip)

        if self.on_friend_disconnected:
            self.on_friend_disconnected(ip)

        logger.info("已断开好友连接: %s", ip)

    def _disconnect_friend_unlocked(self, ip: str):
        """
        断开好友连接的内部实现（调用时须持有 _lock）。

        Args:
            ip: 好友 IP 地址。
        """
        if ip in self.connections:
            sock = self.connections[ip].get("socket")
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
            del self.connections[ip]

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
            ip = ip_or_name
            if ip not in self.connections:
                # 尝试通过名字查找在线 IP
                found_ip = None
                for conn_ip, info in self.connections.items():
                    if info.get("name") == ip_or_name:
                        found_ip = conn_ip
                        break
                if found_ip:
                    ip = found_ip
                else:
                    error_msg = f"好友 {ip_or_name} 不在连接池中"
                    logger.warning(error_msg)
                    if self.on_error:
                        self.on_error(error_msg)
                    return False
            sock = self.connections[ip]["socket"]

        try:
            sock.sendall(data)
            return True
        except Exception as e:
            error_msg = f"发送消息给 {ip} 失败: {e}"
            logger.error(error_msg)
            self._handle_disconnect(ip)
            return False

    def broadcast_to_friends(self, data: bytes):
        """
        向所有已连接好友广播数据。

        Args:
            data: 待发送 of 字节串（已打包的完整消息）。
        """
        with self._lock:
            ip_list = list(self.connections.keys())

        failed_ips: List[str] = []
        for ip in ip_list:
            if not self.send_to_friend(ip, data):
                failed_ips.append(ip)

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
            return [
                {
                    "ip": ip,
                    "name": info["name"],
                    "connected_at": info["connected_at"],
                }
                for ip, info in self.connections.items()
            ]

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
            for ip, info in self.connections.items():
                if info.get("name") == name:
                    return ip
        return ""

    def is_connected(self, ip: str) -> bool:
        """
        检查指定 IP 的好友是否已连接。

        Args:
            ip: 好友 IP 地址。

        Returns:
            True 表示已连接，False 表示未连接。
        """
        with self._lock:
            return ip in self.connections

    def get_friend_name(self, ip: str) -> str:
        """
        获取指定 IP 好友的名字。

        Args:
            ip: 好友 IP 地址。

        Returns:
            好友名字；若未连接则返回空字符串。
        """
        with self._lock:
            if ip in self.connections:
                return self.connections[ip].get("name", "")
            return ""

    def update_friend_name(self, ip: str, name: str):
        """
        更新连接池中好友的名字。

        Args:
            ip:   好友 IP 地址。
            name: 新名字。
        """
        with self._lock:
            if ip in self.connections:
                self.connections[ip]["name"] = name

    def get_connection_count(self) -> int:
        """
        获取当前在线好友连接数。

        Returns:
            连接数。
        """
        with self._lock:
            return len(self.connections)

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
