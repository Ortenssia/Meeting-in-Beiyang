"""File-transfer boundary helpers."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.backend.services.file_store import FileStore
from core.backend.shared.file_message import decode_file_message, encode_file_message


def test_file_message_roundtrip_with_path():
    content = encode_file_message(
        "文件发送失败", "large.bin", r"C:\Temp\large.bin", "transfer-1"
    )

    decoded = decode_file_message(content)

    assert decoded.status == "文件发送失败"
    assert decoded.filename == "large.bin"
    assert decoded.path == r"C:\Temp\large.bin"
    assert decoded.transfer_id == "transfer-1"


def test_file_message_decodes_legacy_plain_filename(tmp_path):
    decoded = decode_file_message("[文件] note.txt", str(tmp_path))

    assert decoded.status == "文件"
    assert decoded.filename == "note.txt"
    assert decoded.path == str(tmp_path / "note.txt")


def test_file_store_hash_and_unique_paths(tmp_path):
    receive_dir = tmp_path / "received"
    avatar_dir = tmp_path / "avatars"
    receive_dir.mkdir()
    avatar_dir.mkdir()
    (receive_dir / "note.txt").write_text("existing", encoding="utf-8")

    store = FileStore(str(receive_dir), str(avatar_dir))
    payload = b"hello"

    assert store.safe_filename("../bad:name.txt") == "bad_name.txt"
    assert store.sha256_bytes(payload) == FileStore.sha256_bytes(payload)
    assert store.unique_receive_path("note.txt").endswith("note_1.txt")
