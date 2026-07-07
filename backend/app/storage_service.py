from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status

from app.config import Settings, get_settings


ALLOWED_WORKSPACE_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class StorageService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.upload_root = Path(self.settings.upload_dir).resolve()
        self.workspace_upload_dir = self.upload_root / "workspaces"
        self.workspace_upload_dir.mkdir(parents=True, exist_ok=True)

    def local_public_url(self, public_api_base_url: str | None, key: str) -> str:
        if public_api_base_url:
            return f"{public_api_base_url.rstrip('/')}/uploads/{key}"
        return f"/uploads/{key}"

    async def upload_workspace_photo(self, file: UploadFile, public_api_base_url: str | None = None) -> str:
        extension = ALLOWED_WORKSPACE_IMAGE_TYPES.get(file.content_type or "")
        if extension is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Workspace photo must be a JPEG, PNG, or WebP image",
            )

        content = await self._read_limited_file(file)
        key = f"workspaces/{uuid4().hex}{extension}"
        if self.settings.storage_provider == "s3":
            return self._upload_s3(key, content, file.content_type or "application/octet-stream")
        return self._upload_local(key, content, public_api_base_url)

    async def _read_limited_file(self, file: UploadFile) -> bytes:
        chunks = []
        total_bytes = 0
        while chunk := await file.read(1024 * 1024):
            total_bytes += len(chunk)
            if total_bytes > self.settings.max_upload_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Workspace photo is too large",
                )
            chunks.append(chunk)

        if total_bytes == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Workspace photo cannot be empty",
            )

        return b"".join(chunks)

    def _upload_local(self, key: str, content: bytes, public_api_base_url: str | None) -> str:
        destination = self.upload_root / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return self.local_public_url(public_api_base_url, key)

    def _upload_s3(self, key: str, content: bytes, content_type: str) -> str:
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("boto3 is required when STORAGE_PROVIDER=s3") from exc

        client = boto3.client(
            "s3",
            region_name=self.settings.s3_region,
            endpoint_url=self.settings.s3_endpoint_url,
            aws_access_key_id=self.settings.s3_access_key_id,
            aws_secret_access_key=self.settings.s3_secret_access_key,
        )
        client.put_object(
            Bucket=self.settings.s3_bucket,
            Key=key,
            Body=content,
            ContentType=content_type,
        )
        return f"{self.settings.s3_public_base_url.rstrip('/')}/{key}"


def get_storage_service(settings: Settings | None = None) -> StorageService:
    return StorageService(settings)
