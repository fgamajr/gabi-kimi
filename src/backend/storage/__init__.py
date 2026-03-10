"""Blob storage for GABI (Tigris/S3-compatible on Fly.io)."""

from src.backend.storage.tigris import (
    get_s3_client,
    get_bucket_name,
    upload_fileobj,
    download_to_path,
    get_object_bytes,
    delete_object,
    is_configured,
)

__all__ = [
    "get_s3_client",
    "get_bucket_name",
    "upload_fileobj",
    "download_to_path",
    "get_object_bytes",
    "delete_object",
    "is_configured",
]
