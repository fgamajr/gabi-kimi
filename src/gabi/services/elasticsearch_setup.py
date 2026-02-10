"""
Elasticsearch index setup for GABI documents.
BM25 + Vector hybrid search with Portuguese (pt-BR) analyzers.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

INDEX_NAME = "gabi_documents_v1"

# NOTE: dense_vector MUST be a top-level field — ES does not support it as
# a multi-field under text.  The embedding vector lives in "content_vector".
INDEX_SETTINGS: dict[str, Any] = {
    "number_of_shards": 1,
    "number_of_replicas": 0,
    "analysis": {
        "analyzer": {
            "pt_br_custom": {
                "type": "custom",
                "tokenizer": "standard",
                "filter": [
                    "lowercase",
                    "brazilian_stop",
                    "brazilian_stemmer",
                ],
            }
        },
        "filter": {
            "brazilian_stop": {
                "type": "stop",
                "stopwords": "_brazilian_",
            },
            "brazilian_stemmer": {
                "type": "stemmer",
                "language": "brazilian",
            },
        },
    },
}

INDEX_MAPPINGS: dict[str, Any] = {
    "properties": {
        "id": {"type": "keyword"},
        "content": {
            "type": "text",
            "analyzer": "pt_br_custom",
            "fields": {
                "keyword": {"type": "keyword"},
            },
        },
        "content_vector": {
            "type": "dense_vector",
            "dims": 384,
            "index": True,
            "similarity": "cosine",
        },
        "title": {
            "type": "text",
            "analyzer": "pt_br_custom",
            "fields": {
                "keyword": {"type": "keyword"},
            },
        },
        "source": {"type": "keyword"},
        "source_type": {"type": "keyword"},
        "url": {"type": "keyword"},
        "created_at": {"type": "date"},
        "updated_at": {"type": "date"},
        "metadata": {"type": "object"},
    }
}

# Keep a combined dict for backward-compat / inspection
INDEX_MAPPING: dict[str, Any] = {
    "mappings": INDEX_MAPPINGS,
    "settings": INDEX_SETTINGS,
}


def create_index(es_client, index_name: str = INDEX_NAME) -> bool:
    """
    Create Elasticsearch index if it doesn't exist (idempotent).

    Args:
        es_client: Elasticsearch client instance
        index_name: Name of the index to create

    Returns:
        True if index was created or already exists, False on error
    """
    try:
        if es_client.indices.exists(index=index_name):
            logger.info("Index '%s' already exists, skipping.", index_name)
            return True

        es_client.indices.create(
            index=index_name,
            mappings=INDEX_MAPPINGS,
            settings=INDEX_SETTINGS,
        )
        logger.info("Index '%s' created successfully.", index_name)
        return True
    except Exception:
        logger.exception("Failed to create index '%s'", index_name)
        return False


def delete_index(es_client, index_name: str = INDEX_NAME) -> bool:
    """
    Delete Elasticsearch index if it exists.

    Args:
        es_client: Elasticsearch client instance
        index_name: Name of the index to delete

    Returns:
        True if index was deleted or didn't exist, False on error
    """
    try:
        if not es_client.indices.exists(index=index_name):
            return True

        es_client.indices.delete(index=index_name)
        logger.info("Index '%s' deleted.", index_name)
        return True
    except Exception:
        logger.exception("Failed to delete index '%s'", index_name)
        return False
