#!/usr/bin/env python3
"""Database Seeding Script for Relationship OS.

Initializes default accounts, canonical conversation room, and active enrollment token.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone
from sqlalchemy import select

import secrets

# Ensure project root in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from apps.api.src.core.database import AsyncSessionLocal, engine, Base
from apps.api.src.models.user import User
from apps.api.src.services.auth_service import AuthService
from apps.api.src.services.message_service import MessageService
from packages.shared.src.constants import UserRole


async def seed():
    print("\n" + "=" * 64)
    print("           ♥ Relationship OS Database Seeder ♥                  ")
    print("=" * 64)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # 1. Seed or find Owner
        owner_res = await db.execute(select(User).where(User.username == "owner"))
        owner = owner_res.scalar_one_or_none()
        owner_pass = os.getenv("SEED_OWNER_PASSWORD") or f"Owner_{secrets.token_urlsafe(12)}"

        if not owner:
            owner = await AuthService.create_user(
                db=db,
                username="owner",
                display_name="Owner (Primary)",
                password=owner_pass,
                role=UserRole.OWNER,
            )
            print("[+] Created Owner account: username='owner'")
        else:
            print("[*] Owner account already exists: username='owner'")

        # 2. Seed or find Recipient
        recipient_res = await db.execute(select(User).where(User.username == "recipient"))
        recipient = recipient_res.scalar_one_or_none()
        recipient_pass = os.getenv("SEED_RECIPIENT_PASSWORD") or f"Recipient_{secrets.token_urlsafe(12)}"

        if not recipient:
            recipient = await AuthService.create_user(
                db=db,
                username="recipient",
                display_name="Recipient (Partner)",
                password=recipient_pass,
                role=UserRole.RECIPIENT,
            )
            print("[+] Created Recipient account: username='recipient'")
        else:
            print("[*] Recipient account already exists: username='recipient'")

        # 3. Create or fetch canonical direct conversation
        conv = await MessageService.get_or_create_private_conversation(
            db=db,
            owner_id=owner.id,
            recipient_id=recipient.id,
            title="Private Sanctuary",
        )
        print(f"[+] Canonical Conversation Room ID: {conv.id}")

        # 4. Generate fresh Enrollment Token for recipient
        raw_token = await AuthService.create_enrollment_token(
            db=db,
            user_id=recipient.id,
            device_name="Primary Terminal",
            platform="cross-platform",
            expires_hours=72,
        )
        await db.commit()

        print("\n" + "-" * 64)
        print("SEEDING COMPLETE. READY FOR INSTANT COMMUNICATION:")
        print("-" * 64)
        print("🌐 Web Application:       http://localhost:8000")
        print(f"👑 Owner Login:           Username: 'owner' | Password: '{owner_pass}'")
        print(f"💌 Recipient Login:       Username: 'recipient' | Password: '{recipient_pass}'")
        print(f"🔑 Recipient Token:       {raw_token}")
        print("\n🚀 Recipient Instant Terminal Launch Commands:")
        print(f"   Linux / macOS:")
        print(f"   ./apps/launcher/launch.sh http://localhost:8000 {raw_token}")
        print(f"\n   Windows PowerShell:")
        print(f"   .\\apps\\launcher\\Launch-RelationshipOS.ps1 -ServerUrl http://localhost:8000 -EnrollmentToken {raw_token}")
        print("=" * 64 + "\n")


if __name__ == "__main__":
    asyncio.run(seed())
