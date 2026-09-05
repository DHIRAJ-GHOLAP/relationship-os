# Relationship OS - Terminal Client Guide

The Relationship OS Terminal Client is an ultra-lightweight, resilient, full-fidelity terminal interface built with **Python Rich**. It allows the recipient or owner to chat in real-time directly from any command-line environment.

---

## 1. Quick Launch (Safe Launchers)

### On Windows PowerShell (5.1+ or Core 7+)
```powershell
.\apps\launcher\Launch-RelationshipOS.ps1 -ServerUrl http://localhost:8000 -EnrollmentToken <YOUR_TOKEN>
```
*Features:*
- Validates local Python 3.8+ installation.
- Creates an isolated user environment in `$env:LOCALAPPDATA\relationship_os\venv`.
- Prints and verifies SHA-256 integrity hashes.
- No blind piping; fully inspectable.

### On Linux & macOS (Bash / Zsh)
```bash
./apps/launcher/launch.sh http://localhost:8000 <YOUR_TOKEN>
```

---

## 2. Direct Invocation

If working directly from a cloned repository with the local virtual environment:

```bash
PYTHONPATH=. .venv/bin/python3 apps/cli/src/cli.py \
  --server http://localhost:8000 \
  --enroll <YOUR_TOKEN>
```

Subsequent launches from the same machine do not require the `--enroll` token; the client persists an authenticated session in secure local storage.

---

## 3. Storage & Local Security

- **Session File Location:** `~/.relationship_os/session.json` (or `%LOCALAPPDATA%\relationship_os\session.json` on Windows).
- **File Permissions:** Enforced as `0600` (`-rw-------`) on Unix systems, preventing other local users from reading cached tokens or session credentials.
- **Content:** Stores the active session token, server URL, authenticated user profile, and cached conversation ID.

---

## 4. Terminal Interface Features

```
╭─────────────────────── ♥ Relationship OS Terminal ♥ ───────────────────────╮
│ Room: Private Sanctuary | Connected to: http://localhost:8000              │
╰─────────────────────────────────────────────────────────────────────────────╯
╭─ Chat History ──────────────────────────────────────────────────────────────╮
│ [14:02:11] (Owner): Welcome to Relationship OS!                            │
│ [14:03:45] (You): Everything is running smoothly.                          │
│                                                                             │
╰─────────────────────────────────────────────────────────────────────────────╯
╭─ Status ───────────────────────────────────────────────────────────────────╮
│ Status: Connected (WebSocket) | Sequence: 42 | Unread: 0                   │
╰─────────────────────────────────────────────────────────────────────────────╯
> Message: 
```

### 4.1 In-Chat Commands
- `/help` - Displays the command quick reference.
- `/sync` - Forces a resynchronization of message history from the server.
- `/clear` - Clears the terminal screen buffer.
- `/quit` or `/exit` - Disconnects cleanly and closes the terminal client.

### 4.2 Network Resilience & Reconnection
- If the network drops, the CLI transitions to an automatic reconnection state with exponential backoff (1s, 2s, 4s, 8s, up to 30s).
- Upon reconnecting, it requests all missing messages using `sync` with `after_sequence = <last_seen_seq>`, ensuring zero lost messages.
