"""Programmatic controller for a reusable local PostgreSQL Docker appliance."""

from __future__ import annotations

from dataclasses import dataclass
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


class InfraError(RuntimeError):
    """Raised for infra lifecycle failures with actionable messages."""


@dataclass(frozen=True)
class InfraConfig:
    compose_file: Path
    service_name: str = "postgres"
    container_name: str = "gabi-postgres-appliance"
    es_service_name: str = "elasticsearch"
    es_container_name: str = "gabi-elasticsearch"
    redis_service_name: str = "redis"
    redis_container_name: str = "gabi-redis"
    user: str = "gabi"
    password: str = "gabi"
    database: str = "gabi"
    port: int = 5433
    es_port: int = 9200
    redis_port: int = 6380
    ready_timeout_sec: int = 60


class PostgresAppliance:
    def __init__(self, config: InfraConfig | None = None) -> None:
        base_dir = Path(__file__).resolve().parent
        self._cfg = config or InfraConfig(compose_file=base_dir / "docker-compose.yml")

    def up(self) -> dict[str, Any]:
        self._ensure_docker_available()
        self._compose(
            [
                "up",
                "-d",
                self._cfg.service_name,
                self._cfg.es_service_name,
                self._cfg.redis_service_name,
            ]
        )
        self._wait_until_ready()
        return self.status()

    def down(self) -> dict[str, Any]:
        self._ensure_docker_available()
        # stop keeps container + volume for fast iterative runs
        self._compose(
            [
                "stop",
                self._cfg.service_name,
                self._cfg.es_service_name,
                self._cfg.redis_service_name,
            ]
        )
        return self.status()

    def destroy(self) -> dict[str, Any]:
        self._ensure_docker_available()
        # full teardown: container + volume
        self._compose(["down", "-v", "--remove-orphans"])
        return self.status()

    def reset_db(self) -> dict[str, Any]:
        # reset must not recreate container/volume; ensure running, then wipe schema only
        self.up()
        sql = (
            "DROP SCHEMA public CASCADE;"
            "CREATE SCHEMA public;"
            "GRANT ALL ON SCHEMA public TO gabi;"
            "GRANT ALL ON SCHEMA public TO public;"
        )
        self._docker_exec_psql(sql)
        return self.status()

    def recreate(self) -> dict[str, Any]:
        self.up()
        self.reset_db()
        return self.status()

    def status(self) -> dict[str, Any]:
        self._ensure_docker_available()
        exists = self._container_exists()
        es_exists = self._container_exists(self._cfg.es_container_name)
        redis_exists = self._container_exists(self._cfg.redis_container_name)
        if not exists:
            return {
                "container": self._cfg.container_name,
                "exists": False,
                "running": False,
                "healthy": False,
                "port": self._cfg.port,
                "elasticsearch": {
                    "container": self._cfg.es_container_name,
                    "exists": es_exists,
                    "running": False,
                    "healthy": False,
                    "port": self._cfg.es_port,
                },
                "redis": {
                    "container": self._cfg.redis_container_name,
                    "exists": redis_exists,
                    "running": False,
                    "healthy": False,
                    "port": self._cfg.redis_port,
                },
            }

        inspect = self._docker_inspect()
        state = inspect.get("State", {})
        health = (state.get("Health") or {}).get("Status", "unknown")
        es_state = {}
        redis_state = {}
        if es_exists:
            es_inspect = self._docker_inspect(self._cfg.es_container_name)
            es_state = es_inspect.get("State", {})
        if redis_exists:
            redis_inspect = self._docker_inspect(self._cfg.redis_container_name)
            redis_state = redis_inspect.get("State", {})
        es_health = (es_state.get("Health") or {}).get("Status", "unknown") if es_state else "unknown"
        redis_health = (redis_state.get("Health") or {}).get("Status", "unknown") if redis_state else "unknown"
        return {
            "container": self._cfg.container_name,
            "exists": True,
            "running": bool(state.get("Running", False)),
            "healthy": health == "healthy",
            "health": health,
            "status": state.get("Status", "unknown"),
            "port": self._cfg.port,
            "elasticsearch": {
                "container": self._cfg.es_container_name,
                "exists": es_exists,
                "running": bool(es_state.get("Running", False)) if es_exists else False,
                "healthy": es_health == "healthy",
                "health": es_health,
                "status": es_state.get("Status", "unknown") if es_exists else "missing",
                "port": self._cfg.es_port,
            },
            "redis": {
                "container": self._cfg.redis_container_name,
                "exists": redis_exists,
                "running": bool(redis_state.get("Running", False)) if redis_exists else False,
                "healthy": redis_health == "healthy",
                "health": redis_health,
                "status": redis_state.get("Status", "unknown") if redis_exists else "missing",
                "port": self._cfg.redis_port,
            },
        }

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + self._cfg.ready_timeout_sec
        last_error: str | None = None

        while time.monotonic() < deadline:
            try:
                st = self.status()
                es = st.get("elasticsearch", {})
                red = st.get("redis", {})
                if (
                    st.get("running")
                    and st.get("healthy")
                    and bool(es.get("running"))
                    and bool(es.get("healthy"))
                    and bool(red.get("running"))
                    and bool(red.get("healthy"))
                ):
                    return
                self._docker_exec_pg_isready()
            except InfraError as ex:
                last_error = str(ex)
            time.sleep(1)

        raise InfraError(
            "Postgres did not become ready within timeout"
            + (f"; last_error={last_error}" if last_error else "")
        )

    def _docker_exec_pg_isready(self) -> None:
        self._run(
            [
                "docker",
                "exec",
                self._cfg.container_name,
                "pg_isready",
                "-U",
                self._cfg.user,
                "-d",
                self._cfg.database,
            ]
        )

    def _docker_exec_psql(self, sql: str) -> None:
        self._run(
            [
                "docker",
                "exec",
                "-e",
                f"PGPASSWORD={self._cfg.password}",
                self._cfg.container_name,
                "psql",
                "-U",
                self._cfg.user,
                "-d",
                self._cfg.database,
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                sql,
            ]
        )

    def _container_exists(self, container_name: str | None = None) -> bool:
        name = container_name or self._cfg.container_name
        cp = self._run(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                f"name=^{name}$",
                "--format",
                "{{.Names}}",
            ],
            check=False,
        )
        return name in (cp.stdout or "").splitlines()

    def _docker_inspect(self, container_name: str | None = None) -> dict[str, Any]:
        name = container_name or self._cfg.container_name
        cp = self._run(["docker", "inspect", name])
        data = json.loads(cp.stdout)
        if not data:
            raise InfraError(f"Container {name} not found")
        return data[0]

    def _compose(self, args: list[str]) -> None:
        cmd = ["docker", "compose", "-f", str(self._cfg.compose_file)] + args
        self._run(cmd)

    def _ensure_docker_available(self) -> None:
        if shutil.which("docker") is None:
            raise InfraError("docker CLI not found in PATH")
        cp = self._run(["docker", "info"], check=False)
        if cp.returncode != 0:
            msg = (cp.stderr or cp.stdout or "").strip()
            raise InfraError(f"docker daemon not available: {msg}")

    def _run(self, cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        cp = subprocess.run(cmd, text=True, capture_output=True)
        if check and cp.returncode != 0:
            msg = (cp.stderr or cp.stdout or "").strip()
            raise InfraError(f"command failed ({' '.join(cmd)}): {msg}")
        return cp
