"""Friend request protocol handling.

This module owns the FRIEND_REQUEST / FRIEND_ACCEPT / FRIEND_DELETE flow.
It is intentionally thin around the existing MessageService primitives so the
first extraction keeps behavior stable while removing relationship protocol
state from the general message/file relay service.
"""

import inspect
import logging
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from core.backend.shared.protocol import Protocol


logger = logging.getLogger(__name__)


class FriendRequestService:
    """Handle friend request send/receive/ack/delete protocol messages."""

    FRIEND_REQUEST = "FRIEND_REQUEST"
    FRIEND_ACCEPT = "FRIEND_ACCEPT"
    FRIEND_REQUEST_ACK = "FRIEND_REQUEST_ACK"

    def __init__(self, owner):
        self.owner = owner
        self._ack_events: Dict[str, threading.Event] = {}
        self._ack_lock = threading.Lock()
        self.udp_friend_request_sender: Optional[
            Callable[[List[str], Dict[str, Any]], bool]
        ] = None

    @property
    def friend_db(self):
        return self.owner.friend_db

    @property
    def connection_manager(self):
        return self.owner.connection_manager

    def send_friend_request(
        self,
        target_name: str,
        target_ip: str,
        target_port: int = Protocol.DEFAULT_TCP_PORT,
        target_user_id: str = "",
        target_candidate_ips=None,
    ) -> bool:
        my_profile = self.friend_db.get_my_profile()
        my_profile["avatar"] = self.owner._shared_avatar_reference(
            my_profile.get("avatar", "")
        )
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
            logger.info("跳过向自己发送好友请求: %s", target_name)
            return False

        relationship = self.friend_db.get_relationship_status(
            user_id=target_user_id,
            name=target_name,
            ip=target_ip,
            port=target_port,
        )
        if relationship in ("pending_sent", "pending_received", "accepted"):
            logger.info(
                "%s 关系状态为 %s，跳过重复好友请求",
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

        def candidate_targets():
            seen = set()
            endpoint = f"{target_ip}:{target_port}" if target_ip and target_port else target_ip
            for candidate in (target_name, endpoint, target_ip):
                if candidate and candidate not in seen:
                    seen.add(candidate)
                    yield candidate

        def mark_sent(send_target: str):
            self.friend_db.upsert_friend_request(
                name=target_name,
                ip=target_ip,
                port=target_port,
                direction="outgoing",
                status="pending",
                user_id=target_user_id,
                msg_id=request_msg["msg_id"],
            )
            self.owner._send_avatar_to_friend(send_target)

        def prepare_ack_wait() -> threading.Event:
            event = threading.Event()
            with self._ack_lock:
                self._ack_events[request_msg["msg_id"]] = event
            return event

        def clear_ack_wait():
            with self._ack_lock:
                self._ack_events.pop(request_msg["msg_id"], None)

        def deliver_once() -> bool:
            for send_target in candidate_targets():
                ack_event = prepare_ack_wait()
                if self.owner._send_data_to_friend(send_target, request_msg):
                    if ack_event.wait(1.5):
                        mark_sent(send_target)
                        clear_ack_wait()
                        return True
                    logger.warning(
                        "好友请求已写入 socket 但未收到到达回执: %s -> %s",
                        my_name,
                        send_target,
                    )
                    mark_sent(send_target)
                    clear_ack_wait()
                    return True
                clear_ack_wait()
            return False

        def deliver_udp_fallback() -> bool:
            sender = self.udp_friend_request_sender
            if not sender:
                return False
            targets = []
            seen = set()
            for ip in [target_ip, *target_candidate_ips]:
                if ip and ip not in seen:
                    seen.add(ip)
                    targets.append(ip)
            if not targets:
                return False
            if sender(targets, request_msg):
                logger.info(
                    "已通过 UDP 兜底发送好友请求: %s -> %s",
                    my_name,
                    target_name,
                )
                mark_sent(target_ip)
                return True
            return False

        if self.connection_manager.is_friend_online(target_name) and deliver_once():
            return True

        # Try UDP in parallel with TCP — UDP is instant (no handshake),
        # so it should win when the PC firewall blocks TCP. The winner
        # delivers the friend request; the loser is ignored.
        udp_started_event = threading.Event()
        udp_result = [False]

        def _try_udp():
            udp_result[0] = deliver_udp_fallback()
            udp_started_event.set()

        udp_thread = threading.Thread(target=_try_udp, daemon=True)
        udp_thread.start()
        # Give UDP a tiny head start so the user sees sub-second response
        # when the PC is reachable via UDP.
        udp_started_event.wait(0.15)

        try:
            connect_ips = []
            seen_ips = set()
            for ip in [target_ip, *target_candidate_ips]:
                if ip and ip not in seen_ips:
                    seen_ips.add(ip)
                    connect_ips.append(ip)
            connected = False
            for connect_ip in connect_ips:
                if udp_result[0]:
                    return True
                if self.connection_manager.connect_to_friend(connect_ip, target_port, target_name):
                    connected = True
                    if connect_ip != target_ip:
                        target_ip = connect_ip
                    break
            if not connected:
                udp_thread.join(timeout=2.0)
                return udp_result[0]
            deadline = time.time() + 2.0
            while time.time() < deadline:
                if deliver_once():
                    return True
                time.sleep(0.1)
            return deliver_once() or deliver_udp_fallback()
        except Exception as e:
            logger.error("发送好友请求失败: %s", e)
            return deliver_udp_fallback()

    def send_friend_accept(self, friend_name: str, friend_ip: str = "") -> bool:
        my_profile = self.friend_db.get_my_profile()
        my_profile["avatar"] = self.owner._shared_avatar_reference(
            my_profile.get("avatar", "")
        )
        my_profile["tcp_port"] = getattr(
            self.connection_manager, "tcp_port", Protocol.DEFAULT_TCP_PORT
        )
        friend = self.friend_db.get_friend(friend_name)
        if not friend:
            logger.warning("好友 %s 不存在", friend_name)
            return False

        accept_msg = {
            "type": self.FRIEND_ACCEPT,
            "msg_id": str(uuid.uuid4()),
            "profile": my_profile,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        }
        port = int(friend.get("port", Protocol.DEFAULT_TCP_PORT) or Protocol.DEFAULT_TCP_PORT)
        target_ip = friend_ip or friend.get("ip", "")

        if self.owner._send_data_to_friend(friend_name, accept_msg):
            self.owner._send_avatar_to_friend(friend_name)
            return True

        if target_ip:
            endpoint = f"{target_ip}:{port}" if port else target_ip
            if self.owner._send_data_to_friend(endpoint, accept_msg):
                self.owner._send_avatar_to_friend(endpoint)
                return True

        if target_ip:
            try:
                logger.info(
                    "无现有连接可发送 FRIEND_ACCEPT，尝试主动连接 %s:%s",
                    target_ip,
                    port,
                )
                conn_ok = self.connection_manager.connect_to_friend(
                    target_ip, port, friend_name
                )
                if conn_ok:
                    time.sleep(0.3)
                    if self.owner._send_data_to_friend(friend_name, accept_msg):
                        self.owner._send_avatar_to_friend(friend_name)
                        return True
                    endpoint = f"{target_ip}:{port}" if port else target_ip
                    if self.owner._send_data_to_friend(endpoint, accept_msg):
                        self.owner._send_avatar_to_friend(endpoint)
                        return True
            except Exception as e:
                logger.error("主动连接 %s:%s 失败: %s", target_ip, port, e)

        logger.warning("无法发送 FRIEND_ACCEPT 给 %s", friend_name)
        return False

    def send_friend_delete(self, friend_name: str, friend_ip: str = "") -> bool:
        friend = self.friend_db.get_friend(friend_name)
        if not friend:
            logger.warning("找不到好友资料，无法发送删除通知 [%s]", friend_name)
            return False

        profile = self.friend_db.get_my_profile()
        delete_msg = {
            "type": Protocol.FRIEND_DELETE,
            "msg_id": str(uuid.uuid4()),
            "profile": {
                "user_id": profile.get("user_id", ""),
                "name": profile.get("name", "Unknown"),
            },
        }
        port = int(friend.get("port", Protocol.DEFAULT_TCP_PORT) or Protocol.DEFAULT_TCP_PORT)
        target_ip = friend_ip or friend.get("ip", "")

        logger.info("尝试发送 FRIEND_DELETE 通知给 %s", friend_name)
        if self.owner._send_data_to_friend(friend_name, delete_msg):
            return True
        if target_ip:
            endpoint = f"{target_ip}:{port}" if port else target_ip
            if self.owner._send_data_to_friend(endpoint, delete_msg):
                return True
        if target_ip:
            try:
                conn_ok = self.connection_manager.connect_to_friend(
                    target_ip, port, friend_name
                )
                if conn_ok:
                    time.sleep(0.3)
                    if self.owner._send_data_to_friend(friend_name, delete_msg):
                        return True
            except Exception as e:
                logger.error(
                    "发送删除通知时主动连接 %s:%s 失败: %s",
                    target_ip,
                    port,
                    e,
                )
        return False

    def handle_friend_request(self, from_ip: str, data: Dict[str, Any]):
        profile = data.get("profile", {})
        sender_name = profile.get("name", "Unknown")
        sender_user_id = profile.get("user_id", "")
        msg_id = data.get("msg_id", "")
        sender_port = int(
            profile.get("tcp_port", Protocol.DEFAULT_TCP_PORT)
            or Protocol.DEFAULT_TCP_PORT
        )

        def send_request_ack():
            if not msg_id:
                return
            ack_msg = {
                "type": self.FRIEND_REQUEST_ACK,
                "request_msg_id": msg_id,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            }
            if sender_name:
                if self.owner._send_data_to_friend_with_fallback(sender_name, ack_msg, from_ip):
                    return
            self.owner._send_data_to_friend(from_ip, ack_msg)

        if msg_id and self.friend_db.check_msg_id(msg_id):
            send_request_ack()
            return
        if msg_id:
            self.friend_db.record_msg_id(msg_id)

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
                avatar=self.owner._shared_avatar_reference(profile.get("avatar", "")),
            )
            self.send_friend_accept(sender_name, from_ip)
            logger.info("%s 已是好友，已补发确认回执", sender_name)
            return

        conditions_matched = self.friend_db.check_conditions_match(profile)
        friend_conditions = self.friend_db.get_friend_conditions()
        auto_accept = friend_conditions.get("auto_accept", False)

        if auto_accept and conditions_matched:
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
                avatar=self.owner._shared_avatar_reference(profile.get("avatar", "")),
            )
            self.send_friend_accept(sender_name, from_ip)
            logger.info("自动接受好友请求: %s", sender_name)
            self.owner.add_system_notification(
                title="好友申请通过 🤝",
                content=f"已自动同意「{sender_name}」的好意申请，你们现在可以开始聊天了！",
                category="success",
            )
            if self.owner.on_friend_accepted:
                try:
                    self.owner.on_friend_accepted(sender_name, from_ip)
                except Exception as e:
                    logger.error("on_friend_accepted 回调异常: %s", e)
            return

        existing_req = self.friend_db.get_friend_request(
            user_id=sender_user_id, name=sender_name
        )
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
        send_request_ack()
        logger.info(
            "好友请求待审核: %s (条件匹配=%s, 重复=%s)",
            sender_name,
            conditions_matched,
            is_already_pending,
        )
        self.owner.add_system_notification(
            title="新好友申请 👤",
            content=f"收到来自「{sender_name}」的好友申请，快来同意吧！",
            category="friend_request",
        )
        if self.owner.on_friend_request:
            try:
                profile = dict(profile)
                profile.setdefault("ip", from_ip)
                try:
                    param_count = len(inspect.signature(self.owner.on_friend_request).parameters)
                except (TypeError, ValueError):
                    param_count = 2
                if param_count >= 3:
                    self.owner.on_friend_request(profile, conditions_matched, from_ip)
                else:
                    self.owner.on_friend_request(profile, conditions_matched)
            except Exception as e:
                logger.error("on_friend_request 回调异常: %s", e)

    def handle_friend_request_ack(self, data: Dict[str, Any]):
        request_msg_id = data.get("request_msg_id", "")
        if not request_msg_id:
            return
        with self._ack_lock:
            event = self._ack_events.get(request_msg_id)
        if event:
            event.set()

    def handle_friend_accept(self, from_ip: str, data: Dict[str, Any]):
        profile = data.get("profile", {})
        friend_name = profile.get("name", "Unknown")
        friend_user_id = profile.get("user_id", "")
        msg_id = data.get("msg_id", "")

        if msg_id and self.friend_db.check_msg_id(msg_id):
            return
        if msg_id:
            self.friend_db.record_msg_id(msg_id)

        tags = profile.get("tags", [])
        bio = profile.get("bio", "")
        port = int(profile.get("tcp_port", Protocol.DEFAULT_TCP_PORT) or Protocol.DEFAULT_TCP_PORT)
        existing = (
            self.friend_db.get_friend_by_user_id(friend_user_id)
            or self.friend_db.get_friend(friend_name)
        )
        if existing:
            self.friend_db.add_friend(
                name=friend_name,
                ip=from_ip,
                port=port,
                tags=tags,
                category=existing.get("category", "朋友"),
                bio=bio,
                user_id=friend_user_id or existing.get("user_id", ""),
                status="accepted",
                avatar=self.owner._shared_avatar_reference(profile.get("avatar", "")),
            )
            logger.info("好友 %s 已存在，更新 IP", friend_name)
        else:
            status = self.friend_db.get_relationship_status(
                user_id=friend_user_id,
                name=friend_name,
                ip=from_ip,
                port=port,
            )
            if status != "pending_sent":
                logger.info(
                    "收到来自 %s 的 FRIEND_ACCEPT 消息，但当前关系状态为 %s，忽略添加好友。",
                    friend_name,
                    status,
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
                avatar=self.owner._shared_avatar_reference(profile.get("avatar", "")),
            )
            logger.info("好友已添加: %s (%s)", friend_name, from_ip)
            self.owner.add_system_notification(
                title="好友申请通过 🤝",
                content=f"「{friend_name}」同意了您的好友申请，你们现在可以开始聊天了！",
                category="success",
            )

        self.friend_db.set_friend_request_status(
            "accepted",
            user_id=friend_user_id,
            name=friend_name,
            ip=from_ip,
            port=port,
        )
        if self.owner.on_friend_accepted:
            try:
                self.owner.on_friend_accepted(friend_name, from_ip)
            except Exception as e:
                logger.error("on_friend_accepted 回调异常: %s", e)

    def handle_friend_delete(self, from_ip: str, data: Dict[str, Any]):
        profile = data.get("profile", {})
        friend_name = profile.get("name", "Unknown")
        friend_user_id = profile.get("user_id", "")
        logger.info("收到来自 %s 的 FRIEND_DELETE 消息，执行双向删除。", friend_name)

        if self.connection_manager:
            friend = (
                self.friend_db.get_friend(friend_name)
                or self.friend_db.get_friend_by_user_id(friend_user_id)
            )
            if friend:
                ip = friend.get("ip")
                port = friend.get("port")
                if ip:
                    endpoint = f"{ip}:{port}" if port else ip
                    if hasattr(self.connection_manager, "disconnect_friend"):
                        self.connection_manager.disconnect_friend(endpoint)

        if self.friend_db:
            self.owner.add_system_notification(
                title="好友删除通知 ⚠️",
                content=f"好友「{friend_name}」已将您从好友列表中删除。",
                category="warning",
            )
            self.friend_db.remove_friend(friend_name)

        if self.owner.on_friend_accepted:
            try:
                self.owner.on_friend_accepted(friend_name, from_ip)
            except Exception as e:
                logger.error("handle_friend_delete 触发回调异常: %s", e)

        if self.owner.on_friend_deleted:
            try:
                self.owner.on_friend_deleted(friend_name)
            except Exception as e:
                logger.error("on_friend_deleted 回调异常: %s", e)
