#!/usr/bin/env python3
"""
Testa a rota de admin upload usando um ZIP baixado pelo mesmo fluxo do pipeline.

O catálogo (ops/data/dou_catalog_registry.json) alimenta as rotas de download:
  - zip_downloader.load_folder_registry() + build_targets(date_range) + download_zip()

Este script: baixa um mês (ex.: 2004-01) com esse fluxo, depois envia o ZIP
via POST /api/admin/upload e opcionalmente consulta o status do job.

Uso (na raiz do repo, com .env carregado):
  python ops/scripts/test_admin_upload_from_catalog.py
  python ops/scripts/test_admin_upload_from_catalog.py --year 2004 --month 1
  python ops/scripts/test_admin_upload_from_catalog.py --zip ops/data/zips/2004-01_DO1.zip  # já baixado
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

# projeto na path e .env
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_env = _ROOT / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))

from src.backend.ingest.date_selector import DateRange
from src.backend.ingest.zip_downloader import build_targets, download_zip, load_folder_registry

import requests


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Baixa um mês do DOU (catálogo) e testa admin upload com esse ZIP"
    )
    ap.add_argument("--year", type=int, default=2004, help="Ano (ex: 2004)")
    ap.add_argument("--month", type=int, default=1, help="Mês (1-12)")
    ap.add_argument(
        "--zip",
        type=Path,
        help="Usar ZIP já existente (não baixar); path absoluto ou relativo ao repo",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Diretório para salvar o ZIP baixado (default: ops/data/zips)",
    )
    ap.add_argument("--no-wait", action="store_true", help="Não fazer poll do job")
    args = ap.parse_args()

    base = os.getenv("GABI_API_BASE", "http://localhost:8000").rstrip("/")
    token = os.getenv("GABI_ADMIN_TOKEN", "dev-admin-token")
    headers = {"Authorization": f"Bearer {token}"}

    zip_path: Path | None = args.zip
    if zip_path and not zip_path.is_absolute():
        zip_path = _ROOT / zip_path

    if not zip_path or not zip_path.exists():
        # Baixar um mês usando o mesmo fluxo que alimenta as rotas (catálogo + zip_downloader)
        load_folder_registry()
        start = date(args.year, args.month, 1)
        if args.month == 12:
            end = date(args.year, 12, 31)
        else:
            end = date(args.year, args.month + 1, 1) - timedelta(days=1)
        dr = DateRange(start=start, end=end)
        targets = build_targets(dr, sections=["do1"], include_extras=False)
        if not targets:
            print(
                f"Nenhum target para {args.year}-{args.month:02d}. "
                "Verifique ops/data/dou_catalog_registry.json (folder_ids + files).",
                file=sys.stderr,
            )
            sys.exit(1)
        out_dir = args.out_dir or (_ROOT / "ops" / "data" / "zips")
        out_dir.mkdir(parents=True, exist_ok=True)
        t = targets[0]
        print(f"Baixando 1 mês ({t.pub_date.strftime('%Y-%m')}) do catálogo: {t.filename} ...")
        result = download_zip(t, out_dir, skip_existing=True)
        if not result.success:
            print(f"Download falhou: {result.error} (HTTP {result.http_status})", file=sys.stderr)
            sys.exit(1)
        zip_path = result.local_path
        assert zip_path and zip_path.exists()
        print(f"Salvo: {zip_path} ({zip_path.stat().st_size} bytes)")

    print(f"Enviando {zip_path} para {base}/api/admin/upload ...")
    with open(zip_path, "rb") as f:
        r = requests.post(
            f"{base}/api/admin/upload",
            headers=headers,
            files={"file": (zip_path.name, f, "application/zip")},
            timeout=300,
        )
    if r.status_code != 202:
        print(f"Upload falhou: {r.status_code} {r.text}", file=sys.stderr)
        sys.exit(1)
    body = r.json()
    job_id = body.get("job_id")
    if not job_id:
        print(f"Resposta sem job_id: {body}", file=sys.stderr)
        sys.exit(1)
    print(f"Job criado: {job_id} (status={body.get('status', 'queued')})")

    if args.no_wait:
        print(f"Ver status: GET {base}/api/admin/jobs/{job_id}")
        return

    print("Aguardando job (completed/failed/partial) ...")
    for i in range(180):
        time.sleep(2)
        j = requests.get(f"{base}/api/admin/jobs/{job_id}", headers=headers, timeout=10)
        if j.status_code != 200:
            print(f"GET job falhou: {j.status_code}")
            continue
        job = j.json()
        status = job.get("status")
        print(
            f"  [{i+1}] status={status} articles_found={job.get('articles_found')} "
            f"ingested={job.get('articles_ingested')} failed={job.get('articles_failed')} "
            f"error={job.get('error_message') or '-'}"
        )
        if status in ("completed", "failed", "partial"):
            print(f"Terminal: {status}")
            if job.get("error_message"):
                print(f"  error_message: {job['error_message']}")
            sys.exit(0 if status == "completed" else 1)
    print("Timeout aguardando status terminal.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
