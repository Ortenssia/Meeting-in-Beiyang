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
45 passed
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
  core/         Business/runtime core: protocol, helpers, services, storage
  screens/      Kivy UI screens
  services/     Compatibility imports for older code paths
  utils/        Compatibility imports for older code paths
tests/          Unit tests for protocol, database, and social flow
assets/         Project assets placeholder for future images, icons, and media
main.py         Application entry point
buildozer.spec  Android packaging configuration
received_files/ Local inbox for files received from friends
```

## Runtime Architecture

`code_share/core` is the non-UI boundary. `SocialRuntime` owns identity loading,
UDP discovery, TCP connections, relationship updates, message relay, file
transfer callbacks, lifecycle start/stop, and health diagnostics. Screens should
call the App-level methods instead of touching lower-level services directly.
