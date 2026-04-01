"""Unit tests for publicacoes hybrid and semantic search payloads."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ops.bin import mcp_es_server  # noqa: E402


class TestPublicacoesSearch(unittest.TestCase):
    @patch("ops.bin.mcp_es_server._get_openai_embedding", return_value=[0.1, 0.2])
    @patch("ops.bin.mcp_es_server.ES.request")
    def test_search_publicacoes_hybrid_uses_page_aware_rrf_window(
        self,
        mock_request,
        _mock_embedding,
    ):
        def fake_request(method: str, path: str, payload: dict):
            self.assertEqual(method, "POST")
            self.assertEqual(path, f"/{mcp_es_server.ES.publicacoes_index}/_search")
            self.assertEqual(payload["from"], 20)
            self.assertEqual(payload["size"], 10)
            self.assertEqual(payload["rank"]["rrf"]["window_size"], 100)
            self.assertEqual(payload["knn"]["k"], 100)
            self.assertEqual(payload["knn"]["num_candidates"], 200)
            self.assertEqual(
                payload["knn"]["filter"],
                {
                    "bool": {
                        "filter": [
                            {"term": {"pub_type": "cartilha"}},
                            {
                                "range": {
                                    "pub_date": {
                                        "gte": "2024-01-01",
                                        "lte": "2024-12-31",
                                    }
                                }
                            },
                        ]
                    }
                },
            )
            return {
                "hits": {
                    "total": {"value": 1},
                    "hits": [
                        {
                            "_score": 0.1234,
                            "_source": {
                                "doc_id": "pub-1",
                                "title": "Manual de Auditoria Operacional",
                                "pub_type": "cartilha",
                                "pub_date": "2020-12-11",
                                "description": "desc",
                                "pdf_urls": [],
                                "source_url": "https://example.com/pub-1",
                                "page_count": 170,
                            },
                        }
                    ],
                }
            }

        mock_request.side_effect = fake_request

        result = mcp_es_server._search_publicacoes_once(
            query="auditoria",
            pub_type="cartilha",
            date_from="2024-01-01",
            date_to="2024-12-31",
            page=3,
            page_size=10,
        )

        self.assertEqual(result["method"], "hybrid_rrf")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["results"][0]["score"], 0.1234)

    @patch("ops.bin.mcp_es_server._get_openai_embedding", return_value=[0.1, 0.2])
    @patch("ops.bin.mcp_es_server.ES.request")
    def test_semantic_publicacoes_uses_publicacoes_index_and_pub_date_filter(
        self,
        mock_request,
        _mock_embedding,
    ):
        def fake_request(method: str, path: str, payload: dict):
            self.assertEqual(method, "POST")
            self.assertEqual(path, f"/{mcp_es_server.ES.publicacoes_index}/_search")
            self.assertEqual(
                payload["knn"]["filter"],
                {
                    "bool": {
                        "filter": [
                            {
                                "range": {
                                    "pub_date": {
                                        "gte": "2024-01-01",
                                        "lte": "2024-12-31",
                                    }
                                }
                            }
                        ]
                    }
                },
            )
            return {
                "hits": {
                    "total": {"value": 1},
                    "hits": [
                        {
                            "sort": [0.8123],
                            "_source": {
                                "doc_id": "pub-2",
                                "title": "Governanca em TIC para o Setor Publico",
                                "pub_type": "cartilha",
                                "pub_date": "2021-01-01",
                                "description": "desc",
                                "pdf_urls": [],
                                "source_url": "https://example.com/pub-2",
                                "page_count": 42,
                            },
                        }
                    ],
                }
            }

        mock_request.side_effect = fake_request

        result = mcp_es_server.es_tcu_semantic_search(
            query="governanca de TI",
            source="publicacoes",
            k=3,
            date_from="2024-01-01",
            date_to="2024-12-31",
            vigente=True,
        )

        self.assertEqual(result["source"], "publicacoes")
        self.assertEqual(result["method"], "semantic_knn")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["results"][0]["score"], 0.8123)
        self.assertTrue(result["results"][0]["is_knn"])
        self.assertEqual(result["results"][0]["knn_score"], 0.8123)


if __name__ == "__main__":
    unittest.main()
