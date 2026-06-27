"""Shared file-message payload helpers.

The backend writes file-transfer chat records and the frontend renders them.
Keeping the wire/text format here prevents UI and service code from each
guessing how a file message is encoded.
"""

import json
import os
from dataclasses import dataclass


DEFAULT_FILE_NAME = "received.bin"


@dataclass(frozen=True)
class FileMessage:
    status: str
    filename: str
    path: str = ""


def encode_file_message(status: str, filename: str, path: str = "") -> str:
    payload = {
        "filename": filename or DEFAULT_FILE_NAME,
        "path": path or "",
    }
    return f"[{status}] " + json.dumps(payload, ensure_ascii=False)


def decode_file_message(content: str, default_dir: str = "") -> FileMessage:
    idx = content.find("]")
    status = content[1:idx] if content.startswith("[") and idx >= 0 else "文件"
    raw = content[idx + 1:].strip() if idx >= 0 else content.strip()
    filename = raw or DEFAULT_FILE_NAME
    file_path = ""

    if raw.startswith("{"):
        try:
            payload = json.loads(raw)
            filename = payload.get("filename") or filename
            file_path = payload.get("path") or ""
        except Exception:
            pass

    if not file_path and default_dir:
        file_path = os.path.join(default_dir, filename)
    return FileMessage(status=status, filename=filename, path=file_path)

