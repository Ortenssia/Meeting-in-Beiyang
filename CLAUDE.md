# CLAUDE.md

Project coding conventions for "相识北洋" (Meeting in Beiyang) — a campus LAN social app built with Python + Flet 0.85.x.

---

## Flet 0.85.x API Conventions (MANDATORY)

This project uses **Flet 0.85.3**. The API differs significantly from older Flet versions (0.24.x and earlier). Always follow these rules when writing Flet code.

### TextField

```python
# ✅ CORRECT — Flet 0.85.x
ft.TextField(
    label="昵称",
    hint_text="请输入你的昵称",
    helper="点击其他位置自动保存",        # NOT helper_text
    multiline=True,
    min_lines=3,
    max_lines=5,
    on_change=self._on_name_change,       # works
    on_blur=self._on_name_blur,           # works
    on_submit=self._on_submit,            # works
    border_radius=12,
    border_color=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
    bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
    content_padding=ft.padding.only(left=12, right=12, top=8, bottom=8),
)
```

| Feature | ❌ Old / Wrong | ✅ Flet 0.85.x |
|---|---|---|
| Helper text below field | `helper_text="..."` | `helper="..."` |
| Dropdown helper text | `helper_text="..."` ✅ | `helper_text="..."` ✅ same (note: NOT `helper`) |
| Blur event | `on_blur=...` | `on_blur=...` ✅ same |
| Change event | `on_change=...` | `on_change=...` ✅ same |
| Submit event | `on_submit=...` | `on_submit=...` ✅ same |

### Dropdown

```python
# ✅ CORRECT — Flet 0.85.x
ft.Dropdown(
    label="最低匹配标签数",
    value="1",
    on_select=lambda _e: self._save(),     # NOT on_change
    options=[ft.dropdown.Option(str(i)) for i in range(1, 11)],
    border_radius=12,
)
```

| Feature | ❌ Old / Wrong | ✅ Flet 0.85.x |
|---|---|---|
| Selection event | `on_change=...` | `on_select=...` |

### Switch

```python
# ✅ CORRECT — Flet 0.85.x
ft.Switch(
    label="自动同意好友申请",
    value=False,
    on_change=lambda _e: self._save(),     # on_change still works for Switch
    active_color=ft.Colors.DEEP_PURPLE_500,
)
```

| Feature | ❌ Old / Wrong | ✅ Flet 0.85.x |
|---|---|---|
| Toggle event | `on_change=...` ✅ | `on_change=...` ✅ same |

### Buttons — Prefer standard buttons over GestureDetector in scrollable containers

`ft.ElevatedButton` is **deprecated since Flet 0.80.0** (removed in 1.0). Use `ft.Button` — it is a drop-in replacement with the same constructor signature (`content`, `icon`, `bgcolor`, `color`, `on_click`, `style`, …).

```python
# ✅ CORRECT — use standard buttons for click actions
ft.Button("保存", on_click=self._save, ...)
ft.OutlinedButton("选择图片", on_click=browse, ...)
ft.IconButton(icon=ft.Icons.ADD, on_click=self._add, ...)
ft.TextButton("取消", on_click=close, ...)

# ❌ WRONG — deprecated, will be removed in Flet 1.0
ft.ElevatedButton("保存", on_click=self._save, ...)

# ❌ AVOID — GestureDetector.on_tap is unreliable inside scrollable Columns
ft.GestureDetector(
    mouse_cursor=ft.MouseCursor.CLICK,
    on_tap=self._save,           # May never fire inside scroll=ScrollMode.AUTO
    content=ft.Container(...)
)
```

### FilePicker

```python
# ✅ CORRECT — FilePicker is a Service in Flet 0.85+, NOT an overlay control
picker = ft.FilePicker()
page.services.append(picker)     # Add to services, NOT page.overlay
```

### Icons

```python
# ✅ CORRECT — Flet 0.85.x icon names
ft.Icons.TAG_ROUNDED
ft.Icons.ADD_CIRCLE_ROUNDED
ft.Icons.CLOSE_ROUNDED
ft.Icons.HOURGLASS_EMPTY_ROUNDED
ft.Icons.REFRESH_ROUNDED

# ❌ WRONG — Old naming scheme
ft.icons.TAG_ROUNDED
```

### Colors

```python
# ✅ CORRECT — Flet 0.85.x
ft.Colors.DEEP_PURPLE_400
ft.Colors.GREEN_400
ft.Colors.RED_400
ft.Colors.SURFACE_CONTAINER_LOW
ft.Colors.ON_SURFACE_VARIANT
ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE)

# ❌ WRONG — Old naming scheme
ft.colors.DEEP_PURPLE_400
```

### Theme / Page

```python
# ✅ CORRECT
page.theme_mode = ft.ThemeMode.SYSTEM
page.padding = ft.padding.only(top=40, left=0, right=0, bottom=0)
page.fonts = {"Noto Sans SC": "fonts/NotoSansSC.ttf"}

ft.Theme(
    color_scheme_seed=ft.Colors.DEEP_PURPLE,
    visual_density=ft.VisualDensity.COMFORTABLE,
    font_family="Noto Sans SC",
)
```

### Containers with gradients and shadows

```python
# ✅ CORRECT
ft.Container(
    gradient=ft.LinearGradient(
        begin=ft.alignment.Alignment.CENTER_LEFT,
        end=ft.alignment.Alignment.CENTER_RIGHT,
        colors=[ft.Colors.DEEP_PURPLE_400, ft.Colors.PURPLE_300],
    ),
    shadow=ft.BoxShadow(
        blur_radius=10,
        color=ft.Colors.with_opacity(0.18, ft.Colors.DEEP_PURPLE_400),
        offset=ft.Offset(0, 3),
    ),
    border=ft.Border(
        bottom=ft.BorderSide(1, ft.Colors.with_opacity(0.06, ft.Colors.ON_SURFACE))
    ),
    border_radius=999,
    animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
)
```

### Platform detection

```python
# ✅ CORRECT
is_mobile = str(page.platform) in ("PagePlatform.ANDROID", "PagePlatform.IOS")
```

---

## Project Architecture

### Layer boundaries (DO NOT VIOLATE)

| Layer | Path | Allowed to access |
|---|---|---|
| Frontend (Views) | `core/frontend/views/` | `app.*` public methods only |
| App Controller | `core/frontend/app.py` (+ `app_runtime` / `app_shell` / `app_service_facade`) | `runtime`, `friend_db`, `message_service` |
| Runtime | `core/backend/services/social_runtime.py` | All backend services |
| Services | `core/backend/services/` | `friend_db`, `shared/*`, `config/*` |
| Shared | `core/backend/shared/` | Nothing else |
| Config | `core/config/` | Nothing else |

**Rules**:
- Views call `self.app.method_name()` — never directly access `self.app.runtime.some_internal`
- Views do NOT import from `core/backend/services/` directly
- Views do NOT access SQLite, raw sockets, or backend locks

### File responsibilities

The backend was split from a few monolithic files into focused repositories and services. Each original file now delegates to its sub-modules.

#### Backend services (`core/backend/services/`)

| File | Responsibility |
|---|---|
| `friend_db.py` | Facade over the friend/profile/message repositories — SQLite schema, locks, connection; delegates CRUD to the `*_repository` modules |
| `friend_repository.py` | CRUD for accepted friends |
| `friend_category_repository.py` | Friend category (分组) records |
| `friend_request_repository.py` | Friend request state persistence |
| `social_repository.py` | Groups and moments persistence |
| `message_repository.py` | Direct chat history and pending relay messages |
| `notification_repository.py` | System notification rows |
| `profile_repository.py` | Local profile and matching-condition persistence |
| `message_service.py` | Message routing facade — delegates to relay/delivery/transfer sub-services |
| `message_relay_service.py` | Heartbeat flood and RELAY_MESSAGE routing |
| `chat_delivery_service.py` | Direct chat-message send/receive |
| `pending_message_flusher.py` | Replay cached offline messages when a friend comes online |
| `file_transfer_service.py` | File transfer control flow (send side) |
| `file_receive_service.py` | Incoming file-offer and receive-side handling (chunking, hashing, disk write) |
| `file_transfer_state.py` | Transfer lifecycle state (senders, receivers, pause/cancel) |
| `file_store.py` | File-on-disk helpers (paths, integrity) |
| `friend_request_service.py` | FRIEND_REQUEST / FRIEND_ACCEPT / FRIEND_DELETE protocol flow |
| `profile_sync_service.py` | Profile sync notice/request/response protocol |
| `social_sync_service.py` | Group chat and moments broadcast sync |
| `connection_manager.py` | TCP connection pool, send/receive, heartbeat — delegates registry/maintenance |
| `connection_registry.py` | Thread-safe endpoint→socket registry (alive-socket preference) |
| `connection_maintenance.py` | Background heartbeat broadcast and local-IP-change notification |
| `udp_service.py` | UDP broadcast, device discovery, cleanup — delegates state/router |
| `udp_discovery_state.py` | Thread-safe discovery state (DeviceInfo) |
| `udp_packet_router.py` | Parsed UDP packet → discovery state changes + callbacks |
| `social_service.py` | Friend cards, chat list aggregation |
| `social_runtime.py` | Lifecycle, callback wiring, orchestration |
| `network_policy.py` | Network allow/deny policy |
| `update_service.py` | App update checking |

#### Shared (`core/backend/shared/`)

| File | Responsibility |
|---|---|
| `protocol.py` | Wire protocol constants and message builders |
| `file_message.py` | Encode/decode file message cards for chat |
| `helpers.py` | Shared utility functions |

#### Frontend (`core/frontend/`)

| File | Responsibility |
|---|---|
| `app.py` | `BeiyangApp` controller — wires runtime, shell, and facade |
| `app_runtime.py` | Build `SocialRuntime` and bind UI callbacks |
| `app_shell.py` | Construct Flet page shell and view instances |
| `app_service_facade.py` | Thin service/db methods exposed to views via `app.*` |
| `views/chat.py` | `ChatView` — delegates rendering/layout/controllers to sub-modules |
| `views/chat_bubble_renderer.py` | Build text/code/file message bubbles |
| `views/chat_layout.py` | Chat tab and chat-window frame builder |
| `views/chat_notifications.py` | System notification panel for chat |
| `views/chat_group_controller.py` | Group info / create / settings dialogs |
| `views/chat_file_offer_controller.py` | Inline file-offer widgets (queue, accept/decline) |
| `views/chat_file_tools.py` | File-message codec and platform helpers |
| `views/chat_transfer_controller.py` | Transfer UI state, speed, stuck-transfer refresh |
| `views/profile.py` | `ProfileView` — delegates settings/tags/media/update to sub-modules |
| `views/profile_settings.py` | Settings controls and layout |
| `views/profile_settings_controller.py` | Network / receive-dir / privacy actions |
| `views/profile_tags.py` | QQ-style tag input controls |
| `views/profile_media_controller.py` | Avatar/background pick, crop, preview |
| `views/profile_update_controller.py` | App update workflow |

### Paths — never hardcode

```python
# ✅ CORRECT
from core.config.paths import get_app_paths
paths = get_app_paths()
db = paths.resolve_db_path("friends.db")       # → .runtime/<instance>/data/friends.db
avatar = paths.asset_src("avatars/boy.png")     # → avatars/boy.png (Flet asset path)

# ❌ WRONG
db_path = "assets/data/friends.db"
avatar = "assets/avatars/boy.png"
```

---

## Code Patterns

### Thread safety

All `friend_db` write operations MUST use `with self._lock:`. Read operations that run outside the lock should not depend on consistency with writes.

```python
# ✅ CORRECT
def save_profile(self, profile):
    with self._lock:
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM my_profile")
        cursor.execute("INSERT INTO my_profile (...) VALUES (...)")
        self.conn.commit()
```

### Connection registration — prefer alive socket

When `_register_connection` finds an existing entry for the same endpoint, prefer the existing socket if it's still alive (`getpeername()` succeeds). Close the new duplicate socket instead. Only replace when the old socket is genuinely dead.

```python
# ✅ CORRECT
if self._socket_alive(old_sock):
    new_sock.close()
    return key           # keep existing connection
# old socket dead → replace with new
old_sock.close()
```

### File transfer progress

- Speed is calculated via a sliding window (3 seconds), NOT a single-sample division
- `_emit_file_progress` throttles to max 8 Hz (125 ms) with 5% threshold forcing
- Sender passes `confirmed` bytes (from receiver ACK) so UI shows both "sent" and "confirmed"
- Receiver tracks `_bytes_written` (actual file pointer position), not `chunk_count × chunk_size`

### Auto-save pattern (profile / settings)

Fields auto-save on `on_blur` (TextField) or `on_select` (Dropdown) / `on_change` (Switch). There is no global "Save" button inside scrollable containers — `GestureDetector.on_tap` is unreliable there.

**CRITICAL**: Always track field values in `_draft_*` variables via `on_change`. In `_auto_save`, read from `_draft_*` (not `control.value`) to guard against event-ordering edge cases where `on_blur`/`on_tap_outside` fires before the last `on_change` value sync completes.

```python
# ✅ CORRECT — draft-value pattern
def __init__(self, app):
    self._draft_bio = ""  # updated on every keystroke

    self.bio_in = ft.TextField(
        label="个人简介",
        multiline=True,
        on_change=lambda e: setattr(self, '_draft_bio', e.control.value or ''),
        on_blur=lambda _e: self._auto_save("bio"),
        on_tap_outside=lambda _e: self._auto_save("bio"),  # catches taps on non-focusable areas
        ...
    )

def _auto_save(self, source=""):
    profile = {
        "bio": (self._draft_bio or self.bio_in.value or "").strip(),
        # ^ draft first, control value as fallback
    }
```

Use BOTH `on_blur` AND `on_tap_outside` for multiline TextField — `on_blur` only fires when focus moves to another focusable control; `on_tap_outside` fires for ANY tap outside the field.

---

## Android Compatibility (MANDATORY)

The project targets Android via a Flutter + `serious_python_android` APK (`build/flutter/`). Every change must keep Android working.

### Platform detection

```python
# ✅ CORRECT — detect Android at runtime
def _is_android() -> bool:
    if hasattr(os, "getandroidapplication"):
        return True
    if "ANDROID_ARGUMENT" in os.environ or "ANDROID_APP_PATH" in os.environ:
        return True
    return False

# For Flet page-level decisions:
is_mobile = str(page.platform) in ("PagePlatform.ANDROID", "PagePlatform.IOS")
```

### File opening — NEVER use os.startfile / xdg-open on Android

`os.startfile` is Windows-only.  `xdg-open` does not exist on Android.  Always branch:

```python
if _is_android():
    subprocess.run(["am", "start", "-a", "android.intent.action.VIEW",
                    "-d", f"file://{path}", "-t", "*/*"], check=False)
elif system == "Windows":
    os.startfile(file_path)
elif system == "Darwin":
    subprocess.run(["open", file_path], check=True)
else:  # Linux
    subprocess.run(["xdg-open", file_path], check=False)
```

### File picker — always try tkinter, fall back to Flet FilePicker

```python
try:
    import tkinter as tk
except ImportError:
    await self._pick_file_flet()   # Android path
    return
# … tkinter filedialog for desktop …
```

### Window settings — skip on mobile

```python
if not is_mobile:
    page.window_width = 460
    page.window_height = 820
    page.window.icon = str(icon_path.resolve())
```

### UDP MulticastLock — REQUIRED on Android

Without a WiFi MulticastLock, the Android WiFi chipset enters power-save and
stops delivering UDP broadcast packets.  `udp_service.start()` acquires the
lock via `jnius.autoclass`; `udp_service.stop()` releases it.

### Paths — assets may be READ-ONLY on Android

Android APK assets are inside the read-only APK file.  `paths.py` automatically
relocates writable directories (`data/`, `received_files/`, `received_avatars/`)
into the app's private storage when `_is_android()` returns True.  Never write
to `assets/` at runtime.

### NEVER do these on Android

| ❌ Forbidden | Reason |
|---|---|
| `os.startfile(path)` | Windows-only API |
| `subprocess.run(["xdg-open", ...], check=True)` | `xdg-open` doesn't exist |
| `tk.Tk()` without try/except | tkinter not available |
| `page.window.icon = "app_icon.ico"` | `.ico` is Windows-only |
| Hardcoded `/tmp/` or `C:\` paths | Use `paths.data_dir` |
| `platform.system()` for Android detection | Android reports `"Linux"`; use `_is_android()` first |

---

## Testing

Run all tests:
```powershell
python -m pytest core/tests -q
```

Tests that create temp directories (`tmp_path` fixture) may error on Windows with `PermissionError: [WinError 5]` when the default basetemp (`%TEMP%\pytest-of-<user>`) is not writable. This is an environment issue, not a code bug. Redirect basetemp to a writable path to confirm:

```powershell
python -m pytest core/tests -q --basetemp="./pytest_basetemp"
```

---

## Git

- Current branch: `main`
- Remote: `https://github.com/Ortenssia/Meeting-in-Beiyang.git`
- Commit messages end with: `Co-Authored-By: Claude <noreply@anthropic.com>`
