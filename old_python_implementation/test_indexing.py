
import asyncio
import logging
from datetime import datetime
from uuid import uuid4

from elasticsearch import AsyncElasticsearch
from gabi.models.document import Document
from gabi.pipeline.indexer import Indexer, ChunkData
from gabi.config import settings

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def test_indexing():
    logger.info("Starting manual indexing test")
    
    # 1. Setup
    es_client = AsyncElasticsearch(
        settings.elasticsearch_url,
        basic_auth=(settings.elasticsearch_username, settings.elasticsearch_password.get_secret_value()) if settings.elasticsearch_password else None
    )
    
    indexer = Indexer(es_client=es_client)
    
    # 2. Create Document
    doc_id = f"test_{uuid4().hex}"
    doc = Document(
        document_id=doc_id,
        source_id="manual_test",
        title="Test Document",
        content_preview="This is a test...",
        fingerprint=f"fp_{uuid4().hex}", # Unique fingerprint
        url="http://test.com",
        version=1,
        ingested_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    
    # 3. Create Chunk
    chunk = ChunkData(
        chunk_index=0,
        text="This is a test document manually indexed.",
        token_count=10,
        char_count=len("This is a test document manually indexed."),
        embedding=[0.1] * 384, # Mock embedding
        metadata={}
    )
    
    # 4. Index
    try:
        logger.info(f"Indexing document {doc_id} to index {settings.elasticsearch_index}...")
        result = await indexer.index_document(doc, [chunk], "manual_test")
        logger.info(f"Indexing result: {result}")
        
    except Exception as e:
        logger.exception("Indexing failed")
    finally:
        await es_client.close()

if __name__ == "__main__":
    asyncio.run(test_indexing())
