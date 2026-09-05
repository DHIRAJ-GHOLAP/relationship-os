"""Secure local credential storage for CLI client across Windows, Linux, and macOS."""

import os
import sys
import json
import stat
from typing import Dict, Optional


def get_credential_dir() -> str:
    """Resolve OS-appropriate protected configuration directory."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        cred_dir = os.path.join(base, "RelationshipOS")
    else:
        cred_dir = os.path.join(os.path.expanduser("~"), ".relationship_os")

    os.makedirs(cred_dir, mode=0o700, exist_ok=True)
    return cred_dir


def get_credential_file() -> str:
    return os.path.join(get_credential_dir(), "credentials.json")


def save_credentials(token: str, server_url: str, user_id: str, username: str, conversation_id: str) -> None:
    """Store credentials with locked file permissions (0600 on Unix)."""
    filepath = get_credential_file()
    data = {
        "access_token": token,
        "server_url": server_url,
        "user_id": user_id,
        "username": username,
        "conversation_id": conversation_id,
    }

    # Write file
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    mode = 0o600  # User read/write only

    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    fd = os.open(filepath, flags, mode)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)

    # Re-enforce permissions
    try:
        os.chmod(filepath, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass


def load_credentials() -> Optional[Dict[str, str]]:
    """Retrieve stored credentials if available."""
    filepath = get_credential_file()
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except Exception:
        return None


def clear_credentials() -> None:
    """Remove stored credentials on logout."""
    filepath = get_credential_file()
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
        except Exception:
            pass
