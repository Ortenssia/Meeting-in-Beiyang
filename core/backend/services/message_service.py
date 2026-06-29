"""
消息中继服务模块 (Challenge 3 - 相识北洋)

负责在 P2P 社交网络中协调好友之间的消息收发与中继：
  - 直连发送：若目标好友在线（在连接池中），直接通过 TCP 发送。
  - 洪泛中继：若目标好友离线，将消息作为 RELAY_MESSAGE 转发给所有在线互友。
  - 去重机制：通过 msg_id 避免洪泛中继产生重复投递。
  - 离线缓存：离线消息存入 pending 队列，好友上线后批量推送。

消息类型（由 Protocol 定义）：
  - CHAT_MESSAGE   : 聊天消息（含 to_name / from_name / content / timestamp）
  - RELAY_MESSAGE  : 中继消息（外层包裹，内含原始消息 + relay_hops）
  - FRIEND_REQUEST : 好友请求（附带发送方 profile + conditions）
  - FRIEND_ACCEPT  : 接受好友请求（附带接受方 profile + IP）
  - HEARTBEAT      : 心跳包（用于维护在线状态与 IP 更新）

依赖：
  - connection_manager: 连接池管理器（TCP 连接管理）
  - friend_db:        好友 / 消息 / 聊天记录 SQLite 存储
"""

import base64
import hashlib
import json
import os
import time
import uuid
import threading
import logging
import inspect
from typing import Any, Callable, Dict, List, Optional

from core.config import get_app_paths
from core.backend.services.file_store import FileStore
from core.backend.services.file_transfer_state import (
    FILE_CANCEL,
    FILE_RESUME_REQ,
    FILE_RESUME_RESP,
    FILE_DECLINE,
    FILE_ACCEPT,
    FileTransferState,
)
from core.backend.services.network_policy import DEFAULT_NETWORK_POLICY, NetworkPolicy
from core.backend.shared.file_message import encode_file_message, decode_file_message
from core.backend.shared.protocol import Protocol

logger = logging.getLogger(__name__)


class MessageService:
    """相识北洋 - 消息中继服务

    在 P2P 网络中为好友之间提供可靠的消息投递，支持直连、洪泛中继和离线缓存。
    """

    # ================================================================== #
    #  消息类型常量（与 Protocol 保持同步，本地缓存避免循环依赖）
    # ================================================================== #
    CHAT_MESSAGE = "CHAT_MESSAGE"
    RELAY_MESSAGE = "RELAY_MESSAGE"
    FRIEND_REQUEST = "FRIEND_REQUEST"
    FRIEND_ACCEPT = "FRIEND_ACCEPT"
    HEARTBEAT = "HEARTBEAT"
    PROFILE_UPDATE_NOTICE = "PROFILE_UPDATE_NOTICE"
    PROFILE_SYNC_REQ = "PROFILE_SYNC_REQ"
    PROFILE_SYNC_RESP = "PROFILE_SYNC_RESP"
    FILE_OFFER = "FILE_OFFER"
    FILE_CHUNK = "FILE_CHUNK"
    FILE_CHUNK_ACK = "FILE_CHUNK_ACK"
    FILE_COMPLETE = "FILE_COMPLETE"
    FILE_COMPLETE_ACK = "FILE_COMPLETE_ACK"

    GROUP_CREATE = "GROUP_CREATE"
    GROUP_CHAT = "GROUP_CHAT"
    GROUP_SYNC_REQ = "GROUP_SYNC_REQ"
    GROUP_SYNC_RESP = "GROUP_SYNC_RESP"
    MOMENTS_PUBLISH = "MOMENTS_PUBLISH"
    MOMENTS_SYNC_REQ = "MOMENTS_SYNC_REQ"
    MOMENTS_SYNC_RESP = "MOMENTS_SYNC_RESP"

    # 洪泛中继最大跳数，防止无限传播
    MAX_RELAY_HOPS = 3

    # 心跳间隔（秒）
    HEARTBEAT_INTERVAL = 15
    FILE_CHUNK_SIZE = 256 * 1024
    FILE_ACK_INTERVAL = 32
    FILE_ACK_TIMEOUT = 30.0
    FILE_MAX_ATTEMPTS = 3

    def __init__(
        self,
        connection_manager,
        friend_db,
        receive_dir: Optional[str] = None,
        avatar_dir: Optional[str] = None,
        network_policy: Optional[NetworkPolicy] = None,
    ):
        """
        初始化消息服务。

        Args:
            connection_manager: 连接池管理器实例，提供以下接口：
                - is_friend_online(name: str) -> bool
                - send_to_friend(name: str, data: bytes) -> bool
                - get_online_friends() -> list[str]
                - get_friend_ip(name: str) -> str
            friend_db: 好友数据库实例，提供以下接口：
                - get_my_profile() -> dict
                - get_friend(name) -> dict | None
                - get_all_friends() -> list[dict]
                - add_friend(name, ip, tags, category, ...) -> None
                - update_friend_ip(name, ip) -> None
                - save_chat_message(from_name, to_name, content, timestamp, msg_id) -> None
                - get_chat_history(friend_name, limit) -> list[dict]
                - check_msg_id(msg_id) -> bool  (True=已存在)
                - record_msg_id(msg_id) -> None
                - get_pending_messages(for_name) -> list[dict]
                - add_pending_message(to_name, data_json) -> None
                - clear_pending_messages(for_name) -> None
                - get_friend_conditions() -> dict
                - check_conditions_match(profile) -> bool
        """
        self.connection_manager = connection_manager
        self.friend_db = friend_db
        self.network_policy = network_policy or DEFAULT_NETWORK_POLICY
        self.HEARTBEAT_INTERVAL = self.network_policy.message_heartbeat_interval
        self.FILE_CHUNK_SIZE = self.network_policy.file_chunk_size
        self.FILE_ACK_INTERVAL = self.network_policy.file_ack_interval
        self.FILE_ACK_TIMEOUT = self.network_policy.file_ack_timeout
        self.FILE_MAX_ATTEMPTS = self.network_policy.file_max_attempts
        paths = get_app_paths()
        self.receive_dir = str(paths.resolve_receive_dir(receive_dir))
        self.avatar_dir = str(paths.resolve_avatar_cache_dir(avatar_dir))
        self.file_store = FileStore(self.receive_dir, self.avatar_dir)

        # 回调函数（由上层 App 或 Screen 绑定）
        self.on_message_received: Optional[Callable[[str, str, str, str], None]] = None
        self.on_friend_request: Optional[Callable[..., None]] = None
        self.on_friend_accepted: Optional[Callable[[str, str], None]] = None
        self.on_friend_deleted: Optional[Callable[[str], None]] = None
        self.on_notifications_changed: Optional[Callable[[], None]] = None
        self.on_friend_profile_update_available: Optional[Callable[[str], None]] = None
        self.on_friend_profile_updated: Optional[Callable[[str], None]] = None
        self.on_file_received: Optional[Callable[[str, str, str], None]] = None
        self.on_file_progress: Optional[
            Callable[[str, str, str, int, int, bool, int], None]
        ] = None
        self.on_file_offer_received: Optional[
            Callable[[str, str, int, str], None]
        ] = None  # (from_name, filename, size, file_id)
        self.on_file_status_changed: Optional[Callable[[str, str], None]] = None  # (file_id, status)

        # Pending file offers awaiting user accept/decline.
        self._pending_file_offers: Dict[str, Dict[str, Any]] = {}
        self._file_offer_lock = threading.Lock()

        # 心跳定时器
        self._heartbeat_timer: Optional[threading.Timer] = None
        self._running = False

        # 已处理的中继消息 ID 集合（内存级去重，限制大小）
        self._processed_relay_ids: set = set()
        self._relay_id_lock = threading.Lock()
        self._MAX_RELAY_CACHE = 5000

        self.file_transfer = FileTransferState()
        self._incoming_files = self.file_transfer.incoming_files
        self._active_senders = self.file_transfer.active_senders
        self._file_resume_events = self.file_transfer.resume_events
        self._file_resume_progress = self.file_transfer.resume_progress
        self._file_lock = self.file_transfer.lock
        self._file_ack_events: Dict[str, threading.Event] = {}
        self._file_ack_progress: Dict[str, int] = {}
        self._file_ack_errors: Dict[str, str] = {}
        self._file_ack_capable: Dict[str, bool] = {}
        self._file_binary_capable: Dict[str, bool] = {}
        self._file_complete_events: Dict[str, threading.Event] = {}
        self._file_complete_results: Dict[str, tuple[bool, str]] = {}
        self._completed_file_transfers: Dict[str, Dict[str, Any]] = {}
        self._file_progress_last_emit: Dict[str, float] = {}

        self.FILE_CANCEL = FILE_CANCEL
        self.FILE_RESUME_REQ = FILE_RESUME_REQ
        self.FILE_RESUME_RESP = FILE_RESUME_RESP
        self.FILE_DECLINE = FILE_DECLINE
        self.FILE_ACCEPT = FILE_ACCEPT
        self._file_final_statuses: Dict[str, str] = {}
        os.makedirs(self.receive_dir, exist_ok=True)
        os.makedirs(self.avatar_dir, exist_ok=True)
        self.runtime = None

    def set_receive_dir(self, receive_dir: str) -> str:
        """Update the chat-file inbox directory used for new incoming files."""
        paths = get_app_paths()
        resolved = str(paths.resolve_receive_dir(receive_dir))
        self.receive_dir = self.file_store.set_receive_dir(resolved)
        return resolved

    # ================================================================== #
    #  生命周期管理
    # ================================================================== #

    def start(self):
        """启动消息服务，开始周期性心跳。"""
        self._running = True
        self._start_heartbeat()
        logger.info("[MessageService] 已启动")

    def stop(self):
        """停止消息服务与心跳。"""
        self._running = False
        if self._heartbeat_timer:
            self._heartbeat_timer.cancel()
            self._heartbeat_timer = None
        logger.info("[MessageService] 已停止")

    # ================================================================== #
    #  发送消息
    # ================================================================== #

    def send_message(self, to_name: str, content: str, msg_id: str = "") -> bool:
        """
        向指定好友发送聊天消息。

        投递策略：
          1. 若目标好友在线（在连接池中），直接发送 CHAT_MESSAGE。
          2. 若目标好友离线，将消息作为 RELAY_MESSAGE 转发给所有在线好友，
             由在线好友代为中继（洪泛）。
          3. 同时将消息存入 chat_history 与 pending 队列。

        Args:
            to_name: 目标好友名称。
            content: 消息文本内容。

        Returns:
            True 表示消息已成功投递（直连或进入中继），False 表示投递失败。
        """
        my_profile = self.friend_db.get_my_profile()
        my_name = my_profile.get("name", "Unknown")
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        msg_id = msg_id or str(uuid.uuid4())

        # 构造 CHAT_MESSAGE
        chat_msg = {
            "type": self.CHAT_MESSAGE,
            "msg_id": msg_id,
            "from_name": my_name,
            "to_name": to_name,
            "content": content,
            "timestamp": timestamp,
        }

        # 保存到本地聊天记录
        self.friend_db.save_chat_message(
            from_name=my_name,
            to_name=to_name,
            content=content,
            timestamp=timestamp,
            msg_id=msg_id,
        )

        # 尝试直连发送
        if not self.connection_manager.is_friend_online(to_name):
            record = self.friend_db.get_friend(to_name) if self.friend_db else None
            if record and record.get("ip"):
                ip = record["ip"]
                port = int(record.get("port") or Protocol.DEFAULT_TCP_PORT)
                logger.info(f"[MessageService] 尝试主动重连以发送消息 -> {to_name} ({ip}:{port})")
                self.connection_manager.connect_to_friend(ip, port, to_name)

        if self.connection_manager.is_friend_online(to_name):
            success = self._send_data_to_friend(to_name, chat_msg)
            if success:
                logger.info(f"[MessageService] 直连发送 -> {to_name}: {content[:50]}")
                return True
            logger.warning(f"[MessageService] 直连发送失败 -> {to_name}，降级为中继")

        # 离线：存入 pending 队列
        self.friend_db.add_pending_message(
            to_name=to_name,
            data_json=json.dumps(chat_msg, ensure_ascii=False),
        )

        # 洪泛中继：发送给所有在线好友
        relay_msg = {
            "type": self.RELAY_MESSAGE,
            "relay_hops": 0,
            "original_message": chat_msg,
        }
        relayed = self._flood_relay(relay_msg, exclude_name=to_name)

        logger.info(
            f"[MessageService] 消息已缓存 + 中继给 {relayed} 个在线好友"
            f" (目标 {to_name} 离线)"
        )
        return True

    def send_friend_request(
        self,
        target_name: str,
        target_ip: str,
        target_port: int = Protocol.DEFAULT_TCP_PORT,
        target_user_id: str = "",
        target_candidate_ips=None,
    ) -> bool:
        """
        向发现的用户发送好友请求。

        Args:
            target_name: 目标用户名称。
            target_ip:   目标用户 IP 地址。
            target_port: 目标用户 TCP 端口。

        Returns:
            True 表示请求已发送。
        """
        my_profile = self.friend_db.get_my_profile()
        my_profile["avatar"] = self._shared_avatar_reference(my_profile.get("avatar", ""))
        my_profile["tcp_port"] = getattr(
            self.connection_manager, "tcp_port", Protocol.DEFAULT_TCP_PORT
        )
        my_name = my_profile.get("name", "")
        my_user_id = my_profile.get("user_id", "")
        if (
            target_user_id
            and my_user_id
            and target_user_id == my_user_id
        ) or (target_name == my_name and target_port == my_profile["tcp_port"]):
            logger.info("[MessageService] 跳过向自己发送好友请求: %s", target_name)
            return False
        relationship = self.friend_db.get_relationship_status(
            user_id=target_user_id,
            name=target_name,
            ip=target_ip,
            port=target_port,
        )
        if relationship in ("pending_sent", "pending_received", "accepted"):
            logger.info(
                "[MessageService] %s 关系状态为 %s，跳过重复好友请求",
                target_name,
                relationship,
            )
            return False
        conditions = self.friend_db.get_friend_conditions()
        target_candidate_ips = target_candidate_ips or []

        request_msg = {
            "type": self.FRIEND_REQUEST,
            "msg_id": str(uuid.uuid4()),
            "profile": my_profile,
            "conditions": conditions,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        }

        def _candidate_targets():
            seen = set()
            endpoint = f"{target_ip}:{target_port}" if target_ip and target_port else target_ip
            for candidate in (target_name, endpoint, target_ip):
                if candidate and candidate not in seen:
                    seen.add(candidate)
                    yield candidate

        def _mark_sent(send_target: str):
            self.friend_db.upsert_friend_request(
                name=target_name,
                ip=target_ip,
                port=target_port,
                direction="outgoing",
                status="pending",
                user_id=target_user_id,
                msg_id=request_msg["msg_id"],
            )
            self._send_avatar_to_friend(send_target)

        def _deliver_once() -> bool:
            for send_target in _candidate_targets():
                if self._send_data_to_friend(send_target, request_msg):
                    _mark_sent(send_target)
                    return True
            return False

        # Prefer an existing name-bound connection first. Otherwise establish
        # the target port connection before trying endpoint fallbacks; this
        # avoids treating a non-existent Android connection as a sent request.
        if self.connection_manager.is_friend_online(target_name) and _deliver_once():
            return True

        # 如果尚未建立连接，尝试先连接再发送
        try:
            connect_ips = []
            seen_ips = set()
            for ip in [target_ip, *target_candidate_ips]:
                if ip and ip not in seen_ips:
                    seen_ips.add(ip)
                    connect_ips.append(ip)
            connected = False
            for connect_ip in connect_ips:
                if self.connection_manager.connect_to_friend(connect_ip, target_port, target_name):
                    connected = True
                    if connect_ip != target_ip:
                        target_ip = connect_ip
                    break
            if not connected:
                return False
            deadline = time.time() + 2.0
            while time.time() < deadline:
                if _deliver_once():
                    return True
                time.sleep(0.1)
            return _deliver_once()
        except Exception as e:
            logger.error(f"[MessageService] 发送好友请求失败: {e}")
            return False

    def send_friend_accept(self, friend_name: str, friend_ip: str = "") -> bool:
        """
        接受好友请求后，向对方发送 FRIEND_ACCEPT 消息。

        投递策略（按优先级）：
          1. 尝试通过已注册的连接（按好友名查找）。
          2. 尝试通过 IP:port 端点查找。
          3. 若仍未找到连接，主动向对方 IP:port 建立出站连接后发送。

        Args:
            friend_name: 已接受的好友名称。
            friend_ip:   对方 IP。入站好友申请尚未按名字登记连接时，用它兜底发送。

        Returns:
            True 表示接受消息已发送。
        """
        my_profile = self.friend_db.get_my_profile()
        my_profile["avatar"] = self._shared_avatar_reference(my_profile.get("avatar", ""))
        my_profile["tcp_port"] = getattr(
            self.connection_manager, "tcp_port", Protocol.DEFAULT_TCP_PORT
        )
        friend = self.friend_db.get_friend(friend_name)
        if not friend:
            logger.warning(f"[MessageService] 好友 {friend_name} 不存在")
            return False

        accept_msg = {
            "type": self.FRIEND_ACCEPT,
            "msg_id": str(uuid.uuid4()),
            "profile": my_profile,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        }

        port = int(friend.get("port", Protocol.DEFAULT_TCP_PORT) or Protocol.DEFAULT_TCP_PORT)
        target_ip = friend_ip or friend.get("ip", "")

        # 1) Try name-based lookup
        if self._send_data_to_friend(friend_name, accept_msg):
            self._send_avatar_to_friend(friend_name)
            return True

        # 2) Try endpoint-based lookup (listening port)
        if target_ip:
            endpoint = f"{target_ip}:{port}" if port else target_ip
            if self._send_data_to_friend(endpoint, accept_msg):
                self._send_avatar_to_friend(endpoint)
                return True

        # 3) Establish a fresh outbound connection and deliver over it
        if target_ip:
            try:
                logger.info(
                    "[MessageService] 无现有连接可发送 FRIEND_ACCEPT，"
                    "尝试主动连接 %s:%s",
                    target_ip,
                    port,
                )
                conn_ok = self.connection_manager.connect_to_friend(
                    target_ip, port, friend_name
                )
                if conn_ok:
                    time.sleep(0.3)  # allow the handshake to settle
                    if self._send_data_to_friend(friend_name, accept_msg):
                        self._send_avatar_to_friend(friend_name)
                        return True
                    # endpoint fallback after connecting
                    if self._send_data_to_friend(endpoint, accept_msg):
                        self._send_avatar_to_friend(endpoint)
                        return True
            except Exception as e:
                logger.error(
                    "[MessageService] 主动连接 %s:%s 失败: %s",
                    target_ip,
                    port,
                    e,
                )

        logger.warning(
            "[MessageService] 无法发送 FRIEND_ACCEPT 给 %s",
            friend_name,
        )
        return False

    def send_friend_delete(self, friend_name: str, friend_ip: str = "") -> bool:
        """向好友发送 FRIEND_DELETE 消息通知对方删除自己。"""
        friend = self.friend_db.get_friend(friend_name)
        if not friend:
            logger.warning("[MessageService] 找不到好友资料，无法发送删除通知 [%s]", friend_name)
            return False

        profile = self.friend_db.get_my_profile()
        sender_name = profile.get("name", "Unknown")
        sender_user_id = profile.get("user_id", "")

        delete_msg = {
            "type": Protocol.FRIEND_DELETE,
            "msg_id": str(uuid.uuid4()),
            "profile": {
                "user_id": sender_user_id,
                "name": sender_name,
            }
        }

        port = int(friend.get("port", Protocol.DEFAULT_TCP_PORT) or Protocol.DEFAULT_TCP_PORT)
        target_ip = friend_ip or friend.get("ip", "")

        logger.info("[MessageService] 尝试发送 FRIEND_DELETE 通知给 %s", friend_name)

        # 1) Try name-based lookup
        if self._send_data_to_friend(friend_name, delete_msg):
            return True

        # 2) Try endpoint-based lookup
        if target_ip:
            endpoint = f"{target_ip}:{port}" if port else target_ip
            if self._send_data_to_friend(endpoint, delete_msg):
                return True

        # 3) Establish fresh outbound connection to send if not connected
        if target_ip:
            try:
                conn_ok = self.connection_manager.connect_to_friend(
                    target_ip, port, friend_name
                )
                if conn_ok:
                    time.sleep(0.3)
                    if self._send_data_to_friend(friend_name, delete_msg):
                        return True
            except Exception as e:
                logger.error("[MessageService] 发送删除通知时主动连接 %s:%s 失败: %s", target_ip, port, e)

        return False

    def send_file(
        self,
        to_name: str,
        file_path: str,
        purpose: str = "chat_file",
        avatar_owner: str = "",
        avatar_user_id: str = "",
        require_online: bool = True,
        file_id: str = "",
    ) -> bool:
        """
        向在线好友发送文件。

        文件传输只走直连 TCP，不进入离线中继队列；这样可以避免大文件在 P2P
        洪泛网络里被重复缓存和转发。
        """
        if not file_path or not os.path.isfile(file_path):
            logger.warning("[MessageService] 文件不存在: %s", file_path)
            return False
        if require_online and not self.connection_manager.is_friend_online(to_name):
            logger.info("[MessageService] 文件发送前主动重连: %s", to_name)
            if not self._reconnect_file_peer(to_name):
                logger.warning("[MessageService] 好友不在线，无法发送文件: %s", to_name)
                return False

        my_profile = self.friend_db.get_my_profile()
        my_name = my_profile.get("name", "Unknown")
        my_user_id = my_profile.get("user_id", "")
        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        file_id = file_id or str(uuid.uuid4())
        sha256 = self._sha256_file(file_path)
        chunk_count = (file_size + self.FILE_CHUNK_SIZE - 1) // self.FILE_CHUNK_SIZE

        offer = {
            "type": self.FILE_OFFER,
            "file_id": file_id,
            "from_name": my_name,
            "to_name": to_name,
            "filename": filename,
            "size": file_size,
            "chunk_size": self.FILE_CHUNK_SIZE,
            "chunk_count": chunk_count,
            "sha256": sha256,
            "timestamp": timestamp,
            "purpose": purpose,
            "avatar_owner": avatar_owner or my_name,
            "avatar_user_id": avatar_user_id or my_user_id,
        }

        complete = {
            "type": self.FILE_COMPLETE,
            "file_id": file_id,
            "from_name": my_name,
            "to_name": to_name,
            "filename": filename,
            "size": file_size,
            "sha256": sha256,
            "timestamp": timestamp,
            "purpose": purpose,
            "avatar_owner": avatar_owner or my_name,
            "avatar_user_id": avatar_user_id or my_user_id,
        }

        ack_event = threading.Event()
        complete_event = threading.Event()
        with self._file_lock:
            self.file_transfer.register_sender(file_id, filename, to_name)
            self._active_senders[file_id]["size"] = file_size
            self._file_ack_events[file_id] = ack_event
            self._file_complete_events[file_id] = complete_event

        try:
            for attempt in range(1, self.FILE_MAX_ATTEMPTS + 1):
                if attempt > 1:
                    logger.warning(
                        "[MessageService] 重试文件传输 %s (%s/%s)",
                        filename,
                        attempt,
                        self.FILE_MAX_ATTEMPTS,
                    )
                    if not self._reconnect_file_peer(to_name):
                        continue

                if not self.connection_manager.is_friend_online(to_name):
                    if not self._reconnect_file_peer(to_name):
                        time.sleep(min(1.5, 0.25 * attempt))
                        continue

                if not self._send_data_to_friend(to_name, offer):
                    self._reconnect_file_peer(to_name)
                    time.sleep(min(1.5, 0.25 * attempt))
                    continue

                completed_chunks, reliable, binary_chunks = self._negotiate_file_resume(
                    to_name, file_id, filename, sha256, chunk_count, purpose
                )
                if completed_chunks:
                    logger.info(
                        "[MessageService] 断点续传文件: %s, 从分块 %s 开始",
                        filename,
                        completed_chunks,
                    )

                if not self._send_file_chunks(
                    to_name,
                    file_id,
                    filename,
                    file_path,
                    completed_chunks,
                    chunk_count,
                    file_size,
                    reliable,
                    binary_chunks,
                    ack_event,
                ):
                    with self._file_lock:
                        cancelled = self.file_transfer.sender_cancelled(file_id)
                    if cancelled:
                        self._send_data_to_friend(
                            to_name, {"type": self.FILE_CANCEL, "file_id": file_id}
                        )
                        return False
                    continue

                complete_event.clear()
                with self._file_lock:
                    self._file_complete_results.pop(file_id, None)
                if not self._send_data_to_friend(to_name, complete):
                    continue

                if reliable:
                    # Timeout scales with file size: base 30 s + 5 s per
                    # 100 MiB.  The incremental SHA256 on the receiver
                    # makes this rarely hit, but a dynamic ceiling protects
                    # against slow storage / very large files.
                    ack_timeout = max(
                        30.0,
                        30.0 + (file_size / (100 * 1024 * 1024)) * 5.0,
                    )
                    if not complete_event.wait(timeout=ack_timeout):
                        logger.warning(
                            "[MessageService] 等待文件完成确认超时 (%.0fs): %s",
                            ack_timeout,
                            filename,
                        )
                        continue
                    with self._file_lock:
                        complete_ok, error = self._file_complete_results.pop(
                            file_id, (False, "接收端未确认")
                        )
                    if not complete_ok:
                        logger.warning(
                            "[MessageService] 接收端拒绝文件完成: %s (%s)",
                            filename,
                            error,
                        )
                        continue

                status = "等待对方接受" if (reliable and error == "pending_accept") else "文件"
                with self._file_lock:
                    self._file_final_statuses[file_id] = status

                if purpose != "avatar":
                    self.friend_db.save_chat_message(
                        from_name=my_name,
                        to_name=to_name,
                        content=self._file_message_content(
                            filename, file_path, file_id, status=status
                        ),
                        timestamp=timestamp,
                        msg_id=file_id,
                    )
                if self.on_file_status_changed:
                    try:
                        self.on_file_status_changed(file_id, status)
                    except Exception:
                        pass
                return True

            logger.error(
                "[MessageService] 文件传输在 %s 次尝试后失败: %s",
                self.FILE_MAX_ATTEMPTS,
                filename,
            )
            return False
        finally:
            with self._file_lock:
                self.file_transfer.pop_sender(file_id)
                self._file_ack_events.pop(file_id, None)
                self._file_ack_progress.pop(file_id, None)
                self._file_ack_errors.pop(file_id, None)
                self._file_ack_capable.pop(file_id, None)
                self._file_binary_capable.pop(file_id, None)
                self._file_complete_events.pop(file_id, None)
                self._file_complete_results.pop(file_id, None)
                self._file_progress_last_emit.pop(file_id, None)

    def _negotiate_file_resume(
        self, to_name, file_id, filename, sha256, chunk_count, purpose
    ) -> tuple[int, bool, bool]:
        """Ask where to resume and which reliable/binary transfer features are supported."""
        if purpose == "avatar":
            return 0, False, False

        resume_event = threading.Event()
        with self._file_lock:
            self._file_resume_events[file_id] = resume_event
            self._file_resume_progress.pop(file_id, None)
            self._file_ack_capable.pop(file_id, None)
            self._file_binary_capable.pop(file_id, None)

        sent = self._send_data_to_friend(
            to_name,
            {
                "type": self.FILE_RESUME_REQ,
                "file_id": file_id,
                "filename": filename,
                "sha256": sha256,
            },
        )
        if sent:
            resume_event.wait(timeout=3.0)
        with self._file_lock:
            self._file_resume_events.pop(file_id, None)
            completed = int(self._file_resume_progress.pop(file_id, 0) or 0)
            reliable = bool(self._file_ack_capable.pop(file_id, False))
            binary_chunks = bool(self._file_binary_capable.pop(file_id, False))
        return max(0, min(completed, chunk_count)), reliable, binary_chunks

    def _send_file_chunks(
        self,
        to_name,
        file_id,
        filename,
        file_path,
        start_chunk,
        chunk_count,
        file_size,
        reliable,
        binary_chunks,
        ack_event,
    ) -> bool:
        """Stream file chunks.

        TCP already provides ordered reliable delivery and natural backpressure.
        Mid-transfer ACKs are therefore treated as advisory receiver progress
        only. Blocking every few chunks on an application ACK makes transfers
        fragile on slower devices: a delayed UI/disk write or lost ACK can freeze
        the sender at a small percentage even though the socket is healthy.
        """
        _ = reliable, ack_event
        sent_bytes = start_chunk * self.FILE_CHUNK_SIZE
        with open(file_path, "rb") as src:
            src.seek(start_chunk * self.FILE_CHUNK_SIZE)
            for index in range(start_chunk, chunk_count):
                while True:
                    with self._file_lock:
                        if self.file_transfer.sender_cancelled(file_id):
                            return False
                        pause_event = self.file_transfer.sender_pause_event(
                            file_id
                        )
                    if pause_event is None:
                        return False
                    if pause_event.wait(timeout=0.25):
                        break

                chunk = src.read(self.FILE_CHUNK_SIZE)
                if not chunk:
                    return False
                if binary_chunks:
                    sent = self._send_binary_chunk_to_friend(
                        to_name, file_id, index, chunk
                    )
                else:
                    chunk_msg = {
                        "type": self.FILE_CHUNK,
                        "file_id": file_id,
                        "chunk_index": index,
                        "data_b64": base64.b64encode(chunk).decode("ascii"),
                    }
                    sent = self._send_data_to_friend(to_name, chunk_msg)
                if not sent:
                    logger.warning(
                        "[MessageService] 文件分块发送失败: %s #%s",
                        filename,
                        index,
                    )
                    return False

                # Track bytes actually sent so the ACK handler can report
                # both "sent" and "confirmed" progress to the UI.
                sent_bytes = min(
                    (index + 1) * self.FILE_CHUNK_SIZE, file_size
                )
                with self._file_lock:
                    sender_state = self._active_senders.get(file_id, {})
                    sender_state["_sent_bytes"] = sent_bytes

                # Surface receiver-side errors promptly if an advisory ACK has
                # reported one, but never block merely waiting for that ACK.
                with self._file_lock:
                    error = self._file_ack_errors.get(file_id, "")
                if error:
                    logger.warning(
                        "[MessageService] 接收端报告文件写入失败: %s (%s)",
                        filename,
                        error,
                    )
                    return False

                # How many bytes the receiver has acknowledged so far.
                with self._file_lock:
                    ack_chunks = int(
                        self._file_ack_progress.get(file_id, 0) or 0
                    )
                confirmed = min(ack_chunks * self.FILE_CHUNK_SIZE, file_size)

                self._emit_file_progress(
                    file_id,
                    to_name,
                    filename,
                    sent_bytes,
                    file_size,
                    True,
                    force=(index + 1 == chunk_count),
                    confirmed=confirmed,
                )
        return True

    def _send_binary_chunk_to_friend(
        self, to_name: str, file_id: str, chunk_index: int, chunk: bytes
    ) -> bool:
        """Send one file chunk as a raw binary protocol frame."""
        try:
            packed = Protocol.create_binary_file_chunk(file_id, chunk_index, chunk)
            return bool(self.connection_manager.send_to_friend(to_name, packed))
        except Exception as exc:
            logger.error(
                "[MessageService] 二进制文件分块发送异常: %s #%s: %s",
                file_id,
                chunk_index,
                exc,
            )
            return False

    def _emit_file_progress(
        self,
        file_id: str,
        peer_name: str,
        filename: str,
        completed: int,
        total: int,
        sending: bool,
        force: bool = False,
        confirmed: int = 0,
    ):
        """Notify the UI of file-transfer progress.

        Throttled to ~8 Hz (125 ms) unless *force* is True or the
        percentage has crossed a 5‑point boundary since the last emit.

        *confirmed* is the byte count the remote side has acknowledged
        (meaningful for senders).  When non-zero the UI can show both
        "sent" and "confirmed" progress side-by-side.
        """
        if not self.on_file_progress:
            return
        now = time.monotonic()
        with self._file_lock:
            last = self._file_progress_last_emit.get(file_id, {})
            last_ts = float(last.get("ts", 0.0) or 0.0)
            last_pct = int(last.get("pct", -1) or -1)
            if not force:
                if now - last_ts < self.network_policy.file_progress_min_interval:
                    return
                if total > 0:
                    current_pct = int(completed / total * 100)
                    if (
                        abs(current_pct - last_pct)
                        < self.network_policy.file_progress_pct_step
                    ):
                        return
            self._file_progress_last_emit[file_id] = {
                "ts": now,
                "pct": int(completed / total * 100) if total else 0,
            }
        try:
            self.on_file_progress(
                file_id,
                peer_name,
                filename,
                completed,
                total,
                sending,
                confirmed=confirmed,
            )
        except Exception:
            logger.debug("[MessageService] on_file_progress 回调异常", exc_info=True)

    def _reconnect_file_peer(self, to_name: str) -> bool:
        """Reconnect a dropped file-transfer peer using its saved endpoint."""
        if self.connection_manager.is_friend_online(to_name):
            return True
        friend = self.friend_db.get_friend(to_name) or {}
        ip = friend.get("ip", "")
        port = int(friend.get("port", Protocol.DEFAULT_TCP_PORT) or Protocol.DEFAULT_TCP_PORT)
        if not ip:
            return False
        try:
            connected = self.connection_manager.connect_to_friend(ip, port, to_name)
            if connected is False:
                return False
            deadline = time.time() + 2.0
            while time.time() < deadline:
                if self.connection_manager.is_friend_online(to_name):
                    return True
                time.sleep(0.05)
            return self.connection_manager.is_friend_online(to_name)
        except Exception:
            logger.warning("[MessageService] 文件传输重连失败: %s", to_name, exc_info=True)
            return False

    # ================================================================== #
    #  接收消息处理
    # ================================================================== #

    def handle_message(self, from_ip: str, data: Dict[str, Any]):
        """
        处理从 TCP 连接收到的消息（核心调度器）。

        根据消息类型分发到不同的处理函数：
          - CHAT_MESSAGE:   若是给我的，显示并保存；若是给别人的，中继转发。
          - RELAY_MESSAGE:  检查去重后，解包原始消息并按 CHAT_MESSAGE 逻辑处理。
          - FRIEND_REQUEST:  检查匹配条件，自动接受或排队等待人工审核。
          - FRIEND_ACCEPT:  添加好友、交换 profile。
          - HEARTBEAT:      更新好友 IP 地址簿。

        Args:
            from_ip: 消息来源 IP 地址。
            data:    解析后的消息字典（必须包含 "type" 字段）。
        """
        msg_type = data.get("type", "")

        try:
            if msg_type == self.CHAT_MESSAGE:
                self._handle_chat_message(from_ip, data)
            elif msg_type == self.RELAY_MESSAGE:
                self._handle_relay_message(from_ip, data)
            elif msg_type == self.FRIEND_REQUEST:
                self._handle_friend_request(from_ip, data)
            elif msg_type == self.FRIEND_ACCEPT:
                self._handle_friend_accept(from_ip, data)
            elif msg_type == Protocol.FRIEND_DELETE:
                self._handle_friend_delete(from_ip, data)
            elif msg_type == self.HEARTBEAT:
                self._handle_heartbeat(from_ip, data)
            elif msg_type == self.PROFILE_UPDATE_NOTICE:
                self._handle_profile_update_notice(from_ip, data)
            elif msg_type == self.PROFILE_SYNC_REQ:
                self._handle_profile_sync_req(from_ip, data)
            elif msg_type == self.PROFILE_SYNC_RESP:
                self._handle_profile_sync_resp(from_ip, data)
            elif msg_type == self.FILE_OFFER:
                self._handle_file_offer(from_ip, data)
            elif msg_type == self.FILE_CHUNK:
                self._handle_file_chunk(from_ip, data)
            elif msg_type == self.FILE_CHUNK_ACK:
                self._handle_file_chunk_ack(from_ip, data)
            elif msg_type == self.FILE_COMPLETE:
                self._handle_file_complete(from_ip, data)
            elif msg_type == self.FILE_COMPLETE_ACK:
                self._handle_file_complete_ack(from_ip, data)
            elif msg_type == self.GROUP_CREATE:
                self._handle_group_create(from_ip, data)
            elif msg_type == self.GROUP_CHAT:
                self._handle_group_chat(from_ip, data)
            elif msg_type == self.GROUP_SYNC_REQ:
                self._handle_group_sync_req(from_ip, data)
            elif msg_type == self.GROUP_SYNC_RESP:
                self._handle_group_sync_resp(from_ip, data)
            elif msg_type == self.MOMENTS_PUBLISH:
                self._handle_moments_publish(from_ip, data)
            elif msg_type == self.MOMENTS_SYNC_REQ:
                self._handle_moments_sync_req(from_ip, data)
            elif msg_type == self.MOMENTS_SYNC_RESP:
                self._handle_moments_sync_resp(from_ip, data)
            elif msg_type == "MOMENT_COMMENT":
                self._handle_moment_comment(from_ip, data)
            elif msg_type == "MOMENT_DELETE":
                self._handle_moment_delete(from_ip, data)
            elif msg_type == self.FILE_CANCEL:
                self._handle_file_cancel(from_ip, data)
            elif msg_type == self.FILE_DECLINE:
                self._handle_file_decline(from_ip, data)
            elif msg_type == self.FILE_ACCEPT:
                self._handle_file_accept(from_ip, data)
            elif msg_type == self.FILE_RESUME_REQ:
                self._handle_file_resume_req(from_ip, data)
            elif msg_type == self.FILE_RESUME_RESP:
                self._handle_file_resume_resp(from_ip, data)
            else:
                logger.warning(f"[MessageService] 未知消息类型: {msg_type}")
        except Exception as exc:
            logger.error(
                "[MessageService] 处理 %s 消息时异常 (from %s): %s",
                msg_type, from_ip, exc,
            )

    # ------------------------------------------------------------------ #
    #  CHAT_MESSAGE 处理
    # ------------------------------------------------------------------ #

    def _handle_chat_message(self, from_ip: str, data: Dict[str, Any]):
        """处理聊天消息。

        若消息是发给我的：保存到 chat_history 并触发回调。
        若消息是发给别人的：中继给其他在线好友（排除来源方向）。
        """
        my_profile = self.friend_db.get_my_profile()
        my_name = my_profile.get("name", "")
        to_name = data.get("to_name", "")
        from_name = data.get("from_name", "")
        content = data.get("content", "")
        timestamp = data.get("timestamp", "")
        msg_id = data.get("msg_id", "")

        # 去重检查
        if msg_id and self.friend_db.check_msg_id(msg_id):
            logger.debug(f"[MessageService] 重复消息 {msg_id}，忽略")
            return
        if msg_id:
            self.friend_db.record_msg_id(msg_id)

        if to_name == my_name:
            # ---- 消息是给我的 ----
            self.friend_db.save_chat_message(
                from_name=from_name,
                to_name=my_name,
                content=content,
                timestamp=timestamp,
                msg_id=msg_id,
            )
            logger.info(f"[MessageService] 收到消息 {from_name}: {content[:50]}")

            # 触发 UI 回调
            if self.on_message_received:
                try:
                    self.on_message_received(from_name, content, timestamp, msg_id)
                except Exception as e:
                    logger.error(f"[MessageService] on_message_received 回调异常: {e}")
        else:
            # ---- 消息不是给我的，中继转发 ----
            logger.info(
                f"[MessageService] 中继消息 {from_name} -> {to_name}（经过本机）"
            )
            if self.connection_manager.is_friend_online(to_name):
                self._relay_chat_to_others(data, exclude_ip=from_ip, exclude_name=from_name)
            else:
                # 目标离线，由本机暂存，等目标上线后中继给它
                self.friend_db.add_pending_message(
                    to_name=to_name,
                    data_json=json.dumps(data, ensure_ascii=False),
                )
                self._relay_chat_to_others(data, exclude_ip=from_ip, exclude_name=from_name)

    # ------------------------------------------------------------------ #
    #  RELAY_MESSAGE 处理
    # ------------------------------------------------------------------ #

    def _handle_relay_message(self, from_ip: str, data: Dict[str, Any]):
        """处理洪泛中继消息。

        1. 检查 msg_id 去重（避免洪泛环路）。
        2. 检查 relay_hops 是否超过最大跳数。
        3. 解包 original_message，按 CHAT_MESSAGE 逻辑处理。
        4. 若目标不是本机，继续洪泛（hops + 1）。
        """
        original_message = data.get("original_message", {})
        relay_hops = data.get("relay_hops", 0)
        msg_id = original_message.get("msg_id", data.get("msg_id", ""))

        # 去重
        with self._relay_id_lock:
            if msg_id in self._processed_relay_ids:
                logger.debug(f"[MessageService] 重复中继 {msg_id}，忽略")
                return
            self._processed_relay_ids.add(msg_id)
            # 控制缓存大小
            if len(self._processed_relay_ids) > self._MAX_RELAY_CACHE:
                excess = len(self._processed_relay_ids) - self._MAX_RELAY_CACHE
                for _ in range(excess):
                    self._processed_relay_ids.pop()

        # 跳数检查
        if relay_hops >= self.MAX_RELAY_HOPS:
            logger.info(f"[MessageService] 中继跳数超限 ({relay_hops})，丢弃 {msg_id}")
            return

        my_profile = self.friend_db.get_my_profile()
        my_name = my_profile.get("name", "")
        to_name = original_message.get("to_name", "")

        if to_name == my_name:
            # 目标是本机，按普通聊天消息处理
            self._handle_chat_message(from_ip, original_message)
        else:
            # 继续洪泛：hops + 1，排除来源
            forwarded_relay = {
                "type": self.RELAY_MESSAGE,
                "relay_hops": relay_hops + 1,
                "original_message": original_message,
            }
            if self.connection_manager.is_friend_online(to_name):
                self._flood_relay(
                    forwarded_relay,
                    exclude_ip=from_ip,
                    exclude_name=original_message.get("from_name", ""),
                )
            else:
                # 目标离线，由本机暂存，等目标上线后中继给它
                self.friend_db.add_pending_message(
                    to_name=to_name,
                    data_json=json.dumps(forwarded_relay, ensure_ascii=False),
                )
                self._flood_relay(
                    forwarded_relay,
                    exclude_ip=from_ip,
                    exclude_name=original_message.get("from_name", ""),
                )

    # ------------------------------------------------------------------ #
    #  PROFILE 同步处理
    # ------------------------------------------------------------------ #

    def _profile_update_key(self, name: str = "", user_id: str = "") -> str:
        return user_id or name or "unknown"

    def _my_profile_version(self) -> str:
        version = self.friend_db.get_app_setting("my_profile_updated_at", "")
        if not version:
            version = str(time.time())
            self.friend_db.set_app_setting("my_profile_updated_at", version)
        return version

    def broadcast_profile_update_notice(self) -> int:
        """Tell online friends that my profile has changed; they choose when to pull it."""
        sent = 0
        for friend in self.connection_manager.get_online_friends():
            friend_name = self._online_friend_name(friend)
            if friend_name and self.send_profile_update_notice(friend_name):
                sent += 1
        return sent

    def send_profile_update_notice(self, friend_name: str) -> bool:
        profile = self.friend_db.get_my_profile()
        version = self._my_profile_version()
        payload = {
            "type": self.PROFILE_UPDATE_NOTICE,
            "from_name": profile.get("name", ""),
            "user_id": profile.get("user_id", ""),
            "version": version,
        }
        return self._send_data_to_friend(friend_name, payload)

    def has_pending_profile_update(self, friend_name: str) -> bool:
        friend = self.friend_db.get_friend(friend_name) or {}
        friend_uid = friend.get("user_id", "")
        # Try user_id-based key first, then name-based, then both
        for key in (
            [self._profile_update_key(friend.get("name", friend_name), friend_uid)]
            + ([friend_name] if friend_name else [])
            + ([friend_uid] if friend_uid and friend_uid != friend_name else [])
        ):
            pending = self.friend_db.get_app_setting(f"profile_pending:{key}", "")
            synced = self.friend_db.get_app_setting(f"profile_synced:{key}", "")
            if pending and pending != synced:
                return True
        return False

    def request_friend_profile(self, friend_name: str) -> bool:
        friend = self.friend_db.get_friend(friend_name) or {}
        return self._send_data_to_friend(
            friend_name,
            {
                "type": self.PROFILE_SYNC_REQ,
                "from_name": self.friend_db.get_my_profile().get("name", ""),
                "target_user_id": friend.get("user_id", ""),
            },
        )

    def _handle_profile_update_notice(self, from_ip: str, data: Dict[str, Any]):
        name = data.get("from_name", "") or self._get_friend_name_by_ip(from_ip)
        user_id = data.get("user_id", "")
        version = str(data.get("version", "") or "")
        if not name or not version:
            return
        key = self._profile_update_key(name, user_id)
        synced = self.friend_db.get_app_setting(f"profile_synced:{key}", "")
        if version != synced:
            # Store under the canonical key (user_id if available, else name)
            self.friend_db.set_app_setting(f"profile_pending:{key}", version)
            # Also store under the name-based key to ensure has_pending_profile_update
            # can find it even if the local friend record lacks a user_id
            if user_id and name and user_id != name:
                self.friend_db.set_app_setting(f"profile_pending:{name}", version)
                self.friend_db.set_app_setting(f"profile_pending:{user_id}", version)
            if self.on_friend_profile_update_available:
                self.on_friend_profile_update_available(name)

    def _handle_profile_sync_req(self, from_ip: str, data: Dict[str, Any]):
        profile = dict(self.friend_db.get_my_profile() or {})
        requester = self._get_friend_name_by_ip(from_ip) or data.get("from_name", "")
        payload = {
            "type": self.PROFILE_SYNC_RESP,
            "profile": {
                "user_id": profile.get("user_id", ""),
                "name": profile.get("name", ""),
                "tags": profile.get("tags", []),
                "bio": profile.get("bio", ""),
                "background": profile.get("background", ""),
                "card_bg": profile.get("card_bg", ""),
            },
            "version": self._my_profile_version(),
        }
        if requester:
            self._send_data_to_friend_with_fallback(requester, payload, from_ip)
            self._send_avatar_to_friend(requester)
            self._send_card_bg_to_friend(requester)

    def _handle_profile_sync_resp(self, from_ip: str, data: Dict[str, Any]):
        profile = dict(data.get("profile") or {})
        name = profile.get("name", "") or self._get_friend_name_by_ip(from_ip)
        if not name:
            return
        friend = self.friend_db.get_friend(name)
        if not friend:
            logger.debug(f"[MessageService] 忽略未添加好友 {name} 的资料同步响应")
            return
        self.friend_db.add_friend(
            name=name,
            ip=friend.get("ip", from_ip) or from_ip,
            port=int(friend.get("port", Protocol.DEFAULT_TCP_PORT) or Protocol.DEFAULT_TCP_PORT),
            tags=profile.get("tags", []),
            bio=profile.get("bio", ""),
            category=friend.get("category", "朋友"),
            user_id=profile.get("user_id", friend.get("user_id", "")),
            status=friend.get("status", "accepted"),
            avatar=friend.get("avatar", ""),
            background=profile.get("background", friend.get("background", "")),
            card_bg=profile.get("card_bg", friend.get("card_bg", "")),
        )
        user_id = profile.get("user_id", "")
        key = self._profile_update_key(name, user_id)
        version = str(data.get("version", "") or "")
        if version:
            self.friend_db.set_app_setting(f"profile_synced:{key}", version)
            self.friend_db.set_app_setting(f"profile_pending:{key}", version)
            # Also sync under alternate keys to cover name-only lookups
            if user_id and name and user_id != name:
                self.friend_db.set_app_setting(f"profile_synced:{name}", version)
                self.friend_db.set_app_setting(f"profile_pending:{name}", version)
                self.friend_db.set_app_setting(f"profile_synced:{user_id}", version)
                self.friend_db.set_app_setting(f"profile_pending:{user_id}", version)
        if self.on_friend_profile_updated:
            self.on_friend_profile_updated(name)

    # ------------------------------------------------------------------ #
    #  FRIEND_REQUEST 处理
    # ------------------------------------------------------------------ #

    def _handle_friend_request(self, from_ip: str, data: Dict[str, Any]):
        """处理好友请求。

        1. 检查对方 profile 是否满足本机设定的好友条件。
        2. 若满足且 auto_accept 已开启，自动接受并发送 FRIEND_ACCEPT。
        3. 否则触发 on_friend_request 回调，等待用户手动决定。
        """
        profile = data.get("profile", {})
        conditions = data.get("conditions", {})
        sender_name = profile.get("name", "Unknown")
        sender_user_id = profile.get("user_id", "")
        msg_id = data.get("msg_id", "")
        sender_port = int(
            profile.get("tcp_port", Protocol.DEFAULT_TCP_PORT)
            or Protocol.DEFAULT_TCP_PORT
        )

        # 去重
        if msg_id and self.friend_db.check_msg_id(msg_id):
            return
        if msg_id:
            self.friend_db.record_msg_id(msg_id)

        # 检查是否已经是好友
        existing = (
            self.friend_db.get_friend_by_user_id(sender_user_id)
            or self.friend_db.get_friend(sender_name)
        )
        if existing:
            self.friend_db.add_friend(
                name=sender_name,
                ip=from_ip,
                port=sender_port,
                tags=profile.get("tags", existing.get("tags", [])),
                category=existing.get("category", "朋友"),
                bio=profile.get("bio", existing.get("bio", "")),
                user_id=sender_user_id or existing.get("user_id", ""),
                status="accepted",
                avatar=self._shared_avatar_reference(profile.get("avatar", "")),
            )
            self.send_friend_accept(sender_name, from_ip)
            logger.info(
                f"[MessageService] {sender_name} 已是好友，已补发确认回执"
            )
            return

        # 检查条件匹配
        conditions_matched = self.friend_db.check_conditions_match(profile)

        friend_conditions = self.friend_db.get_friend_conditions()
        auto_accept = friend_conditions.get("auto_accept", False)

        if auto_accept and conditions_matched:
            # 自动接受
            tags = profile.get("tags", [])
            self.friend_db.add_friend(
                name=sender_name,
                ip=from_ip,
                port=sender_port,
                tags=tags,
                category="朋友",
                bio=profile.get("bio", ""),
                user_id=sender_user_id,
                status="accepted",
                avatar=self._shared_avatar_reference(profile.get("avatar", "")),
            )
            # 发送 ACCEPT 回执
            self.send_friend_accept(sender_name, from_ip)
            logger.info(f"[MessageService] 自动接受好友请求: {sender_name}")

            self.add_system_notification(
                title="好友申请通过 🤝",
                content=f"已自动同意「{sender_name}」的好意申请，你们现在可以开始聊天了！",
                category="success"
            )

            if self.on_friend_accepted:
                try:
                    self.on_friend_accepted(sender_name, from_ip)
                except Exception as e:
                    logger.error(f"[MessageService] on_friend_accepted 回调异常: {e}")
        else:
            # 检查是否已有处于 pending 状态的来向请求
            existing_req = self.friend_db.get_friend_request(user_id=sender_user_id, name=sender_name)
            is_already_pending = (
                existing_req is not None
                and existing_req.get("status") == "pending"
                and existing_req.get("direction") == "incoming"
            )

            self.friend_db.upsert_friend_request(
                name=sender_name,
                ip=from_ip,
                port=sender_port,
                tags=profile.get("tags", []),
                bio=profile.get("bio", ""),
                direction="incoming",
                status="pending",
                user_id=sender_user_id,
                msg_id=msg_id,
            )

            if not is_already_pending:
                # 首次收到，需要人工审核并通知
                logger.info(
                    f"[MessageService] 好友请求待审核: {sender_name} "
                    f"(条件匹配={conditions_matched})"
                )
                self.add_system_notification(
                    title="新好友申请 👤",
                    content=f"收到来自「{sender_name}」的好友申请，快来同意吧！",
                    category="friend_request"
                )
                if self.on_friend_request:
                    try:
                        profile = dict(profile)
                        profile.setdefault("ip", from_ip)
                        try:
                            param_count = len(inspect.signature(self.on_friend_request).parameters)
                        except (TypeError, ValueError):
                            param_count = 2
                        if param_count >= 3:
                            self.on_friend_request(profile, conditions_matched, from_ip)
                        else:
                            self.on_friend_request(profile, conditions_matched)
                    except Exception as e:
                        logger.error(f"[MessageService] on_friend_request 回调异常: {e}")
            else:
                logger.info(f"[MessageService] 收到来自 {sender_name} 的重复好友请求，仅更新请求记录，不重复通知。")

    # ------------------------------------------------------------------ #
    #  FRIEND_ACCEPT 处理
    # ------------------------------------------------------------------ #

    def _handle_friend_accept(self, from_ip: str, data: Dict[str, Any]):
        """处理好友接受回复。

        将对方加入好友列表，更新 IP，并触发回调。
        """
        profile = data.get("profile", {})
        friend_name = profile.get("name", "Unknown")
        friend_user_id = profile.get("user_id", "")
        msg_id = data.get("msg_id", "")

        # 去重
        if msg_id and self.friend_db.check_msg_id(msg_id):
            return
        if msg_id:
            self.friend_db.record_msg_id(msg_id)

        tags = profile.get("tags", [])
        bio = profile.get("bio", "")
        port = int(profile.get("tcp_port", Protocol.DEFAULT_TCP_PORT) or Protocol.DEFAULT_TCP_PORT)

        # 检查是否已经是好友
        existing = (
            self.friend_db.get_friend_by_user_id(friend_user_id)
            or self.friend_db.get_friend(friend_name)
        )
        if existing:
            # 更新 profile 信息
            self.friend_db.add_friend(
                name=friend_name,
                ip=from_ip,
                port=port,
                tags=tags,
                category=existing.get("category", "朋友"),
                bio=bio,
                user_id=friend_user_id or existing.get("user_id", ""),
                status="accepted",
                avatar=self._shared_avatar_reference(profile.get("avatar", "")),
            )
            logger.info(f"[MessageService] 好友 {friend_name} 已存在，更新 IP")
        else:
            # 只有当对方是我们主动请求过的好友（pending_sent）时，才接受 FRIEND_ACCEPT。
            # 这能防止被删除的好友在连通时因自愈机制被自动加回。
            status = self.friend_db.get_relationship_status(
                user_id=friend_user_id,
                name=friend_name,
                ip=from_ip,
                port=port,
            )
            if status != "pending_sent":
                logger.info(
                    f"[MessageService] 收到来自 {friend_name} 的 FRIEND_ACCEPT 消息，"
                    f"但当前关系状态为 {status}，忽略添加好友。"
                )
                return

            self.friend_db.add_friend(
                name=friend_name,
                ip=from_ip,
                port=port,
                tags=tags,
                category="朋友",
                bio=bio,
                user_id=friend_user_id,
                status="accepted",
                avatar=self._shared_avatar_reference(profile.get("avatar", "")),
            )
            logger.info(f"[MessageService] 好友已添加: {friend_name} ({from_ip})")
            self.add_system_notification(
                title="好友申请通过 🤝",
                content=f"「{friend_name}」同意了您的好友申请，你们现在可以开始聊天了！",
                category="success"
            )

        self.friend_db.set_friend_request_status(
            "accepted",
            user_id=friend_user_id,
            name=friend_name,
            ip=from_ip,
            port=port,
        )

        # 触发回调
        if self.on_friend_accepted:
            try:
                self.on_friend_accepted(friend_name, from_ip)
            except Exception as e:
                logger.error(f"[MessageService] on_friend_accepted 回调异常: {e}")

    # ------------------------------------------------------------------ #
    #  FRIEND_DELETE 处理
    # ------------------------------------------------------------------ #

    def _handle_friend_delete(self, from_ip: str, data: Dict[str, Any]):
        """处理好友主动删除我的通知。

        将对方从我的好友列表和好友请求表中删除，并触发回调刷新 UI。
        """
        profile = data.get("profile", {})
        friend_name = profile.get("name", "Unknown")
        friend_user_id = profile.get("user_id", "")

        logger.info(
            f"[MessageService] 收到来自 {friend_name} 的 FRIEND_DELETE 消息，执行双向删除。"
        )

        # 1. 断开与该好友的任何活跃连接
        if self.connection_manager:
            friend = self.friend_db.get_friend(friend_name) or self.friend_db.get_friend_by_user_id(friend_user_id)
            if friend:
                ip = friend.get("ip")
                port = friend.get("port")
                if ip:
                    endpoint = f"{ip}:{port}" if port else ip
                    if hasattr(self.connection_manager, "disconnect_friend"):
                        self.connection_manager.disconnect_friend(endpoint)

        # 2. 从本地数据库中移除好友
        if self.friend_db:
            self.add_system_notification(
                title="好友删除通知 ⚠️",
                content=f"好友「{friend_name}」已将您从好友列表中删除。",
                category="warning"
            )
            self.friend_db.remove_friend(friend_name)

        # 3. 触发 UI 刷新回调
        if self.on_friend_accepted:
            try:
                self.on_friend_accepted(friend_name, from_ip)
            except Exception as e:
                logger.error(f"[MessageService] handle_friend_delete 触发回调异常: {e}")

        # 4. 触发删除通知回调
        if self.on_friend_deleted:
            try:
                self.on_friend_deleted(friend_name)
            except Exception as e:
                logger.error(f"[MessageService] on_friend_deleted 回调异常: {e}")

    # ------------------------------------------------------------------ #
    #  HEARTBEAT 处理
    # ------------------------------------------------------------------ #

    def _handle_heartbeat(self, from_ip: str, data: Dict[str, Any]):
        """处理心跳消息，更新好友 IP 地址。"""
        friend_name = data.get("name", "")
        if not friend_name:
            return

        friend = self.friend_db.get_friend(friend_name)
        if friend:
            old_ip = friend.get("ip", "")
            old_port = int(friend.get("port", Protocol.DEFAULT_TCP_PORT) or 0)
            new_port = int(data.get("port", old_port) or old_port)

            new_avatar = self._shared_avatar_reference(data.get("avatar", ""))
            user_id = data.get("user_id", friend.get("user_id", ""))

            if old_ip != from_ip or (new_port and old_port != new_port) or friend.get("avatar", "") != new_avatar:
                self.friend_db.add_friend(
                    name=friend_name,
                    ip=from_ip,
                    port=new_port or old_port,
                    tags=friend.get("tags", []),
                    category=friend.get("category", "朋友"),
                    bio=friend.get("bio", ""),
                    user_id=user_id or friend.get("user_id", ""),
                    status=friend.get("status", "accepted"),
                    avatar=new_avatar or friend.get("avatar", ""),
                    background=friend.get("background", ""),
                )
                logger.info(
                    f"[MessageService] 心跳更新 {friend_name} 地址与资料: "
                    f"{old_ip}:{old_port} -> {from_ip}:{new_port or old_port}"
                )

    # ------------------------------------------------------------------ #
    #  FILE_* 处理
    # ------------------------------------------------------------------ #

    def _handle_file_offer(self, from_ip: str, data: Dict[str, Any]):
        """接收文件元信息。avatars are auto-accepted; chat files ask the user
        but start buffering data immediately so chunks are not lost."""
        my_name = self.friend_db.get_my_profile().get("name", "")
        to_name = data.get("to_name", "")
        if to_name and to_name != my_name:
            return

        file_id = data.get("file_id", "")
        from_name = data.get("from_name", "")
        if not file_id or not from_name:
            return

        # Prevent duplicate handling of the same file offer ID
        with self._file_offer_lock:
            if file_id in self._pending_file_offers:
                return
        with self._file_lock:
            if file_id in self._incoming_files:
                return

        try:
            for notif in self.friend_db.get_system_notifications():
                if f"[文件ID:{file_id}]" in notif.get("content", ""):
                    return
        except Exception:
            pass

        purpose = data.get("purpose", "chat_file")

        # Always create the incoming state so chunks can be buffered.
        # For chat files, mark as pending — the file will only be
        # finalised when the user accepts.
        self._accept_file_offer_internal(from_ip, data)

        if purpose == "avatar":
            return  # auto-accepted, no dialog needed

        # Mark as pending user confirmation.
        with self._file_lock:
            state = self._incoming_files.get(file_id)
            if state:
                state["pending_accept"] = True

        filename = self._safe_filename(data.get("filename", "received.bin"))
        file_size = int(data.get("size", 0) or 0)
        with self._file_offer_lock:
            self._pending_file_offers[file_id] = True

        # Add a persistent system notification so that the file offer is visible
        # in the notification center and survives restarts/switches.
        sz = file_size
        sz_str = f"{sz} B"
        for unit in ("B", "KiB", "MiB", "GiB"):
            if sz < 1024 or unit == "GiB":
                sz_str = f"{sz:.0f} {unit}" if unit == "B" else f"{sz:.1f} {unit}"
                break
            sz /= 1024
        self.add_system_notification(
            title="文件传输请求 📁",
            content=f"收到来自「{from_name}」的文件传输请求，文件名：「{filename}」({sz_str})。\n[文件ID:{file_id}]",
            category="file_offer"
        )

        if self.on_file_offer_received:
            try:
                self.on_file_offer_received(from_name, filename, file_size, file_id)
            except Exception:
                logger.debug("[MessageService] on_file_offer_received error", exc_info=True)

    def accept_file_offer(self, file_id: str) -> bool:
        """User accepted — finalise if file is already complete."""
        with self._file_offer_lock:
            if file_id not in self._pending_file_offers:
                return False
            del self._pending_file_offers[file_id]

        from_name = ""
        with self._file_lock:
            state = self._incoming_files.get(file_id)
            if not state:
                return False
            state["pending_accept"] = False
            is_complete = state.get("_all_chunks_received", False)
            from_name = state.get("from_name", "")

        if from_name:
            accept_msg = {
                "type": self.FILE_ACCEPT,
                "file_id": file_id,
                "from_name": self.friend_db.get_my_profile().get("name", ""),
            }
            self._send_data_to_friend_with_fallback(from_name, accept_msg, "")

        if is_complete:
            # All chunks arrived while waiting for user decision.
            # Finalise now.
            self._finalise_incoming_file(file_id)
        return True

    def decline_file_offer(self, file_id: str) -> bool:
        """User declined — clean up and notify sender."""
        with self._file_offer_lock:
            if file_id not in self._pending_file_offers:
                return False
            del self._pending_file_offers[file_id]

        from_name = ""
        filename = "received.bin"
        with self._file_lock:
            state = self._incoming_files.pop(file_id, None)
            if state:
                from_name = state.get("from_name", "")
                filename = state.get("filename", "received.bin")
                self._close_incoming_handle(state)
                part_path = state.get("part_path", "")
                if part_path and os.path.exists(part_path):
                    try:
                        os.remove(part_path)
                    except Exception:
                        pass

        if from_name:
            decline_msg = {
                "type": self.FILE_DECLINE,
                "file_id": file_id,
                "from_name": self.friend_db.get_my_profile().get("name", ""),
            }
            self._send_data_to_friend_with_fallback(from_name, decline_msg, "")

            # Save Bob's local decline message to database
            try:
                self.friend_db.save_chat_message(
                    from_name=from_name,
                    to_name=self.friend_db.get_my_profile().get("name", ""),
                    content=self._file_message_content(
                        filename, "", file_id, status="已拒绝接收"
                    ),
                    timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
                    msg_id=file_id,
                )
            except Exception:
                logger.debug("Failed to save local decline chat message", exc_info=True)

        if self.on_file_status_changed:
            try:
                self.on_file_status_changed(file_id, "已拒绝接收")
            except Exception:
                pass
        return True

    def _accept_file_offer_internal(self, from_ip: str, data: Dict[str, Any]):
        """Create incoming file state (original _handle_file_offer logic)."""
        from_name = data.get("from_name", "")
        file_id = data.get("file_id", "")
        filename = self._safe_filename(data.get("filename", "received.bin"))
        purpose = data.get("purpose", "chat_file")
        if purpose == "avatar":
            final_path = self._unique_avatar_path(
                filename,
                data.get("avatar_owner", from_name),
                data.get("avatar_user_id", ""),
            )
            part_path = final_path + ".part"
        else:
            candidate = os.path.join(self.receive_dir, filename)
            if os.path.exists(candidate):
                final_path = self._unique_receive_path(filename)
            else:
                final_path = candidate
            import tempfile
            part_path = os.path.join(
                tempfile.gettempdir(),
                f"meeting_in_beiyang_{file_id}_{filename}.part"
            )

        completed_chunks = 0
        if purpose != "avatar" and os.path.exists(part_path):
            existing_size = os.path.getsize(part_path)
            chunk_size = int(data.get("chunk_size", self.FILE_CHUNK_SIZE) or self.FILE_CHUNK_SIZE)
            completed_chunks = existing_size // chunk_size

        with self._file_lock:
            old_state = self._incoming_files.get(file_id)
            if old_state:
                self._close_incoming_handle(old_state)
            self._incoming_files[file_id] = {
                "from_name": from_name,
                "from_ip": from_ip,
                "filename": filename,
                "final_path": final_path,
                "part_path": part_path,
                "size": int(data.get("size", 0) or 0),
                "chunk_size": int(data.get("chunk_size", self.FILE_CHUNK_SIZE) or self.FILE_CHUNK_SIZE),
                "chunk_count": int(data.get("chunk_count", 0) or 0),
                "sha256": data.get("sha256", ""),
                "timestamp": data.get("timestamp", time.strftime("%Y-%m-%d %H:%M:%S")),
                "purpose": purpose,
                "avatar_owner": data.get("avatar_owner", from_name),
                "avatar_user_id": data.get("avatar_user_id", ""),
                "received": set(range(completed_chunks)),
                "next_expected": completed_chunks,
                "_sha256_state": hashlib.sha256(),
            }

        os.makedirs(os.path.dirname(final_path), exist_ok=True)
        if not os.path.exists(part_path):
            with open(part_path, "wb"):
                pass
        # For resumed transfers, pre-seed the incremental hasher with the
        # existing .part data so the final hexdigest is correct without
        # a slow full-file scan at FILE_COMPLETE time.
        if completed_chunks > 0 and os.path.getsize(part_path) > 0:
            with open(part_path, "rb") as pf:
                while True:
                    block = pf.read(1024 * 1024)
                    if not block:
                        break
                    self._incoming_files[file_id]["_sha256_state"].update(block)
        # Keep the part file open for the whole transfer so each chunk
        # write is just a seek+write instead of an open/close syscall pair.
        try:
            handle = open(part_path, "r+b")
            with self._file_lock:
                state = self._incoming_files.get(file_id)
                if state is not None:
                    state["_file_handle"] = handle
                else:
                    handle.close()
        except Exception:
            logger.warning("[MessageService] 打开接收文件句柄失败: %s", part_path, exc_info=True)
        logger.info("[MessageService] 准备接收文件 %s from %s", filename, from_name)

    @staticmethod
    def _close_incoming_handle(state):
        """Close the cached part-file handle held in *state*, if any."""
        if not state:
            return
        handle = state.pop("_file_handle", None)
        if handle:
            try:
                handle.close()
            except Exception:
                pass

    def _handle_file_chunk(self, from_ip: str, data: Dict[str, Any]):
        """写入一个文件分块。"""
        file_id = data.get("file_id", "")
        if not file_id:
            return

        with self._file_lock:
            state = self._incoming_files.get(file_id)
        if not state:
            logger.warning("[MessageService] 收到未知文件分块: %s", file_id)
            return

        try:
            index = int(data.get("chunk_index", -1))
            if data.get("binary"):
                raw_data = data.get("data", b"")
                if not isinstance(raw_data, (bytes, bytearray)):
                    raise ValueError("invalid binary chunk payload")
                raw = bytes(raw_data)
            else:
                raw = base64.b64decode(
                    data.get("data_b64", "").encode("ascii"), validate=True
                )
            chunk_size = int(state["chunk_size"])
            chunk_count = int(state.get("chunk_count", 0) or 0)
            expected_size = int(state.get("size", 0) or 0)
            if index < 0 or (chunk_count and index >= chunk_count):
                raise ValueError("invalid chunk index")
            if len(raw) > chunk_size:
                raise ValueError("chunk exceeds negotiated size")
            offset = index * chunk_size
            if expected_size and offset + len(raw) > expected_size:
                raise ValueError("chunk exceeds file size")

            with self._file_lock:
                # Track actual bytes written (not chunk_count × chunk_size)
                # so progress is accurate even for variable-size final chunks.
                state.setdefault("_bytes_written", 0)
                handle = state.get("_file_handle")
                if handle is None:
                    handle = open(state["part_path"], "r+b")
                    state["_file_handle"] = handle
                handle.seek(offset)
                handle.write(raw)
                actual_end = handle.tell()
                state["_bytes_written"] = max(
                    state["_bytes_written"], actual_end
                )
                state["received"].add(index)
                # Incremental SHA256 — avoids a full-file hash at the end
                # which can take many seconds for large files and cause
                # the sender's FILE_COMPLETE_ACK timeout to fire.
                state["_sha256_state"].update(raw)
                next_expected = int(state.get("next_expected", 0) or 0)
                while next_expected in state["received"]:
                    next_expected += 1
                state["next_expected"] = next_expected
                ack_due = (
                    next_expected == chunk_count
                    or next_expected % self.FILE_ACK_INTERVAL == 0
                )
        except Exception as exc:
            logger.warning(
                "[MessageService] 文件分块写入失败: %s #%s: %s",
                file_id,
                data.get("chunk_index", "?"),
                exc,
            )
            self._send_file_chunk_ack(state, file_id, ok=False, error=str(exc))
            return

        if ack_due:
            self._send_file_chunk_ack(state, file_id, next_expected=next_expected)

        total_size = int(state.get("size", 0) or 0)
        # Use actual bytes written (accurate for variable-size last chunk).
        completed_size = min(state.get("_bytes_written", 0), total_size)
        self._emit_file_progress(
            file_id,
            state.get("from_name", ""),
            state.get("filename", ""),
            completed_size,
            total_size,
            False,
            force=(chunk_count and state.get("next_expected", 0) >= chunk_count),
        )

    def _send_file_chunk_ack(
        self, state, file_id: str, next_expected: int = 0, ok: bool = True, error: str = ""
    ):
        payload = {
            "type": self.FILE_CHUNK_ACK,
            "file_id": file_id,
            "next_chunk": next_expected,
            "ok": ok,
            "error": error,
        }
        from_name = state.get("from_name", "")
        from_ip = state.get("from_ip", "")
        self._send_data_to_friend_with_fallback(from_name, payload, from_ip)

    def _handle_file_chunk_ack(self, from_ip: str, data: Dict[str, Any]):
        file_id = data.get("file_id", "")
        if not file_id:
            return
        with self._file_lock:
            next_chunk = int(data.get("next_chunk", 0) or 0)
            self._file_ack_progress[file_id] = next_chunk
            if not data.get("ok", True):
                self._file_ack_errors[file_id] = data.get("error", "接收端写入失败")
            event = self._file_ack_events.get(file_id)
            if event:
                event.set()
            # Fetch sender-side file info for progress emission.
            sender = self._active_senders.get(file_id, {})
            peer = sender.get("to_name", "")
            fname = sender.get("filename", "")
            total = int(sender.get("size", 0) or 0)
            sent = int(sender.get("_sent_bytes", 0) or 0)

        if peer and total:
            confirmed = min(next_chunk * self.FILE_CHUNK_SIZE, total)
            self._emit_file_progress(
                file_id,
                peer,
                fname,
                sent,
                total,
                True,
                force=True,
                confirmed=confirmed,
            )

    def _handle_file_complete(self, from_ip: str, data: Dict[str, Any]):
        """完成文件接收、校验并写入聊天记录。"""
        file_id = data.get("file_id", "")
        if not file_id:
            return

        with self._file_lock:
            state = self._incoming_files.get(file_id)
        if not state:
            logger.warning("[MessageService] 收到未知文件完成通知: %s", file_id)
            return

        from_name = data.get("from_name") or state.get("from_name", "")
        from_ip = state.get("from_ip", from_ip)

        if state.get("already_complete"):
            self._send_file_complete_ack(from_name, file_id, True, fallback=from_ip)
            return

        # If the user hasn't accepted yet, defer finalisation but still
        # ACK so the sender doesn't time out.
        if state.get("pending_accept"):
            state["_all_chunks_received"] = True
            state["_pending_complete_data"] = dict(data)
            self._send_file_complete_ack(from_name, file_id, True, error="pending_accept", fallback=from_ip)
            return

        self._finalise_incoming_file(file_id, data)

    def _finalise_incoming_file(
        self, file_id: str, data: Dict[str, Any] = None
    ):
        """Verify, rename and record a fully-received file."""
        with self._file_lock:
            state = self._incoming_files.get(file_id)
        if not state:
            return

        if data is None:
            data = state.get("_pending_complete_data", {})
        from_name = data.get("from_name") or state.get("from_name", "")
        from_ip = state.get("from_ip", "")

        part_path = state["part_path"]
        final_path = state["final_path"]
        self._close_incoming_handle(state)

        expected_count = int(state.get("chunk_count", 0) or 0)
        if expected_count and len(state["received"]) < expected_count:
            logger.warning("[MessageService] 文件未收齐: %s", state["filename"])
            self._send_file_complete_ack(
                from_name, file_id, False, "文件分块未收齐", fallback=from_ip
            )
            return

        expected_hash = data.get("sha256") or state.get("sha256", "")
        incremental = state.get("_sha256_state")
        actual_hash = (
            incremental.hexdigest()
            if incremental
            else self._sha256_file(part_path)
        )
        if expected_hash and actual_hash != expected_hash:
            logger.warning("[MessageService] 文件校验失败: %s", state["filename"])
            with self._file_lock:
                self._incoming_files.pop(file_id, None)
            try:
                os.remove(part_path)
            except OSError:
                pass
            self._send_file_complete_ack(
                from_name, file_id, False, "SHA-256 校验失败", fallback=from_ip
            )
            return

        try:
            import shutil
            shutil.move(part_path, final_path)
        except Exception as e:
            logger.error(f"[MessageService] 移动临时文件失败: {e}, fallback to os.replace")
            os.replace(part_path, final_path)
        with self._file_lock:
            self._incoming_files.pop(file_id, None)

        my_name = self.friend_db.get_my_profile().get("name", "")
        timestamp = data.get("timestamp") or state.get(
            "timestamp", time.strftime("%Y-%m-%d %H:%M:%S")
        )
        filename = state.get("filename", os.path.basename(final_path))
        purpose = data.get("purpose") or state.get("purpose", "chat_file")
        avatar_owner = data.get("avatar_owner") or state.get("avatar_owner", from_name)
        avatar_user_id = data.get("avatar_user_id") or state.get("avatar_user_id", "")

        if purpose == "avatar":
            self.friend_db.update_friend_avatar(
                name=avatar_owner or from_name,
                user_id=avatar_user_id,
                avatar=final_path,
            )
            logger.info("好友头像接收完成: %s -> %s", avatar_owner or from_name, final_path)
            if self.on_file_received:
                try:
                    self.on_file_received(avatar_owner or from_name, final_path, timestamp)
                except Exception:
                    logger.debug("[MessageService] on_file_received 回调异常", exc_info=True)
            self._send_file_complete_ack(from_name, file_id, True, fallback=from_ip)
            return

        if purpose == "card_bg":
            self.friend_db.update_friend_card_bg(
                name=avatar_owner or from_name,
                user_id=avatar_user_id,
                card_bg=final_path,
            )
            logger.info("好友名片背景接收完成: %s -> %s", avatar_owner or from_name, final_path)
            if self.on_file_received:
                try:
                    self.on_file_received(avatar_owner or from_name, final_path, timestamp)
                except Exception:
                    logger.debug("[MessageService] on_file_received 回调异常", exc_info=True)
            self._send_file_complete_ack(from_name, file_id, True, fallback=from_ip)
            return

        content = self._file_message_content(filename, final_path, file_id)

        self.friend_db.save_chat_message(
            from_name=from_name,
            to_name=my_name,
            content=content,
            timestamp=timestamp,
            msg_id=file_id,
        )
        if self.on_file_status_changed:
            try:
                self.on_file_status_changed(file_id, "文件")
            except Exception:
                pass
        logger.info("[MessageService] 文件接收完成: %s", final_path)
        self.add_system_notification(
            title="文件接收通知 📁",
            content=f"成功接收来自「{from_name}」的文件：{filename}\n保存位置：{final_path}",
            category="info"
        )
        with self._file_lock:
            self._completed_file_transfers[file_id] = {
                "final_path": final_path,
                "part_path": part_path,
                "filename": filename,
                "sha256": expected_hash,
                "size": int(state.get("size", 0) or 0),
                "chunk_size": int(state.get("chunk_size", self.FILE_CHUNK_SIZE)),
                "purpose": purpose,
            }
            while len(self._completed_file_transfers) > 256:
                self._completed_file_transfers.pop(next(iter(self._completed_file_transfers)))
        self._send_file_complete_ack(from_name, file_id, True, fallback=from_ip)

        if self.on_message_received:
            try:
                self.on_message_received(from_name, content, timestamp, file_id)
            except Exception as e:
                logger.error(f"[MessageService] on_message_received 回调异常: {e}")
        if self.on_file_received:
            try:
                self.on_file_received(from_name, final_path, timestamp)
            except Exception:
                logger.debug("[MessageService] on_file_received 回调异常", exc_info=True)

    def _send_file_complete_ack(
        self, to_name: str, file_id: str, ok: bool, error: str = "", fallback: str = ""
    ):
        payload = {
            "type": self.FILE_COMPLETE_ACK,
            "file_id": file_id,
            "ok": ok,
            "error": error,
        }
        self._send_data_to_friend_with_fallback(to_name, payload, fallback)

    def _handle_file_complete_ack(self, from_ip: str, data: Dict[str, Any]):
        file_id = data.get("file_id", "")
        if not file_id:
            return
        with self._file_lock:
            self._file_complete_results[file_id] = (
                bool(data.get("ok", False)),
                data.get("error", ""),
            )
            event = self._file_complete_events.get(file_id)
            if event:
                event.set()

    # ================================================================== #
    #  离线消息刷新
    # ================================================================== #

    def flush_pending_messages(self, friend_name: str):
        """
        当好友上线时，将所有 pending 消息批量发送。

        典型调用场景：connection_manager 检测到新连接建立后调用此方法。

        Args:
            friend_name: 刚上线的好友名称。
        """
        pending = self.friend_db.get_pending_messages(friend_name)
        if not pending:
            return

        sent_count = 0
        for record in pending:
            try:
                # 重新构建 CHAT_MESSAGE 字典，因为 pending_messages 存储了消息字段
                data = {
                    "type": self.CHAT_MESSAGE,
                    "msg_id": record.get("msg_id", ""),
                    "from_name": record.get("from_name", ""),
                    "to_name": record.get("to_name", ""),
                    "content": record.get("content", ""),
                    "timestamp": record.get("timestamp", ""),
                }
                if self._send_data_to_friend(friend_name, data):
                    sent_count += 1
            except Exception as e:
                logger.error(f"[MessageService] 发送 pending 消息失败: {e}")

        # 清空已发送的 pending 消息
        self.friend_db.clear_pending_messages(friend_name)
        logger.info(
            f"[MessageService] 已向 {friend_name} 补发 {sent_count}/{len(pending)} "
            f"条离线消息"
        )

    # ================================================================== #
    #  心跳机制
    # ================================================================== #

    def _start_heartbeat(self):
        """启动周期性心跳广播。"""
        if not self._running:
            return

        self._send_heartbeat_to_all()

        self._heartbeat_timer = threading.Timer(
            self.HEARTBEAT_INTERVAL, self._start_heartbeat
        )
        self._heartbeat_timer.daemon = True
        self._heartbeat_timer.start()

    def _send_heartbeat_to_all(self):
        """向所有在线好友发送心跳包。"""
        my_profile = self.friend_db.get_my_profile()
        heartbeat_msg = {
            "type": self.HEARTBEAT,
            "name": my_profile.get("name", "Unknown"),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "avatar": self._shared_avatar_reference(my_profile.get("avatar", "")),
            "user_id": my_profile.get("user_id", ""),
        }

        online_friends = self.connection_manager.get_online_friends()
        for friend in online_friends:
            friend_name = self._online_friend_name(friend)
            try:
                self._send_data_to_friend(friend_name, heartbeat_msg)
            except Exception as e:
                logger.debug(f"[MessageService] 心跳发送失败 -> {friend_name}: {e}")

    # ================================================================== #
    #  内部工具方法
    # ================================================================== #

    def _sha256_file(self, path: str) -> str:
        return self.file_store.sha256_file(path)

    def _sha256_bytes(self, data: bytes) -> str:
        return self.file_store.sha256_bytes(data)

    def _safe_filename(self, filename: str) -> str:
        return self.file_store.safe_filename(filename)

    def _unique_receive_path(self, filename: str) -> str:
        return self.file_store.unique_receive_path(filename)

    def _file_message_content(
        self, filename: str, path: str = "", transfer_id: str = "", status: str = "文件"
    ) -> str:
        return encode_file_message(status, filename, path, transfer_id)

    def get_file_final_status(self, file_id: str) -> str:
        with self._file_lock:
            return self._file_final_statuses.pop(file_id, "文件")

    def _unique_avatar_path(self, filename: str, owner_name: str = "", user_id: str = "") -> str:
        return self.file_store.unique_avatar_path(filename, owner_name, user_id)

    def _shared_avatar_reference(self, avatar: str) -> str:
        value = (avatar or "").strip()
        if not value:
            return ""
        if os.path.isabs(value):
            return ""
        if value.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")):
            return get_app_paths().asset_src(value)
        return ""

    def _send_avatar_to_friend(self, friend_name: str) -> bool:
        profile = self.friend_db.get_my_profile()
        avatar_path = (profile.get("avatar") or "").strip()
        if avatar_path and not os.path.isabs(avatar_path):
            candidate = get_app_paths().assets_dir / avatar_path.replace("\\", "/")
            if candidate.is_file():
                avatar_path = str(candidate)
        if not avatar_path or not os.path.isfile(avatar_path):
            return False
        if not avatar_path.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")):
            return False
        return self.send_file(
            friend_name,
            avatar_path,
            purpose="avatar",
            avatar_owner=profile.get("name", ""),
            avatar_user_id=profile.get("user_id", ""),
            require_online=False,
        )

    def _send_card_bg_to_friend(self, friend_name: str) -> bool:
        profile = self.friend_db.get_my_profile()
        card_bg_path = (profile.get("card_bg") or "").strip()
        if card_bg_path and not os.path.isabs(card_bg_path):
            candidate = get_app_paths().assets_dir / card_bg_path.replace("\\", "/")
            if candidate.is_file():
                card_bg_path = str(candidate)
        if not card_bg_path or not os.path.isfile(card_bg_path):
            return False
        if not card_bg_path.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")):
            return False
        return self.send_file(
            friend_name,
            card_bg_path,
            purpose="card_bg",
            avatar_owner=profile.get("name", ""),
            avatar_user_id=profile.get("user_id", ""),
            require_online=False,
        )

    def broadcast_avatar_update(self) -> int:
        """Push the current avatar file to all online friends immediately."""
        sent = 0
        my_name = self.friend_db.get_my_profile().get("name", "")
        for friend in self.connection_manager.get_online_friends():
            friend_name = self._online_friend_name(friend)
            if not friend_name or friend_name == my_name:
                continue
            if self._send_avatar_to_friend(friend_name):
                sent += 1
        return sent

    def _send_data_to_friend(self, friend_name: str, data: Dict[str, Any]) -> bool:
        """
        通过 connection_manager 将字典数据序列化为 JSON 字节并发送给指定好友。

        Args:
            friend_name: 目标好友名称。
            data:        要发送的消息字典。

        Returns:
            True 表示发送成功。
        """
        try:
            json_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
            packed_bytes = Protocol.pack_with_header(json_bytes)
            return self.connection_manager.send_to_friend(friend_name, packed_bytes)
        except Exception as e:
            logger.error(f"[MessageService] 发送给 {friend_name} 失败: {e}")
            return False

    def _send_data_to_friend_with_fallback(
        self, friend_name: str, data: Dict[str, Any], fallback: str = ""
    ) -> bool:
        """Send to a peer by name, falling back to its endpoint/IP if needed."""
        if friend_name and self._send_data_to_friend(friend_name, data):
            return True
        if fallback and fallback != friend_name:
            return self._send_data_to_friend(fallback, data)
        return False

    def add_system_notification(self, title: str, content: str, category: str = "info") -> bool:
        """添加一条系统通知并调用回调刷新 UI。"""
        if self.friend_db:
            ok = self.friend_db.add_system_notification(title, content, category)
            if ok and self.on_notifications_changed:
                try:
                    self.on_notifications_changed()
                except Exception as e:
                    logger.error(f"[MessageService] on_notifications_changed 回调异常: {e}")
            return ok
        return False

    def _online_friend_name(self, friend: Any) -> str:
        if isinstance(friend, dict):
            return friend.get("name", "")
        return str(friend or "")

    def _online_friend_ip(self, friend: Any) -> str:
        if isinstance(friend, dict):
            return friend.get("ip", "")
        record = self.friend_db.get_friend(str(friend or "")) if self.friend_db else None
        return record.get("ip", "") if record else ""

    def _flood_relay(
        self,
        relay_msg: Dict[str, Any],
        exclude_name: str = "",
        exclude_ip: str = "",
    ) -> int:
        """
        将中继消息洪泛发送给所有在线好友（排除指定名称/IP）。

        Args:
            relay_msg:    RELAY_MESSAGE 格式的消息字典。
            exclude_name: 需要排除的好友名称（通常是消息的最终目标或原始发送者）。
            exclude_ip:   需要排除的来源 IP。

        Returns:
            实际发送的好友数量。
        """
        online_friends = self.connection_manager.get_online_friends()
        count = 0
        for friend in online_friends:
            friend_name = self._online_friend_name(friend)
            if friend_name == exclude_name:
                continue
            friend_record = self.friend_db.get_friend(friend_name)
            if friend_record and exclude_ip and friend_record.get("ip", "") == exclude_ip:
                continue
            if self._send_data_to_friend(friend_name, relay_msg):
                count += 1

        return count

    def _relay_chat_to_others(
        self,
        chat_msg: Dict[str, Any],
        exclude_ip: str = "",
        exclude_name: str = "",
    ) -> int:
        """
        将聊天消息包装为 RELAY_MESSAGE 后洪泛给其他在线好友。

        Args:
            chat_msg:     原始 CHAT_MESSAGE 字典.
            exclude_ip:   排除的来源 IP.
            exclude_name: 排除的名称.

        Returns:
            实际中继的好友数量.
        """
        relay_msg = {
            "type": self.RELAY_MESSAGE,
            "relay_hops": 1,
            "original_message": chat_msg,
        }
        return self._flood_relay(
            relay_msg,
            exclude_name=exclude_name,
            exclude_ip=exclude_ip,
        )

    # ================================================================== #
    #  群组与空间动态处理器及发送器 (Gossip & Moments)
    # ================================================================== #

    def _get_friend_name_by_ip(self, ip: str) -> Optional[str]:
        if self.connection_manager:
            for f in self.connection_manager.get_online_friends():
                if self._online_friend_ip(f) == ip:
                    return self._online_friend_name(f)
        return None

    def create_group(self, group_name: str, members: List[str]) -> str:
        group_id = str(uuid.uuid4())
        my_name = self.runtime.device_name
        if my_name not in members:
            members.append(my_name)

        self.friend_db.save_group(group_id, group_name, members, owner=my_name, only_owner_manage=0)

        payload = {
            "type": self.GROUP_CREATE,
            "group_id": group_id,
            "group_name": group_name,
            "members": members,
            "owner": my_name,
            "only_owner_manage": 0,
        }

        for m in members:
            if m != my_name:
                self._send_data_to_friend(m, payload)
        return group_id

    def send_group_chat_message(self, group_id: str, content: str, msg_id: str = "") -> bool:
        group = self.friend_db.get_group(group_id)
        if not group:
            return False

        my_name = self.runtime.device_name
        msg_id = msg_id or str(uuid.uuid4())
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

        self.friend_db.save_group_chat_message(msg_id, group_id, my_name, content, timestamp)

        payload = {
            "type": self.GROUP_CHAT,
            "msg_id": msg_id,
            "group_id": group_id,
            "sender": my_name,
            "content": content,
            "timestamp": timestamp,
        }

        members = group.get("members", [])
        for m in members:
            if m != my_name:
                self._send_data_to_friend(m, payload)
        return True

    def sync_groups_with_friend(self, friend_name: str):
        my_name = self.runtime.device_name
        groups = self.friend_db.get_all_groups()
        for g in groups:
            members = g.get("members", [])
            if friend_name in members and my_name in members:
                history = self.friend_db.get_group_chat_history(g["group_id"], limit=1)
                last_timestamp = history[0]["timestamp"] if history else "1970-01-01 00:00:00"

                payload = {
                    "type": self.GROUP_SYNC_REQ,
                    "group_id": g["group_id"],
                    "last_timestamp": last_timestamp,
                }
                self._send_data_to_friend(friend_name, payload)

    def sync_moments_with_friend(self, friend_name: str):
        my_name = self.runtime.device_name
        payload = {
            "type": self.MOMENTS_SYNC_REQ,
            "sender_name": my_name,
        }
        self._send_data_to_friend(friend_name, payload)

    def publish_moment(self, content: str, media_path: str = "") -> bool:
        my_name = self.runtime.device_name
        post_id = str(uuid.uuid4())
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

        media_data = ""
        if media_path and os.path.exists(media_path):
            try:
                import base64
                with open(media_path, "rb") as f:
                    media_data = base64.b64encode(f.read()).decode("utf-8")
            except Exception:
                pass

        self.friend_db.save_moment(post_id, my_name, content, media_path, timestamp)

        payload = {
            "type": self.MOMENTS_PUBLISH,
            "post_id": post_id,
            "author": my_name,
            "content": content,
            "media_name": os.path.basename(media_path) if media_path else "",
            "media_data": media_data,
            "timestamp": timestamp,
        }

        for friend in self.connection_manager.get_online_friends():
            friend_name = self._online_friend_name(friend)
            if friend_name:
                self._send_data_to_friend(friend_name, payload)
        return True

    def publish_moment_comment(self, post_id: str, content: str) -> bool:
        if not self.friend_db:
            return False
        comment_id = f"comment_{uuid.uuid4().hex}"
        my_name = self.runtime.device_name
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

        ok = self.friend_db.save_moment_comment(comment_id, post_id, my_name, content, timestamp)
        if ok:
            payload = {
                "type": "MOMENT_COMMENT",
                "comment_id": comment_id,
                "post_id": post_id,
                "author": my_name,
                "content": content,
                "timestamp": timestamp,
            }
            for friend in self.connection_manager.get_online_friends():
                friend_name = self._online_friend_name(friend)
                if friend_name:
                    self._send_data_to_friend(friend_name, payload)
            if hasattr(self.runtime, "on_moments_changed") and self.runtime.on_moments_changed:
                self.runtime.on_moments_changed()
            return True
        return False

    def _handle_group_create(self, from_ip: str, data: Dict[str, Any]):
        group_id = data.get("group_id", "")
        group_name = data.get("group_name", "")
        members = data.get("members", [])
        owner = data.get("owner", "")
        only_owner_manage = int(data.get("only_owner_manage", 0) or 0)
        if group_id and group_name:
            self.friend_db.save_group(group_id, group_name, members, owner=owner, only_owner_manage=only_owner_manage)
            if hasattr(self.runtime, "on_friends_changed") and self.runtime.on_friends_changed:
                self.runtime.on_friends_changed()

    def _handle_group_chat(self, from_ip: str, data: Dict[str, Any]):
        msg_id = data.get("msg_id", "")
        group_id = data.get("group_id", "")
        sender = data.get("sender", "")
        content = data.get("content", "")
        timestamp = data.get("timestamp", "")

        if not group_id or not sender:
            return

        if not self.friend_db.get_group(group_id):
            self.friend_db.save_group(group_id, f"群聊_{group_id[:8]}", [sender, self.runtime.device_name])

        self.friend_db.save_group_chat_message(msg_id, group_id, sender, content, timestamp)

        if hasattr(self.runtime, "on_group_message_received") and self.runtime.on_group_message_received:
            self.runtime.on_group_message_received(group_id, sender, content, timestamp)

    def _handle_group_sync_req(self, from_ip: str, data: Dict[str, Any]):
        group_id = data.get("group_id", "")
        last_timestamp = data.get("last_timestamp", "1970-01-01 00:00:00")

        if not group_id:
            return

        # Get messages newer than last_timestamp
        conn = self.friend_db.conn
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM group_chat_history WHERE group_id = ? AND timestamp > ? ORDER BY timestamp ASC",
            (group_id, last_timestamp),
        )
        rows = cursor.fetchall()
        messages = [dict(r) for r in rows]

        friend_name = self._get_friend_name_by_ip(from_ip)
        if friend_name:
            payload = {
                "type": self.GROUP_SYNC_RESP,
                "group_id": group_id,
                "messages": messages,
            }
            self._send_data_to_friend(friend_name, payload)

    def _handle_group_sync_resp(self, from_ip: str, data: Dict[str, Any]):
        group_id = data.get("group_id", "")
        messages = data.get("messages", [])

        updated = False
        for msg in messages:
            msg_id = msg.get("msg_id", "")
            sender = msg.get("sender", "")
            content = msg.get("content", "")
            timestamp = msg.get("timestamp", "")

            if not msg_id or not group_id:
                continue

            if not self.friend_db.has_group_message(msg_id):
                self.friend_db.save_group_chat_message(msg_id, group_id, sender, content, timestamp)
                updated = True

                if hasattr(self.runtime, "on_group_message_received") and self.runtime.on_group_message_received:
                    self.runtime.on_group_message_received(group_id, sender, content, timestamp)

    def _handle_moments_publish(self, from_ip: str, data: Dict[str, Any]):
        post_id = data.get("post_id", "")
        author = data.get("author", "")
        content = data.get("content", "")
        media_name = data.get("media_name", "")
        media_data = data.get("media_data", "")
        timestamp = data.get("timestamp", "")

        if not post_id or not author:
            return

        local_media_path = ""
        if media_name and media_data:
            try:
                import base64
                save_path = os.path.join(self.receive_dir, f"moment_{post_id}_{media_name}")
                with open(save_path, "wb") as f:
                    f.write(base64.b64decode(media_data))
                local_media_path = save_path
            except Exception as e:
                logger.error("保存空间图片失败: %s", e)

        self.friend_db.save_moment(post_id, author, content, local_media_path, timestamp)

        if hasattr(self.runtime, "on_moments_changed") and self.runtime.on_moments_changed:
            self.runtime.on_moments_changed()

    def _handle_moment_comment(self, from_ip: str, data: Dict[str, Any]):
        comment_id = data.get("comment_id")
        post_id = data.get("post_id")
        author = data.get("author")
        content = data.get("content")
        timestamp = data.get("timestamp")
        if comment_id and post_id and author and content and timestamp:
            self.friend_db.save_moment_comment(comment_id, post_id, author, content, timestamp)
            if hasattr(self.runtime, "on_moments_changed") and self.runtime.on_moments_changed:
                self.runtime.on_moments_changed()

    def _handle_moments_sync_req(self, from_ip: str, data: Dict[str, Any]):
        my_name = self.runtime.device_name
        moments = self.friend_db.get_moments(limit=50)
        my_moments = [m for m in moments if m["author"] == my_name]

        posts = []
        for m in my_moments:
            media_path = m.get("media_path", "")
            media_data = ""
            if media_path and os.path.exists(media_path):
                try:
                    import base64
                    with open(media_path, "rb") as f:
                        media_data = base64.b64encode(f.read()).decode("utf-8")
                except Exception:
                    pass
            posts.append({
                "post_id": m["post_id"],
                "author": m["author"],
                "content": m["content"],
                "media_name": os.path.basename(media_path) if media_path else "",
                "media_data": media_data,
                "timestamp": m["timestamp"],
            })

        # Collect all comments for each of our moments
        my_comments = []
        for m in my_moments:
            comments = self.friend_db.get_moment_comments(m["post_id"]) or []
            my_comments.extend(comments)

        payload = {
            "type": self.MOMENTS_SYNC_RESP,
            "posts": posts,
            "comments": my_comments,
            "sender_name": my_name,
        }

        friend_name = data.get("sender_name", "") or self._get_friend_name_by_ip(from_ip)
        if friend_name:
            self._send_data_to_friend(friend_name, payload)

    def _handle_moments_sync_resp(self, from_ip: str, data: Dict[str, Any]):
        posts = data.get("posts", [])
        updated = False

        friend_name = data.get("sender_name", "") or self._get_friend_name_by_ip(from_ip)
        if friend_name and self.friend_db:
            try:
                local_moments = self.friend_db.get_moments(limit=200)
                friend_local_moments = [m for m in local_moments if m.get("author") == friend_name]
                active_post_ids = {p.get("post_id") for p in posts if p.get("post_id")}
                for m in friend_local_moments:
                    pid = m.get("post_id")
                    if pid and pid not in active_post_ids:
                        self.friend_db.delete_moment(pid)
                        updated = True
            except Exception:
                pass

        for p in posts:
            post_id = p.get("post_id", "")
            author = p.get("author", "")
            content = p.get("content", "")
            media_name = p.get("media_name", "")
            media_data = p.get("media_data", "")
            timestamp = p.get("timestamp", "")

            if not post_id or not author:
                continue

            if not self.friend_db.has_moment(post_id):
                local_media_path = ""
                if media_name and media_data:
                    try:
                        import base64
                        save_path = os.path.join(self.receive_dir, f"moment_{post_id}_{media_name}")
                        with open(save_path, "wb") as f:
                            f.write(base64.b64decode(media_data))
                        local_media_path = save_path
                    except Exception:
                        pass

                self.friend_db.save_moment(post_id, author, content, local_media_path, timestamp)
                updated = True

        comments = data.get("comments") or []
        for c in comments:
            cid = c.get("comment_id")
            pid = c.get("post_id")
            cauth = c.get("author")
            ccont = c.get("content")
            cts = c.get("timestamp")
            if cid and pid and cauth and ccont and cts:
                if self.friend_db.save_moment_comment(cid, pid, cauth, ccont, cts):
                    updated = True

        if updated and hasattr(self.runtime, "on_moments_changed") and self.runtime.on_moments_changed:
            self.runtime.on_moments_changed()

    def pause_file_transfer(self, file_id: str) -> bool:
        """Pause an active outgoing transfer without discarding its state."""
        with self._file_lock:
            paused = self.file_transfer.pause_sender(file_id)
        if paused:
            logger.info("[MessageService] 文件传输已暂停: %s", file_id)
        return paused

    def resume_file_transfer(self, file_id: str) -> bool:
        """Resume an outgoing transfer paused by the user."""
        with self._file_lock:
            resumed = self.file_transfer.resume_sender(file_id)
        if resumed:
            logger.info("[MessageService] 文件传输已继续: %s", file_id)
        return resumed

    def cancel_file_transfer(self, file_id: str):
        """取消正在进行的文件发送或接收。"""
        filename = ""
        to_name = ""
        with self._file_lock:
            sender = self.file_transfer.mark_sender_cancelled(file_id)
            if sender:
                filename = sender["filename"]
                to_name = sender["to_name"]

        from_name = ""
        with self._file_lock:
            state = self._incoming_files.pop(file_id, None)
        if state:
            self._close_incoming_handle(state)
            filename = state["filename"]
            from_name = state["from_name"]
            part_path = state["part_path"]
            if os.path.exists(part_path):
                try:
                    os.remove(part_path)
                except Exception:
                    pass

        if to_name:
            cancel_msg = {
                "type": self.FILE_CANCEL,
                "file_id": file_id,
            }
            self._send_data_to_friend(to_name, cancel_msg)
        elif from_name:
            cancel_msg = {
                "type": self.FILE_CANCEL,
                "file_id": file_id,
            }
            self._send_data_to_friend(from_name, cancel_msg)

        try:
            old_content = self.friend_db.get_chat_message_content(file_id)
            if old_content:
                decoded = decode_file_message(old_content, self.receive_dir)
                new_content = encode_file_message(
                    "已取消",
                    decoded.filename,
                    decoded.path,
                    file_id,
                )
                self.friend_db.update_chat_message_content(file_id, new_content)
        except Exception:
            logger.debug("Failed to update database message status on file cancel", exc_info=True)

        if self.on_file_status_changed:
            try:
                self.on_file_status_changed(file_id, "已取消")
            except Exception:
                pass

        logger.info("[MessageService] 用户主动取消了文件传输: %s", filename)
        if hasattr(self.runtime, "on_friends_changed") and self.runtime.on_friends_changed:
            self.runtime.on_friends_changed()

    def _handle_file_cancel(self, from_ip: str, data: Dict[str, Any]):
        """处理对端发来的取消传输通知。"""
        file_id = data.get("file_id", "")
        if not file_id:
            return

        with self._file_lock:
            self.file_transfer.mark_sender_cancelled(file_id)
            self.file_transfer.pop_sender(file_id)

        with self._file_lock:
            state = self._incoming_files.pop(file_id, None)
        if state:
            self._close_incoming_handle(state)
            part_path = state["part_path"]
            if os.path.exists(part_path):
                try:
                    os.remove(part_path)
                except Exception:
                    pass

        try:
            old_content = self.friend_db.get_chat_message_content(file_id)
            if old_content:
                decoded = decode_file_message(old_content, self.receive_dir)
                new_content = encode_file_message(
                    "对方已取消",
                    decoded.filename,
                    decoded.path,
                    file_id,
                )
                self.friend_db.update_chat_message_content(file_id, new_content)
        except Exception:
            logger.debug("Failed to update database message status on file cancel", exc_info=True)

        if self.on_file_status_changed:
            try:
                self.on_file_status_changed(file_id, "对方已取消")
            except Exception:
                pass

        logger.info("[MessageService] 对端已取消文件传输: %s", file_id)

    def _handle_file_decline(self, from_ip: str, data: Dict[str, Any]):
        """对方拒绝了文件传输 — 取消发送。"""
        file_id = data.get("file_id", "")
        if not file_id:
            return
        with self._file_lock:
            self.file_transfer.mark_sender_cancelled(file_id)
            # Also set the complete result to "declined" so the sender's
            # retry loop does not retry.
            self._file_complete_results[file_id] = (False, "对方已拒绝")
            self._file_ack_errors[file_id] = "对方已拒绝"
            event = self._file_complete_events.get(file_id)
            if event:
                event.set()  # wake the sender's retry loop

        # Update database message to "对方已拒绝"
        try:
            old_content = self.friend_db.get_chat_message_content(file_id)
            if old_content:
                decoded = decode_file_message(old_content, self.receive_dir)
                new_content = encode_file_message(
                    "对方已拒绝",
                    decoded.filename,
                    decoded.path,
                    file_id,
                )
                self.friend_db.update_chat_message_content(file_id, new_content)
        except Exception:
            logger.debug("Failed to update database message status on file decline", exc_info=True)

        if self.on_file_status_changed:
            try:
                self.on_file_status_changed(file_id, "对方已拒绝")
            except Exception:
                pass

        logger.info("[MessageService] 对端已取消文件传输: %s", file_id)
        if hasattr(self.runtime, "on_friends_changed") and self.runtime.on_friends_changed:
            self.runtime.on_friends_changed()

    def _handle_file_accept(self, from_ip: str, data: Dict[str, Any]):
        """对方接受了文件传输 — 更新为成功状态。"""
        file_id = data.get("file_id", "")
        if not file_id:
            return

        try:
            old_content = self.friend_db.get_chat_message_content(file_id)
            if old_content:
                decoded = decode_file_message(old_content, self.receive_dir)
                # Only update if the current saved state is "等待对方接受"
                if decoded.status == "等待对方接受":
                    new_content = encode_file_message(
                        "文件",
                        decoded.filename,
                        decoded.path,
                        file_id,
                    )
                    self.friend_db.update_chat_message_content(file_id, new_content)
        except Exception:
            logger.debug("Failed to update database message status on file accept", exc_info=True)

        if self.on_file_status_changed:
            try:
                self.on_file_status_changed(file_id, "文件")
            except Exception:
                pass

    def _handle_file_resume_req(self, from_ip: str, data: Dict[str, Any]):
        """处理断点续传检测请求。"""
        file_id = data.get("file_id", "")
        filename = self._safe_filename(data.get("filename", "received.bin"))
        _sha256 = data.get("sha256", "")
        if not file_id:
            return

        with self._file_lock:
            state = self._incoming_files.get(file_id)
            part_path = state.get("part_path", "") if state else ""
            state_from_name = state.get("from_name", "") if state else ""
        if not part_path:
            candidate = os.path.join(self.receive_dir, filename)
            if os.path.exists(candidate):
                final_path = self._unique_receive_path(filename)
            else:
                final_path = candidate

            import tempfile
            part_path = os.path.join(
                tempfile.gettempdir(),
                f"meeting_in_beiyang_{file_id}_{filename}.part"
            )

        completed_chunks = 0
        if state and state.get("already_complete"):
            completed_chunks = int(state.get("chunk_count", 0) or 0)
        elif state:
            completed_chunks = int(state.get("next_expected", 0) or 0)
            if not state.get("received") and os.path.exists(part_path):
                chunk_size = int(state.get("chunk_size", self.FILE_CHUNK_SIZE))
                completed_chunks = os.path.getsize(part_path) // chunk_size
        elif os.path.exists(part_path):
            existing_size = os.path.getsize(part_path)
            chunk_size = int(
                state.get("chunk_size", self.FILE_CHUNK_SIZE)
                if state else self.FILE_CHUNK_SIZE
            )
            completed_chunks = existing_size // chunk_size

        payload = {
            "type": self.FILE_RESUME_RESP,
            "file_id": file_id,
            "completed_chunks": completed_chunks,
            "supports_ack": True,
            "supports_binary": True,
        }

        friend_name = self._get_friend_name_by_ip(from_ip) or state_from_name
        if friend_name:
            self._send_data_to_friend_with_fallback(friend_name, payload, from_ip)
        elif from_ip:
            self._send_data_to_friend(from_ip, payload)

    def _handle_file_resume_resp(self, from_ip: str, data: Dict[str, Any]):
        """处理断点续传检测回复。"""
        file_id = data.get("file_id", "")
        completed_chunks = int(data.get("completed_chunks", 0) or 0)
        if not file_id:
            return

        with self._file_lock:
            self._file_resume_progress[file_id] = completed_chunks
            self._file_ack_capable[file_id] = bool(data.get("supports_ack", False))
            self._file_binary_capable[file_id] = bool(
                data.get("supports_binary", False)
            )
            event = self._file_resume_events.get(file_id)
            if event:
                event.set()

    def publish_moment_delete(self, post_id: str) -> bool:
        if not self.friend_db:
            return False

        ok = self.friend_db.delete_moment(post_id)
        if not ok:
            return False

        payload = {
            "type": "MOMENT_DELETE",
            "post_id": post_id,
            "sender_name": self.runtime.device_name,
        }
        for f in self.connection_manager.get_online_friends():
            try:
                self._send_data_to_friend(f["name"], payload)
            except Exception:
                pass

        if hasattr(self.runtime, "on_moments_changed") and self.runtime.on_moments_changed:
            self.runtime.on_moments_changed()

        return True

    def _handle_moment_delete(self, from_ip: str, data: Dict[str, Any]):
        post_id = data.get("post_id", "")
        if not post_id:
            return

        sender_name = data.get("sender_name", "") or self._get_friend_name_by_ip(from_ip)
        if self.friend_db:
            try:
                moments = self.friend_db.get_moments(limit=100)
                target = None
                for m in moments:
                    if m.get("post_id") == post_id:
                        target = m
                        break

                if target:
                    author = target.get("author", "")
                    if author == sender_name or not sender_name:
                        self.friend_db.delete_moment(post_id)
                        if hasattr(self.runtime, "on_moments_changed") and self.runtime.on_moments_changed:
                            self.runtime.on_moments_changed()
            except Exception:
                pass
