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
python main.py
```

Optional runtime arguments:

```powershell
python main.py --port 7779 --udp-port 8890 --db friends.db --name Alice
```

Same-machine two-user test:

```powershell
python main.py --name Alice --port 7779 --udp-port 8890 --db alice.db
python main.py --name Bob --port 7780 --udp-port 8891 --db bob.db
```

The two instances must use different database files so they get different
user/device identities. UDP discovery probes loopback, local interface IPs,
broadcast addresses, and common discovery ports for this workflow.

## Run Tests

```powershell
python -m pytest -q
```

Current validation result:

```text
44 passed
```

## Android Build

Build outputs are intentionally not tracked in Git. To create a local APK, use
Buildozer from this project directory:

```bash
buildozer android debug
```

## Project Layout

```text
code_share/
  screens/      Kivy UI screens
  services/     Social runtime, UDP discovery, TCP connection pool, message relay, SQLite storage
  utils/        Protocol and helper functions
tests/          Unit tests for protocol, database, and social flow
main.py         Application entry point
buildozer.spec  Android packaging configuration
received_files/ Local inbox for files received from friends
```

## Runtime Architecture

`SocialRuntime` is the boundary between the Kivy UI and the P2P system. It owns
identity loading, UDP discovery, TCP connections, relationship updates, message
relay, file transfer callbacks, lifecycle start/stop, and health diagnostics.
Screens should call the App-level methods instead of touching lower-level
services directly.
