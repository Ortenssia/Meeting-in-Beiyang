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

import json
import os
import time
import threading
import logging
from typing import Any, Callable, Dict, List, Optional

from core.config import get_app_paths
from core.backend.services.chat_delivery_service import ChatDeliveryService
from core.backend.services.file_store import FileStore
from core.backend.services.file_transfer_state import (
    FILE_CANCEL,
    FILE_RESUME_REQ,
    FILE_RESUME_RESP,
    FILE_DECLINE,
    FILE_ACCEPT,
    FileTransferState,
)
from core.backend.services.file_transfer_service import FileTransferService
from core.backend.services.friend_request_service import FriendRequestService
from core.backend.services.message_relay_service import MessageRelayService
from core.backend.services.network_policy import DEFAULT_NETWORK_POLICY, NetworkPolicy
from core.backend.services.pending_message_flusher import PendingMessageFlusher
from core.backend.services.profile_sync_service import ProfileSyncService
from core.backend.services.social_sync_service import SocialSyncService
from core.backend.shared.file_message import encode_file_message
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
    FRIEND_REQUEST_ACK = "FRIEND_REQUEST_ACK"
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
        self.file_transfers = FileTransferService(self)
        self.friend_requests = FriendRequestService(self)
        self.relay = MessageRelayService(self)
        self.pending_flusher = PendingMessageFlusher(self)
        self.profile_sync = ProfileSyncService(self)
        self.social_sync = SocialSyncService(self)

        self.FILE_CANCEL = FILE_CANCEL
        self.FILE_RESUME_REQ = FILE_RESUME_REQ
        self.FILE_RESUME_RESP = FILE_RESUME_RESP
        self.FILE_DECLINE = FILE_DECLINE
        self.FILE_ACCEPT = FILE_ACCEPT
        self._file_final_statuses: Dict[str, str] = {}
        os.makedirs(self.receive_dir, exist_ok=True)
        os.makedirs(self.avatar_dir, exist_ok=True)
        self.runtime = None
        self.chat_delivery = ChatDeliveryService(self)

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
        return self.chat_delivery.send_message(to_name, content, msg_id)

    def send_friend_request(
        self,
        target_name: str,
        target_ip: str,
        target_port: int = Protocol.DEFAULT_TCP_PORT,
        target_user_id: str = "",
        target_candidate_ips=None,
    ) -> bool:
        return self.friend_requests.send_friend_request(
            target_name,
            target_ip,
            target_port,
            target_user_id,
            target_candidate_ips,
        )

    def send_friend_accept(self, friend_name: str, friend_ip: str = "") -> bool:
        return self.friend_requests.send_friend_accept(friend_name, friend_ip)

    def send_friend_delete(self, friend_name: str, friend_ip: str = "") -> bool:
        return self.friend_requests.send_friend_delete(friend_name, friend_ip)

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
        return self.file_transfers.send_file(
            to_name,
            file_path,
            purpose,
            avatar_owner,
            avatar_user_id,
            require_online,
            file_id,
        )

    def _negotiate_file_resume(
        self, to_name, file_id, filename, sha256, chunk_count, purpose
    ) -> tuple[int, bool, bool]:
        return self.file_transfers._negotiate_file_resume(
            to_name, file_id, filename, sha256, chunk_count, purpose
        )

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
        return self.file_transfers._send_file_chunks(
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
        )

    def _send_binary_chunk_to_friend(
        self, to_name: str, file_id: str, chunk_index: int, chunk: bytes
    ) -> bool:
        return self.file_transfers._send_binary_chunk_to_friend(
            to_name, file_id, chunk_index, chunk
        )

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
        self.file_transfers._emit_file_progress(
            file_id,
            peer_name,
            filename,
            completed,
            total,
            sending,
            force,
            confirmed,
        )

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
            elif msg_type == self.FRIEND_REQUEST_ACK:
                self._handle_friend_request_ack(data)
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
        self.chat_delivery.handle_chat_message(from_ip, data)

    # ------------------------------------------------------------------ #
    #  RELAY_MESSAGE 处理
    # ------------------------------------------------------------------ #

    def _handle_relay_message(self, from_ip: str, data: Dict[str, Any]):
        self.relay.handle_relay_message(from_ip, data)

    def _profile_update_key(self, name: str = "", user_id: str = "") -> str:
        return self.profile_sync.profile_update_key(name, user_id)

    def _my_profile_version(self) -> str:
        return self.profile_sync.my_profile_version()

    def broadcast_profile_update_notice(self) -> int:
        return self.profile_sync.broadcast_profile_update_notice()

    def send_profile_update_notice(self, friend_name: str) -> bool:
        return self.profile_sync.send_profile_update_notice(friend_name)

    def has_pending_profile_update(self, friend_name: str) -> bool:
        return self.profile_sync.has_pending_profile_update(friend_name)

    def request_friend_profile(self, friend_name: str) -> bool:
        return self.profile_sync.request_friend_profile(friend_name)

    def _handle_profile_update_notice(self, from_ip: str, data: Dict[str, Any]):
        self.profile_sync.handle_profile_update_notice(from_ip, data)

    def _handle_profile_sync_req(self, from_ip: str, data: Dict[str, Any]):
        self.profile_sync.handle_profile_sync_req(from_ip, data)

    def _handle_profile_sync_resp(self, from_ip: str, data: Dict[str, Any]):
        self.profile_sync.handle_profile_sync_resp(from_ip, data)

    def _handle_friend_request(self, from_ip: str, data: Dict[str, Any]):
        self.friend_requests.handle_friend_request(from_ip, data)

    def _handle_friend_request_ack(self, data: Dict[str, Any]):
        self.friend_requests.handle_friend_request_ack(data)

    # ------------------------------------------------------------------ #
    #  FRIEND_ACCEPT 处理
    # ------------------------------------------------------------------ #

    def _handle_friend_accept(self, from_ip: str, data: Dict[str, Any]):
        self.friend_requests.handle_friend_accept(from_ip, data)

    # ------------------------------------------------------------------ #
    #  FRIEND_DELETE 处理
    # ------------------------------------------------------------------ #

    def _handle_friend_delete(self, from_ip: str, data: Dict[str, Any]):
        self.friend_requests.handle_friend_delete(from_ip, data)

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
        self.file_transfers.handle_file_offer(from_ip, data)

    def accept_file_offer(self, file_id: str) -> bool:
        return self.file_transfers.accept_file_offer(file_id)

    def decline_file_offer(self, file_id: str) -> bool:
        return self.file_transfers.decline_file_offer(file_id)

    def _accept_file_offer_internal(self, from_ip: str, data: Dict[str, Any]):
        self.file_transfers._accept_file_offer_internal(from_ip, data)

    @staticmethod
    def _close_incoming_handle(state):
        FileTransferService._close_incoming_handle(state)

    def _handle_file_chunk(self, from_ip: str, data: Dict[str, Any]):
        self.file_transfers.handle_file_chunk(from_ip, data)

    def _send_file_chunk_ack(
        self, state, file_id: str, next_expected: int = 0, ok: bool = True, error: str = ""
    ):
        self.file_transfers._send_file_chunk_ack(
            state, file_id, next_expected, ok, error
        )

    def _handle_file_chunk_ack(self, from_ip: str, data: Dict[str, Any]):
        self.file_transfers.handle_file_chunk_ack(from_ip, data)

    def _handle_file_complete(self, from_ip: str, data: Dict[str, Any]):
        self.file_transfers.handle_file_complete(from_ip, data)

    def _finalise_incoming_file(
        self, file_id: str, data: Dict[str, Any] = None
    ):
        self.file_transfers._finalise_incoming_file(file_id, data)

    def _send_file_complete_ack(
        self, to_name: str, file_id: str, ok: bool, error: str = "", fallback: str = ""
    ):
        self.file_transfers._send_file_complete_ack(
            to_name, file_id, ok, error, fallback
        )

    def _handle_file_complete_ack(self, from_ip: str, data: Dict[str, Any]):
        self.file_transfers.handle_file_complete_ack(from_ip, data)

    # ================================================================== #
    #  离线消息刷新
    # ================================================================== #

    def flush_pending_messages(self, friend_name: str):
        self.pending_flusher.flush_pending_messages(friend_name)

    # ================================================================== #
    #  心跳机制
    # ================================================================== #

    def _start_heartbeat(self):
        self.relay.start_heartbeat()

    def _send_heartbeat_to_all(self):
        self.relay.send_heartbeat_to_all()

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
        return self.file_transfers.get_file_final_status(file_id)

    def _unique_avatar_path(self, filename: str, owner_name: str = "", user_id: str = "") -> str:
        return self.file_store.unique_avatar_path(filename, owner_name, user_id)

    def _shared_avatar_reference(self, avatar: str) -> str:
        return self.profile_sync.shared_avatar_reference(avatar)

    def _send_avatar_to_friend(self, friend_name: str) -> bool:
        return self.profile_sync.send_avatar_to_friend(friend_name)

    def _send_card_bg_to_friend(self, friend_name: str) -> bool:
        return self.profile_sync.send_card_bg_to_friend(friend_name)

    def broadcast_avatar_update(self) -> int:
        return self.profile_sync.broadcast_avatar_update()

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
        return self.relay.online_friend_name(friend)

    def _online_friend_ip(self, friend: Any) -> str:
        return self.relay.online_friend_ip(friend)

    def _flood_relay(
        self,
        relay_msg: Dict[str, Any],
        exclude_name: str = "",
        exclude_ip: str = "",
    ) -> int:
        return self.relay.flood_relay(relay_msg, exclude_name=exclude_name, exclude_ip=exclude_ip)

    def _relay_chat_to_others(
        self,
        chat_msg: Dict[str, Any],
        exclude_ip: str = "",
        exclude_name: str = "",
    ) -> int:
        return self.relay.relay_chat_to_others(chat_msg, exclude_ip=exclude_ip, exclude_name=exclude_name)

    def _get_friend_name_by_ip(self, ip: str) -> Optional[str]:
        if self.connection_manager:
            for f in self.connection_manager.get_online_friends():
                if self._online_friend_ip(f) == ip:
                    return self._online_friend_name(f)
        return None

    def create_group(self, group_name: str, members: List[str]) -> str:
        return self.social_sync.create_group(group_name, members)

    def send_group_chat_message(self, group_id: str, content: str, msg_id: str = "") -> bool:
        return self.social_sync.send_group_chat_message(group_id, content, msg_id)

    def sync_groups_with_friend(self, friend_name: str):
        self.social_sync.sync_groups_with_friend(friend_name)

    def sync_moments_with_friend(self, friend_name: str):
        self.social_sync.sync_moments_with_friend(friend_name)

    def publish_moment(self, content: str, media_path: str = "") -> bool:
        return self.social_sync.publish_moment(content, media_path)

    def publish_moment_comment(self, post_id: str, content: str) -> bool:
        return self.social_sync.publish_moment_comment(post_id, content)

    def _handle_group_create(self, from_ip: str, data: Dict[str, Any]):
        self.social_sync.handle_group_create(from_ip, data)

    def _handle_group_chat(self, from_ip: str, data: Dict[str, Any]):
        self.social_sync.handle_group_chat(from_ip, data)

    def _handle_group_sync_req(self, from_ip: str, data: Dict[str, Any]):
        self.social_sync.handle_group_sync_req(from_ip, data)

    def _handle_group_sync_resp(self, from_ip: str, data: Dict[str, Any]):
        self.social_sync.handle_group_sync_resp(from_ip, data)

    def _handle_moments_publish(self, from_ip: str, data: Dict[str, Any]):
        self.social_sync.handle_moments_publish(from_ip, data)

    def _handle_moment_comment(self, from_ip: str, data: Dict[str, Any]):
        self.social_sync.handle_moment_comment(from_ip, data)

    def _handle_moments_sync_req(self, from_ip: str, data: Dict[str, Any]):
        self.social_sync.handle_moments_sync_req(from_ip, data)

    def _handle_moments_sync_resp(self, from_ip: str, data: Dict[str, Any]):
        self.social_sync.handle_moments_sync_resp(from_ip, data)

    def pause_file_transfer(self, file_id: str) -> bool:
        return self.file_transfers.pause_file_transfer(file_id)

    def resume_file_transfer(self, file_id: str) -> bool:
        return self.file_transfers.resume_file_transfer(file_id)

    def cancel_file_transfer(self, file_id: str):
        self.file_transfers.cancel_file_transfer(file_id)

    def _handle_file_cancel(self, from_ip: str, data: Dict[str, Any]):
        self.file_transfers.handle_file_cancel(from_ip, data)

    def _handle_file_decline(self, from_ip: str, data: Dict[str, Any]):
        self.file_transfers.handle_file_decline(from_ip, data)

    def _handle_file_accept(self, from_ip: str, data: Dict[str, Any]):
        self.file_transfers.handle_file_accept(from_ip, data)

    def _handle_file_resume_req(self, from_ip: str, data: Dict[str, Any]):
        self.file_transfers.handle_file_resume_req(from_ip, data)

    def _handle_file_resume_resp(self, from_ip: str, data: Dict[str, Any]):
        self.file_transfers.handle_file_resume_resp(from_ip, data)

    def publish_moment_delete(self, post_id: str) -> bool:
        return self.social_sync.publish_moment_delete(post_id)

    def _handle_moment_delete(self, from_ip: str, data: Dict[str, Any]):
        self.social_sync.handle_moment_delete(from_ip, data)
