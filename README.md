# Meeting in Beiyang

Challenge 3 project for a campus social networking app, originally named "相识北洋".

The app is built with Python and Kivy. It supports peer discovery, friend requests,
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
- Offline message cache and relay forwarding
- Android packaging with Buildozer

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
python core/main.py --name Alice --port 7779 --udp-port 8890 --db alice.db
python core/main.py --name Bob --port 7780 --udp-port 8891 --db bob.db
```

The two instances must use different database files so they get different
user/device identities. UDP discovery probes loopback, local interface IPs,
broadcast addresses, and common discovery ports for this workflow.
Database files created from plain names such as `alice.db` are stored under
`assets/data/`.

## Run Tests

```powershell
python -m pytest core/tests -q
```

Current validation result:

```text
47 passed
```

## Android Build

Build outputs are intentionally not tracked in Git. To create a local APK, use
Buildozer from this project directory:

```bash
buildozer android debug
```

## Project Layout

```text
core/           Application code: UI screens, runtime, protocol, services, storage
  tests/        Unit tests for protocol, database, and social flow
assets/         Project assets, local databases, and received files
  data/         Local SQLite databases (ignored except .gitkeep)
  received_files/ Local inbox for files received from friends
core/main.py    Application entry point
buildozer.spec  Android packaging configuration
```

## Runtime Architecture

`core` is the application code boundary. `SocialRuntime` owns identity loading,
UDP discovery, TCP connections, relationship updates, message relay, file
transfer callbacks, lifecycle start/stop, and health diagnostics. Screens should
call the App-level methods instead of touching lower-level services directly.
