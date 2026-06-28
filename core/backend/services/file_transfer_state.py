"""
Runtime state for chat file transfers.

The service layer owns the actual network protocol, while this object keeps
the mutable in-memory bookkeeping in one place.
"""

import threading
from typing import Any, Dict, Optional


FILE_CANCEL = "FILE_CANCEL"
FILE_RESUME_REQ = "FILE_RESUME_REQ"
FILE_RESUME_RESP = "FILE_RESUME_RESP"
FILE_DECLINE = "FILE_DECLINE"
FILE_ACCEPT = "FILE_ACCEPT"


class FileTransferState:
    """In-memory state shared by file send, receive, cancel and resume flows."""

    def __init__(self):
        self.incoming_files: Dict[str, Dict[str, Any]] = {}
        self.active_senders: Dict[str, Dict[str, Any]] = {}
        self.resume_events: Dict[str, threading.Event] = {}
        self.resume_progress: Dict[str, int] = {}
        self.lock = threading.Lock()

    def register_sender(self, file_id: str, filename: str, to_name: str):
        pause_event = threading.Event()
        pause_event.set()
        self.active_senders[file_id] = {
            "cancelled": False,
            "paused": False,
            "pause_event": pause_event,
            "filename": filename,
            "to_name": to_name,
        }

    def mark_sender_cancelled(self, file_id: str) -> Optional[Dict[str, Any]]:
        sender = self.active_senders.get(file_id)
        if sender:
            sender["cancelled"] = True
            sender["pause_event"].set()
        return sender

    def pop_sender(self, file_id: str) -> Optional[Dict[str, Any]]:
        return self.active_senders.pop(file_id, None)

    def sender_cancelled(self, file_id: str) -> bool:
        return bool(self.active_senders.get(file_id, {}).get("cancelled"))

    def pause_sender(self, file_id: str) -> bool:
        sender = self.active_senders.get(file_id)
        if not sender or sender.get("cancelled"):
            return False
        sender["paused"] = True
        sender["pause_event"].clear()
        return True

    def resume_sender(self, file_id: str) -> bool:
        sender = self.active_senders.get(file_id)
        if not sender or sender.get("cancelled"):
            return False
        sender["paused"] = False
        sender["pause_event"].set()
        return True

    def sender_paused(self, file_id: str) -> bool:
        return bool(self.active_senders.get(file_id, {}).get("paused"))

    def sender_pause_event(self, file_id: str) -> Optional[threading.Event]:
        sender = self.active_senders.get(file_id)
        return sender.get("pause_event") if sender else None

    def active_file_id_for(self, filename: str) -> str:
        for file_id, state in self.incoming_files.items():
            if state.get("filename") == filename:
                return file_id
        for file_id, state in self.active_senders.items():
            if state.get("filename") == filename:
                return file_id
        return ""
