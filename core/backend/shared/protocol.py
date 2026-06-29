"""
社交消息协议模块 (Challenge 3 - 相识北洋)

定义基于 TCP 的 P2P 社交消息协议，包含社交、聊天和文件传输消息：
  - PROFILE_EXCHANGE:   交换自我介绍（姓名、标签、简介）
  - FRIEND_REQUEST:     发送好友请求（附带个人资料）
  - FRIEND_ACCEPT:      接受好友请求
  - FRIEND_REJECT:      拒绝好友请求
  - CHAT_MESSAGE:       文本聊天消息（支持中继路径追踪）
  - RELAY_MESSAGE:      转发聊天消息给另一位好友（包裹 CHAT_MESSAGE）
  - HEARTBEAT:          周期性 IP 宣告（用于 IP 变更检测）
  - ONLINE_STATUS:      上线/下线状态通知
  - FRIEND_CONDITIONS:  分享好友匹配条件
  - FILE_OFFER:         文件传输元信息
  - FILE_CHUNK:         文件分块数据
  - FILE_COMPLETE:      文件传输完成通知

同时定义 UDP PING/PONG 协议用于局域网设备发现。

数据包格式：4 字节大端长度前缀 + JSON 主体
UDP 端口：8890 | TCP 端口：7779
"""

import json
import struct
from typing import Any, Dict, List, Optional, Tuple


class Protocol:
    """挑战3：相识北洋 - 社交消息协议常量与工具方法"""

    # ------------------------------------------------------------------ #
    #  UDP 消息类型（设备发现）
    # ------------------------------------------------------------------ #
    UDP_PING = "PING"
    UDP_PONG = "PONG"

    # ------------------------------------------------------------------ #
    #  TCP 消息类型（社交协议）
    # ------------------------------------------------------------------ #
    PROFILE_EXCHANGE = "PROFILE_EXCHANGE"   # 交换自我介绍
    FRIEND_REQUEST = "FRIEND_REQUEST"       # 发送好友请求
    FRIEND_ACCEPT = "FRIEND_ACCEPT"         # 接受好友请求
    FRIEND_REJECT = "FRIEND_REJECT"         # 拒绝好友请求
    FRIEND_DELETE = "FRIEND_DELETE"         # 删除好友关系通知
    CHAT_MESSAGE = "CHAT_MESSAGE"           # 文本聊天消息
    RELAY_MESSAGE = "RELAY_MESSAGE"         # 转发消息（洪泛中继）
    HEARTBEAT = "HEARTBEAT"                 # 心跳 / IP 宣告
    ONLINE_STATUS = "ONLINE_STATUS"         # 上线/下线状态
    FRIEND_CONDITIONS = "FRIEND_CONDITIONS" # 好友匹配条件
    FILE_OFFER = "FILE_OFFER"               # 文件传输元信息
    FILE_CHUNK = "FILE_CHUNK"               # 文件分块数据
    FILE_COMPLETE = "FILE_COMPLETE"         # 文件传输完成

    GROUP_CREATE = "GROUP_CREATE"           # 创群通知
    GROUP_CHAT = "GROUP_CHAT"               # 群聊天消息
    GROUP_SYNC_REQ = "GROUP_SYNC_REQ"       # 群历史记录同步请求（Gossip Sync）
    GROUP_SYNC_RESP = "GROUP_SYNC_RESP"     # 群历史记录同步响应
    MOMENTS_PUBLISH = "MOMENTS_PUBLISH"     # 空间发帖推送
    MOMENTS_SYNC_REQ = "MOMENTS_SYNC_REQ"   # 空间动态同步请求
    MOMENTS_SYNC_RESP = "MOMENTS_SYNC_RESP" # 空间动态同步响应

    # ------------------------------------------------------------------ #
    #  默认端口（与 challenge1/2 区分）
    # ------------------------------------------------------------------ #
    DEFAULT_UDP_PORT = 8890
    DEFAULT_TCP_PORT = 7779

    # 包头固定长度：4 字节无符号大端整数
    HEADER_LENGTH = 4
    BINARY_CHUNK_MAGIC = b"BFCH1"

    # ================================================================== #
    #  UDP 数据包构造与解析
    # ================================================================== #

    @staticmethod
    def create_ping_packet(
        device_name: str,
        tcp_port: int = DEFAULT_TCP_PORT,
        user_id: str = "",
        device_id: str = "",
        candidate_ips: Optional[List[str]] = None,
    ) -> bytes:
        """
        创建 UDP PING 广播包。

        Args:
            device_name: 本机设备名 / 用户名。
            tcp_port:    本机监听的 TCP 端口。

        Returns:
            UTF-8 编码的 JSON 字节串。
        """
        packet = {
            "type": Protocol.UDP_PING,
            "device_name": device_name,
            "tcp_port": tcp_port,
            "user_id": user_id,
            "device_id": device_id,
            "candidate_ips": candidate_ips or [],
        }
        return json.dumps(packet, ensure_ascii=False).encode("utf-8")

    @staticmethod
    def create_pong_packet(
        device_name: str,
        ip_address: str,
        tcp_port: int = DEFAULT_TCP_PORT,
        user_id: str = "",
        device_id: str = "",
        candidate_ips: Optional[List[str]] = None,
    ) -> bytes:
        """
        创建 UDP PONG 应答包。

        Args:
            device_name: 本机设备名 / 用户名。
            ip_address:  本机 IP 地址。
            tcp_port:    本机监听的 TCP 端口。

        Returns:
            UTF-8 编码的 JSON 字节串。
        """
        packet = {
            "type": Protocol.UDP_PONG,
            "device_name": device_name,
            "ip": ip_address,
            "tcp_port": tcp_port,
            "user_id": user_id,
            "device_id": device_id,
            "candidate_ips": candidate_ips or [],
        }
        return json.dumps(packet, ensure_ascii=False).encode("utf-8")

    @staticmethod
    def parse_udp_packet(data: bytes) -> Dict[str, Any]:
        """
        解析 UDP 数据包。

        Args:
            data: 原始字节串。

        Returns:
            解析后的字典；解析失败时返回空字典。
        """
        try:
            return json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    # ================================================================== #
    #  TCP 带长度前缀的通用收发
    # ================================================================== #

    @staticmethod
    def pack_with_header(data: bytes) -> bytes:
        """
        在数据前添加 4 字节大端长度头。

        Args:
            data: 待封装的载荷字节串。

        Returns:
            包头 + 载荷。
        """
        header = struct.pack("!I", len(data))
        return header + data

    @staticmethod
    def unpack_with_header(sock) -> Tuple[bool, bytes]:
        """
        从 socket 读取一个完整的 [长度头 + 载荷] 消息。

        Args:
            sock: 已连接的 TCP socket。

        Returns:
            (success, data) -- success 为 False 表示连接已断开或读取失败。
        """
        # 读取 4 字节包头
        header = b""
        while len(header) < Protocol.HEADER_LENGTH:
            chunk = sock.recv(Protocol.HEADER_LENGTH - len(header))
            if not chunk:
                return False, b""
            header += chunk

        body_len = struct.unpack("!I", header)[0]

        # 循环读取直到收齐整个包体
        body_buf = b""
        while len(body_buf) < body_len:
            chunk = sock.recv(body_len - len(body_buf))
            if not chunk:
                return False, b""
            body_buf += chunk

        return True, body_buf

    # ================================================================== #
    #  TCP JSON 消息构造（通用 + 各类型便捷方法）
    # ================================================================== #

    @staticmethod
    def create_message(msg_type: str, **kwargs: Any) -> bytes:
        """
        构造通用 JSON 消息并打包（带长度头）。

        消息体结构示例::

            {"type": "CHAT_MESSAGE", "msg_id": "xxx", "from": "Alice", ...}

        Args:
            msg_type: 消息类型常量。
            **kwargs: 随消息类型变化的附加字段。

        Returns:
            带 4 字节长度头的完整字节串，可直接 socket.send()。
        """
        payload = {"type": msg_type}
        payload.update(kwargs)
        json_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return Protocol.pack_with_header(json_bytes)

    @staticmethod
    def parse_message(data: bytes) -> Dict[str, Any]:
        """
        解析 TCP 载荷的 JSON 主体。

        Args:
            data: unpack_with_header 返回的载荷字节串。

        Returns:
            解析后的字典；解析失败返回空字典。
        """
        binary = Protocol.parse_binary_file_chunk(data)
        if binary:
            return binary
        try:
            return json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    @staticmethod
    def create_binary_file_chunk(file_id: str, chunk_index: int, data: bytes) -> bytes:
        """Create a packed binary file chunk frame.

        Frame body:
            magic(5) + header_len(4) + UTF-8 JSON header + raw bytes
        """
        header = json.dumps(
            {
                "type": Protocol.FILE_CHUNK,
                "binary": True,
                "file_id": file_id,
                "chunk_index": chunk_index,
                "size": len(data),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        body = (
            Protocol.BINARY_CHUNK_MAGIC
            + struct.pack("!I", len(header))
            + header
            + data
        )
        return Protocol.pack_with_header(body)

    @staticmethod
    def parse_binary_file_chunk(data: bytes) -> Dict[str, Any]:
        if not data.startswith(Protocol.BINARY_CHUNK_MAGIC):
            return {}
        prefix_len = len(Protocol.BINARY_CHUNK_MAGIC)
        if len(data) < prefix_len + 4:
            return {}
        header_len = struct.unpack("!I", data[prefix_len:prefix_len + 4])[0]
        header_start = prefix_len + 4
        header_end = header_start + header_len
        if header_end > len(data):
            return {}
        try:
            header = json.loads(data[header_start:header_end].decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        raw = data[header_end:]
        if int(header.get("size", len(raw)) or 0) != len(raw):
            return {}
        header["data"] = raw
        return header

    # -- 便捷方法：PROFILE_EXCHANGE ------------------------------------- #

    @staticmethod
    def create_profile_exchange(
        name: str,
        tags: List[str],
        bio: str,
        tcp_port: int = DEFAULT_TCP_PORT,
        user_id: str = "",
        device_id: str = "",
    ) -> bytes:
        """
        创建 PROFILE_EXCHANGE 消息（自我介绍）。

        Args:
            name: 用户名 / 昵称。
            tags: 兴趣标签列表，如 ["摄影", "编程", "篮球"]。
            bio:  个人简介。

        Returns:
            带长度头的完整消息字节串。
        """
        return Protocol.create_message(
            Protocol.PROFILE_EXCHANGE,
            name=name,
            tags=tags,
            bio=bio,
            tcp_port=tcp_port,
            user_id=user_id,
            device_id=device_id,
        )

    # -- 便捷方法：FRIEND_REQUEST --------------------------------------- #

    @staticmethod
    def create_friend_request(
        name: str,
        tags: List[str],
        bio: str,
        conditions: Optional[Dict[str, Any]] = None,
        user_id: str = "",
        device_id: str = "",
        tcp_port: int = DEFAULT_TCP_PORT,
    ) -> bytes:
        """
        创建 FRIEND_REQUEST 消息（好友请求）。

        附带发送方的个人资料，以便接收方决定是否接受。

        Args:
            name: 请求方用户名。
            tags: 请求方兴趣标签。
            bio:  请求方个人简介。
            conditions: 请求方好友条件。

        Returns:
            带长度头的完整消息字节串。
        """
        return Protocol.create_message(
            Protocol.FRIEND_REQUEST,
            profile={
                "user_id": user_id,
                "device_id": device_id,
                "name": name,
                "tags": tags,
                "bio": bio,
                "tcp_port": tcp_port,
            },
            conditions=conditions or {},
        )

    # -- 便捷方法：FRIEND_ACCEPT ---------------------------------------- #

    @staticmethod
    def create_friend_accept(
        name: str,
        tags: List[str],
        bio: str,
        user_id: str = "",
        device_id: str = "",
        tcp_port: int = DEFAULT_TCP_PORT,
    ) -> bytes:
        """
        创建 FRIEND_ACCEPT 消息（接受好友请求）。

        Args:
            name: 接受方用户名。
            tags: 接受方兴趣标签。
            bio:  接受方个人简介。

        Returns:
            带长度头的完整消息字节串。
        """
        return Protocol.create_message(
            Protocol.FRIEND_ACCEPT,
            name=name,
            tags=tags,
            bio=bio,
            profile={
                "user_id": user_id,
                "device_id": device_id,
                "name": name,
                "tags": tags,
                "bio": bio,
                "tcp_port": tcp_port,
            },
        )

    # -- 便捷方法：FRIEND_REJECT ---------------------------------------- #

    @staticmethod
    def create_friend_reject(name: str, reason: str = "") -> bytes:
        """
        创建 FRIEND_REJECT 消息（拒绝好友请求）。

        Args:
            name:   拒绝方用户名。
            reason: 拒绝原因（可选）。

        Returns:
            带长度头的完整消息字节串。
        """
        return Protocol.create_message(
            Protocol.FRIEND_REJECT,
            name=name,
            reason=reason,
        )

    # -- 便捷方法：FRIEND_DELETE ---------------------------------------- #

    @staticmethod
    def create_friend_delete(name: str) -> bytes:
        """
        创建 FRIEND_DELETE 消息（主动删除好友关系通知）。

        Args:
            name: 删除方用户名。

        Returns:
            带长度头的完整消息字节串。
        """
        return Protocol.create_message(
            Protocol.FRIEND_DELETE,
            name=name,
        )

    # -- 便捷方法：CHAT_MESSAGE ----------------------------------------- #

    @staticmethod
    def create_chat_message(msg_id: str, from_name: str, to_name: str,
                            content: str, timestamp: str,
                            relay_path: Optional[List[str]] = None) -> bytes:
        """
        创建 CHAT_MESSAGE 消息（文本聊天）。

        Args:
            msg_id:     消息唯一标识（UUID4）。
            from_name:  发送方用户名。
            to_name:    接收方用户名。
            content:    消息正文。
            timestamp:  发送时间戳（YYYY-MM-DD HH:MM:SS）。
            relay_path: 中继路径列表，记录消息经过的节点 IP（可为空）。

        Returns:
            带长度头的完整消息字节串。
        """
        payload = {
            "type": Protocol.CHAT_MESSAGE,
            "msg_id": msg_id,
            "from_name": from_name,
            "to_name": to_name,
            "from": from_name,
            "to": to_name,
            "content": content,
            "timestamp": timestamp,
            "relay_path": relay_path or [],
        }
        json_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return Protocol.pack_with_header(json_bytes)

    # -- 便捷方法：RELAY_MESSAGE ---------------------------------------- #

    @staticmethod
    def create_relay_message(original_message: Dict[str, Any],
                             relay_hops: List[str]) -> bytes:
        """
        创建 RELAY_MESSAGE 消息（洪泛中继）。

        Args:
            original_message: 原始 CHAT_MESSAGE 解析后的字典。
            relay_hops:       中继路径节点列表。

        Returns:
            带长度头的完整消息字节串。
        """
        return Protocol.create_message(
            Protocol.RELAY_MESSAGE,
            original_message=original_message,
            relay_hops=relay_hops,
        )

    # -- 便捷方法：HEARTBEAT -------------------------------------------- #

    @staticmethod
    def create_heartbeat(name: str, ip: str, port: int) -> bytes:
        """
        创建 HEARTBEAT 消息（心跳 / IP 宣告）。

        周期性发送给所有好友，用于检测 IP 变更和维持连接。

        Args:
            name: 用户名。
            ip:   当前 IP 地址。
            port: 当前 TCP 监听端口。

        Returns:
            带长度头的完整消息字节串。
        """
        return Protocol.create_message(
            Protocol.HEARTBEAT,
            name=name,
            ip=ip,
            port=port,
        )

    # -- 便捷方法：ONLINE_STATUS ---------------------------------------- #

    @staticmethod
    def create_online_status(name: str, online: bool) -> bytes:
        """
        创建 ONLINE_STATUS 消息（上线/下线通知）。

        Args:
            name:   用户名。
            online: True 表示上线，False 表示下线。

        Returns:
            带长度头的完整消息字节串。
        """
        return Protocol.create_message(
            Protocol.ONLINE_STATUS,
            name=name,
            online=online,
        )

    # -- 便捷方法：FRIEND_CONDITIONS ------------------------------------ #

    @staticmethod
    def create_friend_conditions(required_tags: List[str],
                                 optional_tags: List[str],
                                 min_match_count: int,
                                 auto_accept: bool) -> bytes:
        """
        创建 FRIEND_CONDITIONS 消息（好友匹配条件）。

        Args:
            required_tags:    必须匹配的标签列表。
            optional_tags:    可选匹配的标签列表。
            min_match_count:  最少匹配标签数（含必须标签）。
            auto_accept:      匹配时是否自动接受好友请求。

        Returns:
            带长度头的完整消息字节串。
        """
        return Protocol.create_message(
            Protocol.FRIEND_CONDITIONS,
            required_tags=required_tags,
            optional_tags=optional_tags,
            min_match_count=min_match_count,
            auto_accept=auto_accept,
        )

    # -- 便捷方法：文件传输 -------------------------------------------- #

    @staticmethod
    def create_file_offer(
        file_id: str,
        from_name: str,
        to_name: str,
        filename: str,
        size: int,
        chunk_size: int,
        chunk_count: int,
        sha256: str = "",
        timestamp: str = "",
        purpose: str = "chat_file",
        avatar_owner: str = "",
        avatar_user_id: str = "",
    ) -> bytes:
        """创建 FILE_OFFER 消息（文件元信息）。"""
        return Protocol.create_message(
            Protocol.FILE_OFFER,
            file_id=file_id,
            from_name=from_name,
            to_name=to_name,
            filename=filename,
            size=size,
            chunk_size=chunk_size,
            chunk_count=chunk_count,
            sha256=sha256,
            timestamp=timestamp,
            purpose=purpose,
            avatar_owner=avatar_owner,
            avatar_user_id=avatar_user_id,
        )

    @staticmethod
    def create_file_chunk(
        file_id: str,
        chunk_index: int,
        data_b64: str,
    ) -> bytes:
        """创建 FILE_CHUNK 消息（base64 分块）。"""
        return Protocol.create_message(
            Protocol.FILE_CHUNK,
            file_id=file_id,
            chunk_index=chunk_index,
            data_b64=data_b64,
        )

    @staticmethod
    def create_file_complete(
        file_id: str,
        from_name: str,
        to_name: str,
        filename: str,
        size: int,
        sha256: str = "",
        timestamp: str = "",
        purpose: str = "chat_file",
        avatar_owner: str = "",
        avatar_user_id: str = "",
    ) -> bytes:
        """创建 FILE_COMPLETE 消息（传输完成）。"""
        return Protocol.create_message(
            Protocol.FILE_COMPLETE,
            file_id=file_id,
            from_name=from_name,
            to_name=to_name,
            filename=filename,
            size=size,
            sha256=sha256,
            timestamp=timestamp,
            purpose=purpose,
            avatar_owner=avatar_owner,
            avatar_user_id=avatar_user_id,
        )
