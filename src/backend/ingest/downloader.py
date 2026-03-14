import logging
import requests
import time
import os
from typing import Optional, List, Dict
import json

logger = logging.getLogger(__name__)

class DouDownloader:
    BASE_URL = "https://www.in.gov.br/documents"
    GROUP_ID = "49035712"
    
    def __init__(self, registry_path: str = "ops/data/dou_catalog_registry.json"):
        self.registry = self._load_registry(registry_path)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
        })

    def _load_registry(self, path: str) -> Dict:
        if not os.path.exists(path):
            logger.error(f"Registry not found at {path}")
            return {}
        with open(path, 'r') as f:
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
            response = self.session.get(url, timeout=120) # Increased timeout for larger files
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
