"""Shared file-message payload helpers.

The backend writes file-transfer chat records and the frontend renders them.
Keeping the wire/text format here prevents UI and service code from each
guessing how a file message is encoded.
"""

import json
import os
from dataclasses import dataclass


DEFAULT_FILE_NAME = "received.bin"
FILE_MESSAGE_STATUSES = {
    "文件",
    "正在发送文件",
    "正在接收文件",
    "文件发送失败",
    "文件接收失败",
    "等待对方接受",
    "已拒绝接收",
    "对方已拒绝",
}


@dataclass(frozen=True)
class FileMessage:
    status: str
    filename: str
    path: str = ""
    transfer_id: str = ""


def encode_file_message(
    status: str, filename: str, path: str = "", transfer_id: str = ""
) -> str:
    payload = {
        "filename": filename or DEFAULT_FILE_NAME,
        "path": path or "",
    }
    if transfer_id:
        payload["transfer_id"] = transfer_id
    return f"[{status}] " + json.dumps(payload, ensure_ascii=False)


def decode_file_message(content: str, default_dir: str = "") -> FileMessage:
    idx = content.find("]")
    status = content[1:idx] if content.startswith("[") and idx >= 0 else "文件"
    raw = content[idx + 1:].strip() if idx >= 0 else content.strip()
    filename = raw or DEFAULT_FILE_NAME
    file_path = ""
    transfer_id = ""

    if raw.startswith("{"):
        try:
            payload = json.loads(raw)
            filename = payload.get("filename") or filename
            file_path = payload.get("path") or ""
            transfer_id = payload.get("transfer_id") or ""
        except Exception:
            pass

    if not file_path and default_dir:
        file_path = os.path.join(default_dir, filename)
    return FileMessage(
        status=status,
        filename=filename,
        path=file_path,
        transfer_id=transfer_id,
    )


def is_file_message_content(content: str) -> bool:
    """Return True when *content* is an encoded file-transfer chat record."""
    if not content.startswith("[") or "]" not in content:
        return False
    idx = content.find("]")
    status = content[1:idx]
    raw = content[idx + 1:].strip()
    if status in FILE_MESSAGE_STATUSES:
        return True
    if not raw.startswith("{"):
        return False
    try:
        payload = json.loads(raw)
    except Exception:
        return False
    return "filename" in payload and (
        "transfer_id" in payload
        or "path" in payload
        or status.endswith("文件")
        or "文件" in status
    )
