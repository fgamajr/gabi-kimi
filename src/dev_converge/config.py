from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DEV_CONVERGE_MONGO_STRING: str = "mongodb://mongo:27017/gabi_dou"
    DEV_CONVERGE_DB_NAME: str = "gabi_dou"
    DEV_CONVERGE_SITE_URL: str = "https://converge.gabidou.top"
    DEV_CONVERGE_ALLOWED_HOSTS: str = "localhost,127.0.0.1,dev-converge-api"
    DEV_CONVERGE_API_TOKENS: str = ""
    DEV_CONVERGE_DATA_ROOT: str = "/data/dev_converge"
    DEV_CONVERGE_SYNC_TIMEOUT_SEC: int = 90
    DEV_CONVERGE_JOB_RETENTION_HOURS: int = 168
    DEV_CONVERGE_STALE_JOB_SEC: int = 600
    DEV_CONVERGE_MAX_PARALLEL_AGENTS: int = 4

    @property
    def api_tokens(self) -> dict[str, str]:
        tokens: dict[str, str] = {}
        for entry in self.DEV_CONVERGE_API_TOKENS.split(","):
            entry = entry.strip()
            if not entry:
                continue
            if ":" in entry:
                label, token = entry.split(":", 1)
                tokens[token.strip()] = label.strip()
            else:
                tokens[entry] = "anonymous"
        return tokens

    @property
    def allowed_hosts(self) -> list[str]:
        hosts = [
            host.strip()
            for host in self.DEV_CONVERGE_ALLOWED_HOSTS.split(",")
            if host.strip()
        ]
        site_hostname = urlparse(self.DEV_CONVERGE_SITE_URL).hostname
        if site_hostname and site_hostname not in hosts:
            hosts.append(site_hostname)
        return hosts

    @property
    def data_root(self) -> Path:
        return Path(self.DEV_CONVERGE_DATA_ROOT)

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
