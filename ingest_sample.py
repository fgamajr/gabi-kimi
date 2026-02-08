#!/usr/bin/env python3
"""Sample data ingestion script for GABI.

Ingests TCU sumulas into the database using the proper pipeline.
"""

import asyncio
import json
import sys
import os

sys.path.insert(0, 'src')

from dotenv import load_dotenv
load_dotenv('.env')

import asyncpg
from gabi.pipeline.parser import get_parser
from gabi.pipeline.fingerprint import Fingerprinter
from gabi.pipeline.chunker import Chunker
from gabi.pipeline.contracts import FetchedContent, FetchMetadata
from elasticsearch import Elasticsearch


def to_pgvector(vector_list):
    """Converte lista Python para formato pgvector string."""
    return '[' + ','.join(str(x) for x in vector_list) + ']'


async def ingest_sample_data():
    """Ingest sample TCU data."""
    print("🚀 Starting sample data ingestion...")
    
    # Sample TCU data
    csv_data = """ID,NUMERO,ANO,ORGAO,TEMA,ENUNCIADO
SUM-001,1,2012,TCU,SUMULA,E vedada a participacao de cooperativas em licitacoes publicas sem previsao legal.
SUM-002,2,2013,TCU,SUMULA,O principio da impessoalidade exige que a licitacao seja processada e julgada sem comprometimento etico.
SUM-003,3,2014,TCU,SUMULA,Os contratos administrativos sao regulados pela Lei 8.666 de 1993 e suas alteracoes.
SUM-004,4,2015,TCU,SUMULA,A dispensa de licitacao e inexigibilidade requerem fundamentacao explicita e analise previa.
SUM-005,5,2016,TCU,SUMULA,As parcerias publico-privadas devem seguir rigorosamente as regras do RDC.
SUM-006,6,2017,TCU,SUMULA,Adesão a ata de registro de preços exige preço igual ou inferior ao registrado.
SUM-007,7,2018,TCU,SUMULA,A licitacao é o procedimento adequado para contratacao de obras e servicos.
SUM-008,8,2019,TCU,SUMULA,O contrato administrativo pode ser alterado por acordo das partes em casos específicos.
SUM-009,9,2020,TCU,SUMULA,A gestao de riscos é obrigatoria em contratos de alta complexidade.
SUM-010,10,2021,TCU,SUMULA,O controle social deve ser garantido em todas as etapas da despesa pública."""
    
    csv_content = csv_data.encode('utf-8')
    
    content = FetchedContent(
        url="https://portal.tcu.gov.br/sumulas.csv",
        content=csv_content,
        metadata=FetchMetadata(
            url="https://portal.tcu.gov.br/sumulas.csv",
            content_type="text/csv",
            content_length=len(csv_content),
            headers={}
        )
    )
    
    # Parse CSV
    parser = get_parser('csv')
    parse_config = {
        'input_format': 'csv',
        'strategy': 'row_to_document',
        'delimiter': ',',
        'mapping': {
            'document_id': {'from': 'ID'},
            'number': {'from': 'NUMERO'},
            'year': {'from': 'ANO'},
            'orgao': {'from': 'ORGAO'},
            'tema': {'from': 'TEMA'},
            'content': {'from': 'ENUNCIADO'}
        }
    }
    
    result = await parser.parse(content, parse_config)
    print(f"📄 Parsed {len(result.documents)} documents")
    
    # Connect to database
    conn = await asyncpg.connect('postgresql://gabi:gabidev@localhost:5432/gabi')
    
    try:
        # Insert source
        await conn.execute("""
            INSERT INTO sources (source_id, name, source_type, is_active)
            VALUES ('tcu_sumulas', 'TCU Sumulas', 'static_csv', true)
            ON CONFLICT (source_id) DO NOTHING
        """)
        print("✅ Source 'tcu_sumulas' created")
        
        # Fingerprint and chunk
        fingerprinter = Fingerprinter()
        chunker = Chunker(max_tokens=100, overlap_tokens=10)
        
        total_chunks = 0
        es_docs = []
        
        for doc in result.documents:
            fp = fingerprinter.compute(doc)
            chunks = chunker.chunk(doc.content, metadata={'doc_id': doc.document_id})
            total_chunks += len(chunks.chunks)
            
            # Insert document
            await conn.execute("""
                INSERT INTO documents (document_id, source_id, content, fingerprint, metadata, chunk_count)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (document_id) DO UPDATE SET 
                    content = EXCLUDED.content,
                    fingerprint = EXCLUDED.fingerprint,
                    chunk_count = EXCLUDED.chunk_count
            """, 
                doc.document_id, 
                'tcu_sumulas',
                doc.content,
                fp.fingerprint,
                json.dumps(doc.metadata),
                len(chunks.chunks)
            )
            
            # Prepare ES document
            es_docs.append({
                "document_id": doc.document_id,
                "content": doc.content,
                "metadata": doc.metadata,
            })
            
            # Insert chunks with dummy embeddings
            for chunk in chunks.chunks:
                embedding_str = to_pgvector([0.0] * 384)
                await conn.execute("""
                    INSERT INTO document_chunks (document_id, chunk_index, chunk_text, embedding, embedding_model)
                    VALUES ($1, $2, $3, $4::vector, $5)
                    ON CONFLICT (document_id, chunk_index) DO UPDATE SET
                        chunk_text = EXCLUDED.chunk_text,
                        embedding = EXCLUDED.embedding
                """, doc.document_id, chunk.index, chunk.text, embedding_str, 'placeholder')
        
        # Index in Elasticsearch
        es = Elasticsearch(["http://localhost:9200"])
        for doc in es_docs:
            es.index(
                index="gabi_documents",
                id=doc["document_id"],
                body={
                    "document_id": doc["document_id"],
                    "content": doc["content"],
                    "metadata": doc["metadata"],
                    "timestamp": "2024-01-01T00:00:00"
                }
            )
        
        print(f"✅ Indexed {len(es_docs)} documents in Elasticsearch")
        print(f"✅ Ingested {len(result.documents)} documents with {total_chunks} chunks")
        
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(ingest_sample_data())
