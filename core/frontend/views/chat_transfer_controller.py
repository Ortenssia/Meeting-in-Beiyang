"""File-transfer UI state controller for ChatView."""

import threading
import time


class ChatTransferController:
    """Owns transfer state, speed calculation, and stalled-transfer refresh."""

    SPEED_WINDOW = 3.0

    def __init__(self, owner):
        self.owner = owner

    def remember_state(self, file_id, **changes):
        if not file_id:
            return {}
        state = self.owner._transfer_states.setdefault(file_id, {})
        state.update(changes)
        state["updated_at"] = time.monotonic()
        return state

    def render_active_for(self, friend_name):
        if not self.owner._msg_list or not friend_name:
            return
        for file_id, state in list(self.owner._transfer_states.items()):
            if state.get("peer_name") != friend_name or state.get("final"):
                continue
            content = self.owner._file_message_content(
                state.get(
                    "status",
                    "正在发送文件" if state.get("sending") else "正在接收文件",
                ),
                state.get("filename", "文件"),
                state.get("file_path", ""),
                file_id,
            )
            self.owner._append_bubble(
                self.owner.app.device_name if state.get("sending") else friend_name,
                content,
                state.get("timestamp", time.strftime("%H:%M:%S", time.localtime())),
                is_self=bool(state.get("sending")),
            )

    def start_watchdog(self, file_id):
        if not file_id or file_id in self.owner._transfer_watchdogs:
            return
        self.owner._transfer_watchdogs.add(file_id)

        def watchdog():
            try:
                while True:
                    time.sleep(0.8)
                    widget = self.owner._transfer_widgets.get(file_id)
                    if not widget:
                        return
                    if widget.get("paused"):
                        continue
                    percent = float(widget.get("percent", 0.0) or 0.0)
                    if percent >= 100:
                        return
                    idle = time.monotonic() - float(widget.get("last_data_ts", 0.0))
                    if idle < 1.5:
                        continue

                    self.update_speed(widget, 0, widget.get("last_completed", 0))
                    direction = "发送" if widget.get("sending") else "接收"
                    widget["status"].value = (
                        f"⏳ {direction}等待对端/网络 · {percent:.0f}% · "
                        f"{self.owner._format_speed(widget.get('speed', 0.0))}"
                    )
                    if self.owner.page:
                        try:
                            self.owner.page.update()
                        except Exception:
                            return
            finally:
                self.owner._transfer_watchdogs.discard(file_id)

        threading.Thread(target=watchdog, daemon=True).start()

    def update_speed(self, widget: dict, completed: int, prev_completed: int):
        now = time.monotonic()
        samples = widget.setdefault("_speed_samples", [])
        if completed > prev_completed:
            samples.append((now, completed))
        cutoff = now - self.SPEED_WINDOW
        while len(samples) > 1 and samples[0][0] < cutoff:
            samples.pop(0)
        if len(samples) >= 2:
            window_dt = samples[-1][0] - samples[0][0]
            window_db = samples[-1][1] - samples[0][1]
            instant = window_db / max(0.05, window_dt)
        elif completed > 0:
            start_ts = widget.get("_start_ts", now)
            elapsed = max(0.05, now - start_ts)
            instant = completed / elapsed
        else:
            instant = 0.0
        previous = float(widget.get("speed", 0.0) or 0.0)
        alpha = 0.45
        widget["speed"] = (
            instant if previous <= 0 else previous * (1 - alpha) + instant * alpha
        )

    def find_widget(self, peer_name="", filename="", sending=None):
        for transfer_id, widget in list(self.owner._transfer_widgets.items()):
            if peer_name and widget.get("peer_name") != peer_name:
                continue
            if filename and widget.get("filename") != filename:
                continue
            if sending is not None and bool(widget.get("sending")) != bool(sending):
                continue
            return transfer_id, widget
        return "", None

    def mark_closed(self, file_id: str):
        if not file_id:
            return
        self.owner._closed_file_transfers.add(file_id)
        if file_id in self.owner._transfer_states:
            self.owner._transfer_states[file_id]["final"] = True
        self.owner._transfer_widgets.pop(file_id, None)
        self.owner._pending_file_offers.pop(file_id, None)
