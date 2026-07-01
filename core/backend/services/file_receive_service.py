"""Incoming file-offer and receive-side handlers for FileTransferService."""

import base64
import hashlib
import logging
import os
import time
from typing import Any, Dict

logger = logging.getLogger(__name__)


class FileReceiveService:
    """Handle incoming file offers, chunks, completion, and local finalisation."""

    def __init__(self, owner):
        self.owner = owner

    def __getattr__(self, name):
        return getattr(self.owner, name)

    def handle_file_offer(self, from_ip: str, data: Dict[str, Any]):
        my_name = self.friend_db.get_my_profile().get("name", "")
        to_name = data.get("to_name", "")
        if to_name and to_name != my_name:
            return

        file_id = data.get("file_id", "")
        from_name = data.get("from_name", "")
        if not file_id or not from_name:
            return

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
        self._accept_file_offer_internal(from_ip, data)

        if purpose == "avatar":
            return

        with self._file_lock:
            state = self._incoming_files.get(file_id)
            if state:
                state["pending_accept"] = True

        filename = self.owner._safe_filename(data.get("filename", "received.bin"))
        file_size = int(data.get("size", 0) or 0)
        with self._file_offer_lock:
            self._pending_file_offers[file_id] = True

        size_value = file_size
        size_label = f"{size_value} B"
        for unit in ("B", "KiB", "MiB", "GiB"):
            if size_value < 1024 or unit == "GiB":
                size_label = (
                    f"{size_value:.0f} {unit}"
                    if unit == "B"
                    else f"{size_value:.1f} {unit}"
                )
                break
            size_value /= 1024
        self.owner.add_system_notification(
            title="文件传输请求 📁",
            content=f"收到来自「{from_name}」的文件传输请求，文件名：「{filename}」({size_label})。\n[文件ID:{file_id}]",
            category="file_offer",
        )

        if self.on_file_offer_received:
            try:
                self.on_file_offer_received(from_name, filename, file_size, file_id)
            except Exception:
                logger.debug("[MessageService] on_file_offer_received error", exc_info=True)


    def accept_file_offer(self, file_id: str) -> bool:
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
            self.owner._send_data_to_friend_with_fallback(from_name, accept_msg, "")

        if is_complete:
            self._finalise_incoming_file(file_id)
        return True


    def decline_file_offer(self, file_id: str) -> bool:
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
            self.owner._send_data_to_friend_with_fallback(from_name, decline_msg, "")

            try:
                self.friend_db.save_chat_message(
                    from_name=from_name,
                    to_name=self.friend_db.get_my_profile().get("name", ""),
                    content=self.owner._file_message_content(
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
        from_name = data.get("from_name", "")
        file_id = data.get("file_id", "")
        filename = self.owner._safe_filename(data.get("filename", "received.bin"))
        purpose = data.get("purpose", "chat_file")
        if purpose == "avatar":
            final_path = self.owner._unique_avatar_path(
                filename,
                data.get("avatar_owner", from_name),
                data.get("avatar_user_id", ""),
            )
            part_path = final_path + ".part"
        else:
            candidate = os.path.join(self.receive_dir, filename)
            if os.path.exists(candidate):
                final_path = self.owner._unique_receive_path(filename)
            else:
                final_path = candidate
            import tempfile
            part_path = os.path.join(
                tempfile.gettempdir(),
                f"meeting_in_beiyang_{file_id}_{filename}.part",
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
        if completed_chunks > 0 and os.path.getsize(part_path) > 0:
            with open(part_path, "rb") as part_file:
                while True:
                    block = part_file.read(1024 * 1024)
                    if not block:
                        break
                    self._incoming_files[file_id]["_sha256_state"].update(block)
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

    @staticmethod
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
                state.setdefault("_bytes_written", 0)
                handle = state.get("_file_handle")
                if handle is None:
                    handle = open(state["part_path"], "r+b")
                    state["_file_handle"] = handle
                handle.seek(offset)
                handle.write(raw)
                actual_end = handle.tell()
                state["_bytes_written"] = max(state["_bytes_written"], actual_end)
                state["received"].add(index)
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
        self.owner._send_data_to_friend_with_fallback(from_name, payload, from_ip)


    def handle_file_complete(self, from_ip: str, data: Dict[str, Any]):
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

        if state.get("pending_accept"):
            state["_all_chunks_received"] = True
            state["_pending_complete_data"] = dict(data)
            self._send_file_complete_ack(from_name, file_id, True, error="pending_accept", fallback=from_ip)
            return

        self._finalise_incoming_file(file_id, data)


    def _finalise_incoming_file(self, file_id: str, data: Dict[str, Any] = None):
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
            else self.owner._sha256_file(part_path)
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
        except Exception as exc:
            logger.error("[MessageService] 移动临时文件失败: %s, fallback to os.replace", exc)
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

        content = self.owner._file_message_content(filename, final_path, file_id)

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
        self.owner.add_system_notification(
            title="文件接收通知 📁",
            content=f"成功接收来自「{from_name}」的文件：{filename}\n保存位置：{final_path}",
            category="info",
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
            except Exception as exc:
                logger.error("[MessageService] on_message_received 回调异常: %s", exc)
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
        self.owner._send_data_to_friend_with_fallback(to_name, payload, fallback)


