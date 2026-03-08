# Fly.io Tigris Storage (Admin Upload Bucket)

Last updated: 2026-03-08

This runbook covers creating and binding a Tigris blob storage bucket to the GABI Fly app so FastAPI can read/write uploaded DOU files (XML/ZIP) via boto3.

## Prerequisites

- Fly CLI logged in (`fly auth login`)
- App `gabi-dou-web` (or your app name) already created

## One-time: Create bucket and bind to app

```bash
# Create Tigris bucket in region gru (São Paulo)
fly storage create --name gabi-dou-uploads --region gru -a gabi-dou-web
```

This command:

1. Creates a Tigris bucket (S3-compatible) in the `gru` region
2. Binds it to the app and **automatically sets** these Fly secrets:
   - `AWS_ENDPOINT_URL_S3` — Tigris endpoint URL
   - `AWS_ACCESS_KEY_ID` — Tigris access key
   - `AWS_SECRET_ACCESS_KEY` — Tigris secret key
   - `BUCKET_NAME` — bucket name (e.g. `gabi-dou-uploads`)

No manual `fly secrets set` is required for Tigris after `fly storage create`.

## Verify from the app

After deploy, the backend uses these env vars in `src/backend/storage/tigris.py` (boto3 client). To confirm FastAPI can upload and read back:

1. **Admin storage check endpoint** (requires admin auth):
   ```bash
   curl -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
     https://YOUR_APP.fly.dev/api/admin/storage-check
   ```
   - If configured: returns `200` with `{"ok": true}` after uploading and reading a test blob
   - If not configured: returns `503` with message that Tigris env vars are missing

2. **Local dev** (optional): set the same four env vars in `.env` (e.g. from a second Fly app with Tigris, or a local MinIO) and run the same request against `http://localhost:8000`.

## Environment variables (reference)

| Variable | Source | Purpose |
|----------|--------|---------|
| `AWS_ENDPOINT_URL_S3` | `fly storage create` (auto) | Tigris S3 endpoint |
| `AWS_ACCESS_KEY_ID` | `fly storage create` (auto) | Tigris auth |
| `AWS_SECRET_ACCESS_KEY` | `fly storage create` (auto) | Tigris auth |
| `BUCKET_NAME` | `fly storage create` (auto) | Bucket name |
| `AWS_REGION` | Optional, default `auto` | boto3 region (Tigris uses `auto` or `gru`) |

## Code usage

```python
from src.backend.storage import get_s3_client, get_bucket_name, upload_fileobj, download_to_path

# Stream upload (e.g. from FastAPI UploadFile.file)
upload_fileobj(fileobj, key="uploads/{job_id}/{filename}")

# Download to local path (e.g. in worker)
download_to_path(key, Path("/tmp/work") / "file.zip")
```

## References

- [Fly.io Tigris docs](https://fly.io/docs/tigris/)
- [Fly.io Python + Object Storage](https://fly.io/docs/python/do-more/add-object-storage/)
- [Tigris boto3 / AWS Python SDK](https://www.tigrisdata.com/docs/sdks/s3/aws-python-sdk/)
