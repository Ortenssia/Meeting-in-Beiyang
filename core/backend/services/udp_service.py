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
import json
import threading
import time
from typing import Callable, Dict, List, Optional

from core.backend.services.network_policy import DEFAULT_NETWORK_POLICY, NetworkPolicy
from core.backend.services.udp_discovery_state import (
    DeviceInfo,
    DeviceRegistry,
    UDPDiagnostics,
    clean_candidate_ips,
)
from core.backend.services.udp_packet_router import UDPPacketRouter
from core.backend.shared.helpers import Helpers
from core.backend.shared.protocol import Protocol


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
        network_policy: Optional[NetworkPolicy] = None,
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
        self.network_policy = network_policy or DEFAULT_NETWORK_POLICY
        self.sock: Optional[socket.socket] = None
        self._device_registry = DeviceRegistry()
        self.devices = self._device_registry.devices
        self.running = False
        self.multicast_lock = None
        self._targets_cache: List[str] = []
        self._targets_cache_at = 0.0
        self._last_active_scan_at = 0.0

        self._devices_lock = self._device_registry.lock
        self._diagnostics = UDPDiagnostics()
        self._packet_router = UDPPacketRouter(self)

        # 回调函数（由上层设置）
        self.on_device_found: Optional[Callable[[DeviceInfo], None]] = None
        self.on_device_seen: Optional[Callable[[DeviceInfo], None]] = None
        self.on_device_offline: Optional[Callable[[str], None]] = None
        self.on_friend_request_packet: Optional[Callable[[str, dict], None]] = None

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
    UDP_MAX_PACKET_SIZE = 8 * 1024

    @classmethod
    def _is_virtual_iface(cls, name: str) -> bool:
        name_lower = name.lower()
        return any(kw in name_lower for kw in cls._VIRTUAL_IFACE_KW)

    def _get_broadcast_targets(
        self,
        include_subnet_scan: bool = True,
        refresh: bool = False,
    ) -> List[str]:
        """获取所有潜在的广播目标 IP 地址，包含应对校园网的子网单播扫描。

        虚拟网卡（VPN、Docker、WSL 等）的子网不会做单播扫描，
        因为在虚拟子网里不可能发现真实的局域网用户。
        """
        now = time.monotonic()
        if (
            include_subnet_scan
            and not refresh
            and self._targets_cache
            and now - self._targets_cache_at < self.network_policy.udp_target_cache_ttl
        ):
            return list(self._targets_cache)

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
                    include_subnet_scan
                    and ip
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
        result = sorted(set(targets))
        if include_subnet_scan:
            self._targets_cache = list(result)
            self._targets_cache_at = now
        return result

    def _get_candidate_ips(self) -> List[str]:
        """Return local addresses worth advertising for TCP fallback."""
        candidates = []
        try:
            for iface in Helpers._detect_interfaces():
                ip = iface.get("ip", "")
                if not ip or ip.startswith("127."):
                    continue
                if self._is_virtual_iface(iface.get("name", "")):
                    continue
                if ip.startswith("198.18.") or ip.startswith("198.19.") or ip.startswith("172.19."):
                    continue
                candidates.append(ip)
        except Exception:
            pass
        default_ip = Helpers.get_default_ip()
        if default_ip and not default_ip.startswith("127.") and default_ip in candidates:
            candidates.insert(0, default_ip)
        seen = set()
        return [ip for ip in candidates if not (ip in seen or seen.add(ip))]

    # ================================================================== #
    #  生命周期
    # ================================================================== #

    @staticmethod
    def _acquire_android_multicast_lock():
        """Return no native lock when running under the Flet Android host.

        The app declares CHANGE_WIFI_MULTICAST_STATE in its Flet manifest.
        Direct access to another framework's activity is not portable in the
        Flet runtime; a future native Flet extension can provide a real lock.
        """
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
                    self.device_name,
                    self.tcp_port,
                    self.user_id,
                    self.device_id,
                    self._get_candidate_ips(),
                )
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                now = time.monotonic()
                include_subnet_scan = (
                    now - self._last_active_scan_at
                    >= self.network_policy.udp_active_scan_interval
                )
                if include_subnet_scan:
                    self._last_active_scan_at = now
                targets = self._get_broadcast_targets(
                    include_subnet_scan=include_subnet_scan
                )
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
            time.sleep(self.network_policy.udp_broadcast_interval)

    def _receive_worker(self):
        """接收线程：处理收到的 PING 和 PONG 包。"""
        while self.running:
            try:
                data, addr = self.sock.recvfrom(self.UDP_MAX_PACKET_SIZE)
                self._packet_router.handle_datagram(data, addr)

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
                for ip in self._device_registry.remove_offline():
                    if self.on_device_offline:
                        self.on_device_offline(ip)
            except Exception:
                pass
            time.sleep(self.network_policy.udp_broadcast_interval)

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
        candidate_ips: Optional[List[str]] = None,
    ):
        """
        添加或更新已发现的设备。

        若为新设备则触发 on_device_found 回调。

        Args:
            ip:          设备 IP。
            device_name: 设备名称。
            tcp_port:    设备 TCP 端口。
        """
        device, changed = self._device_registry.upsert(
            ip, device_name, tcp_port, user_id, device_id, candidate_ips
        )
        self._mark_diagnostic(last_device_at=device.last_seen)
        if changed and self.on_device_found:
            self.on_device_found(device)
        if self.on_device_seen:
            self.on_device_seen(device)

    def get_online_devices(self) -> List[DeviceInfo]:
        """
        获取当前所有在线设备列表。

        Returns:
            在线的 DeviceInfo 列表。
        """
        return self._device_registry.online()

    @staticmethod
    def _clean_candidate_ips(primary_ip: str, values: List[str]) -> List[str]:
        return clean_candidate_ips(primary_ip, values)

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
                self.device_name,
                self.tcp_port,
                self.user_id,
                self.device_id,
                self._get_candidate_ips(),
            )
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            
            # 探测端口列表，用于支持单机多实例测试
            probe_ports = self._get_probe_ports()
            
            # 1. 广播扫描
            targets = self._get_broadcast_targets(refresh=True)
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
                    if self._is_virtual_iface(iface.get("name", "")):
                        continue
                    ip = iface.get("ip")
                    mask = iface.get("mask")
                    if ip:
                        for p_port in probe_ports:
                            self._send_probe(ping_data, ip, p_port)
                    if (
                        ip
                        and mask
                        and not ip.startswith("127.")
                        and not self._is_virtual_iface(iface.get("name", ""))
                    ):
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
                self.device_name,
                self.tcp_port,
                self.user_id,
                self.device_id,
                self._get_candidate_ips(),
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

    def send_friend_request_packet(self, hosts: List[str], payload: dict) -> bool:
        """Send a small FRIEND_REQUEST payload over UDP as a TCP fallback."""
        if not self.sock:
            self._mark_diagnostic(last_error="UDP socket is not initialized.")
            return False
        try:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        except Exception as exc:
            self._mark_diagnostic(last_error=f"UDP friend request encode failed: {exc}")
            return False
        if len(data) > self.UDP_MAX_PACKET_SIZE:
            self._mark_diagnostic(last_error="UDP friend request packet is too large.")
            return False
        sent = 0
        ports = self._get_probe_ports()
        for host in hosts:
            for port in ports:
                if self._send_probe(data, host, int(port)):
                    sent += 1
        return sent > 0

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
        self._diagnostics.update(**values)

    def _bump_diagnostic(self, key: str, amount: int = 1):
        self._diagnostics.bump(key, amount)

    def get_diagnostics(self) -> dict:
        """Return a snapshot useful for explaining why discovery is empty."""
        try:
            interfaces = Helpers._detect_interfaces()
        except Exception as e:
            interfaces = []
            self._mark_diagnostic(last_error=f"Interface detection failed: {e}")

        device_count = len(self._device_registry.online())
        diagnostics = self._diagnostics.snapshot()

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
            "network_policy": {
                "profile": self.network_policy.profile_name,
                "udp_broadcast_interval": self.network_policy.udp_broadcast_interval,
                "udp_active_scan_interval": self.network_policy.udp_active_scan_interval,
                "udp_target_cache_ttl": self.network_policy.udp_target_cache_ttl,
            },
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
