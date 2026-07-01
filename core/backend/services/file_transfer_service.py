"""
File transfer orchestration for MessageService.

This service owns the file-transfer control flow while reusing MessageService's
existing connection, storage, callback, and state primitives during the split.
"""

import base64
import hashlib
import logging
import os
import time
import threading
import uuid
from typing import Any, Dict

from core.backend.services.file_receive_service import FileReceiveService
from core.backend.shared.file_message import encode_file_message, decode_file_message
from core.backend.shared.protocol import Protocol

logger = logging.getLogger(__name__)


class FileTransferService:
    """Transitional extraction of file transfer behavior from MessageService."""

    def __init__(self, owner):
        self.owner = owner
        self.receiver = FileReceiveService(self)

    def __getattr__(self, name):
        return getattr(self.owner, name)

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
        if not file_path or not os.path.isfile(file_path):
            logger.warning("[MessageService] 文件不存在: %s", file_path)
            return False
        if require_online and not self.connection_manager.is_friend_online(to_name):
            logger.info("[MessageService] 文件发送前主动重连: %s", to_name)
            if not self.owner._reconnect_file_peer(to_name):
                logger.warning("[MessageService] 好友不在线，无法发送文件: %s", to_name)
                return False

        my_profile = self.friend_db.get_my_profile()
        my_name = my_profile.get("name", "Unknown")
        my_user_id = my_profile.get("user_id", "")
        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        file_id = file_id or str(uuid.uuid4())
        sha256 = self.owner._sha256_file(file_path)
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
                    if not self.owner._reconnect_file_peer(to_name):
                        continue

                if not self.connection_manager.is_friend_online(to_name):
                    if not self.owner._reconnect_file_peer(to_name):
                        time.sleep(min(1.5, 0.25 * attempt))
                        continue

                if not self.owner._send_data_to_friend(to_name, offer):
                    self.owner._reconnect_file_peer(to_name)
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
                        self.owner._send_data_to_friend(
                            to_name, {"type": self.FILE_CANCEL, "file_id": file_id}
                        )
                        return False
                    continue

                complete_event.clear()
                with self._file_lock:
                    self._file_complete_results.pop(file_id, None)
                if not self.owner._send_data_to_friend(to_name, complete):
                    continue

                error = ""
                if reliable:
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
                        content=self.owner._file_message_content(
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
        if purpose == "avatar":
            return 0, False, False

        resume_event = threading.Event()
        with self._file_lock:
            self._file_resume_events[file_id] = resume_event
            self._file_resume_progress.pop(file_id, None)
            self._file_ack_capable.pop(file_id, None)
            self._file_binary_capable.pop(file_id, None)

        sent = self.owner._send_data_to_friend(
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
        _ = reliable, ack_event
        sent_bytes = start_chunk * self.FILE_CHUNK_SIZE
        with open(file_path, "rb") as src:
            src.seek(start_chunk * self.FILE_CHUNK_SIZE)
            for index in range(start_chunk, chunk_count):
                while True:
                    with self._file_lock:
                        if self.file_transfer.sender_cancelled(file_id):
                            return False
                        pause_event = self.file_transfer.sender_pause_event(file_id)
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
                    sent = self.owner._send_data_to_friend(to_name, chunk_msg)
                if not sent:
                    logger.warning(
                        "[MessageService] 文件分块发送失败: %s #%s",
                        filename,
                        index,
                    )
                    return False

                sent_bytes = min((index + 1) * self.FILE_CHUNK_SIZE, file_size)
                with self._file_lock:
                    sender_state = self._active_senders.get(file_id, {})
                    sender_state["_sent_bytes"] = sent_bytes

                with self._file_lock:
                    error = self._file_ack_errors.get(file_id, "")
                if error:
                    logger.warning(
                        "[MessageService] 接收端报告文件写入失败: %s (%s)",
                        filename,
                        error,
                    )
                    return False

                with self._file_lock:
                    ack_chunks = int(self._file_ack_progress.get(file_id, 0) or 0)
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

    def handle_file_offer(self, from_ip: str, data: Dict[str, Any]):
        self.receiver.handle_file_offer(from_ip, data)

    def accept_file_offer(self, file_id: str) -> bool:
        return self.receiver.accept_file_offer(file_id)

    def decline_file_offer(self, file_id: str) -> bool:
        return self.receiver.decline_file_offer(file_id)

    def _accept_file_offer_internal(self, from_ip: str, data: Dict[str, Any]):
        self.receiver._accept_file_offer_internal(from_ip, data)

    def _close_incoming_handle(state):
        if not state:
            return
        handle = state.pop("_file_handle", None)
        if handle:
            try:
                handle.close()
            except Exception:
                pass

    def handle_file_chunk(self, from_ip: str, data: Dict[str, Any]):
        self.receiver.handle_file_chunk(from_ip, data)

    def _send_file_chunk_ack(
        self, state, file_id: str, next_expected: int = 0, ok: bool = True, error: str = ""
    ):
        self.receiver._send_file_chunk_ack(state, file_id, next_expected, ok, error)

    def handle_file_chunk_ack(self, from_ip: str, data: Dict[str, Any]):
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

    def handle_file_complete(self, from_ip: str, data: Dict[str, Any]):
        self.receiver.handle_file_complete(from_ip, data)

    def _finalise_incoming_file(self, file_id: str, data: Dict[str, Any] = None):
        self.receiver._finalise_incoming_file(file_id, data)

    def _send_file_complete_ack(
        self, to_name: str, file_id: str, ok: bool, error: str = "", fallback: str = ""
    ):
        self.receiver._send_file_complete_ack(to_name, file_id, ok, error, fallback)

    def handle_file_complete_ack(self, from_ip: str, data: Dict[str, Any]):
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

    def get_file_final_status(self, file_id: str) -> str:
        with self._file_lock:
            return self._file_final_statuses.pop(file_id, "文件")

    def pause_file_transfer(self, file_id: str) -> bool:
        with self._file_lock:
            paused = self.file_transfer.pause_sender(file_id)
        if paused:
            logger.info("[MessageService] 文件传输已暂停: %s", file_id)
        return paused

    def resume_file_transfer(self, file_id: str) -> bool:
        with self._file_lock:
            resumed = self.file_transfer.resume_sender(file_id)
        if resumed:
            logger.info("[MessageService] 文件传输已继续: %s", file_id)
        return resumed

    def cancel_file_transfer(self, file_id: str):
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
            self.owner._send_data_to_friend(to_name, cancel_msg)
        elif from_name:
            cancel_msg = {
                "type": self.FILE_CANCEL,
                "file_id": file_id,
            }
            self.owner._send_data_to_friend(from_name, cancel_msg)

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

    def handle_file_cancel(self, from_ip: str, data: Dict[str, Any]):
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

    def handle_file_decline(self, from_ip: str, data: Dict[str, Any]):
        file_id = data.get("file_id", "")
        if not file_id:
            return
        with self._file_lock:
            self.file_transfer.mark_sender_cancelled(file_id)
            self._file_complete_results[file_id] = (False, "对方已拒绝")
            self._file_ack_errors[file_id] = "对方已拒绝"
            event = self._file_complete_events.get(file_id)
            if event:
                event.set()

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

    def handle_file_accept(self, from_ip: str, data: Dict[str, Any]):
        file_id = data.get("file_id", "")
        if not file_id:
            return

        try:
            old_content = self.friend_db.get_chat_message_content(file_id)
            if old_content:
                decoded = decode_file_message(old_content, self.receive_dir)
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

    def handle_file_resume_req(self, from_ip: str, data: Dict[str, Any]):
        file_id = data.get("file_id", "")
        filename = self.owner._safe_filename(data.get("filename", "received.bin"))
        if not file_id:
            return

        with self._file_lock:
            state = self._incoming_files.get(file_id)
            part_path = state.get("part_path", "") if state else ""
            state_from_name = state.get("from_name", "") if state else ""
        if not part_path:
            candidate = os.path.join(self.receive_dir, filename)
            if os.path.exists(candidate):
                self.owner._unique_receive_path(filename)

            import tempfile
            part_path = os.path.join(
                tempfile.gettempdir(),
                f"meeting_in_beiyang_{file_id}_{filename}.part",
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

        friend_name = self.owner._get_friend_name_by_ip(from_ip) or state_from_name
        if friend_name:
            self.owner._send_data_to_friend_with_fallback(friend_name, payload, from_ip)
        elif from_ip:
            self.owner._send_data_to_friend(from_ip, payload)

    def handle_file_resume_resp(self, from_ip: str, data: Dict[str, Any]):
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
