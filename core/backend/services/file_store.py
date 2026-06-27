"""Local file-transfer storage helpers."""

import hashlib
import os


class FileStore:
    """Owns filename safety, collision-free paths, and file hashes."""

    def __init__(self, receive_dir: str, avatar_dir: str):
        self.receive_dir = receive_dir
        self.avatar_dir = avatar_dir

    def set_receive_dir(self, receive_dir: str) -> str:
        os.makedirs(receive_dir, exist_ok=True)
        self.receive_dir = receive_dir
        return self.receive_dir

    @staticmethod
    def sha256_file(path: str) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def sha256_bytes(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def safe_filename(filename: str) -> str:
        name = os.path.basename(filename or "received.bin").strip()
        if not name:
            name = "received.bin"
        return "".join(ch if ch not in '<>:"/\\|?*' else "_" for ch in name)

    def unique_receive_path(self, filename: str) -> str:
        base, ext = os.path.splitext(filename)
        candidate = os.path.join(self.receive_dir, filename)
        index = 1
        while os.path.exists(candidate) or os.path.exists(candidate + ".part"):
            candidate = os.path.join(self.receive_dir, f"{base}_{index}{ext}")
            index += 1
        return candidate

    def unique_avatar_path(
        self,
        filename: str,
        owner_name: str = "",
        user_id: str = "",
    ) -> str:
        _base, ext = os.path.splitext(filename)
        if ext.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"):
            ext = ".png"
        owner = self.safe_filename(user_id or owner_name or "friend")
        candidate = os.path.join(self.avatar_dir, f"{owner}_avatar{ext}")
        index = 1
        while os.path.exists(candidate) or os.path.exists(candidate + ".part"):
            candidate = os.path.join(self.avatar_dir, f"{owner}_avatar_{index}{ext}")
            index += 1
        return candidate

