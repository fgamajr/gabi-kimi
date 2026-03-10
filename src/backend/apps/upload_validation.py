"""Deep upload validation for admin XML/ZIP uploads."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import PurePosixPath
import zipfile

from src.backend.ingest.xml_parser import INLabsXMLParser, XMLParseError

PEEK_SIZE = 512
ZIP_MAGIC = b"PK\x03\x04"
ZIP_EMPTY_MAGIC = b"PK\x05\x06"
MAX_ZIP_MEMBERS = int(os.getenv("GABI_ADMIN_UPLOAD_MAX_ZIP_MEMBERS", "50000"))
MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES = int(
    os.getenv("GABI_ADMIN_UPLOAD_MAX_UNCOMPRESSED_BYTES", str(2 * 1024 * 1024 * 1024))
)
MAX_XML_ENTRY_BYTES = int(os.getenv("GABI_ADMIN_UPLOAD_MAX_XML_ENTRY_BYTES", str(50 * 1024 * 1024)))
_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp"})
_XML_EXTENSIONS = frozenset({".xml"})


class UploadValidationError(ValueError):
    """Permanent upload validation failure."""


@dataclass(slots=True)
class UploadValidationResult:
    file_type: str
    xml_entries: int = 0
    valid_xml_entries: int = 0
    image_entries: int = 0
    warnings: list[str] = field(default_factory=list)


def _peek(file) -> bytes:
    pos = file.tell()
    data = file.read(PEEK_SIZE)
    file.seek(pos)
    return data


def detect_upload_type(peek_bytes: bytes) -> str | None:
    if not peek_bytes:
        return None
    if peek_bytes.startswith(ZIP_MAGIC) or peek_bytes.startswith(ZIP_EMPTY_MAGIC):
        return "zip"
    stripped = peek_bytes.lstrip(b"\xef\xbb\xbf \t\r\n")
    if stripped.startswith(b"<?xml") or stripped.startswith(b"<"):
        return "xml"
    return None


def _decode_xml_bytes(raw: bytes, source_name: str) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UploadValidationError(f"{source_name}: invalid UTF-8 XML encoding") from exc


def _validate_xml_bytes(raw: bytes, source_name: str) -> None:
    if len(raw) > MAX_XML_ENTRY_BYTES:
        raise UploadValidationError(
            f"{source_name}: XML entry too large ({len(raw)} bytes, limit {MAX_XML_ENTRY_BYTES})"
        )
    parser = INLabsXMLParser()
    xml_text = _decode_xml_bytes(raw, source_name)
    try:
        parser.parse_string(xml_text)
    except XMLParseError as exc:
        raise UploadValidationError(f"{source_name}: {exc}") from exc


def _is_path_traversal(name: str) -> bool:
    if not name:
        return True
    path = PurePosixPath(name)
    if path.is_absolute():
        return True
    return ".." in path.parts


def _sniff_image_header(header: bytes) -> bool:
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if header.startswith(b"\xff\xd8\xff"):
        return True
    if header.startswith((b"GIF87a", b"GIF89a")):
        return True
    if header.startswith(b"BM"):
        return True
    if header.startswith((b"II*\x00", b"MM\x00*")):
        return True
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return True
    return False


def _validate_xml_upload(file) -> UploadValidationResult:
    payload = file.read()
    _validate_xml_bytes(payload, "upload.xml")
    file.seek(0)
    return UploadValidationResult(file_type="xml", xml_entries=1, valid_xml_entries=1)


def _validate_zip_upload(file) -> UploadValidationResult:
    result = UploadValidationResult(file_type="zip")
    try:
        with zipfile.ZipFile(file, "r") as zf:
            infos = [info for info in zf.infolist() if not info.is_dir()]
            if len(infos) > MAX_ZIP_MEMBERS:
                raise UploadValidationError(f"ZIP has too many entries ({len(infos)}, limit {MAX_ZIP_MEMBERS})")

            total_uncompressed = 0
            xml_infos: list[zipfile.ZipInfo] = []
            image_infos: list[zipfile.ZipInfo] = []
            for info in infos:
                name = info.filename
                if _is_path_traversal(name):
                    raise UploadValidationError(f"ZIP path traversal rejected: {name}")
                total_uncompressed += max(0, int(info.file_size))
                if total_uncompressed > MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES:
                    raise UploadValidationError(
                        f"ZIP expands beyond the configured safe limit ({MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES} bytes)"
                    )
                suffix = PurePosixPath(name).suffix.lower()
                if suffix in _XML_EXTENSIONS:
                    xml_infos.append(info)
                elif suffix in _IMAGE_EXTENSIONS:
                    image_infos.append(info)

            if not xml_infos:
                raise UploadValidationError("ZIP does not contain any .xml entries")

            bad_member = zf.testzip()
            if bad_member:
                raise UploadValidationError(f"ZIP member failed CRC check: {bad_member}")

            result.xml_entries = len(xml_infos)
            result.image_entries = len(image_infos)

            xml_errors: list[str] = []
            for info in xml_infos:
                try:
                    with zf.open(info) as src:
                        _validate_xml_bytes(src.read(), info.filename)
                    result.valid_xml_entries += 1
                    break
                except UploadValidationError as exc:
                    if len(xml_errors) < 5:
                        xml_errors.append(str(exc))

            if result.valid_xml_entries == 0:
                detail = "; ".join(xml_errors) if xml_errors else "no valid XML entries"
                raise UploadValidationError(f"ZIP has zero valid XML entries: {detail}")

            for info in image_infos[:10]:
                with zf.open(info) as src:
                    if not _sniff_image_header(src.read(32)):
                        result.warnings.append(f"{info.filename}: unrecognized image signature")
    except UploadValidationError:
        raise
    except zipfile.BadZipFile as exc:
        raise UploadValidationError(f"Corrupted ZIP archive: {exc}") from exc
    except OSError as exc:
        raise UploadValidationError(f"Unreadable ZIP archive: {exc}") from exc
    finally:
        file.seek(0)

    return result


def validate_upload_file(file) -> UploadValidationResult:
    """
    Deep-validate upload content before persisting to storage.

    Returns an UploadValidationResult with file_type and summary fields.
    Raises UploadValidationError on permanent validation failure.
    """
    peek = _peek(file)
    kind = detect_upload_type(peek)
    if kind is None:
        raise UploadValidationError(
            "Only XML and ZIP files are accepted. "
            "Upload a file that starts with <?xml or < (XML) or with ZIP magic bytes (ZIP archive)."
        )
    if kind == "xml":
        return _validate_xml_upload(file)
    return _validate_zip_upload(file)
