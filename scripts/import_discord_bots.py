#!/usr/bin/env python3
"""Securely import and configure multi-bot Discord failover pool from Ai Civilization.

Extracts bot tokens and channel ID, configures local .env without leaking secrets to stdout.
"""

import os
from pathlib import Path

ENV_SOURCE = Path("/home/flash/Documents/Ai Civilization/.env")
TARGET_ENV = Path(__file__).resolve().parent.parent / ".env"

BOT_KEYS = [
    "DISCORD_TOKEN_HOST",
    "DISCORD_TOKEN_ALICE",
    "DISCORD_TOKEN_JOHN",
    "DISCORD_TOKEN_MIA",
    "DISCORD_TOKEN_RICK",
    "DISCORD_TOKEN_LEO",
]


import sys

def main():
    if not ENV_SOURCE.is_file():
        print(f"[!] Source .env not found at {ENV_SOURCE}")
        return

    source_vars = {}
    with open(ENV_SOURCE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            source_vars[key.strip()] = val.strip().strip('"').strip("'")

    # Use channel provided via CLI arg or default to the user-specified channel
    channel_id = sys.argv[1] if len(sys.argv) > 1 else "1545735336926388354"
    guild_id = "1304086099265589279"
    discovered_bots = []


    for k in BOT_KEYS:
        val = source_vars.get(k)
        if val:
            name = k.replace("DISCORD_TOKEN_", "")
            discovered_bots.append((name, val))

    if not discovered_bots:
        print("[!] No Discord bot tokens found in source .env")
        return

    primary_name, primary_token = discovered_bots[0]
    backup_tokens = [token for _, token in discovered_bots[1:]]
    backup_names = [name for name, _ in discovered_bots[1:]]

    # Read existing target .env or create new
    existing_lines = []
    if TARGET_ENV.is_file():
        with open(TARGET_ENV, "r", encoding="utf-8") as f:
            for line in f:
                # Filter out previous discord settings
                if not any(
                    line.startswith(prefix)
                    for prefix in [
                        "DISCORD_ENABLED=",
                        "DISCORD_BOT_TOKEN=",
                        "DISCORD_BACKUP_TOKENS=",
                        "DISCORD_CHANNEL_ID=",
                        "DISCORD_GUILD_ID=",
                    ]
                ):
                    existing_lines.append(line.rstrip("\n"))

    existing_lines.extend([
        "",
        "# Discord Multi-Bot Failover Pool",
        "DISCORD_ENABLED=true",
        f'DISCORD_BOT_TOKEN="{primary_token}"',
        f'DISCORD_BACKUP_TOKENS="{",".join(backup_tokens)}"',
        f'DISCORD_CHANNEL_ID="{channel_id}"',
        f'DISCORD_GUILD_ID="{guild_id}"',
    ])

    with open(TARGET_ENV, "w", encoding="utf-8") as f:
        f.write("\n".join(existing_lines) + "\n")

    os.chmod(TARGET_ENV, 0o600)

    print("=" * 64)
    print("      ♥ Discord Multi-Bot Failover Pool Configured ♥           ")
    print("=" * 64)
    print(f"[✓] Primary Bot:     {primary_name}")
    print(f"[✓] Backup Bots:      {', '.join(backup_names)} ({len(backup_names)} backups)")
    print(f"[✓] Target Channel:  {channel_id}")
    print(f"[✓] Local Config:    {TARGET_ENV} (Permissions: 0600)")
    print("[✓] Failover Policy: If primary bot encounters rate limits or errors,")
    print("                     the adapter automatically fails over sequentially.")
    print("=" * 64)


if __name__ == "__main__":
    main()
