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

## Run Tests

```powershell
python -m pytest -q
```

Current validation result:

```text
27 passed
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
  services/     UDP discovery, TCP connection pool, message relay, SQLite storage
  utils/        Protocol and helper functions
tests/          Unit tests for protocol, database, and social flow
main.py         Application entry point
buildozer.spec  Android packaging configuration
```
