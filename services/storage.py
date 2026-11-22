"""
Storage abstraction untuk Image Management System.

Tiga strategi didukung:
- LocalStorage   : simpan file ke disk lokal VPS
- UrlStorage     : hanya menyimpan referensi URL eksternal (tidak upload apapun)
- S3Storage      : upload ke storage S3-compatible (MinIO, Wasabi, AWS S3, dst)

Semua strategi mengembalikan tuple (storage_type, location) yang disimpan
di kolom ImageAsset.location, dan menyediakan resolve_url() untuk
mendapatkan URL yang bisa ditampilkan kembali di Discord.
"""

from __future__ import annotations

import abc
import uuid
from pathlib import Path

from config import settings


class StorageBackend(abc.ABC):
    @abc.abstractmethod
    async def save(self, *, filename: str, data: bytes) -> str:
        """Menyimpan data dan mengembalikan 'location' yang disimpan di database."""

    @abc.abstractmethod
    def resolve_url(self, location: str) -> str:
        """Mengubah 'location' tersimpan menjadi URL yang bisa diakses."""

    @abc.abstractmethod
    async def delete(self, location: str) -> None:
        """Menghapus file/object dari storage jika memang dikelola bot."""


class LocalStorage(StorageBackend):
    def __init__(self) -> None:
        self.base_path = Path(settings.local_storage_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    async def save(self, *, filename: str, data: bytes) -> str:
        ext = Path(filename).suffix
        unique_name = f"{uuid.uuid4().hex}{ext}"
        target = self.base_path / unique_name
        target.write_bytes(data)
        return str(target)

    def resolve_url(self, location: str) -> str:
        # File lokal tidak memiliki URL publik otomatis; kembalikan path-nya.
        # Jika bot di-host bersama web server, path ini bisa di-mapping ke URL statis.
        return location

    async def delete(self, location: str) -> None:
        base_path = self.base_path.resolve()
        target = Path(location).resolve()
        if not target.is_relative_to(base_path):
            raise RuntimeError("Lokasi image berada di luar direktori storage lokal.")
        target.unlink(missing_ok=True)


class UrlStorage(StorageBackend):
    """Dipakai ketika admin hanya menempelkan URL gambar yang sudah ada, tanpa upload."""

    async def save(self, *, filename: str, data: bytes) -> str:
        raise NotImplementedError("UrlStorage tidak menerima upload biner, gunakan save_url().")

    async def save_url(self, url: str) -> str:
        return url

    def resolve_url(self, location: str) -> str:
        return location

    async def delete(self, location: str) -> None:
        return None


class S3Storage(StorageBackend):
    def __init__(self) -> None:
        if not all(
            [
                settings.s3_endpoint_url,
                settings.s3_access_key,
                settings.s3_secret_key,
                settings.s3_bucket_name,
            ]
        ):
            raise RuntimeError(
                "Konfigurasi S3 belum lengkap. Isi S3_ENDPOINT_URL, S3_ACCESS_KEY, "
                "S3_SECRET_KEY, dan S3_BUCKET_NAME di .env untuk memakai storage_type=s3."
            )
        import boto3  # import lokal agar boto3 opsional bila S3 tidak dipakai

        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
        )
        self._bucket = settings.s3_bucket_name

    async def save(self, *, filename: str, data: bytes) -> str:
        ext = Path(filename).suffix
        key = f"{uuid.uuid4().hex}{ext}"
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data)
        return key

    def resolve_url(self, location: str) -> str:
        if settings.s3_public_base_url:
            return f"{settings.s3_public_base_url.rstrip('/')}/{location}"
        return self._client.generate_presigned_url(
            "get_object", Params={"Bucket": self._bucket, "Key": location}, ExpiresIn=3600
        )

    async def delete(self, location: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=location)


def get_storage_backend(storage_type: str) -> StorageBackend:
    if storage_type == "local":
        return LocalStorage()
    if storage_type == "url":
        return UrlStorage()
    if storage_type == "s3":
        return S3Storage()
    raise ValueError(f"storage_type tidak dikenal: {storage_type}")
