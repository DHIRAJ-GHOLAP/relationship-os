"""Storage abstraction and file attachment validation service."""

import os
import uuid
import aiofiles
from abc import ABC, abstractmethod
from typing import Dict, Optional, Tuple
from fastapi import UploadFile

from apps.api.src.core.config import settings
from apps.api.src.core.exceptions import AppException
from packages.shared.src.constants import ErrorCode

FORBIDDEN_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".sh", ".ps1", ".vbs", ".msi",
    ".scr", ".pif", ".com", ".jar", ".dll", ".so", ".bin",
}


class StorageProvider(ABC):
    """Abstract storage interface allowing future S3 / CloudVaulter backends."""
    @abstractmethod
    async def put(self, file_path: str, content: bytes, content_type: str) -> str:
        pass

    @abstractmethod
    async def get(self, file_path: str) -> bytes:
        pass

    @abstractmethod
    async def delete(self, file_path: str) -> bool:
        pass

    @abstractmethod
    async def create_upload_url(self, file_path: str, content_type: str) -> str:
        pass

    @abstractmethod
    async def create_download_url(self, file_path: str) -> str:
        pass


class LocalStorageProvider(StorageProvider):
    """Local filesystem storage provider."""
    def __init__(self, base_dir: str = settings.STORAGE_LOCAL_DIR):
        self.base_dir = os.path.abspath(base_dir)
        os.makedirs(self.base_dir, exist_ok=True)

    def _get_abs_path(self, file_path: str) -> str:
        # Prevent path traversal
        clean_path = os.path.normpath(file_path).lstrip("/")
        abs_target = os.path.abspath(os.path.join(self.base_dir, clean_path))
        if not abs_target.startswith(self.base_dir):
            raise AppException(ErrorCode.FORBIDDEN, "Path traversal detected in storage path")
        return abs_target

    async def put(self, file_path: str, content: bytes, content_type: str) -> str:
        abs_path = self._get_abs_path(file_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "wb") as f:
            f.write(content)
        return file_path

    async def get(self, file_path: str) -> bytes:
        abs_path = self._get_abs_path(file_path)
        if not os.path.exists(abs_path):
            raise AppException(ErrorCode.NOT_FOUND, "Stored file not found")
        with open(abs_path, "rb") as f:
            return f.read()

    async def delete(self, file_path: str) -> bool:
        abs_path = self._get_abs_path(file_path)
        if os.path.exists(abs_path):
            os.remove(abs_path)
            return True
        return False

    async def create_upload_url(self, file_path: str, content_type: str) -> str:
        return f"/api/v1/attachments/upload/{file_path}"

    async def create_download_url(self, file_path: str) -> str:
        return f"/api/v1/attachments/download/{file_path}"


storage_provider = LocalStorageProvider()


def validate_attachment(filename: str, file_size: int, mime_type: str) -> Tuple[bool, str]:
    """Validate attachment safety against executables and size limits."""
    if file_size > settings.MAX_ATTACHMENT_SIZE_BYTES:
        return False, f"File size ({file_size} bytes) exceeds limit of {settings.MAX_ATTACHMENT_SIZE_BYTES} bytes"

    _, ext = os.path.splitext(filename.lower())
    if ext in FORBIDDEN_EXTENSIONS:
        return False, f"Executable or script extensions ({ext}) are strictly prohibited"

    if not mime_type or mime_type.startswith("application/x-dosexec"):
        return False, "Dangerous MIME type detected"

    return True, "Safe"
