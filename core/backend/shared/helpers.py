"""
辅助函数模块 (Challenge 3 - 相识北洋)

提供 IP 获取、时间格式化、文件大小格式化、IP 校验、UUID 生成等通用工具函数。
新增 generate_msg_id() 和 match_friend_conditions() 用于社交消息场景。
"""

import socket
import time
import uuid
from typing import Dict, List


class Helpers:
    """辅助工具类"""

    # ================================================================== #
    #  网络相关
    # ================================================================== #

    _cached_local_ips = None
    _cached_local_ips_time = 0.0
    _cached_default_ip = None
    _cached_default_ip_time = 0.0

    @staticmethod
    def _detect_interfaces() -> List[dict]:
        """
        探测所有可用的网络接口。
        返回列表，每个元素为字典：{"ip": str, "mask": str, "name": str, "gateway": str, "broadcast": str}
        """
        import os
        interfaces = []

        # Windows network interfaces.
        if not interfaces and os.name == 'nt':
            try:
                import subprocess
                import re
                out = subprocess.check_output("ipconfig", shell=True, text=True, errors='ignore')
                blocks = re.split(r'\n(?=[^\s])', out)
                for block in blocks:
                    lines = [line.strip() for line in block.split('\n') if line.strip()]
                    if not lines:
                        continue
                    adapter_name = lines[0]
                    ip = None
                    mask = None
                    gateway = None
                    for line in lines[1:]:
                        if "IPv4 Address" in line or "IPv4 地址" in line:
                            ip_match = re.search(r':\s*([\d.]+)', line)
                            if ip_match:
                                ip = ip_match.group(1)
                        elif "Subnet Mask" in line or "子网掩码" in line:
                            mask_match = re.search(r':\s*([\d.]+)', line)
                            if mask_match:
                                mask = mask_match.group(1)
                        elif "Default Gateway" in line or "默认网关" in line:
                            gw_match = re.search(r':\s*([\d.]+)', line)
                            if gw_match:
                                gateway = gw_match.group(1)

                    if ip and mask:
                        interfaces.append({
                            "name": adapter_name,
                            "ip": ip,
                            "mask": mask,
                            "gateway": gateway,
                            "broadcast": None
                        })
            except Exception:
                pass

        # Android/Java network interfaces fallback.
        if not interfaces:
            try:
                import importlib
                j_module = importlib.import_module("j" + "nius")
                autoclass = j_module.autoclass
                NetworkInterface = autoclass('java.net.NetworkInterface')
                interfaces_enum = NetworkInterface.getNetworkInterfaces()
                if interfaces_enum:
                    while interfaces_enum.hasMoreElements():
                        ni = interfaces_enum.nextElement()
                        if not ni.isUp() or ni.isLoopback():
                            continue
                        name = ni.getName()
                        addrs = ni.getInterfaceAddresses()
                        if addrs:
                            for addr in addrs.toArray():
                                inet_addr = addr.getAddress()
                                if inet_addr:
                                    ip = inet_addr.getHostAddress()
                                    if ip and ":" not in ip and not ip.startswith("127."):
                                        prefix = addr.getNetworkPrefixLength()
                                        mask = Helpers._prefix_to_mask(prefix)
                                        bcast_obj = addr.getBroadcast()
                                        broadcast = bcast_obj.getHostAddress() if bcast_obj else None
                                        interfaces.append({
                                            "name": name,
                                            "ip": ip,
                                            "mask": mask,
                                            "gateway": None,
                                            "broadcast": broadcast
                                        })
            except Exception:
                pass

        # Generic desktop fallback.
        if not interfaces:
            try:
                import socket
                for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                    ip = info[4][0]
                    if not ip.startswith("127."):
                        interfaces.append({
                            "name": "Generic",
                            "ip": ip,
                            "mask": "255.255.255.0",
                            "gateway": None,
                            "broadcast": None
                        })
            except Exception:
                pass

        # 补全 broadcast 地址
        for iface in interfaces:
            if not iface.get("broadcast"):
                iface["broadcast"] = Helpers._calculate_broadcast(iface["ip"], iface["mask"])

        return interfaces

    @staticmethod
    def _prefix_to_mask(prefix_len: int) -> str:
        """CIDR 前缀长度转子网掩码字符串"""
        mask_val = (0xffffffff >> (32 - prefix_len)) << (32 - prefix_len)
        parts = [
            str((mask_val >> 24) & 0xff),
            str((mask_val >> 16) & 0xff),
            str((mask_val >> 8) & 0xff),
            str(mask_val & 0xff)
        ]
        return ".".join(parts)

    @staticmethod
    def _calculate_broadcast(ip: str, mask: str) -> str:
        """根据 IP 和子网掩码计算广播地址"""
        try:
            ip_parts = [int(p) for p in ip.split('.')]
            mask_parts = [int(p) for p in mask.split('.')]
            bcast_parts = []
            for i in range(4):
                bcast_parts.append(str(ip_parts[i] | (255 - mask_parts[i])))
            return ".".join(bcast_parts)
        except Exception:
            return "255.255.255.255"

    @staticmethod
    def _get_best_ip(ifaces: List[dict]) -> str:
        if not ifaces:
            return "127.0.0.1"

        virtual_keywords = [
            'vpn', 'tun', 'tap', 'docker', 'vbox', 'virtualbox', 'vmware',
            'loopback', 'wsl', 'xray', 'hamachi', 'radmin', 'clash',
            'singbox', 'sing-box', 'wintun', 'nekoray', 'v2ray', 'bypass'
        ]

        def score_iface(iface):
            name_lower = iface["name"].lower()
            ip = iface.get("ip", "")
            score = 0

            # 判断是否是虚拟/代理网卡或代理网段（Clash默认使用198.18/19网段，sing-box常用172.19网段）
            is_virtual = any(kw in name_lower for kw in virtual_keywords)
            is_proxy_subnet = ip.startswith("198.18.") or ip.startswith("198.19.") or ip.startswith("172.19.")

            if is_virtual or is_proxy_subnet:
                score -= 1000  # 给予极低分，避免排在首位
            else:
                score += 100

            gw = iface.get("gateway")
            if gw and gw != "0.0.0.0":
                score += 50

            if any(k in name_lower for k in ["wlan", "wireless", "wi-fi", "ethernet", "本地连接"]):
                score += 30

            return score

        sorted_ifaces = sorted(ifaces, key=score_iface, reverse=True)
        return sorted_ifaces[0]["ip"]

    @staticmethod
    def get_local_ips() -> List[str]:
        """
        获取所有本地 IPv4 地址（不含回环 127.x）。
        """
        now = time.time()
        if Helpers._cached_local_ips is not None and (now - Helpers._cached_local_ips_time < 10.0):
            return Helpers._cached_local_ips

        ifaces = Helpers._detect_interfaces()
        ips = ["127.0.0.1"]
        for iface in ifaces:
            ip = iface["ip"]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)

        default_ip = Helpers.get_default_ip()
        if default_ip and default_ip not in ips and not default_ip.startswith("127."):
            ips.append(default_ip)

        Helpers._cached_local_ips = ips
        Helpers._cached_local_ips_time = now
        return ips

    @staticmethod
    def get_default_ip() -> str:
        """
        获取当前正在使用的默认 IP 地址。
        自动辨识并过滤代理网卡及 TUN 虚拟 IP 范围。
        """
        now = time.time()
        if Helpers._cached_default_ip is not None and (now - Helpers._cached_default_ip_time < 10.0):
            return Helpers._cached_default_ip

        ifaces = Helpers._detect_interfaces()
        best_ip = Helpers._get_best_ip(ifaces)

        def is_proxy_or_invalid(ip):
            return (
                not ip or ip == "127.0.0.1" or
                ip.startswith("198.18.") or ip.startswith("198.19.") or
                ip.startswith("172.19.")
            )

        # 如果判定获取到的是代理 IP 或环回 IP，则通过向特定地址建连进行路由探测
        if is_proxy_or_invalid(best_ip):
            # 优先选择天大内部 DNS 或国内公共 DNS，因为系统代理一般会直连/绕过局域网及国内直连
            probe_targets = [
                "202.113.15.1",    # 天津大学主 DNS 服务器 (校园网内直连)
                "223.5.5.5",       # 阿里公共 DNS (国内直连)
                "119.29.29.29",     # 腾讯公共 DNS (国内直连)
                "8.8.8.8"          # Google Public DNS (外网备份)
            ]
            for target in probe_targets:
                try:
                    import socket
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.connect((target, 80))
                    probe_ip = s.getsockname()[0]
                    s.close()
                    if not is_proxy_or_invalid(probe_ip):
                        best_ip = probe_ip
                        break
                except Exception:
                    continue

        # 兜底：如果探测后依然无法获得有效物理 IP，且本地接口中存在非代理的物理 IP，则强制返回第一个
        if is_proxy_or_invalid(best_ip) and ifaces:
            for iface in ifaces:
                ip = iface.get("ip", "")
                if not is_proxy_or_invalid(ip):
                    best_ip = ip
                    break

        Helpers._cached_default_ip = best_ip
        Helpers._cached_default_ip_time = now
        return best_ip

    @staticmethod
    def get_hostname() -> str:
        """
        获取本机设备名。

        Returns:
            设备名字符串；失败时返回 "Unknown_Device"。
        """
        try:
            return socket.gethostname()
        except Exception:
            return "Unknown_Device"

    @staticmethod
    def validate_ip(ip: str) -> bool:
        """
        验证 IPv4 地址格式是否合法。

        Args:
            ip: 待校验的 IP 字符串。

        Returns:
            True 表示格式正确，False 表示不合法。
        """
        try:
            parts = ip.split(".")
            if len(parts) != 4:
                return False
            for part in parts:
                num = int(part)
                if num < 0 or num > 255:
                    return False
            return True
        except (ValueError, AttributeError):
            return False

    # ================================================================== #
    #  时间与格式化
    # ================================================================== #

    @staticmethod
    def get_timestamp() -> str:
        """
        获取当前时间的可读字符串。

        Returns:
            格式为 "YYYY-MM-DD HH:MM:SS" 的时间戳。
        """
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

    @staticmethod
    def format_file_size(size_bytes: int) -> str:
        """
        将字节数格式化为人类可读的文件大小。

        Args:
            size_bytes: 文件字节数。

        Returns:
            格式化后的字符串，如 "1.50 MB"。
        """
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.2f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.2f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

    # ================================================================== #
    #  社交功能辅助函数（Challenge 3 新增）
    # ================================================================== #

    @staticmethod
    def generate_msg_id() -> str:
        """
        生成消息唯一标识符。

        使用 UUID4 算法生成一个 128 位随机 ID，确保全局唯一性。
        格式为 32 位十六进制字符串（不含连字符）。

        Returns:
            32 位十六进制 UUID 字符串，如 "a3f8b2c1d4e5f6a7b8c9d0e1f2a3b4c5"。
        """
        return uuid.uuid4().hex

    @staticmethod
    def match_friend_conditions(profile_tags: List[str],
                                conditions: Dict) -> bool:
        """
        检查个人资料标签是否满足好友匹配条件。

        匹配规则：
          1. required_tags（必须标签）：profile_tags 必须包含全部必须标签。
          2. optional_tags（可选标签）：计入总匹配数但不强制要求。
          3. min_match_count：必须标签 + 命中可选标签的总数 >= min_match_count。

        Args:
            profile_tags: 被检查用户的兴趣标签列表。
            conditions:   匹配条件字典，应包含以下键：
                - required_tags (List[str]):   必须匹配的标签。
                - optional_tags (List[str]):   可选匹配的标签。
                - min_match_count (int):       最少匹配标签总数（默认 1）。
                - auto_accept (bool):          是否自动接受（仅做信息传递，不影响返回值）。

        Returns:
            True 表示满足匹配条件，False 表示不满足。
        """
        if not conditions:
            return False

        required_tags: List[str] = conditions.get("required_tags", [])
        optional_tags: List[str] = conditions.get("optional_tags", [])
        min_match_count: int = conditions.get("min_match_count", 1)

        # 如果没有设置任何条件，默认不匹配（避免无差别添加好友）
        if not required_tags and not optional_tags:
            return False

        profile_set = set(tag.strip().lower() for tag in profile_tags)

        # 检查必须标签：全部命中才算通过必须条件
        required_set = set(tag.strip().lower() for tag in required_tags)
        if required_set and not required_set.issubset(profile_set):
            return False

        # 统计总匹配数：必须标签命中数 + 可选标签命中数
        required_matched = len(required_set & profile_set)
        optional_set = set(tag.strip().lower() for tag in optional_tags)
        optional_matched = len(optional_set & profile_set)

        total_matched = required_matched + optional_matched
        return total_matched >= min_match_count

    @staticmethod
    def get_subnet_hosts(ip: str, mask: str) -> List[str]:
        """根据 IP 和子网掩码计算出所有可能的局域网主机 IP (限制在 /22 以上子网)"""
        try:
            ip_parts = [int(p) for p in ip.split('.')]
            mask_parts = [int(p) for p in mask.split('.')]

            # 计算网络地址和主机数量
            net_parts = []
            for i in range(4):
                net_parts.append(ip_parts[i] & mask_parts[i])

            # 计算总的主机数量
            wildcard_parts = [255 - m for m in mask_parts]
            total_hosts = (wildcard_parts[0] << 24) + (wildcard_parts[1] << 16) + (wildcard_parts[2] << 8) + wildcard_parts[3]

            # 限制在 /22 Subnet (最多 1022 个主机)，避免卡死或造成网络风暴
            # 如果是大型网络（如校园网，掩码为 /16 或 /17），退化为扫描当前 IP 所在的近邻 /24 子网网段 (最多 254 个主机)
            if total_hosts > 1024 or total_hosts <= 0:
                try:
                    parts = ip.split('.')
                    if len(parts) == 4:
                        prefix = ".".join(parts[:3])
                        hosts = []
                        for i in range(1, 255):
                            h_ip = f"{prefix}.{i}"
                            if h_ip != ip:
                                hosts.append(h_ip)
                        return hosts
                except Exception:
                    pass
                return []

            hosts = []
            net_val = (net_parts[0] << 24) + (net_parts[1] << 16) + (net_parts[2] << 8) + net_parts[3]
            for i in range(1, total_hosts):  # 排除网络地址 (i=0) 和广播地址 (i=total_hosts)
                val = net_val + i
                h_ip = f"{(val >> 24) & 0xff}.{(val >> 16) & 0xff}.{(val >> 8) & 0xff}.{val & 0xff}"
                if h_ip != ip:
                    hosts.append(h_ip)
            return hosts
        except Exception:
            return []
