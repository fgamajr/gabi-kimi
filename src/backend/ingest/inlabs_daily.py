from __future__ import annotations

import argparse
import io
import logging
import os
import random
import shutil
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urljoin, urlparse

import psycopg
import requests
from dotenv import load_dotenv
from lxml import html
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.backend.core.config import settings
from src.backend.ingest.dou_processor import DouProcessor
from src.backend.ingest.sync_dou import _pg_url, ingest_documents


logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_INLABS_BASE_URL = "https://inlabs.in.gov.br/"
_LOGIN_URL = urljoin(_INLABS_BASE_URL, "logar.php")
_ACCESS_URL = urljoin(_INLABS_BASE_URL, "acessar.php")
_DATE_URL_TEMPLATE = urljoin(_INLABS_BASE_URL, "index.php?p={date}")
_DEFAULT_DOWNLOAD_ROOT = Path(settings.PIPELINE_TMP) / "inlabs_daily"
_REQUEST_DELAY_SEC = 1.0
_ZIP_BATCH_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "max-age=0",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}
_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.6; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/122.0.0.0 Safari/537.36",
]


def _load_env_files() -> None:
    for filename in (".env.local", ".env"):
        path = _REPO_ROOT / filename
        if path.exists():
            load_dotenv(path, override=False)


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _iter_dates(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _download_root() -> Path:
    root = Path(os.getenv("INLABS_TMP_DIR", str(_DEFAULT_DOWNLOAD_ROOT))).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _pick_user_agent() -> str:
    return random.choice(_USER_AGENTS)


def _build_headers() -> dict[str, str]:
    headers = dict(_ZIP_BATCH_HEADERS)
    headers["User-Agent"] = _pick_user_agent()
    return headers


def _resolve_credentials() -> tuple[str | None, str | None, str | None]:
    _load_env_files()
    user = (os.getenv("INLABS_USER") or "").strip() or None
    password = (
        os.getenv("INLABS_PWD") or os.getenv("INLABS_PASSWORD") or ""
    ).strip() or None
    cookie = (os.getenv("GABI_INLABS_COOKIE") or "").strip() or None
    return user, password, cookie


class InlabsClient:
    def __init__(self) -> None:
        self.user, self.password, self.cookie = _resolve_credentials()
        self.session = requests.Session()
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST"),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(pool_connections=8, pool_maxsize=8, max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        # Route INLABS requests through a residential proxy to bypass WAF datacenter IP blocking.
        # Set INLABS_PROXY=http://user:pass@host:port in .env to enable.
        proxy_url = (os.getenv("INLABS_PROXY") or "").strip() or None
        if proxy_url:
            self.session.proxies = {"http": proxy_url, "https": proxy_url}
            logger.info("INLABS proxy configured")

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        headers = kwargs.pop("headers", {})
        merged_headers = _build_headers()
        merged_headers.update(headers)
        response = self.session.request(
            method, url, headers=merged_headers, timeout=(10, 180), **kwargs
        )
        time.sleep(_REQUEST_DELAY_SEC)
        return response

    def _login_once(self) -> None:
        if not ((self.user and self.password) or self.cookie):
            raise RuntimeError("INLABS credentials are not configured")

        if self.cookie:
            self.session.headers.update({"Cookie": self.cookie})

        if self.user and self.password:
            landing = self._request("GET", _ACCESS_URL)
            landing.raise_for_status()
            if "Request Rejected" in landing.text:
                raise RuntimeError("INLABS rejected the login page request")

            payload = {
                "email": self.user,
                "password": self.password,
            }
            response = self._request(
                "POST", _LOGIN_URL, data=payload, allow_redirects=True
            )
            response.raise_for_status()
            if "Request Rejected" in response.text:
                raise RuntimeError("INLABS rejected the login request")
            if "Minha Conta" in response.text or "Olá " in response.text:
                logger.info("Authenticated with INLABS using user/password")
                return
            if "inlabs_session_cookie" in response.headers.get("set-cookie", ""):
                logger.info("Authenticated with INLABS using session cookie")
                return

        if self.cookie:
            test_response = self._request(
                "GET", _DATE_URL_TEMPLATE.format(date=_today_utc().isoformat())
            )
            test_response.raise_for_status()
            if "Minha Conta" in test_response.text or "Olá " in test_response.text:
                logger.info("Authenticated with INLABS using pre-existing cookie")
                return

        raise RuntimeError("INLABS authentication failed")

    def login(self) -> None:
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                self._login_once()
                return
            except Exception as exc:
                last_error = exc
                logger.warning("INLABS login attempt %s/3 failed: %s", attempt, exc)
                if attempt < 3:
                    time.sleep(attempt * 2)
        assert last_error is not None
        raise last_error

    def fetch_day_index(self, target_date: date) -> str:
        response = self._request(
            "GET", _DATE_URL_TEMPLATE.format(date=target_date.isoformat())
        )
        response.raise_for_status()
        if "Request Rejected" in response.text:
            raise RuntimeError("INLABS rejected the request")
        if "Minha Conta" not in response.text and "Olá " not in response.text:
            raise RuntimeError("INLABS day page did not look authenticated")
        return response.text

    def list_day_zip_links(self, target_date: date) -> list[tuple[str, str]]:
        page = self.fetch_day_index(target_date)
        root = html.fromstring(page)
        links: list[tuple[str, str]] = []
        for anchor in root.xpath("//a[@href]"):
            href = anchor.get("href") or ""
            absolute_url = urljoin(_INLABS_BASE_URL, href.replace("&amp;", "&"))
            query = parse_qs(urlparse(absolute_url).query)
            filename = (query.get("dl") or [None])[0] or " ".join(
                anchor.itertext()
            ).strip()
            if not filename.lower().endswith(".zip"):
                continue
            if target_date.isoformat() not in filename:
                continue
            links.append((filename, absolute_url))
        return links

    def _inspect_zip_entries(self, zip_bytes: bytes) -> tuple[int, list[str]]:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            names = archive.namelist()
        xml_entries = [name for name in names if name.lower().endswith(".xml")]
        return len(xml_entries), names[:10]

    def download_day_zips(
        self, target_date: date, download_dir: Path | None = None
    ) -> list[Path]:
        zip_links = self.list_day_zip_links(target_date)
        if not zip_links:
            logger.warning("No INLABS ZIPs found for %s", target_date.isoformat())
            return []

        base_dir = download_dir or _download_root()
        day_dir = base_dir / target_date.isoformat()
        day_dir.mkdir(parents=True, exist_ok=True)

        saved_paths: list[Path] = []
        for filename, url in zip_links:
            destination = day_dir / filename
            logger.info("Downloading INLABS ZIP %s", url)
            response = self._request("GET", url, stream=True)
            response.raise_for_status()
            if "application/octet-stream" not in response.headers.get(
                "Content-Type", ""
            ):
                body = response.text[:200]
                raise RuntimeError(f"Unexpected response for {filename}: {body}")
            with destination.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
            zip_bytes = destination.read_bytes()
            try:
                xml_count, sample_entries = self._inspect_zip_entries(zip_bytes)
            except zipfile.BadZipFile as exc:
                logger.warning(
                    "Skipping invalid INLABS archive %s: %s",
                    filename,
                    exc,
                )
                destination.unlink(missing_ok=True)
                continue
            if xml_count == 0:
                logger.warning(
                    "Skipping INLABS archive without XML entries %s sample_entries=%s",
                    filename,
                    sample_entries,
                )
                destination.unlink(missing_ok=True)
                continue
            saved_paths.append(destination)
        return saved_paths


def _pg_count_for_date(target_date: date) -> int:
    """Count DOU docs in Postgres for a given pub_date."""
    with psycopg.connect(_pg_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM raw.dou_documents_raw_data WHERE pub_date = %s",
                (target_date,),
            )
            return cur.fetchone()[0]


def process_daily_zips(zip_paths: list[Path]) -> int:
    processor = DouProcessor()
    total_docs = 0
    for zip_path in zip_paths:
        documents = processor.process_zip(zip_path.read_bytes(), zip_path.name)
        if not documents:
            logger.warning("No documents extracted from %s", zip_path)
            continue
        ingest_documents(documents)
        total_docs += len(documents)
    return total_docs


def ingest_single_day(
    target_date: date, download_dir: Path | None = None, *, skip_counts: bool = False
) -> dict[str, int]:
    before_count = -1
    after_count = -1
    if not skip_counts:
        before_count = _pg_count_for_date(target_date)

    client = InlabsClient()
    client.login()
    zip_paths = client.download_day_zips(target_date, download_dir=download_dir)
    processed_docs = process_daily_zips(zip_paths)

    if not skip_counts:
        after_count = _pg_count_for_date(target_date)
        inserted_delta = max(0, after_count - before_count)
    else:
        inserted_delta = processed_docs
    return {
        "zip_count": len(zip_paths),
        "processed_docs": processed_docs,
        "pg_before": before_count,
        "pg_after": after_count,
        "inserted_delta": inserted_delta,
    }


def ingest_month_to_date(
    year: int, month: int, *, end_date: date | None = None
) -> dict[str, int]:
    today = end_date or _today_utc()
    if year != today.year or month != today.month:
        raise ValueError(
            "INLABS month-to-date ingest only supports the current UTC month"
        )

    start = date(year, month, 1)
    totals = {
        "days_ok": 0,
        "days_failed": 0,
        "zip_count": 0,
        "processed_docs": 0,
        "inserted_delta": 0,
    }
    client = InlabsClient()
    client.login()

    for current_date in _iter_dates(start, today):
        try:
            zip_paths = client.download_day_zips(current_date)
            if not zip_paths:
                logger.warning("No daily ZIPs found for %s", current_date.isoformat())
                totals["days_failed"] += 1
                continue

            before_count = _pg_count_for_date(current_date)
            processed_docs = process_daily_zips(zip_paths)
            after_count = _pg_count_for_date(current_date)

            totals["days_ok"] += 1
            totals["zip_count"] += len(zip_paths)
            totals["processed_docs"] += processed_docs
            totals["inserted_delta"] += max(0, after_count - before_count)
        except Exception as exc:
            logger.warning(
                "INLABS ingest failed for %s: %s", current_date.isoformat(), exc
            )
            totals["days_failed"] += 1

    return totals


def cleanup_download_root() -> None:
    shutil.rmtree(_download_root(), ignore_errors=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="INLABS daily DOU ingest")
    parser.add_argument("--date", type=str, help="Single day to ingest (YYYY-MM-DD)")
    parser.add_argument("--year", type=int, help="Year for month-to-date ingest")
    parser.add_argument("--month", type=int, help="Month for month-to-date ingest")
    parser.add_argument(
        "--zip-path",
        action="append",
        help="Process one or more already-downloaded ZIP paths",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep downloaded ZIPs under the temp root",
    )
    parser.add_argument(
        "--skip-counts",
        action="store_true",
        help="Skip Mongo before/after date counts for faster daily ingest",
    )
    return parser


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )
    args = build_parser().parse_args()

    if args.zip_path:
        processed_docs = process_daily_zips(
            [Path(path).expanduser() for path in args.zip_path]
        )
        logger.info(
            "INLABS zip-path processing complete processed_docs=%s zip_count=%s",
            processed_docs,
            len(args.zip_path),
        )
    elif args.date:
        target_date = date.fromisoformat(args.date)
        result = ingest_single_day(target_date, skip_counts=args.skip_counts)
        logger.info(
            "INLABS day complete date=%s zip_count=%s processed_docs=%s inserted_delta=%s pg_before=%s pg_after=%s",
            args.date,
            result["zip_count"],
            result["processed_docs"],
            result["inserted_delta"],
            result["pg_before"],
            result["pg_after"],
        )
    elif args.year and args.month:
        result = ingest_month_to_date(args.year, args.month)
        logger.info(
            "INLABS month-to-date complete year=%s month=%s days_ok=%s days_failed=%s zip_count=%s processed_docs=%s inserted_delta=%s",
            args.year,
            args.month,
            result["days_ok"],
            result["days_failed"],
            result["zip_count"],
            result["processed_docs"],
            result["inserted_delta"],
        )
    else:
        raise SystemExit("Pass --date YYYY-MM-DD or --year YYYY --month MM")

    if not args.keep_temp:
        cleanup_download_root()


if __name__ == "__main__":
    main()
