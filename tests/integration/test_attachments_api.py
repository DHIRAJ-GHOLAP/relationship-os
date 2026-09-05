"""Integration tests for Attachment preparation, safety validation, upload, and download."""

import io
import pytest
from httpx import AsyncClient

from apps.api.src.core.config import settings
from apps.api.src.services.storage_service import storage_provider


@pytest.mark.asyncio
async def test_attachment_rejection_of_dangerous_extensions(client: AsyncClient, auth_headers):
    """Dangerous file extensions (.exe, .ps1, .sh, .bat) must be strictly rejected."""
    for bad_file in ["malware.exe", "trojan.ps1", "script.sh", "run.bat", "calc.cmd"]:
        resp = await client.post(
            "/api/v1/attachments/prepare",
            json={
                "filename": bad_file,
                "file_size": 1024,
                "mime_type": "application/octet-stream",
            },
            headers=auth_headers["recipient"],
        )
        assert resp.status_code == 400
        assert "prohibited" in resp.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_attachment_rejection_of_oversized_file(client: AsyncClient, auth_headers):
    """Files exceeding MAX_ATTACHMENT_SIZE_BYTES must be rejected during preparation."""
    oversized = settings.MAX_ATTACHMENT_SIZE_BYTES + 1024
    resp = await client.post(
        "/api/v1/attachments/prepare",
        json={
            "filename": "huge_video.mp4",
            "file_size": oversized,
            "mime_type": "video/mp4",
        },
        headers=auth_headers["recipient"],
    )
    assert resp.status_code == 400
    assert "exceeds limit" in resp.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_attachment_full_upload_and_download_lifecycle(client: AsyncClient, auth_headers):
    """Verify end-to-end prepare -> upload binary -> download binary with safe headers."""
    sample_content = b"PDF-1.4 % Simulated Relationship OS PDF Document Payload"
    sample_filename = "shared_notes.pdf"
    sample_mime = "application/pdf"

    # 1. Prepare attachment
    prep_resp = await client.post(
        "/api/v1/attachments/prepare",
        json={
            "filename": sample_filename,
            "file_size": len(sample_content),
            "mime_type": sample_mime,
        },
        headers=auth_headers["recipient"],
    )
    assert prep_resp.status_code == 200
    prep_data = prep_resp.json()
    att_id = prep_data["attachment_id"]
    upload_url = prep_data["upload_url"]
    assert att_id is not None
    assert upload_url == f"/api/v1/attachments/upload/{att_id}"

    # 2. Upload file content via multipart/form-data
    files = {"file": (sample_filename, io.BytesIO(sample_content), sample_mime)}
    up_resp = await client.post(
        upload_url,
        files=files,
        headers=auth_headers["recipient"],
    )
    assert up_resp.status_code == 200

    # 3. Download file content
    dl_resp = await client.get(
        f"/api/v1/attachments/download/{att_id}",
        headers=auth_headers["owner"],
    )
    assert dl_resp.status_code == 200
    assert dl_resp.content == sample_content
    assert dl_resp.headers["content-type"] == sample_mime
    assert f'filename="{sample_filename}"' in dl_resp.headers["content-disposition"]
    assert dl_resp.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_storage_path_traversal_prevention():
    """Storage provider must reject path traversal attempts."""
    from apps.api.src.core.exceptions import AppException
    with pytest.raises(AppException) as excinfo:
        storage_provider._get_abs_path("../../../etc/passwd")
    assert "path traversal" in str(excinfo.value.message).lower()
