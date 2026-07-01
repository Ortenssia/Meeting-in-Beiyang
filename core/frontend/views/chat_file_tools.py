"""File-message and platform helpers for ChatView."""

import os
import subprocess
from typing import Dict

from core.backend.shared.file_message import (
    decode_file_message,
    encode_file_message,
    is_file_message_content,
)


def is_file_message(content: str) -> bool:
    return is_file_message_content(content)


def file_info_from_content(content: str, receive_dir: str) -> Dict[str, str]:
    decoded = decode_file_message(content, receive_dir)
    return {
        "filename": decoded.filename,
        "path": decoded.path,
        "transfer_id": decoded.transfer_id,
    }


def decode_file_content(content: str, receive_dir: str):
    return decode_file_message(content, receive_dir)


def file_message_content(
    status: str,
    filename: str,
    file_path: str,
    transfer_id: str = "",
) -> str:
    return encode_file_message(status, filename, file_path, transfer_id)


def is_android() -> bool:
    if hasattr(os, "getandroidapplication"):
        return True
    if "ANDROID_ARGUMENT" in os.environ or "ANDROID_APP_PATH" in os.environ:
        return True
    return False


def open_file_with_os(file_path: str):
    import platform
    system = platform.system()
    if is_android():
        try:
            subprocess.run(
                [
                    "am",
                    "start",
                    "-a",
                    "android.intent.action.VIEW",
                    "-d",
                    f"file://{file_path}",
                    "-t",
                    "*/*",
                ],
                check=False,
            )
        except Exception:
            pass
    elif system == "Windows":
        os.startfile(file_path)
    elif system == "Darwin":
        subprocess.run(["open", file_path], check=True)
    else:
        subprocess.run(["xdg-open", file_path], check=False)


def open_folder_with_os(file_path: str, folder_path: str):
    import platform
    system = platform.system()
    if is_android():
        try:
            subprocess.run(
                [
                    "am",
                    "start",
                    "-a",
                    "android.intent.action.VIEW",
                    "-d",
                    f"file://{folder_path}",
                ],
                check=False,
            )
        except Exception:
            open_file_with_os(file_path)
    elif system == "Windows":
        win_path = file_path.replace("/", "\\")
        subprocess.run(
            f'explorer /select,"{win_path}"',
            shell=True,
        )
    elif system == "Darwin":
        subprocess.run(["open", "-R", file_path], check=True)
    else:
        subprocess.run(["xdg-open", folder_path], check=False)


def format_bytes(value) -> str:
    value = float(max(0, value or 0))
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GiB"


def format_speed(bytes_per_second) -> str:
    if not bytes_per_second or bytes_per_second <= 0:
        return "0 B/s"
    return f"{format_bytes(bytes_per_second)}/s"


def is_final_file_status(status: str) -> bool:
    return bool(status) and "正在" not in status and "等待" not in status
