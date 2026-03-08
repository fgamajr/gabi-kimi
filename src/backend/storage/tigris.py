"""Tigris (S3-compatible) blob storage for Fly.io.

Config from env: AWS_ENDPOINT_URL_S3, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, BUCKET_NAME.
See docs/runbooks/FLY_TIGRIS_STORAGE.md for creating and binding the bucket.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO

import boto3
from botocore.config import Config


def is_configured() -> bool:
    """Return True if Tigris env vars are set (bucket bound to app)."""
    return bool(
        os.getenv("AWS_ENDPOINT_URL_S3")
        and os.getenv("AWS_ACCESS_KEY_ID")
        and os.getenv("AWS_SECRET_ACCESS_KEY")
        and os.getenv("BUCKET_NAME")
    )


def get_s3_client():
    """S3 client configured for Fly.io Tigris (s3v4, virtual-hosted style)."""
    return boto3.client(
        "s3",
        endpoint_url=os.environ["AWS_ENDPOINT_URL_S3"],
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        region_name=os.getenv("AWS_REGION", "auto"),
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "virtual"},
        ),
    )


def get_bucket_name() -> str:
    """Bucket name from env (set by fly storage create)."""
    return os.environ["BUCKET_NAME"]


def upload_fileobj(fileobj: BinaryIO, key: str, bucket: str | None = None) -> None:
    """Stream upload to Tigris. Does not seek; reads from current position."""
    client = get_s3_client()
    bucket = bucket or get_bucket_name()
    client.upload_fileobj(fileobj, bucket, key)


def download_to_path(key: str, dest: Path | str, bucket: str | None = None) -> Path:
    """Download object from Tigris to local path. Returns path to file."""
    client = get_s3_client()
    bucket = bucket or get_bucket_name()
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    client.download_file(bucket, key, str(dest))
    return dest


def get_object_bytes(key: str, bucket: str | None = None) -> bytes:
    """Read object from Tigris into bytes (e.g. for verification)."""
    client = get_s3_client()
    bucket = bucket or get_bucket_name()
    resp = client.get_object(Bucket=bucket, Key=key)
    return resp["Body"].read()


def delete_object(key: str, bucket: str | None = None) -> None:
    """Delete object from Tigris (e.g. cleanup test blobs)."""
    client = get_s3_client()
    bucket = bucket or get_bucket_name()
    client.delete_object(Bucket=bucket, Key=key)
