# Meeting in Beiyang

Challenge 3 project for a campus social networking app, originally named "相识北洋".

The app is built with Python and Flet. It supports peer discovery, friend requests,
profile-based matching, friend management, chat history, IP mobility updates, and
offline message relay through online friends.

## Features

- UDP LAN discovery for nearby users
- TCP peer connections between friends
- Personal profile and friend matching conditions
- Automatic or manual friend request approval
- Friend categories, search, removal, and online status
- Chat screen with persisted message history
- Direct P2P file transfer between online friends with chunking and SHA-256 checks
- Configurable received-file save directory with persisted local setting
- File cards can open, reveal, copy path, cancel active transfers, and unzip zip files
- Offline message cache and relay forwarding

## UI

The app uses [Flet](https://flet.io) for its UI layer (Material 3, follows the
system light/dark setting). The UI lives under `core/frontend/` and only talks
to the service layer through the `BeiyangApp` controller — it never touches
UDP/TCP/SQLite directly.

Runtime paths are resolved by `core/config/paths.py`. Do not hard-code asset,
database, font, or received-file paths in UI or service code. Writable
locations can be overridden with environment variables such as
`BEIYANG_DATA_DIR` and `BEIYANG_RECEIVED_DIR`, while bundled image/font assets
remain under the configured Flet assets directory.

## Run Locally

```powershell
pip install -r requirements.txt
python core/main.py
```

Optional runtime arguments:

```powershell
python core/main.py --port 7779 --udp-port 8890 --db friends.db --name Alice
```

Same-machine two-user test:

```powershell
python core/main.py --instance alice --name Alice --port 7779 --udp-port 8890
python core/main.py --instance bob --name Bob --port 7780 --udp-port 8891
```

Or start both instances with one command:

```powershell
powershell -ExecutionPolicy Bypass -File operations/run_local_pair.ps1
```

`--instance` gives each process an isolated database, received-file directory,
and avatar cache under `.runtime/<instance>/`. The bundled assets remain shared.
The two processes must still use different TCP and UDP listening ports. UDP
discovery probes loopback, local interface IPs, broadcast addresses, and the
local test discovery ports, so Alice and Bob can find each other on one PC.

Normal launches use concise `INFO` logging. Use `--log-level DEBUG` only when
framework-level diagnostics are intentionally needed.

## Run Tests

```powershell
python -m pytest core/tests -q
```

Current validation result:

```text
91 passed
```

## Project Layout

```text
core/           Application code, split by responsibility
  config/       Path/platform configuration; no UI or network logic
  frontend/     Frontend: theme, widgets, views, app controller
    views/      One module per screen (discover/friends/chat/profile/settings)
  backend/      Backend package
    services/   Discovery, TCP, messaging, SQLite persistence
    shared/     Protocol and host/network helpers shared by backend services
  ops/          Operational bootstrap and launch helpers
  tests/        Unit tests for protocol, database, and social flow
assets/         Bundled assets plus default local desktop data locations
  avatars/      Built-in profile images referenced by asset-relative paths
  data/         Local SQLite databases (ignored except .gitkeep)
  received_files/ Local inbox for files received from friends
core/main.py    Application entry point
operations/     Local operational scripts, including two-instance testing
```

## Runtime Architecture

`core` is the application code boundary:

- Frontend: `core/frontend/` builds Flet controls and calls App-level methods.
- Backend: `core/backend/services/` owns identity loading, UDP discovery, TCP
  connections, relationship updates, message relay, file transfer callbacks,
  lifecycle start/stop, and health diagnostics.
- Shared backend helpers: `core/backend/shared/` owns protocol constants and
  host/network utility functions plus message payload formats shared with UI.
- File-transfer storage rules live in `core/backend/services/file_store.py` so
  filename safety, collision handling, and hashing do not leak into UI code.
- File-transfer runtime state lives in
  `core/backend/services/file_transfer_state.py` so send/receive/cancel/resume
  bookkeeping is not scattered through the message service or UI.
- Operations: `core/ops/` prepares imports, working directory, and launch-time
  setup.
- Configuration: `core/config/` owns path and platform decisions.

Screens should call the App-level methods instead of touching lower-level
services directly.
