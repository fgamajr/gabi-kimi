from __future__ import annotations

import json
import time
from datetime import date
from typing import Any

from bson import ObjectId

from ops.migrations._common import (
    clamp_spot_check_size,
    count_postgres,
    iter_batches,
    safe_bool,
    safe_date,
    safe_json_payload,
    sha256_text,
    write_log,
)


RAW_TABLE = "raw.tcu_acordaos_raw_data"
TYPED_TABLE = "raw.tcu_acordaos"


# ---------------------------------------------------------------------------
# Two-family taxonomy
# ---------------------------------------------------------------------------
# Family A — "acordao-completo" (source_type=tcu_acordao):
#   tipos: ACÓRDÃO, ACÓRDÃO DE RELAÇÃO, DECISÃO
#   primary text: acordao_texto  (CSV col: ACORDAO)
#   extra text:   relatorio, voto, sumario, decisao
#   key cols:     has_relatorio, has_voto, relator, situacao, tipoprocesso
#
# Family B — "jurisprudencia" (source_types: tcu_jurisprudencia,
#             tcu_boletim_jurisprudencia, tcu_boletim_pessoal, tcu_boletim_lc,
#             tcu_resposta_consulta, tcu_sumula):
#   tipos: JURISPRUDÊNCIA SELECIONADA, BOLETIM, RESPOSTA A CONSULTA, SÚMULA
#   primary text: enunciado         (CSV col: ENUNCIADO)
#   secondary:    excerto/sumario, texto_acordao, texto_info
#   key cols:     area, tema, subtema, numero_referencia, vigente, autortese
# ---------------------------------------------------------------------------

_ACORDAO_TIPOS = {"ACÓRDÃO", "ACÓRDÃO DE RELAÇÃO", "DECISÃO"}


def ensure_schema(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS raw.tcu_acordaos_raw_data (
                id TEXT PRIMARY KEY,
                all_fields JSONB NOT NULL,
                dumped_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS raw.tcu_acordaos (
                id TEXT PRIMARY KEY,
                tipo TEXT,
                source_type TEXT,           -- tcu_acordao | tcu_jurisprudencia | tcu_sumula | ...
                -- Family A (acordao-completo) columns
                has_relatorio BOOLEAN,
                has_voto BOOLEAN,
                relator TEXT,
                situacao TEXT,
                tipoprocesso TEXT,
                -- Family B (jurisprudencia/boletim/sumula/resposta) columns
                area TEXT,
                tema TEXT,
                subtema TEXT,
                numero_referencia TEXT,     -- NUMSUMULA for súmulas, NUMERO for boletins
                vigente BOOLEAN,            -- only súmulas
                autortese TEXT,
                -- Shared
                data_sessao DATE,
                colegiado TEXT,
                raw_text_hash TEXT NOT NULL, -- SHA256(acordao_texto) for Family A; SHA256(enunciado) for Family B
                all_fields JSONB NOT NULL,
                migrated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS ix_raw_tcu_acordaos_tipo ON raw.tcu_acordaos (tipo);
            CREATE INDEX IF NOT EXISTS ix_raw_tcu_acordaos_source_type ON raw.tcu_acordaos (source_type);
            CREATE INDEX IF NOT EXISTS ix_raw_tcu_acordaos_data_sessao ON raw.tcu_acordaos (data_sessao);
            CREATE INDEX IF NOT EXISTS ix_raw_tcu_acordaos_area ON raw.tcu_acordaos (area);
            """
        )

        # Migrate existing table: add missing columns if they don't exist yet
        new_cols = [
            ("source_type", "TEXT"),
            ("relator", "TEXT"),
            ("situacao", "TEXT"),
            ("tipoprocesso", "TEXT"),
            ("area", "TEXT"),
            ("tema", "TEXT"),
            ("subtema", "TEXT"),
            ("numero_referencia", "TEXT"),
            ("vigente", "BOOLEAN"),
            ("autortese", "TEXT"),
        ]
        for col, coltype in new_cols:
            cur.execute(
                """
                ALTER TABLE raw.tcu_acordaos ADD COLUMN IF NOT EXISTS %s %s;
                """ % (col, coltype)  # noqa: S608 – column names are hardcoded above, not user input
            )
        for idx_col in ("source_type", "area"):
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_raw_tcu_acordaos_%s ON raw.tcu_acordaos (%s);
                """ % (idx_col, idx_col)  # noqa: S608
            )
    conn.commit()


def _build_typed_fields(document: dict[str, Any]) -> dict[str, Any]:
    tipo = document.get("tipo")
    source_type = document.get("source_type")
    data_sessao = safe_date(document.get("data_sessao"))
    colegiado = document.get("colegiado")

    if tipo in _ACORDAO_TIPOS:
        # Family A: acordao-completo
        acordao_texto = document.get("acordao_texto")
        raw_text_hash = sha256_text(acordao_texto if isinstance(acordao_texto, str) else "")
        return {
            "tipo": tipo,
            "source_type": source_type,
            "has_relatorio": safe_bool(document.get("has_relatorio")),
            "has_voto": safe_bool(document.get("has_voto")),
            "relator": document.get("relator") or document.get("RELATOR"),
            "situacao": document.get("situacao") or document.get("SITUACAO"),
            "tipoprocesso": document.get("tipoprocesso") or document.get("TIPOPROCESSO"),
            "data_sessao": data_sessao,
            "colegiado": colegiado,
            "raw_text_hash": raw_text_hash,
            # Family B columns null for this family
            "area": None,
            "tema": None,
            "subtema": None,
            "numero_referencia": None,
            "vigente": None,
            "autortese": None,
        }
    else:
        # Family B: jurisprudencia / boletim / sumula / resposta-consulta
        enunciado = document.get("enunciado")
        raw_text_hash = sha256_text(enunciado if isinstance(enunciado, str) else "")
        # numero_referencia: NUMSUMULA for súmulas, NUMERO for boletins
        num = document.get("numero_sumula") or document.get("numero") or document.get("num_sumula")
        vigente_raw = document.get("vigente")
        vigente = safe_bool(vigente_raw) if vigente_raw is not None else None
        return {
            "tipo": tipo,
            "source_type": source_type,
            "has_relatorio": None,
            "has_voto": None,
            "relator": None,
            "situacao": None,
            "tipoprocesso": document.get("tipoprocesso") or document.get("TIPOPROCESSO"),
            "data_sessao": data_sessao,
            "colegiado": colegiado,
            "raw_text_hash": raw_text_hash,
            "area": document.get("area"),
            "tema": document.get("tema"),
            "subtema": document.get("subtema"),
            "numero_referencia": str(num) if num is not None else None,
            "vigente": vigente,
            "autortese": document.get("autortese") or document.get("autor_tese"),
        }


def _insert_raw_batch(conn: Any, batch: list[dict[str, Any]]) -> int:
    values: list[tuple[str, str]] = []
    for document in batch:
        doc_id = str(document.get("_id", "")).strip()
        if not doc_id:
            continue
        payload = safe_json_payload(document)
        values.append((doc_id, json.dumps(payload, ensure_ascii=False)))

    if not values:
        return 0

    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO raw.tcu_acordaos_raw_data (id, all_fields) VALUES (%s, %s::jsonb) ON CONFLICT (id) DO NOTHING;",
            values,
        )
    conn.commit()
    return len(values)


def _materialize_typed(conn: Any, page_size: int) -> int:
    inserted = 0
    last_id = ""
    while True:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, all_fields
                FROM raw.tcu_acordaos_raw_data
                WHERE id > %s
                ORDER BY id
                LIMIT %s;
                """,
                (last_id, page_size),
            )
            rows = cur.fetchall()

        if not rows:
            break

        payload: list[tuple] = []
        for doc_id, all_fields in rows:
            fields = all_fields if isinstance(all_fields, dict) else {}
            f = _build_typed_fields(fields)
            payload.append((
                doc_id,
                f["tipo"], f["source_type"],
                f["has_relatorio"], f["has_voto"], f["relator"], f["situacao"], f["tipoprocesso"],
                f["area"], f["tema"], f["subtema"], f["numero_referencia"], f["vigente"], f["autortese"],
                f["data_sessao"], f["colegiado"], f["raw_text_hash"],
                json.dumps(fields, ensure_ascii=False),
            ))

        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO raw.tcu_acordaos (
                    id, tipo, source_type,
                    has_relatorio, has_voto, relator, situacao, tipoprocesso,
                    area, tema, subtema, numero_referencia, vigente, autortese,
                    data_sessao, colegiado, raw_text_hash, all_fields
                )
                VALUES (%s, %s, %s,  %s, %s, %s, %s, %s,  %s, %s, %s, %s, %s, %s,  %s, %s, %s, %s::jsonb)
                ON CONFLICT (id) DO UPDATE SET
                    tipo = EXCLUDED.tipo,
                    source_type = EXCLUDED.source_type,
                    has_relatorio = EXCLUDED.has_relatorio,
                    has_voto = EXCLUDED.has_voto,
                    relator = EXCLUDED.relator,
                    situacao = EXCLUDED.situacao,
                    tipoprocesso = EXCLUDED.tipoprocesso,
                    area = EXCLUDED.area,
                    tema = EXCLUDED.tema,
                    subtema = EXCLUDED.subtema,
                    numero_referencia = EXCLUDED.numero_referencia,
                    vigente = EXCLUDED.vigente,
                    autortese = EXCLUDED.autortese,
                    data_sessao = EXCLUDED.data_sessao,
                    colegiado = EXCLUDED.colegiado,
                    raw_text_hash = EXCLUDED.raw_text_hash,
                    all_fields = EXCLUDED.all_fields;
                """,
                payload,
            )
        conn.commit()
        inserted += len(payload)
        last_id = rows[-1][0]

    return inserted


def _spot_check_hashes(mongo_collection: Any, conn: Any, sample_size: int) -> tuple[int, int]:
    sample_size = clamp_spot_check_size(sample_size)
    if sample_size <= 0:
        return 0, 0

    # Sample from Postgres — include tipo so we can pick the correct hash source per family
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, tipo, raw_text_hash FROM raw.tcu_acordaos ORDER BY random() LIMIT %s",
            (sample_size,),
        )
        pg_rows: dict[str, tuple[str | None, str]] = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

    if not pg_rows:
        return 0, 0

    oid_list: list[Any] = []
    for id_str in pg_rows:
        try:
            oid_list.append(ObjectId(id_str))
        except Exception:
            pass

    if not oid_list:
        return 0, 0

    checked = 0
    errors = 0
    for document in mongo_collection.find({"_id": {"$in": oid_list}}):
        doc_id = str(document.get("_id", "")).strip()
        if not doc_id:
            continue
        tipo, stored_hash = pg_rows[doc_id]
        if tipo in _ACORDAO_TIPOS:
            # Family A: hash of acordao_texto
            text = document.get("acordao_texto")
        else:
            # Family B: hash of enunciado
            text = document.get("enunciado")
        expected = sha256_text(text if isinstance(text, str) else "")
        checked += 1
        if stored_hash != expected:
            errors += 1

    return checked, errors


def run(
    mongo_db: Any,
    conn: Any,
    spec: Any,
    *,
    batch_size: int,
    typed_page_size: int,
    spot_check_size: int,
    raw_only: bool,
    limit: int | None,
    ddl_only: bool,
) -> None:
    ensure_schema(conn)
    if ddl_only:
        print(json.dumps({"collection": spec.name, "stage": "ddl_only", "status": "ok"}, ensure_ascii=False))
        return

    mongo_collection = mongo_db[spec.mongo_name]
    source_count = mongo_collection.estimated_document_count()
    effective_source_count = min(source_count, limit) if limit is not None else source_count
    print(f"[{spec.name}] source_count={source_count} effective={effective_source_count}")

    raw_start = time.perf_counter()
    raw_seen = 0
    for batch in iter_batches(mongo_collection, batch_size, limit=limit):
        raw_seen += _insert_raw_batch(conn, batch)
        if raw_seen and raw_seen % 10000 == 0:
            print(f"[{spec.name}] raw processed={raw_seen}")

    raw_target = count_postgres(conn, RAW_TABLE)
    raw_elapsed = time.perf_counter() - raw_start
    raw_status = "ok" if raw_seen == effective_source_count else "warn"

    write_log(
        conn,
        collection=spec.name,
        stage="raw_dump",
        count_mongo=effective_source_count,
        count_postgres=raw_target,
        hash_errors=0,
        duration_s=raw_elapsed,
        status=raw_status,
        details={"batch_size": batch_size, "limit": limit, "inserted_this_run": raw_seen, "raw_only": raw_only},
    )

    print(
        json.dumps(
            {
                "collection": spec.name,
                "stage": "raw_dump",
                "count_source": effective_source_count,
                "count_target": raw_target,
                "inserted_this_run": raw_seen,
                "duration_s": round(raw_elapsed, 2),
                "status": raw_status,
            },
            ensure_ascii=False,
        )
    )

    if raw_only:
        return

    typed_start = time.perf_counter()
    typed_processed = _materialize_typed(conn, typed_page_size)
    typed_target = count_postgres(conn, TYPED_TABLE)
    typed_elapsed = time.perf_counter() - typed_start
    checked, hash_errors = _spot_check_hashes(mongo_collection, conn, spot_check_size)
    typed_status = "ok" if hash_errors == 0 else "warn"

    write_log(
        conn,
        collection=spec.name,
        stage="typed_materialization",
        count_mongo=raw_target,
        count_postgres=typed_target,
        hash_errors=hash_errors,
        duration_s=typed_elapsed,
        status=typed_status,
        details={
            "typed_page_size": typed_page_size,
            "typed_processed": typed_processed,
            "spot_check_size": spot_check_size,
            "spot_check_checked": checked,
            "limit": limit,
        },
    )

    print(
        json.dumps(
            {
                "collection": spec.name,
                "stage": "typed_materialization",
                "count_source": raw_target,
                "count_target": typed_target,
                "typed_processed": typed_processed,
                "spot_check_checked": checked,
                "hash_errors": hash_errors,
                "duration_s": round(typed_elapsed, 2),
                "status": typed_status,
            },
            ensure_ascii=False,
        )
    )