"""
UDP 广播服务模块 (Challenge 3 - 相识北洋)

负责局域网设备发现和在线状态维护：
  - 定时广播 PING 包宣告自身存在
  - 监听 PING 并自动回复 PONG
  - 跟踪已知设备，超时后标记离线
  - 通过回调通知上层设备上/下线事件

使用端口 8890（与 challenge1 的 8888、challenge2 的 8889 区分）。
"""

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


class DeviceInfo:
    """表示一个已发现的局域网设备。"""

    def __init__(
        self,
        ip: str,
        device_name: str,
        tcp_port: int,
        last_seen: float,
        user_id: str = "",
        device_id: str = "",
    ):
        """
        Args:
            ip:          设备 IP 地址。
            device_name: 设备名称 / 用户名。
            tcp_port:    设备监听的 TCP 端口。
            last_seen:   最后一次收到该设备消息的时间戳。
        """
        self.ip = ip
        self.device_name = device_name
        self.tcp_port = tcp_port
        self.last_seen = last_seen
        self.user_id = user_id
        self.device_id = device_id

    def is_online(self, timeout: int = 15) -> bool:
        """
        判断设备是否在线。

        Args:
            timeout: 超时秒数，默认 15 秒。

        Returns:
            True 表示设备在线。
        """
        return (time.time() - self.last_seen) < timeout

    def __repr__(self) -> str:
        return (
            f"DeviceInfo(ip={self.ip!r}, name={self.device_name!r}, "
            f"tcp_port={self.tcp_port}, online={self.is_online()})"
        )


class UDPService:
    """
    UDP 广播服务。

    启动后会在三个后台线程中分别执行：
      1. 广播线程 -- 每隔 5 秒向子网广播 PING
      2. 接收线程 -- 监听 PING/PONG 并更新设备表
      3. 清理线程 -- 定期检查并移除超时设备

    上层通过设置 on_device_found / on_device_offline 回调来响应事件。
    """

    def __init__(
        self,
        port: int = Protocol.DEFAULT_UDP_PORT,
        device_name: str = "",
        tcp_port: int = Protocol.DEFAULT_TCP_PORT,
        user_id: str = "",
        device_id: str = "",
    ):
        """
        Args:
            port:        UDP 监听/广播端口，默认 8890。
            device_name: 本机设备名称 / 用户名，留空则自动获取。
            tcp_port:    本机 TCP 服务端口，用于告知对端连接地址。
        """
        self.port = port
        self.device_name = device_name or Helpers.get_hostname()
        self.tcp_port = tcp_port
        self.user_id = user_id
        self.device_id = device_id
        self.sock: Optional[socket.socket] = None
        self.devices: Dict[str, DeviceInfo] = {}  # identity key -> DeviceInfo
        self.running = False
        self.multicast_lock = None

        # 设备列表锁，保护多线程读写 devices 字典
        self._devices_lock = threading.Lock()

        # 回调函数（由上层设置）
        self.on_device_found: Optional[Callable[[DeviceInfo], None]] = None
        self.on_device_offline: Optional[Callable[[str], None]] = None

        # 后台线程引用
        self._broadcast_thread: Optional[threading.Thread] = None
        self._receive_thread: Optional[threading.Thread] = None
        self._cleanup_thread: Optional[threading.Thread] = None

    def _get_broadcast_targets(self) -> List[str]:
        """获取所有潜在的广播目标 IP 地址，包含应对校园网的子网单播扫描。"""
        # 127.0.0.1 and local interface IPs are required for same-machine
        # multi-instance tests where each app listens on a different UDP port.
        targets = ["127.0.0.1", "255.255.255.255"]
        try:
            ifaces = Helpers._detect_interfaces()
            for iface in ifaces:
                bcast = iface.get("broadcast")
                if bcast and bcast != "127.255.255.255" and bcast != "255.255.255.255":
                    targets.append(bcast)
                    
                # 校园网专属破局方案：对当前的 /24 子网进行主动的单播扫描！
                # 因为很多校园网 AP 和交换机会屏蔽 `255.255.255.255` 和子网广播包，
                # 但它们通常不会拦截普通的单播 (Unicast) UDP 数据。
                ip = iface.get("ip")
                mask = iface.get("mask")
                if ip:
                    targets.append(ip)
                
                # 如果是常见的 255.255.255.0 子网，且不是本机回环
                if ip and mask == "255.255.255.0" and not ip.startswith("127."):
                    parts = ip.split(".")
                    if len(parts) == 4:
                        prefix = f"{parts[0]}.{parts[1]}.{parts[2]}"
                        # 将整个网段的 1~254 都加入目标列表
                        for i in range(1, 255):
                            scan_ip = f"{prefix}.{i}"
                            targets.append(scan_ip)
        except Exception as e:
            print(f"[UDPService] Error getting targets: {e}")
        return list(set(targets))

    # ================================================================== #
    #  生命周期
    # ================================================================== #

    def start(self):
        """
        启动 UDP 服务。

        创建 UDP socket 并启动三个后台守护线程。
        若服务已在运行则直接返回。
        """
        if self.running:
            return

        # 尝试为 Android 系统获取多播锁 (MulticastLock) 允许接收 UDP 广播
        try:
            from kivy.utils import platform
        except ImportError:
            import sys
            platform = 'android' if hasattr(sys, 'getandroidapilevel') else sys.platform

        if platform == 'android':
            try:
                from jnius import autoclass
                PythonActivity = autoclass('org.kivy.android.PythonActivity')
                Context = autoclass('android.content.Context')
                activity = PythonActivity.mActivity
                wifi = activity.getSystemService(Context.WIFI_SERVICE)
                self.multicast_lock = wifi.createMulticastLock("social_udp_lock")
                self.multicast_lock.acquire()
                print("[UDPService] Successfully acquired Android MulticastLock")
            except Exception as e:
                print(f"[UDPService] Warning: Failed to acquire Android MulticastLock: {e}")

        # 创建并配置 UDP socket
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind(("0.0.0.0", self.port))
            self.sock.setblocking(False)
            self.running = True
        except Exception as e:
            print(f"[UDPService] Error binding UDP socket on port {self.port}: {e}")
            self.sock = None
            self.running = False
            return

        # 广播线程：定时发送 PING
        self._broadcast_thread = threading.Thread(
            target=self._broadcast_worker, daemon=True, name="UDP-Broadcast"
        )
        self._broadcast_thread.start()

        # 接收线程：处理 PING/PONG
        self._receive_thread = threading.Thread(
            target=self._receive_worker, daemon=True, name="UDP-Receive"
        )
        self._receive_thread.start()

        # 清理线程：移除超时设备
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_worker, daemon=True, name="UDP-Cleanup"
        )
        self._cleanup_thread.start()

    def stop(self):
        """停止 UDP 服务并关闭 socket并释放锁。"""
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        
        # 释放 Android 上的多播锁
        if self.multicast_lock:
            try:
                if self.multicast_lock.isHeld():
                    self.multicast_lock.release()
                    print("[UDPService] Successfully released Android MulticastLock")
            except Exception as e:
                print(f"[UDPService] Warning: Failed to release Android MulticastLock: {e}")
            self.multicast_lock = None

    # ================================================================== #
    #  后台工作线程
    # ================================================================== #

    def _broadcast_worker(self):
        """广播线程：每 5 秒向子网发送一次 PING。"""
        while self.running:
            try:
                ping_data = Protocol.create_ping_packet(
                    self.device_name, self.tcp_port, self.user_id, self.device_id
                )
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                targets = self._get_broadcast_targets()
                # 探测常见 UDP 发现端口，支持单机多实例测试
                probe_ports = list(set([8890, 8891, 8892, 8893, self.port]))
                for target in targets:
                    for p_port in probe_ports:
                        try:
                            self.sock.sendto(ping_data, (target, p_port))
                        except Exception:
                            pass
            except Exception:
                pass
            time.sleep(5)

    def _receive_worker(self):
        """接收线程：处理收到的 PING 和 PONG 包。"""
        while self.running:
            try:
                data, addr = self.sock.recvfrom(1024)
                packet = Protocol.parse_udp_packet(data)

                if not packet:
                    continue

                packet_type = packet.get("type")
                sender_ip = addr[0]

                # 忽略自己发出的包，优先用 device_id；旧包回退到端口/昵称。
                local_ips = Helpers.get_local_ips()
                if sender_ip in local_ips:
                    packet_device_id = packet.get("device_id", "")
                    if (
                        packet_device_id
                        and self.device_id
                        and packet_device_id == self.device_id
                    ):
                        continue
                    if not packet_device_id and (
                        addr[1] == self.port
                        or packet.get("device_name") == self.device_name
                    ):
                        continue

                if packet_type == Protocol.UDP_PING:
                    # 收到 PING -- 回复 PONG 并记录设备
                    device_name = packet.get("device_name", "Unknown")
                    tcp_port = packet.get("tcp_port", Protocol.DEFAULT_TCP_PORT)
                    user_id = packet.get("user_id", "")
                    device_id = packet.get("device_id", "")

                    pong_data = Protocol.create_pong_packet(
                        self.device_name,
                        Helpers.get_default_ip(),
                        self.tcp_port,
                        self.user_id,
                        self.device_id,
                    )
                    # 回复 PONG 到发送端包的真实源地址(IP 和 Port)，确保支持多实例测试
                    self.sock.sendto(pong_data, addr)

                    self._add_device(sender_ip, device_name, tcp_port, user_id, device_id)

                elif packet_type == Protocol.UDP_PONG:
                    # 收到 PONG -- 记录设备
                    device_name = packet.get("device_name", "Unknown")
                    tcp_port = packet.get("tcp_port", Protocol.DEFAULT_TCP_PORT)
                    user_id = packet.get("user_id", "")
                    device_id = packet.get("device_id", "")

                    # 总是使用 sender_ip（UDP 报文的源 IP），因为这一定是局域网内可达的物理 IP。
                    # 避免使用对端包内宣告的 ip（对端可能因为 VPN/代理等配置导致判定错误）
                    self._add_device(sender_ip, device_name, tcp_port, user_id, device_id)

            except BlockingIOError:
                # 非阻塞 socket 暂无数据
                time.sleep(0.05)
            except Exception:
                time.sleep(0.05)

    def _cleanup_worker(self):
        """清理线程：每 5 秒检查一次，移除超时离线设备。"""
        while self.running:
            try:
                offline_names: List[str] = []
                offline_ips: List[str] = []

                with self._devices_lock:
                    for name, device in self.devices.items():
                        if not device.is_online():
                            offline_names.append(name)
                            offline_ips.append(device.ip)

                    for name in offline_names:
                        del self.devices[name]

                # 在锁外触发回调，避免死锁
                for ip in offline_ips:
                    if self.on_device_offline:
                        self.on_device_offline(ip)

            except Exception:
                pass
            time.sleep(5)

    # ================================================================== #
    #  设备管理
    # ================================================================== #

    def _add_device(
        self,
        ip: str,
        device_name: str,
        tcp_port: int,
        user_id: str = "",
        device_id: str = "",
    ):
        """
        添加或更新已发现的设备。

        若为新设备则触发 on_device_found 回调。

        Args:
            ip:          设备 IP。
            device_name: 设备名称。
            tcp_port:    设备 TCP 端口。
        """
        current_time = time.time()
        is_new = False
        is_update_notify = False
        key = user_id or f"{device_name}@{ip}:{int(tcp_port or 0)}"

        with self._devices_lock:
            if key in self.devices:
                # 更新已有设备
                old_device = self.devices[key]
                if (
                    old_device.ip != ip
                    or old_device.tcp_port != tcp_port
                    or old_device.device_name != device_name
                ):
                    is_update_notify = True
                self.devices[key].last_seen = current_time
                self.devices[key].ip = ip
                self.devices[key].device_name = device_name
                self.devices[key].tcp_port = tcp_port
                self.devices[key].user_id = user_id
                self.devices[key].device_id = device_id
            else:
                # 新设备
                self.devices[key] = DeviceInfo(
                    ip, device_name, tcp_port, current_time, user_id, device_id
                )
                is_new = True

        # 在锁外触发回调，避免死锁
        if (is_new or is_update_notify) and self.on_device_found:
            self.on_device_found(self.devices[key])

    def get_online_devices(self) -> List[DeviceInfo]:
        """
        获取当前所有在线设备列表。

        Returns:
            在线的 DeviceInfo 列表。
        """
        with self._devices_lock:
            return [device for device in self.devices.values() if device.is_online()]

    def manual_scan(self):
        """
        手动触发一次广播和子网单播扫描。
        立即向广播地址以及子网内的所有主机发送 PING 包，绕过路由器的多播/广播限制。
        """
        if not self.sock:
            print("[UDPService] Cannot scan, UDP socket not initialized.")
            return

        try:
            ping_data = Protocol.create_ping_packet(
                self.device_name, self.tcp_port, self.user_id, self.device_id
            )
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            
            # 探测端口列表，用于支持单机多实例测试
            probe_ports = list(set([8890, 8891, 8892, 8893, self.port]))
            
            # 1. 广播扫描
            targets = self._get_broadcast_targets()
            for target in targets:
                for p_port in probe_ports:
                    try:
                        self.sock.sendto(ping_data, (target, p_port))
                    except Exception:
                        pass
            
            # 2. 子网单播扫描 (突破路由器对广播的禁用)
            try:
                ifaces = Helpers._detect_interfaces()
                loopback_targets = ["127.0.0.1"]
                for host in loopback_targets:
                    for p_port in probe_ports:
                        try:
                            self.sock.sendto(ping_data, (host, p_port))
                        except Exception:
                            pass
                for iface in ifaces:
                    ip = iface.get("ip")
                    mask = iface.get("mask")
                    if ip:
                        for p_port in probe_ports:
                            try:
                                self.sock.sendto(ping_data, (ip, p_port))
                            except Exception:
                                pass
                    if ip and mask and not ip.startswith("127."):
                        hosts = Helpers.get_subnet_hosts(ip, mask)
                        for host in hosts:
                            for p_port in probe_ports:
                                try:
                                    self.sock.sendto(ping_data, (host, p_port))
                                except Exception:
                                    pass
            except Exception as e:
                print(f"[UDPService] Subnet unicast scan failed: {e}")
        except Exception:
            pass
