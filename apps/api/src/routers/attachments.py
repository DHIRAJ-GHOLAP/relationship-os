"""Attachment preparation, validation, and storage router."""

import os
import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.src.core.database import get_db
from apps.api.src.core.security import get_current_user_and_session
from apps.api.src.core.exceptions import AppException, NotFoundException
from apps.api.src.models.attachment import Attachment
from apps.api.src.services.storage_service import storage_provider, validate_attachment
from packages.shared.src.constants import ErrorCode

router = APIRouter(prefix="/api/v1/attachments", tags=["Attachments"])


class PrepareAttachmentRequest(BaseModel):
    filename: str
    file_size: int
    mime_type: str


class PrepareAttachmentResponse(BaseModel):
    attachment_id: str
    filename: str
    upload_url: str
    mime_type: str


@router.post("/prepare", response_model=PrepareAttachmentResponse)
async def prepare_attachment(
    body: PrepareAttachmentRequest,
    auth=Depends(get_current_user_and_session),
    db: AsyncSession = Depends(get_db),
):
    """Validate file metadata and issue an authorized upload target."""
    safe, reason = validate_attachment(body.filename, body.file_size, body.mime_type)
    if not safe:
        raise AppException(ErrorCode.INVALID_REQUEST, f"Attachment rejected: {reason}")

    # Generate safe unique storage path
    file_uuid = str(uuid.uuid4())
    _, ext = os.path.splitext(body.filename)
    safe_storage_name = f"{file_uuid}{ext.lower()}"

    attachment = Attachment(
        id=file_uuid,
        message_id=None,  # Linked upon message send
        filename=body.filename,
        file_size=body.file_size,
        mime_type=body.mime_type,
        storage_path=safe_storage_name,
        created_at=datetime.now(timezone.utc),
    )
    db.add(attachment)
    await db.flush()

    upload_url = await storage_provider.create_upload_url(attachment.id, body.mime_type)

    return PrepareAttachmentResponse(
        attachment_id=attachment.id,
        filename=body.filename,
        upload_url=upload_url,
        mime_type=body.mime_type,
    )


@router.post("/upload/{attachment_id}")
async def upload_attachment_file(
    attachment_id: str,
    file: UploadFile = File(...),
    auth=Depends(get_current_user_and_session),
    db: AsyncSession = Depends(get_db),
):
    """Receive and store binary content for a prepared attachment."""
    query = select(Attachment).where(Attachment.id == attachment_id)
    att = (await db.execute(query)).scalar_one_or_none()
    if not att:
        raise NotFoundException("Attachment preparation record not found")

    content = await file.read()
    if len(content) > att.file_size * 1.1:  # sanity check against declared size
        raise AppException(ErrorCode.INVALID_REQUEST, "Uploaded content exceeds prepared size")

    await storage_provider.put(att.storage_path, content, att.mime_type)
    return {"message": "Attachment uploaded successfully", "id": attachment_id}


@router.get("/download/{attachment_id}")
async def download_attachment_file(
    attachment_id: str,
    auth=Depends(get_current_user_and_session),
    db: AsyncSession = Depends(get_db),
):
    """Download stored attachment content with safe response headers."""
    query = select(Attachment).where(Attachment.id == attachment_id)
    att = (await db.execute(query)).scalar_one_or_none()
    if not att:
        raise NotFoundException("Attachment not found")

    content = await storage_provider.get(att.storage_path)
    return Response(
        content=content,
        media_type=att.mime_type,
        headers={
            "Content-Disposition": f'inline; filename="{att.filename}"',
        },
    )
