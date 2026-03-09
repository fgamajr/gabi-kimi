#!/usr/bin/env python3
"""Create MinIO bucket gabi-dou-uploads (local dev). Run from repo root with .env loaded."""
import os
import sys

# Load .env if present
env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
if os.path.isfile(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))

import boto3
from botocore.config import Config

endpoint = os.getenv("AWS_ENDPOINT_URL_S3")
bucket = os.getenv("BUCKET_NAME", "gabi-dou-uploads")
if not endpoint:
    print("Set AWS_ENDPOINT_URL_S3 and other MinIO vars in .env", file=sys.stderr)
    sys.exit(1)

client = boto3.client(
    "s3",
    endpoint_url=endpoint,
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "minioadmin"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "minioadmin"),
    region_name=os.getenv("AWS_REGION", "us-east-1"),
    config=Config(s3={"addressing_style": "path"}),
)
try:
    client.create_bucket(Bucket=bucket)
    print(f"Bucket {bucket} created.")
except client.exceptions.BucketAlreadyOwnedByYou:
    print(f"Bucket {bucket} already exists.")
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
