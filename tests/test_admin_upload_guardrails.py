from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import zipfile

from src.backend.apps.upload_validation import (
    UploadValidationError,
    validate_upload_file,
)
from src.backend.ingest.dou_ingest import DOUIngestor, ZIPIngestResult
from src.backend.workers.arq_worker import classify_ingest_failure, _retry_delay_seconds


FIXTURE_XML = (
    Path(__file__).resolve().parent / "fixtures" / "xml_samples" / "2026-02-27-DO1_515_20260227_23615168.xml"
)


def _build_zip(entries: dict[str, bytes]) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    buf.seek(0)
    return buf


class UploadValidationTests(unittest.TestCase):
    def test_valid_xml_upload_is_accepted(self) -> None:
        with FIXTURE_XML.open("rb") as fh:
            result = validate_upload_file(io.BytesIO(fh.read()))
        self.assertEqual(result.file_type, "xml")
        self.assertEqual(result.valid_xml_entries, 1)

    def test_invalid_xml_upload_is_rejected(self) -> None:
        payload = io.BytesIO(b"<broken><article></broken>")
        with self.assertRaises(UploadValidationError):
            validate_upload_file(payload)

    def test_corrupted_zip_is_rejected(self) -> None:
        payload = io.BytesIO(b"PK\x03\x04not-a-real-zip")
        with self.assertRaises(UploadValidationError):
            validate_upload_file(payload)

    def test_zip_without_xml_is_rejected(self) -> None:
        payload = _build_zip({"image.png": b"\x89PNG\r\n\x1a\nfake"})
        with self.assertRaises(UploadValidationError):
            validate_upload_file(payload)

    def test_zip_with_path_traversal_is_rejected(self) -> None:
        payload = _build_zip({"../evil.xml": FIXTURE_XML.read_bytes()})
        with self.assertRaises(UploadValidationError):
            validate_upload_file(payload)

    def test_zip_with_zero_valid_xmls_is_rejected(self) -> None:
        payload = _build_zip({"bad.xml": b"<broken><article></broken>"})
        with self.assertRaises(UploadValidationError):
            validate_upload_file(payload)

    def test_zip_with_valid_xml_and_bad_image_warns(self) -> None:
        payload = _build_zip(
            {
                "good.xml": FIXTURE_XML.read_bytes(),
                "bad.png": b"not-a-real-png",
            }
        )
        result = validate_upload_file(payload)
        self.assertEqual(result.file_type, "zip")
        self.assertEqual(result.valid_xml_entries, 1)
        self.assertEqual(result.image_entries, 1)
        self.assertTrue(result.warnings)


class IngestGuardrailTests(unittest.TestCase):
    def test_ingest_zip_fails_before_db_when_all_xmls_are_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / "invalid.zip"
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("bad.xml", "<broken><article></broken>")

            with patch("psycopg2.connect", side_effect=AssertionError("DB should not be touched")):
                result = DOUIngestor("dbname=unused").ingest_zip(zip_path)

        self.assertFalse(result.success)
        self.assertGreater(result.parse_errors, 0)
        self.assertEqual(result.articles_found, 0)
        self.assertIn("zero valid XML articles", " ".join(result.errors))


class WorkerRetryPolicyTests(unittest.TestCase):
    def test_classify_parse_only_failure_as_permanent(self) -> None:
        result = ZIPIngestResult(zip_path=Path("x.zip"), xml_count=1, parse_errors=2, articles_found=0)
        self.assertEqual(classify_ingest_failure(result), "permanent")

    def test_classify_transaction_failure_as_transient(self) -> None:
        result = ZIPIngestResult(zip_path=Path("x.zip"), xml_count=1, errors=["transaction: timeout"])
        result.success = False
        self.assertEqual(classify_ingest_failure(result), "transient")

    def test_retry_delay_uses_exponential_backoff(self) -> None:
        self.assertEqual(_retry_delay_seconds(0), 30)
        self.assertEqual(_retry_delay_seconds(1), 60)
        self.assertEqual(_retry_delay_seconds(2), 120)


if __name__ == "__main__":
    unittest.main()
