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

from core.backend.shared.helpers import Helpers
from core.backend.shared.protocol import Protocol


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
        self._diagnostics_lock = threading.Lock()
        self._diagnostics = {
            "started_at": None,
            "last_scan_at": None,
            "last_receive_at": None,
            "last_device_at": None,
            "last_error": "",
            "last_targets": 0,
            "last_probe_ports": [],
            "send_attempts": 0,
            "send_success": 0,
            "send_errors": 0,
            "receive_packets": 0,
            "receive_ping": 0,
            "receive_pong": 0,
            "receive_resets_ignored": 0,
        }

        # 回调函数（由上层设置）
        self.on_device_found: Optional[Callable[[DeviceInfo], None]] = None
        self.on_device_seen: Optional[Callable[[DeviceInfo], None]] = None
        self.on_device_offline: Optional[Callable[[str], None]] = None

        # 后台线程引用
        self._broadcast_thread: Optional[threading.Thread] = None
        self._receive_thread: Optional[threading.Thread] = None
        self._cleanup_thread: Optional[threading.Thread] = None

    # Interface name substrings that indicate a virtual / non-physical
    # adapter whose subnet should NOT be unicast-scanned.
    _VIRTUAL_IFACE_KW = (
        "vpn", "tun", "tap", "docker", "vbox", "virtualbox",
        "vmware", "loopback", "wsl", "hyper-v", "hamachi",
        "radmin", "zerotier", "tailscale", "wireguard",
        "utun", "utap", "ppp", "pptp", "l2tp", "sstp",
    )

    @classmethod
    def _is_virtual_iface(cls, name: str) -> bool:
        name_lower = name.lower()
        return any(kw in name_lower for kw in cls._VIRTUAL_IFACE_KW)

    def _get_broadcast_targets(self) -> List[str]:
        """获取所有潜在的广播目标 IP 地址，包含应对校园网的子网单播扫描。

        虚拟网卡（VPN、Docker、WSL 等）的子网不会做单播扫描，
        因为在虚拟子网里不可能发现真实的局域网用户。
        """
        targets = ["127.0.0.1", "255.255.255.255"]
        try:
            ifaces = Helpers._detect_interfaces()
            for iface in ifaces:
                bcast = iface.get("broadcast")
                if bcast and bcast != "127.255.255.255" and bcast != "255.255.255.255":
                    targets.append(bcast)

                ip = iface.get("ip")
                mask = iface.get("mask")
                if ip:
                    targets.append(ip)

                # 校园网专属破局方案：对物理网卡的 /24 子网进行主动单播扫描。
                # 虚拟网卡（Docker、VPN 等）子网不存在真实局域网用户，跳过。
                if (
                    ip
                    and mask == "255.255.255.0"
                    and not ip.startswith("127.")
                    and not self._is_virtual_iface(iface.get("name", ""))
                ):
                    parts = ip.split(".")
                    if len(parts) == 4:
                        prefix = f"{parts[0]}.{parts[1]}.{parts[2]}"
                        for i in range(1, 255):
                            targets.append(f"{prefix}.{i}")
        except Exception as e:
            print(f"[UDPService] Error getting targets: {e}")
        return list(set(targets))

    # ================================================================== #
    #  生命周期
    # ================================================================== #

    @staticmethod
    def _acquire_android_multicast_lock():
        """Acquire a WiFi MulticastLock on Android so UDP broadcasts are
        received even when the device enters power-saving mode."""
        try:
            # Only attempt on Android; the jnius / pyjnius packages are
            # available inside a p4a / Buildozer / Serious-Python APK.
            from jnius import autoclass  # type: ignore
        except ImportError:
            return None
        try:
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            Context = autoclass("android.content.Context")
            wifi = activity.getSystemService(Context.WIFI_SERVICE)
            lock = wifi.createMulticastLock("beiyang_udp_lock")
            lock.setReferenceCounted(True)
            lock.acquire()
            return lock
        except Exception:
            return None

    def start(self):
        """
        启动 UDP 服务。

        创建 UDP socket 并启动三个后台守护线程。
        若服务已在运行则直接返回。
        """
        if self.running:
            return

        # On Android, acquire a WiFi MulticastLock before binding the socket
        # so the radio stays awake for broadcast reception.
        self.multicast_lock = self._acquire_android_multicast_lock()

        # 创建并配置 UDP socket
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._disable_windows_udp_connreset()
            self.sock.bind(("0.0.0.0", self.port))
            self.sock.setblocking(False)
            self.running = True
            self._mark_diagnostic(started_at=time.time(), last_error="")
        except Exception as e:
            message = f"UDP {self.port} bind failed: {e}"
            self._mark_diagnostic(last_error=message)
            print(f"[UDPService] Error binding UDP socket on port {self.port}: {e}")
            self.sock = None
            self.running = False
            # Release the MulticastLock on failure
            if self.multicast_lock:
                try:
                    self.multicast_lock.release()
                except Exception:
                    pass
                self.multicast_lock = None
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
        """停止 UDP 服务并关闭 socket 并释放锁。"""
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        # Release Android MulticastLock if held.
        if self.multicast_lock:
            try:
                if self.multicast_lock.isHeld():
                    self.multicast_lock.release()
            except Exception:
                pass
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
                probe_ports = self._get_probe_ports()
                self._mark_diagnostic(
                    last_scan_at=time.time(),
                    last_targets=len(targets),
                    last_probe_ports=probe_ports,
                )
                for target in targets:
                    for p_port in probe_ports:
                        self._send_probe(ping_data, target, p_port)
            except Exception as e:
                self._mark_diagnostic(last_error=f"UDP broadcast failed: {e}")
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
                self._bump_diagnostic("receive_packets")
                self._mark_diagnostic(last_receive_at=time.time(), last_error="")

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

                # 本机多实例场景归一化：当报文源 IP 命中本机任一网卡（含
                # Docker/Hamachi/WSL 等虚拟网卡）时，OS 会因虚拟网卡在多个源
                # IP 间轮询，导致每次 PING/PONG 记录的对方 IP 都在抖动，TCP
                # 随后连到错误网卡而失败。归一化为 127.0.0.1 可保证本机两实例
                # 之间 TCP 必然可达；真实局域网场景（源 IP 不在本机列表）不受影响。
                record_ip = "127.0.0.1" if sender_ip in local_ips else sender_ip

                if packet_type == Protocol.UDP_PING:
                    self._bump_diagnostic("receive_ping")
                    # 收到 PING -- 回复 PONG 并记录设备
                    device_name = packet.get("device_name", "Unknown")
                    tcp_port = packet.get("tcp_port", Protocol.DEFAULT_TCP_PORT)
                    user_id = packet.get("user_id", "")
                    device_id = packet.get("device_id", "")

                    # 若对方也是本机实例，宣告 127.0.0.1 让对方用回环地址记录我们
                    advertised_ip = "127.0.0.1" if sender_ip in local_ips else Helpers.get_default_ip()
                    pong_data = Protocol.create_pong_packet(
                        self.device_name,
                        advertised_ip,
                        self.tcp_port,
                        self.user_id,
                        self.device_id,
                    )
                    # 回复 PONG 到发送端包的真实源地址(IP 和 Port)，确保支持多实例测试
                    self.sock.sendto(pong_data, addr)

                    self._add_device(record_ip, device_name, tcp_port, user_id, device_id)

                elif packet_type == Protocol.UDP_PONG:
                    self._bump_diagnostic("receive_pong")
                    # 收到 PONG -- 记录设备
                    device_name = packet.get("device_name", "Unknown")
                    tcp_port = packet.get("tcp_port", Protocol.DEFAULT_TCP_PORT)
                    user_id = packet.get("user_id", "")
                    device_id = packet.get("device_id", "")

                    # 总是使用 sender_ip（UDP 报文的源 IP），因为这一定是局域网内可达的物理 IP。
                    # 避免使用对端包内宣告的 ip（对端可能因为 VPN/代理等配置导致判定错误）
                    self._add_device(record_ip, device_name, tcp_port, user_id, device_id)

            except BlockingIOError:
                # 非阻塞 socket 暂无数据
                time.sleep(0.05)
            except OSError as e:
                if self._is_transient_receive_error(e):
                    self._bump_diagnostic("receive_resets_ignored")
                else:
                    self._mark_diagnostic(last_error=f"UDP receive failed: {e}")
                time.sleep(0.05)
            except Exception as e:
                self._mark_diagnostic(last_error=f"UDP receive failed: {e}")
                time.sleep(0.05)

    def _disable_windows_udp_connreset(self):
        """Prevent ICMP port-unreachable replies from breaking UDP recv on Windows."""
        control_code = getattr(socket, "SIO_UDP_CONNRESET", None)
        if self.sock is None or control_code is None or not hasattr(self.sock, "ioctl"):
            return
        try:
            self.sock.ioctl(control_code, False)
        except OSError:
            pass

    @staticmethod
    def _is_transient_receive_error(error: OSError) -> bool:
        return getattr(error, "winerror", None) == 10054 or error.errno == 10054

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
        canonical = device_id or user_id
        key = canonical or f"{device_name}@{ip}:{int(tcp_port or 0)}"

        with self._devices_lock:
            # ── merge / deduplicate ──────────────────────────────
            # When a PING arrives with a stable identity (device_id
            # or user_id), look for any previous fallback-key entry
            # for the same device_name and fold it into the new key.
            # This prevents the same person appearing twice in the
            # discover list (once under their stable id and once
            # under "name@old-ip:port").
            if canonical:
                for existing_key, existing in list(self.devices.items()):
                    if existing_key == key:
                        continue
                    if (
                        existing.device_name == device_name
                        and int(existing.tcp_port or 0) == int(tcp_port or 0)
                        and not (existing.device_id or existing.user_id)
                    ):
                        # Stale fallback entry — merge into canonical key.
                        self.devices[key] = existing
                        self.devices[key].user_id = user_id
                        self.devices[key].device_id = device_id
                        del self.devices[existing_key]
                        break

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
        self._mark_diagnostic(last_device_at=current_time)

        device = self.devices[key]

        # 在锁外触发回调，避免死锁
        if (is_new or is_update_notify) and self.on_device_found:
            self.on_device_found(device)
        if self.on_device_seen:
            self.on_device_seen(device)

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
            message = "UDP socket is not initialized. Check firewall or port binding."
            self._mark_diagnostic(last_error=message)
            print("[UDPService] Cannot scan, UDP socket not initialized.")
            return

        try:
            ping_data = Protocol.create_ping_packet(
                self.device_name, self.tcp_port, self.user_id, self.device_id
            )
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            
            # 探测端口列表，用于支持单机多实例测试
            probe_ports = self._get_probe_ports()
            
            # 1. 广播扫描
            targets = self._get_broadcast_targets()
            self._mark_diagnostic(
                last_scan_at=time.time(),
                last_targets=len(targets),
                last_probe_ports=probe_ports,
            )
            for target in targets:
                for p_port in probe_ports:
                    self._send_probe(ping_data, target, p_port)
            
            # 2. 子网单播扫描 (突破路由器对广播的禁用)
            try:
                ifaces = Helpers._detect_interfaces()
                loopback_targets = ["127.0.0.1"]
                for host in loopback_targets:
                    for p_port in probe_ports:
                        self._send_probe(ping_data, host, p_port)
                for iface in ifaces:
                    ip = iface.get("ip")
                    mask = iface.get("mask")
                    if ip:
                        for p_port in probe_ports:
                            self._send_probe(ping_data, ip, p_port)
                    if ip and mask and not ip.startswith("127."):
                        hosts = Helpers.get_subnet_hosts(ip, mask)
                        for host in hosts:
                            for p_port in probe_ports:
                                self._send_probe(ping_data, host, p_port)
            except Exception as e:
                self._mark_diagnostic(last_error=f"Subnet unicast scan failed: {e}")
                print(f"[UDPService] Subnet unicast scan failed: {e}")
        except Exception as e:
            self._mark_diagnostic(last_error=f"Manual scan failed: {e}")

    def probe_host(self, host: str, ports: Optional[List[int]] = None) -> dict:
        """Probe one host with UDP discovery packets."""
        result = {
            "host": host,
            "ports": ports or self._get_probe_ports(),
            "sent": 0,
            "failed": 0,
        }
        if not self.sock:
            message = "UDP socket is not initialized. Check firewall or port binding."
            self._mark_diagnostic(last_error=message)
            result["error"] = message
            return result

        try:
            ping_data = Protocol.create_ping_packet(
                self.device_name, self.tcp_port, self.user_id, self.device_id
            )
            self._mark_diagnostic(
                last_scan_at=time.time(),
                last_targets=1,
                last_probe_ports=result["ports"],
            )
            for port in result["ports"]:
                if self._send_probe(ping_data, host, int(port)):
                    result["sent"] += 1
                else:
                    result["failed"] += 1
        except Exception as e:
            message = f"UDP probe to {host} failed: {e}"
            self._mark_diagnostic(last_error=message)
            result["error"] = message
        return result

    def _get_probe_ports(self) -> List[int]:
        """Return discovery ports used by both normal and manual scans."""
        return sorted(set([8890, 8891, 8892, 8893, self.port]))

    def _send_probe(self, payload: bytes, host: str, port: int) -> bool:
        self._bump_diagnostic("send_attempts")
        try:
            self.sock.sendto(payload, (host, port))
            self._bump_diagnostic("send_success")
            return True
        except Exception as e:
            self._bump_diagnostic("send_errors")
            self._mark_diagnostic(last_error=f"UDP send to {host}:{port} failed: {e}")
            return False

    def _mark_diagnostic(self, **values):
        with self._diagnostics_lock:
            self._diagnostics.update(values)

    def _bump_diagnostic(self, key: str, amount: int = 1):
        with self._diagnostics_lock:
            self._diagnostics[key] = int(self._diagnostics.get(key, 0) or 0) + amount

    def get_diagnostics(self) -> dict:
        """Return a snapshot useful for explaining why discovery is empty."""
        try:
            interfaces = Helpers._detect_interfaces()
        except Exception as e:
            interfaces = []
            self._mark_diagnostic(last_error=f"Interface detection failed: {e}")

        with self._devices_lock:
            device_count = len([d for d in self.devices.values() if d.is_online()])
        with self._diagnostics_lock:
            diagnostics = dict(self._diagnostics)

        local_ips = []
        for iface in interfaces:
            ip = iface.get("ip")
            if ip and ip not in local_ips:
                local_ips.append(ip)
        if "127.0.0.1" not in local_ips:
            local_ips.append("127.0.0.1")

        diagnostics.update({
            "udp_port": self.port,
            "tcp_port": self.tcp_port,
            "udp_running": self.running,
            "has_socket": self.sock is not None,
            "device_count": device_count,
            "local_ips": local_ips,
            "interfaces": interfaces,
            "probe_ports": self._get_probe_ports(),
        })
        diagnostics["hint"] = self._diagnostic_hint(diagnostics)
        return diagnostics

    def _diagnostic_hint(self, diagnostics: dict) -> str:
        if not diagnostics.get("udp_running") or not diagnostics.get("has_socket"):
            return "UDP 没有启动，优先检查端口占用和 Windows 防火墙。"
        if not diagnostics.get("interfaces"):
            return "没有识别到可用网卡，请检查网络连接或 VPN/虚拟网卡优先级。"
        if diagnostics.get("send_success", 0) == 0:
            return "扫描包没有成功发出，通常是 socket 或系统权限问题。"
        if diagnostics.get("receive_packets", 0) == 0:
            return "已发出扫描但没有收到回应；常见原因是防火墙、不同网段或 AP 隔离。"
        if diagnostics.get("device_count", 0) == 0:
            return "收到过 UDP 包但没有可用用户，可能是协议不匹配或对方被识别为本机。"
        return "发现链路正常。"
