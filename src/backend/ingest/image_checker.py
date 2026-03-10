"""Image availability checking, caching, and HTML rewriting for DOU documents."""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from src.backend.ingest.html_extractor import ImageRef

_ROOT = Path(__file__).resolve().parents[3]
_CACHE_ROOT = _ROOT / "ops" / "data" / "dou" / "images"
_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp"})
_TABLE_HINT_RE = re.compile(r"\b(tabela|quadro|anexo|tab|grid|conforme tabela)\b", re.IGNORECASE)
_SIGNATURE_HINT_RE = re.compile(r"\b(assinatura|sign|rubrica)\b", re.IGNORECASE)
_EMBLEM_HINT_RE = re.compile(r"\b(bras[aã]o|logo|emblema)\b", re.IGNORECASE)


@dataclass(slots=True)
class CheckedImage:
    media_name: str
    original_url: str | None
    availability_status: str
    alt_text: str | None
    context_hint: str
    fallback_text: str
    position_in_doc: int
    ingest_timestamp: str
    retry_count: int
    source_filename: str | None
    local_path: str | None
    media_type: str | None
    file_extension: str | None
    size_bytes: int | None
    width_px: int | None
    height_px: int | None
    data: bytes | None = None


def media_name_from_ref(raw: str) -> str:
    """Normalize image reference to a stable media_name."""
    if not raw:
        return ""
    token = raw.strip().rsplit("/", 1)[-1].strip()
    return re.sub(r"\.[A-Za-z0-9]{2,5}$", "", token)


def resolve_external_media_url(src: str | None) -> str | None:
    """Resolve relative /images URLs to absolute in.gov.br URLs."""
    if not src:
        return None
    ref = src.strip()
    if not ref:
        return None
    if ref.startswith("http://") or ref.startswith("https://"):
        return ref
    if ref.startswith("/"):
        return f"https://www.in.gov.br{ref}"
    return None


def build_fallback_text(context_hint: str) -> str:
    mapping = {
        "table": "Tabela disponível apenas no documento original",
        "signature": "Assinatura — conteúdo não disponível digitalmente",
        "emblem": "Brasão/logotipo institucional",
        "chart": "Gráfico disponível apenas no documento original",
        "unknown": "Conteúdo gráfico não disponível",
    }
    return mapping.get(context_hint, mapping["unknown"])


def infer_context_hint(
    source_filename: str | None,
    alt_text: str | None = None,
    context_snippet: str | None = None,
    width_px: int | None = None,
) -> str:
    haystack = " ".join(part for part in [source_filename or "", alt_text or "", context_snippet or ""] if part).strip()
    if _TABLE_HINT_RE.search(haystack):
        return "table"
    if _SIGNATURE_HINT_RE.search(haystack):
        return "signature"
    if _EMBLEM_HINT_RE.search(haystack):
        return "emblem"
    if width_px and width_px > 400:
        return "table"
    return "unknown"


def summarize_checked_images(items: list[CheckedImage]) -> dict[str, int]:
    summary = {"total_images": len(items), "available": 0, "missing": 0, "unknown": 0}
    for item in items:
        key = item.availability_status
        if key not in summary:
            summary[key] = 0
        summary[key] += 1
    return summary


def rewrite_document_html_images(html: str, doc_id: str, items: list[CheckedImage]) -> str:
    """Rewrite img tags to stable local/media API URLs and annotate sequence metadata."""
    if not html or not items:
        return html

    tag_re = re.compile(r"<img\b[^>]*>", re.IGNORECASE | re.DOTALL)
    ordered = sorted(items, key=lambda value: value.position_in_doc)
    index = {"value": 0}

    def _set_attr(tag: str, name: str, value: str) -> str:
        attr_re = re.compile(rf"""\b{name}\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+)""", re.IGNORECASE)
        replacement = f'{name}="{value}"'
        if attr_re.search(tag):
            return attr_re.sub(replacement, tag, count=1)
        close = "/>" if tag.rstrip().endswith("/>") else ">"
        trimmed = tag[:-2] if close == "/>" else tag[:-1]
        return f"{trimmed} {replacement}{close}"

    def repl(match: re.Match[str]) -> str:
        if index["value"] >= len(ordered):
            return match.group(0)
        item = ordered[index["value"]]
        index["value"] += 1
        local_src = f"/api/media/{doc_id}/{item.media_name}"
        tag = match.group(0)
        tag = _set_attr(tag, "src", local_src)
        tag = _set_attr(tag, "data-image-seq", str(item.position_in_doc))
        if item.alt_text:
            tag = _set_attr(tag, "alt", item.alt_text)
        if item.original_url:
            tag = _set_attr(tag, "data-original-url", item.original_url)
        return tag

    return tag_re.sub(repl, html)


def check_document_images(
    doc_id: str,
    refs: list[ImageRef],
    image_lookup: dict[str, Path] | None = None,
    retry_count: int = 0,
) -> list[CheckedImage]:
    """Synchronous wrapper for document image checking."""
    return asyncio.run(
        _check_document_images_async(
            doc_id=doc_id,
            refs=refs,
            image_lookup=image_lookup or {},
            retry_count=retry_count,
        )
    )


async def _check_document_images_async(
    doc_id: str,
    refs: list[ImageRef],
    image_lookup: dict[str, Path],
    retry_count: int = 0,
) -> list[CheckedImage]:
    if not refs:
        return []

    timeout = httpx.Timeout(5.0, connect=5.0)
    limits = httpx.Limits(max_connections=8, max_keepalive_connections=4)
    async with httpx.AsyncClient(
        timeout=timeout, limits=limits, headers={"User-Agent": "gabi-image-checker/1.0"}
    ) as client:
        tasks = [
            _classify_one_image(
                client=client,
                doc_id=doc_id,
                ref=ref,
                image_lookup=image_lookup,
                retry_count=retry_count,
            )
            for ref in refs
        ]
        return await asyncio.gather(*tasks)


async def _classify_one_image(
    client: httpx.AsyncClient,
    doc_id: str,
    ref: ImageRef,
    image_lookup: dict[str, Path],
    retry_count: int,
) -> CheckedImage:
    ref_name = media_name_from_ref(ref.name)
    source_filename = (ref.source or ref.name or "").strip().rsplit("/", 1)[-1] or None
    ingest_timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    img_path = image_lookup.get(ref_name)
    if img_path and img_path.exists():
        ext = img_path.suffix.lower()
        cached = _cache_local_file(doc_id=doc_id, media_name=ref_name, source_path=img_path)
        context_hint = infer_context_hint(source_filename or img_path.name, ref.alt_text, ref.context_snippet)
        data = img_path.read_bytes()
        return CheckedImage(
            media_name=ref_name,
            original_url=resolve_external_media_url(ref.source),
            availability_status="available",
            alt_text=ref.alt_text,
            context_hint=context_hint,
            fallback_text=build_fallback_text(context_hint),
            position_in_doc=ref.sequence,
            ingest_timestamp=ingest_timestamp,
            retry_count=retry_count,
            source_filename=source_filename or img_path.name,
            local_path=cached,
            media_type=_guess_media_type(ext),
            file_extension=ext or None,
            size_bytes=len(data),
            width_px=None,
            height_px=None,
            data=data,
        )

    original_url = resolve_external_media_url(ref.source)
    context_hint = infer_context_hint(source_filename, ref.alt_text, ref.context_snippet)
    if not original_url:
        return CheckedImage(
            media_name=ref_name,
            original_url=None,
            availability_status="missing",
            alt_text=ref.alt_text,
            context_hint=context_hint,
            fallback_text=build_fallback_text(context_hint),
            position_in_doc=ref.sequence,
            ingest_timestamp=ingest_timestamp,
            retry_count=retry_count,
            source_filename=source_filename,
            local_path=None,
            media_type=None,
            file_extension=None,
            size_bytes=None,
            width_px=None,
            height_px=None,
        )

    probe = await _probe_remote_image(client, original_url)
    availability_status = probe["status"]
    local_path: str | None = None
    payload: bytes | None = None
    media_type = probe.get("media_type")
    file_extension = probe.get("file_extension")
    size_bytes = probe.get("size_bytes")
    if availability_status == "available":
        payload = probe.get("data")
        if payload:
            local_path = _cache_bytes(
                doc_id=doc_id,
                media_name=ref_name,
                payload=payload,
                file_extension=file_extension,
            )
            size_bytes = len(payload)

    return CheckedImage(
        media_name=ref_name,
        original_url=original_url,
        availability_status=availability_status,
        alt_text=ref.alt_text,
        context_hint=context_hint,
        fallback_text=build_fallback_text(context_hint),
        position_in_doc=ref.sequence,
        ingest_timestamp=ingest_timestamp,
        retry_count=retry_count + (1 if availability_status == "unknown" else 0),
        source_filename=source_filename,
        local_path=local_path,
        media_type=media_type,
        file_extension=file_extension,
        size_bytes=size_bytes,
        width_px=None,
        height_px=None,
        data=None,
    )


async def _probe_remote_image(client: httpx.AsyncClient, url: str, max_redirects: int = 3) -> dict[str, Any]:
    current = url
    redirects = 0
    while True:
        try:
            response = await client.head(current, follow_redirects=False)
        except httpx.TimeoutException:
            return {"status": "missing"}
        except httpx.HTTPError:
            return {"status": "unknown"}

        status = response.status_code
        if status in {301, 302, 303, 307, 308}:
            location = response.headers.get("location")
            if not location:
                return {"status": "missing"}
            next_url = urljoin(current, location)
            if _treat_redirect_as_missing(current, next_url):
                return {"status": "missing"}
            redirects += 1
            if redirects > max_redirects:
                return {"status": "missing"}
            current = next_url
            continue

        if status == 200:
            media_type = (response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
            if not media_type.startswith("image/"):
                return {"status": "missing", "media_type": media_type or None}
            try:
                download = await client.get(current, follow_redirects=True)
                download.raise_for_status()
            except httpx.TimeoutException:
                return {"status": "missing", "media_type": media_type}
            except httpx.HTTPStatusError as ex:
                if ex.response.status_code in {403, 429}:
                    return {"status": "unknown", "media_type": media_type}
                return {"status": "missing", "media_type": media_type}
            except httpx.HTTPError:
                return {"status": "unknown", "media_type": media_type}
            payload = download.content
            return {
                "status": "available",
                "media_type": media_type,
                "file_extension": _extension_for_url(current, media_type),
                "size_bytes": len(payload),
                "data": payload,
            }

        if status in {404, 410}:
            return {"status": "missing"}
        if status in {403, 429}:
            return {"status": "unknown"}
        return {"status": "unknown"}


def _treat_redirect_as_missing(original_url: str, next_url: str) -> bool:
    original = urlparse(original_url)
    target = urlparse(next_url)
    if not target.netloc:
        return False
    if original.netloc != target.netloc:
        return True
    normalized_path = target.path.strip("/") if target.path else ""
    return normalized_path in {"", "index.html", "home"}


def _guess_media_type(ext: str) -> str:
    return mimetypes.guess_type(f"file{ext}")[0] or "application/octet-stream"


def _extension_for_url(url: str, media_type: str | None) -> str | None:
    ext = Path(urlparse(url).path).suffix.lower()
    if ext in _IMAGE_EXTENSIONS:
        return ext
    ext_from_type = mimetypes.guess_extension(media_type or "")
    if ext_from_type in _IMAGE_EXTENSIONS:
        return ext_from_type
    return None


def _cache_local_file(doc_id: str, media_name: str, source_path: Path) -> str:
    target_dir = _CACHE_ROOT / doc_id
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = source_path.suffix.lower() or ".bin"
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()[:16]
    target = target_dir / f"{media_name}-{digest}{suffix}"
    if not target.exists():
        shutil.copy2(source_path, target)
    return str(target.relative_to(_ROOT))


def _cache_bytes(doc_id: str, media_name: str, payload: bytes, file_extension: str | None) -> str:
    target_dir = _CACHE_ROOT / doc_id
    target_dir.mkdir(parents=True, exist_ok=True)
    ext = file_extension if file_extension and file_extension.startswith(".") else ".bin"
    digest = hashlib.sha256(payload).hexdigest()[:16]
    target = target_dir / f"{media_name}-{digest}{ext}"
    if not target.exists():
        target.write_bytes(payload)
    return str(target.relative_to(_ROOT))


def checked_image_row(item: CheckedImage) -> dict[str, Any]:
    """Serialize checked image metadata for DB insert / JSON responses."""
    payload = asdict(item)
    payload.pop("data", None)
    return payload
