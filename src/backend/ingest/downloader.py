import json
import logging
import os
from pathlib import Path
import time
from typing import Dict, List, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_REGISTRY_PATH = _REPO_ROOT / "ops" / "data" / "dou_catalog_registry.json"

class DouDownloader:
    BASE_URL = "https://www.in.gov.br/documents"
    GROUP_ID = "49035712"
    
    def __init__(self, registry_path: str | None = None):
        self.registry = self._load_registry(registry_path)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
        })
        retry = Retry(
            total=5,
            connect=5,
            read=5,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(pool_connections=32, pool_maxsize=32, max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _load_registry(self, path: str | None) -> Dict:
        configured_path = path or os.getenv("DOU_REGISTRY_PATH")
        registry_path = Path(configured_path).expanduser() if configured_path else _DEFAULT_REGISTRY_PATH

        if not registry_path.is_absolute():
            registry_path = (_REPO_ROOT / registry_path).resolve()

        if not registry_path.exists():
            raise FileNotFoundError(
                f"DOU registry not found at {registry_path}. "
                "Commit ops/data/dou_catalog_registry.json or set DOU_REGISTRY_PATH explicitly."
            )

        logger.info("Loading DOU registry from %s", registry_path)
        with registry_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def get_month_data(self, year: int, month: int) -> Optional[Dict]:
        """Get folder ID and file list for a specific month."""
        month_key = f"{year}-{month:02d}"
        folder_id = self.registry.get("folder_ids", {}).get(month_key)
        files = self.registry.get("files", {}).get(month_key, [])
        
        if not folder_id:
            logger.warning(f"No folder ID found for {month_key}")
            return None
            
        return {"folder_id": folder_id, "files": files}

    def download_file(self, folder_id: str, filename: str, save_path: Optional[str] = None) -> Optional[bytes]:
        """
        Download a file from Liferay.
        If save_path is provided, saves the file to that location.
        """
        url = f"{self.BASE_URL}/{self.GROUP_ID}/{folder_id}/{filename}"
        try:
            logger.info(f"Downloading {url}")
            response = self.session.get(url, timeout=(10, 180))
            response.raise_for_status()
            content = response.content
            
            if save_path:
                # Ensure directory exists
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                with open(save_path, 'wb') as f:
                    f.write(content)
                logger.info(f"Saved to {save_path}")
                
            return content
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download {url}: {e}")
            return None
