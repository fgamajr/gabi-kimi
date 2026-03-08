"""Upload file type validation by magic bytes (UPLD-04). XML and ZIP only."""
from __future__ import annotations

PEEK_SIZE = 512

# ZIP: local file header signature
ZIP_MAGIC = b"PK\x03\x04"
ZIP_EMPTY_MAGIC = b"PK\x05\x06"


def _peek(file) -> bytes:
    """Read first PEEK_SIZE bytes; caller must seek(0) before streaming."""
    pos = file.tell()
    data = file.read(PEEK_SIZE)
    file.seek(pos)
    return data


def detect_upload_type(peek_bytes: bytes) -> str | None:
    """
    Return 'xml' or 'zip' if peek_bytes match; None otherwise.
    XML: <?xml or (optional BOM/whitespace) then <.
    ZIP: PK\\x03\\x04 or PK\\x05\\x06.
    """
    if not peek_bytes:
        return None
    # ZIP
    if peek_bytes.startswith(ZIP_MAGIC) or peek_bytes.startswith(ZIP_EMPTY_MAGIC):
        return "zip"
    # XML: strip BOM and leading whitespace, then check for <?xml or <
    stripped = peek_bytes.lstrip(b"\xef\xbb\xbf \t\r\n")
    if stripped.startswith(b"<?xml"):
        return "xml"
    if stripped.startswith(b"<"):
        return "xml"
    return None


def validate_upload_file(file) -> str:
    """
    Validate file by magic bytes. Returns 'xml' or 'zip'.
    Raises ValueError with clear message if not XML or ZIP.
    Resets file position to 0 so caller can stream to Tigris.
    """
    peek = _peek(file)
    kind = detect_upload_type(peek)
    if kind is None:
        raise ValueError(
            "Only XML and ZIP files are accepted. "
            "Upload a file that starts with <?xml or < (XML) or with ZIP magic bytes (ZIP archive)."
        )
    file.seek(0)
    return kind
