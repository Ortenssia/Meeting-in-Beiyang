"""
Group chat and moments synchronization service.

This module owns the social broadcast paths that used to live inside
MessageService: group creation/chat/sync and moments publish/comment/delete/sync.
"""

import base64
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SocialSyncService:
    """Extracted group and moments behavior backed by MessageService primitives."""

    def __init__(self, owner):
        self.owner = owner

    @property
    def connection_manager(self):
        return self.owner.connection_manager

    @property
    def friend_db(self):
        return self.owner.friend_db

    @property
    def receive_dir(self) -> str:
        return self.owner.receive_dir

    @property
    def runtime(self):
        return self.owner.runtime

    def _get_friend_name_by_ip(self, ip: str) -> Optional[str]:
        if self.connection_manager:
            for friend in self.connection_manager.get_online_friends():
                if self.owner._online_friend_ip(friend) == ip:
                    return self.owner._online_friend_name(friend)
        return None

    def create_group(self, group_name: str, members: List[str]) -> str:
        group_id = str(uuid.uuid4())
        my_name = self.runtime.device_name
        if my_name not in members:
            members.append(my_name)

        self.friend_db.save_group(
            group_id,
            group_name,
            members,
            owner=my_name,
            only_owner_manage=0,
        )

        payload = {
            "type": self.owner.GROUP_CREATE,
            "group_id": group_id,
            "group_name": group_name,
            "members": members,
            "owner": my_name,
            "only_owner_manage": 0,
        }

        for member in members:
            if member != my_name:
                self.owner._send_data_to_friend(member, payload)
        return group_id

    def send_group_chat_message(self, group_id: str, content: str, msg_id: str = "") -> bool:
        group = self.friend_db.get_group(group_id)
        if not group:
            return False

        my_name = self.runtime.device_name
        msg_id = msg_id or str(uuid.uuid4())
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

        self.friend_db.save_group_chat_message(msg_id, group_id, my_name, content, timestamp)

        payload = {
            "type": self.owner.GROUP_CHAT,
            "msg_id": msg_id,
            "group_id": group_id,
            "sender": my_name,
            "content": content,
            "timestamp": timestamp,
        }

        members = group.get("members", [])
        for member in members:
            if member != my_name:
                self.owner._send_data_to_friend(member, payload)
        return True

    def sync_groups_with_friend(self, friend_name: str):
        my_name = self.runtime.device_name
        groups = self.friend_db.get_all_groups()
        for group in groups:
            members = group.get("members", [])
            if friend_name in members and my_name in members:
                history = self.friend_db.get_group_chat_history(
                    group["group_id"],
                    limit=1,
                )
                last_timestamp = history[0]["timestamp"] if history else "1970-01-01 00:00:00"

                payload = {
                    "type": self.owner.GROUP_SYNC_REQ,
                    "group_id": group["group_id"],
                    "last_timestamp": last_timestamp,
                }
                self.owner._send_data_to_friend(friend_name, payload)

    def sync_moments_with_friend(self, friend_name: str):
        payload = {
            "type": self.owner.MOMENTS_SYNC_REQ,
            "sender_name": self.runtime.device_name,
        }
        self.owner._send_data_to_friend(friend_name, payload)

    def publish_moment(self, content: str, media_path: str = "") -> bool:
        my_name = self.runtime.device_name
        post_id = str(uuid.uuid4())
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

        media_data = self._read_media_b64(media_path)
        self.friend_db.save_moment(post_id, my_name, content, media_path, timestamp)

        payload = {
            "type": self.owner.MOMENTS_PUBLISH,
            "post_id": post_id,
            "author": my_name,
            "content": content,
            "media_name": os.path.basename(media_path) if media_path else "",
            "media_data": media_data,
            "timestamp": timestamp,
        }

        for friend in self.connection_manager.get_online_friends():
            friend_name = self.owner._online_friend_name(friend)
            if friend_name:
                self.owner._send_data_to_friend(friend_name, payload)
        return True

    def publish_moment_comment(self, post_id: str, content: str) -> bool:
        if not self.friend_db:
            return False
        comment_id = f"comment_{uuid.uuid4().hex}"
        my_name = self.runtime.device_name
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

        ok = self.friend_db.save_moment_comment(
            comment_id,
            post_id,
            my_name,
            content,
            timestamp,
        )
        if not ok:
            return False

        payload = {
            "type": "MOMENT_COMMENT",
            "comment_id": comment_id,
            "post_id": post_id,
            "author": my_name,
            "content": content,
            "timestamp": timestamp,
        }
        for friend in self.connection_manager.get_online_friends():
            friend_name = self.owner._online_friend_name(friend)
            if friend_name:
                self.owner._send_data_to_friend(friend_name, payload)
        self._notify_moments_changed()
        return True

    def publish_moment_delete(self, post_id: str) -> bool:
        if not self.friend_db:
            return False

        ok = self.friend_db.delete_moment(post_id)
        if not ok:
            return False

        payload = {
            "type": "MOMENT_DELETE",
            "post_id": post_id,
            "sender_name": self.runtime.device_name,
        }
        for friend in self.connection_manager.get_online_friends():
            try:
                self.owner._send_data_to_friend(friend["name"], payload)
            except Exception:
                pass

        self._notify_moments_changed()
        return True

    def handle_group_create(self, from_ip: str, data: Dict[str, Any]):
        group_id = data.get("group_id", "")
        group_name = data.get("group_name", "")
        members = data.get("members", [])
        owner = data.get("owner", "")
        only_owner_manage = int(data.get("only_owner_manage", 0) or 0)
        if group_id and group_name:
            self.friend_db.save_group(
                group_id,
                group_name,
                members,
                owner=owner,
                only_owner_manage=only_owner_manage,
            )
            self._notify_friends_changed()

    def handle_group_chat(self, from_ip: str, data: Dict[str, Any]):
        msg_id = data.get("msg_id", "")
        group_id = data.get("group_id", "")
        sender = data.get("sender", "")
        content = data.get("content", "")
        timestamp = data.get("timestamp", "")

        if not group_id or not sender:
            return

        if not self.friend_db.get_group(group_id):
            self.friend_db.save_group(
                group_id,
                f"群聊_{group_id[:8]}",
                [sender, self.runtime.device_name],
            )

        self.friend_db.save_group_chat_message(msg_id, group_id, sender, content, timestamp)

        if (
            hasattr(self.runtime, "on_group_message_received")
            and self.runtime.on_group_message_received
        ):
            self.runtime.on_group_message_received(group_id, sender, content, timestamp)

    def handle_group_sync_req(self, from_ip: str, data: Dict[str, Any]):
        group_id = data.get("group_id", "")
        last_timestamp = data.get("last_timestamp", "1970-01-01 00:00:00")

        if not group_id:
            return

        conn = self.friend_db.conn
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM group_chat_history WHERE group_id = ? AND timestamp > ? ORDER BY timestamp ASC",
            (group_id, last_timestamp),
        )
        rows = cursor.fetchall()
        messages = [dict(row) for row in rows]

        friend_name = self._get_friend_name_by_ip(from_ip)
        if friend_name:
            payload = {
                "type": self.owner.GROUP_SYNC_RESP,
                "group_id": group_id,
                "messages": messages,
            }
            self.owner._send_data_to_friend(friend_name, payload)

    def handle_group_sync_resp(self, from_ip: str, data: Dict[str, Any]):
        group_id = data.get("group_id", "")
        messages = data.get("messages", [])

        for msg in messages:
            msg_id = msg.get("msg_id", "")
            sender = msg.get("sender", "")
            content = msg.get("content", "")
            timestamp = msg.get("timestamp", "")

            if not msg_id or not group_id:
                continue

            if not self.friend_db.has_group_message(msg_id):
                self.friend_db.save_group_chat_message(
                    msg_id,
                    group_id,
                    sender,
                    content,
                    timestamp,
                )

                if (
                    hasattr(self.runtime, "on_group_message_received")
                    and self.runtime.on_group_message_received
                ):
                    self.runtime.on_group_message_received(group_id, sender, content, timestamp)

    def handle_moments_publish(self, from_ip: str, data: Dict[str, Any]):
        post_id = data.get("post_id", "")
        author = data.get("author", "")
        content = data.get("content", "")
        media_name = data.get("media_name", "")
        media_data = data.get("media_data", "")
        timestamp = data.get("timestamp", "")

        if not post_id or not author:
            return

        local_media_path = self._save_media_b64(post_id, media_name, media_data)
        self.friend_db.save_moment(post_id, author, content, local_media_path, timestamp)
        self._notify_moments_changed()

    def handle_moment_comment(self, from_ip: str, data: Dict[str, Any]):
        comment_id = data.get("comment_id")
        post_id = data.get("post_id")
        author = data.get("author")
        content = data.get("content")
        timestamp = data.get("timestamp")
        if comment_id and post_id and author and content and timestamp:
            self.friend_db.save_moment_comment(comment_id, post_id, author, content, timestamp)
            self._notify_moments_changed()

    def handle_moments_sync_req(self, from_ip: str, data: Dict[str, Any]):
        my_name = self.runtime.device_name
        moments = self.friend_db.get_moments(limit=50)
        my_moments = [moment for moment in moments if moment["author"] == my_name]

        posts = []
        for moment in my_moments:
            media_path = moment.get("media_path", "")
            posts.append({
                "post_id": moment["post_id"],
                "author": moment["author"],
                "content": moment["content"],
                "media_name": os.path.basename(media_path) if media_path else "",
                "media_data": self._read_media_b64(media_path),
                "timestamp": moment["timestamp"],
            })

        my_comments = []
        for moment in my_moments:
            comments = self.friend_db.get_moment_comments(moment["post_id"]) or []
            my_comments.extend(comments)

        payload = {
            "type": self.owner.MOMENTS_SYNC_RESP,
            "posts": posts,
            "comments": my_comments,
            "sender_name": my_name,
        }

        friend_name = data.get("sender_name", "") or self._get_friend_name_by_ip(from_ip)
        if friend_name:
            self.owner._send_data_to_friend(friend_name, payload)

    def handle_moments_sync_resp(self, from_ip: str, data: Dict[str, Any]):
        posts = data.get("posts", [])
        updated = False

        friend_name = data.get("sender_name", "") or self._get_friend_name_by_ip(from_ip)
        if friend_name and self.friend_db:
            try:
                local_moments = self.friend_db.get_moments(limit=200)
                friend_local_moments = [
                    moment for moment in local_moments
                    if moment.get("author") == friend_name
                ]
                active_post_ids = {post.get("post_id") for post in posts if post.get("post_id")}
                for moment in friend_local_moments:
                    pid = moment.get("post_id")
                    if pid and pid not in active_post_ids:
                        self.friend_db.delete_moment(pid)
                        updated = True
            except Exception:
                pass

        for post in posts:
            post_id = post.get("post_id", "")
            author = post.get("author", "")
            content = post.get("content", "")
            media_name = post.get("media_name", "")
            media_data = post.get("media_data", "")
            timestamp = post.get("timestamp", "")

            if not post_id or not author:
                continue

            if not self.friend_db.has_moment(post_id):
                local_media_path = self._save_media_b64(post_id, media_name, media_data)
                self.friend_db.save_moment(post_id, author, content, local_media_path, timestamp)
                updated = True

        comments = data.get("comments") or []
        for comment in comments:
            comment_id = comment.get("comment_id")
            post_id = comment.get("post_id")
            author = comment.get("author")
            content = comment.get("content")
            timestamp = comment.get("timestamp")
            if comment_id and post_id and author and content and timestamp:
                if self.friend_db.save_moment_comment(
                    comment_id,
                    post_id,
                    author,
                    content,
                    timestamp,
                ):
                    updated = True

        if updated:
            self._notify_moments_changed()

    def handle_moment_delete(self, from_ip: str, data: Dict[str, Any]):
        post_id = data.get("post_id", "")
        if not post_id:
            return

        sender_name = data.get("sender_name", "") or self._get_friend_name_by_ip(from_ip)
        if self.friend_db:
            try:
                moments = self.friend_db.get_moments(limit=100)
                target = None
                for moment in moments:
                    if moment.get("post_id") == post_id:
                        target = moment
                        break

                if target:
                    author = target.get("author", "")
                    if author == sender_name or not sender_name:
                        self.friend_db.delete_moment(post_id)
                        self._notify_moments_changed()
            except Exception:
                pass

    def _read_media_b64(self, media_path: str) -> str:
        if not media_path or not os.path.exists(media_path):
            return ""
        try:
            with open(media_path, "rb") as file:
                return base64.b64encode(file.read()).decode("utf-8")
        except Exception:
            return ""

    def _save_media_b64(self, post_id: str, media_name: str, media_data: str) -> str:
        if not media_name or not media_data:
            return ""
        try:
            save_path = os.path.join(self.receive_dir, f"moment_{post_id}_{media_name}")
            with open(save_path, "wb") as file:
                file.write(base64.b64decode(media_data))
            return save_path
        except Exception as exc:
            logger.error("保存空间图片失败: %s", exc)
            return ""

    def _notify_friends_changed(self):
        if hasattr(self.runtime, "on_friends_changed") and self.runtime.on_friends_changed:
            self.runtime.on_friends_changed()

    def _notify_moments_changed(self):
        if hasattr(self.runtime, "on_moments_changed") and self.runtime.on_moments_changed:
            self.runtime.on_moments_changed()
