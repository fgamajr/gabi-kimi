"""Testes unitários para comandos CLI."""

from __future__ import annotations

import json

from gabi import cli


def test_build_parser_includes_ingest_all() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(
        ["ingest-all", "--sources-file", "sources.yaml", "--max-docs-per-source", "1", "--disable-embeddings"]
    )
    assert args.command == "ingest-all"
    assert args.sources_file == "sources.yaml"
    assert args.max_docs_per_source == 1
    assert args.disable_embeddings is True


def test_load_source_ids(tmp_path) -> None:
    sources_file = tmp_path / "sources.yaml"
    sources_file.write_text(
        "sources:\n  source_a:\n    discovery: {}\n  source_b:\n    discovery: {}\n",
        encoding="utf-8",
    )
    source_ids = cli._load_source_ids(str(sources_file))
    assert source_ids == ["source_a", "source_b"]


def test_build_ingest_all_summary_top_level_buckets() -> None:
    results = [
        {
            "source_id": "ok_source",
            "status": "success",
            "errors": [],
            "error_summary": {},
        },
        {
            "source_id": "ext_fail",
            "status": "failed",
            "errors": [{"error": "dns", "classification": "source_unreachable_external"}],
            "error_summary": {"source_unreachable_external": 1},
            "source_unreachable": True,
        },
        {
            "source_id": "int_fail",
            "status": "failed",
            "errors": [{"error": "valueerror", "classification": "internal_pipeline_regression"}],
            "error_summary": {"internal_pipeline_regression": 1},
        },
    ]

    summary = cli._build_ingest_all_summary(results, total_elapsed_seconds=12.34)

    assert summary["total_sources"] == 3
    assert summary["successful_sources"] == 1
    assert summary["failed_sources"] == 2
    assert summary["failed_sources_external_unreachable"] == 1
    assert summary["failed_sources_internal_regression"] == 1
    assert summary["failed_sources_other"] == 0
    assert summary["error_summary"]["source_unreachable_external"] == 1
    assert summary["error_summary"]["internal_pipeline_regression"] == 1


def test_ingest_all_command_outputs_aggregate_summary(monkeypatch, tmp_path, capsys) -> None:
    sources_file = tmp_path / "sources.yaml"
    sources_file.write_text(
        "sources:\n  s_ok:\n    discovery: {}\n  s_ext:\n    discovery: {}\n",
        encoding="utf-8",
    )

    def _fake_run_sync(
        source_id: str,
        run_id: str | None,
        max_docs_per_source: int | None = None,
        disable_embeddings: bool = False,
    ) -> dict:
        assert max_docs_per_source == 1
        assert disable_embeddings is True
        if source_id == "s_ok":
            return {
                "source_id": source_id,
                "status": "success",
                "errors": [],
                "error_summary": {},
            }
        return {
            "source_id": source_id,
            "status": "failed",
            "errors": [{"error": "dns", "classification": "source_unreachable_external"}],
            "error_summary": {"source_unreachable_external": 1},
            "source_unreachable": True,
        }

    monkeypatch.setattr(cli, "_run_sync", _fake_run_sync)

    exit_code = cli.ingest_all_command(
        str(sources_file),
        run_id=None,
        max_docs_per_source=1,
        disable_embeddings=True,
    )
    assert exit_code == 0

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["total_sources"] == 2
    assert payload["failed_sources_external_unreachable"] == 1
    assert payload["failed_sources_internal_regression"] == 0
    assert payload["error_summary"]["source_unreachable_external"] == 1
