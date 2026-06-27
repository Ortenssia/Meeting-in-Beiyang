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

try:
    from ..utils.protocol import Protocol
except ImportError:
    from utils.protocol import Protocol

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
    FILE_OFFER = "FILE_OFFER"
    FILE_CHUNK = "FILE_CHUNK"
    FILE_COMPLETE = "FILE_COMPLETE"

    # 洪泛中继最大跳数，防止无限传播
    MAX_RELAY_HOPS = 3

    # 心跳间隔（秒）
    HEARTBEAT_INTERVAL = 15
    FILE_CHUNK_SIZE = 48 * 1024

    def __init__(self, connection_manager, friend_db, receive_dir: str = "assets/received_files"):
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
        self.receive_dir = receive_dir

        # 回调函数（由上层 App 或 Screen 绑定）
        self.on_message_received: Optional[Callable[[str, str, str], None]] = None
        self.on_friend_request: Optional[Callable[..., None]] = None
        self.on_friend_accepted: Optional[Callable[[str, str], None]] = None
        self.on_file_received: Optional[Callable[[str, str, str], None]] = None
        self.on_file_progress: Optional[Callable[[str, str, int, int], None]] = None

        # 心跳定时器
        self._heartbeat_timer: Optional[threading.Timer] = None
        self._running = False

        # 已处理的中继消息 ID 集合（内存级去重，限制大小）
        self._processed_relay_ids: set = set()
        self._relay_id_lock = threading.Lock()
        self._MAX_RELAY_CACHE = 5000

        self._incoming_files: Dict[str, Dict[str, Any]] = {}
        self._file_lock = threading.Lock()
        os.makedirs(self.receive_dir, exist_ok=True)

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

    def send_message(self, to_name: str, content: str) -> bool:
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
        msg_id = str(uuid.uuid4())

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

        request_msg = {
            "type": self.FRIEND_REQUEST,
            "msg_id": str(uuid.uuid4()),
            "profile": my_profile,
            "conditions": conditions,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        }

        # 尝试通过连接管理器直接发送
        if self.connection_manager.is_friend_online(target_name):
            sent = self._send_data_to_friend(target_name, request_msg)
            if sent:
                self.friend_db.upsert_friend_request(
                    name=target_name,
                    ip=target_ip,
                    port=target_port,
                    direction="outgoing",
                    status="pending",
                    user_id=target_user_id,
                    msg_id=request_msg["msg_id"],
                )
            return sent

        # 如果尚未建立连接，尝试先连接再发送
        try:
            self.connection_manager.connect_to_friend(target_ip, target_port, target_name)
            sent = self._send_data_to_friend(target_name, request_msg)
            if sent:
                self.friend_db.upsert_friend_request(
                    name=target_name,
                    ip=target_ip,
                    port=target_port,
                    direction="outgoing",
                    status="pending",
                    user_id=target_user_id,
                    msg_id=request_msg["msg_id"],
                )
            return sent
        except Exception as e:
            logger.error(f"[MessageService] 发送好友请求失败: {e}")
            return False

    def send_friend_accept(self, friend_name: str, friend_ip: str = "") -> bool:
        """
        接受好友请求后，向对方发送 FRIEND_ACCEPT 消息。

        Args:
            friend_name: 已接受的好友名称。
            friend_ip:   对方 IP。入站好友申请尚未按名字登记连接时，用它兜底发送。

        Returns:
            True 表示接受消息已发送。
        """
        my_profile = self.friend_db.get_my_profile()
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

        if self._send_data_to_friend(friend_name, accept_msg):
            return True
        if friend_ip:
            port = friend.get("port", Protocol.DEFAULT_TCP_PORT)
            endpoint = f"{friend_ip}:{port}" if port else friend_ip
            return self._send_data_to_friend(endpoint, accept_msg)
        return False

    def send_file(self, to_name: str, file_path: str) -> bool:
        """
        向在线好友发送文件。

        文件传输只走直连 TCP，不进入离线中继队列；这样可以避免大文件在 P2P
        洪泛网络里被重复缓存和转发。
        """
        if not file_path or not os.path.isfile(file_path):
            logger.warning("[MessageService] 文件不存在: %s", file_path)
            return False
        if not self.connection_manager.is_friend_online(to_name):
            logger.warning("[MessageService] 好友不在线，无法发送文件: %s", to_name)
            return False

        my_profile = self.friend_db.get_my_profile()
        my_name = my_profile.get("name", "Unknown")
        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        file_id = str(uuid.uuid4())
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
        }
        if not self._send_data_to_friend(to_name, offer):
            return False

        with open(file_path, "rb") as src:
            for index, chunk in enumerate(iter(lambda: src.read(self.FILE_CHUNK_SIZE), b"")):
                chunk_msg = {
                    "type": self.FILE_CHUNK,
                    "file_id": file_id,
                    "chunk_index": index,
                    "data_b64": base64.b64encode(chunk).decode("ascii"),
                }
                if not self._send_data_to_friend(to_name, chunk_msg):
                    logger.warning("[MessageService] 文件分块发送失败: %s #%s", filename, index)
                    return False
                if self.on_file_progress:
                    try:
                        self.on_file_progress(to_name, filename, index + 1, chunk_count)
                    except Exception:
                        logger.debug("[MessageService] on_file_progress 回调异常", exc_info=True)

        complete = {
            "type": self.FILE_COMPLETE,
            "file_id": file_id,
            "from_name": my_name,
            "to_name": to_name,
            "filename": filename,
            "size": file_size,
            "sha256": sha256,
            "timestamp": timestamp,
        }
        if not self._send_data_to_friend(to_name, complete):
            return False

        self.friend_db.save_chat_message(
            from_name=my_name,
            to_name=to_name,
            content=f"[文件] {filename}",
            timestamp=timestamp,
            msg_id=file_id,
        )
        return True

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

        if msg_type == self.CHAT_MESSAGE:
            self._handle_chat_message(from_ip, data)
        elif msg_type == self.RELAY_MESSAGE:
            self._handle_relay_message(from_ip, data)
        elif msg_type == self.FRIEND_REQUEST:
            self._handle_friend_request(from_ip, data)
        elif msg_type == self.FRIEND_ACCEPT:
            self._handle_friend_accept(from_ip, data)
        elif msg_type == self.HEARTBEAT:
            self._handle_heartbeat(from_ip, data)
        elif msg_type == self.FILE_OFFER:
            self._handle_file_offer(from_ip, data)
        elif msg_type == self.FILE_CHUNK:
            self._handle_file_chunk(from_ip, data)
        elif msg_type == self.FILE_COMPLETE:
            self._handle_file_complete(from_ip, data)
        else:
            logger.warning(f"[MessageService] 未知消息类型: {msg_type}")

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
                    self.on_message_received(from_name, content, timestamp)
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
            )
            # 发送 ACCEPT 回执
            self.send_friend_accept(sender_name, from_ip)
            logger.info(f"[MessageService] 自动接受好友请求: {sender_name}")

            if self.on_friend_accepted:
                try:
                    self.on_friend_accepted(sender_name, from_ip)
                except Exception as e:
                    logger.error(f"[MessageService] on_friend_accepted 回调异常: {e}")
        else:
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
            # 需要人工审核
            logger.info(
                f"[MessageService] 好友请求待审核: {sender_name} "
                f"(条件匹配={conditions_matched})"
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
            )
            logger.info(f"[MessageService] 好友 {friend_name} 已存在，更新 IP")
        else:
            self.friend_db.add_friend(
                name=friend_name,
                ip=from_ip,
                port=port,
                tags=tags,
                category="朋友",
                bio=bio,
                user_id=friend_user_id,
                status="accepted",
            )
            logger.info(f"[MessageService] 好友已添加: {friend_name} ({from_ip})")

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
            if old_ip != from_ip or (new_port and old_port != new_port):
                self.friend_db.add_friend(
                    name=friend_name,
                    ip=from_ip,
                    port=new_port or old_port,
                    tags=friend.get("tags", []),
                    category=friend.get("category", "朋友"),
                    bio=friend.get("bio", ""),
                    user_id=friend.get("user_id", ""),
                    status=friend.get("status", "accepted"),
                )
                logger.info(
                    f"[MessageService] 心跳更新 {friend_name} 地址: "
                    f"{old_ip}:{old_port} -> {from_ip}:{new_port or old_port}"
                )

    # ------------------------------------------------------------------ #
    #  FILE_* 处理
    # ------------------------------------------------------------------ #

    def _handle_file_offer(self, from_ip: str, data: Dict[str, Any]):
        """接收文件元信息并创建临时接收状态。"""
        my_name = self.friend_db.get_my_profile().get("name", "")
        to_name = data.get("to_name", "")
        if to_name and to_name != my_name:
            return

        file_id = data.get("file_id", "")
        from_name = data.get("from_name", "")
        if not file_id or not from_name:
            return

        filename = self._safe_filename(data.get("filename", "received.bin"))
        final_path = self._unique_receive_path(filename)
        part_path = final_path + ".part"

        with self._file_lock:
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
                "received": set(),
            }

        os.makedirs(os.path.dirname(final_path), exist_ok=True)
        with open(part_path, "wb"):
            pass
        logger.info("[MessageService] 准备接收文件 %s from %s", filename, from_name)

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
            raw = base64.b64decode(data.get("data_b64", "").encode("ascii"))
        except Exception:
            logger.warning("[MessageService] 文件分块解析失败: %s", file_id)
            return

        if index < 0:
            return

        with self._file_lock:
            offset = index * int(state["chunk_size"])
            with open(state["part_path"], "r+b") as dst:
                dst.seek(offset)
                dst.write(raw)
            state["received"].add(index)
            received_count = len(state["received"])
            chunk_count = int(state.get("chunk_count", 0) or 0)

        if self.on_file_progress:
            try:
                self.on_file_progress(
                    state.get("from_name", ""),
                    state.get("filename", ""),
                    received_count,
                    chunk_count,
                )
            except Exception:
                logger.debug("[MessageService] on_file_progress 回调异常", exc_info=True)

    def _handle_file_complete(self, from_ip: str, data: Dict[str, Any]):
        """完成文件接收、校验并写入聊天记录。"""
        my_name = self.friend_db.get_my_profile().get("name", "")
        file_id = data.get("file_id", "")
        if not file_id:
            return

        with self._file_lock:
            state = self._incoming_files.pop(file_id, None)
        if not state:
            logger.warning("[MessageService] 收到未知文件完成通知: %s", file_id)
            return

        part_path = state["part_path"]
        final_path = state["final_path"]
        expected_count = int(state.get("chunk_count", 0) or 0)
        if expected_count and len(state["received"]) < expected_count:
            logger.warning("[MessageService] 文件未收齐: %s", state["filename"])
            return

        expected_hash = data.get("sha256") or state.get("sha256", "")
        if expected_hash and self._sha256_file(part_path) != expected_hash:
            logger.warning("[MessageService] 文件校验失败: %s", state["filename"])
            return

        os.replace(part_path, final_path)
        from_name = data.get("from_name") or state.get("from_name", "")
        timestamp = data.get("timestamp") or state.get("timestamp", time.strftime("%Y-%m-%d %H:%M:%S"))
        filename = state.get("filename", os.path.basename(final_path))
        content = f"[文件] {filename}"

        self.friend_db.save_chat_message(
            from_name=from_name,
            to_name=my_name,
            content=content,
            timestamp=timestamp,
            msg_id=file_id,
        )
        logger.info("[MessageService] 文件接收完成: %s", final_path)

        if self.on_message_received:
            try:
                self.on_message_received(from_name, content, timestamp)
            except Exception as e:
                logger.error(f"[MessageService] on_message_received 回调异常: {e}")
        if self.on_file_received:
            try:
                self.on_file_received(from_name, final_path, timestamp)
            except Exception:
                logger.debug("[MessageService] on_file_received 回调异常", exc_info=True)

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
        }

        online_friends = self.connection_manager.get_online_friends()
        for friend in online_friends:
            friend_name = friend["name"] if isinstance(friend, dict) else friend
            try:
                self._send_data_to_friend(friend_name, heartbeat_msg)
            except Exception as e:
                logger.debug(f"[MessageService] 心跳发送失败 -> {friend_name}: {e}")

    # ================================================================== #
    #  内部工具方法
    # ================================================================== #

    def _sha256_file(self, path: str) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _sha256_bytes(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _safe_filename(self, filename: str) -> str:
        name = os.path.basename(filename or "received.bin").strip()
        if not name:
            name = "received.bin"
        return "".join(ch if ch not in '<>:"/\\|?*' else "_" for ch in name)

    def _unique_receive_path(self, filename: str) -> str:
        base, ext = os.path.splitext(filename)
        candidate = os.path.join(self.receive_dir, filename)
        index = 1
        while os.path.exists(candidate) or os.path.exists(candidate + ".part"):
            candidate = os.path.join(self.receive_dir, f"{base}_{index}{ext}")
            index += 1
        return candidate

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
            friend_name = friend["name"] if isinstance(friend, dict) else friend
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
