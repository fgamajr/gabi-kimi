#!/bin/bash
# GABI YOLO Setup - Roda tudo automaticamente!

set -e  # Exit on error

echo ""
echo "🚀 GABI YOLO MODE ACTIVATED"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Docker containers are running
check_containers() {
    log_info "Checking Docker containers..."
    
    REQUIRED_CONTAINERS=("gabi_postgres" "gabi_elasticsearch" "gabi_redis")
    
    for container in "${REQUIRED_CONTAINERS[@]}"; do
        if docker ps --format "table {{.Names}}" | grep -q "^${container}$"; then
            log_info "  ✅ $container is running"
        else
            log_error "  ❌ $container is NOT running"
            log_warn "Starting containers with docker-compose..."
            docker-compose up -d postgres elasticsearch redis 2>/dev/null || \
                docker compose up -d postgres elasticsearch redis 2>/dev/null || \
                { log_error "Failed to start containers"; exit 1; }
            sleep 5
        fi
    done
}

# Wait for PostgreSQL
wait_for_postgres() {
    log_info "Waiting for PostgreSQL..."
    until PGPASSWORD=gabidev psql -h localhost -U gabi -d gabi -c "SELECT 1;" > /dev/null 2>&1; do
        echo -n "."
        sleep 1
    done
    echo " ✅"
}

# Wait for Elasticsearch
wait_for_elasticsearch() {
    log_info "Waiting for Elasticsearch..."
    until curl -s http://localhost:9200/_cluster/health | grep -q '"status":"yellow"\|"status":"green"'; do
        echo -n "."
        sleep 1
    done
    echo " ✅"
}

# Create database tables
create_tables() {
    log_info "Creating database tables..."
    
    PGPASSWORD=gabidev psql -h localhost -U gabi -d gabi << 'SQL'
-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Drop existing tables for clean start
DROP TABLE IF EXISTS document_chunks CASCADE;
DROP TABLE IF EXISTS document_embeddings CASCADE;
DROP TABLE IF EXISTS document_audit_log CASCADE;
DROP TABLE IF EXISTS document_processing CASCADE;
DROP TABLE IF EXISTS documents CASCADE;
DROP TABLE IF EXISTS source_health CASCADE;
DROP TABLE IF EXISTS sources CASCADE;

-- Sources table
CREATE TABLE sources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    source_type VARCHAR(50) NOT NULL,
    connection_config JSONB DEFAULT '{}',
    discovery_config JSONB DEFAULT '{}',
    schedule_config JSONB DEFAULT '{}',
    is_active BOOLEAN DEFAULT true,
    last_crawl_at TIMESTAMP WITH TIME ZONE,
    next_crawl_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(100),
    metadata JSONB DEFAULT '{}'
);

-- Documents table with soft delete
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id VARCHAR(255) UNIQUE NOT NULL,
    source_id VARCHAR(100) REFERENCES sources(source_id),
    content TEXT,
    content_type VARCHAR(50) DEFAULT 'text/plain',
    fingerprint VARCHAR(64) UNIQUE NOT NULL,
    fingerprint_algorithm VARCHAR(20) DEFAULT 'sha256',
    metadata JSONB DEFAULT '{}',
    is_deleted BOOLEAN DEFAULT false,
    deleted_at TIMESTAMP WITH TIME ZONE,
    deleted_by VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    indexed_at TIMESTAMP WITH TIME ZONE,
    chunk_count INTEGER DEFAULT 0,
    token_count INTEGER DEFAULT 0,
    version INTEGER DEFAULT 1
);

-- Document chunks with vector embeddings (384 dimensions per ADR-001)
CREATE TABLE document_chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id VARCHAR(255) REFERENCES documents(document_id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    token_count INTEGER,
    char_count INTEGER,
    section_type VARCHAR(100),
    embedding VECTOR(384),
    embedding_model VARCHAR(100),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(document_id, chunk_index)
);

-- HNSW index for vector similarity
CREATE INDEX idx_chunks_embedding_hnsw ON document_chunks 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- Document processing status
CREATE TABLE document_processing (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id VARCHAR(255) REFERENCES documents(document_id) ON DELETE CASCADE,
    status VARCHAR(50) DEFAULT 'pending',
    stage VARCHAR(50),
    retry_count INTEGER DEFAULT 0,
    error_message TEXT,
    worker_id VARCHAR(100),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Audit log (immutable)
CREATE TABLE document_audit_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    table_name VARCHAR(100) NOT NULL,
    record_id VARCHAR(255) NOT NULL,
    operation VARCHAR(20) NOT NULL,
    old_data JSONB,
    new_data JSONB,
    changed_by VARCHAR(100),
    changed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    transaction_id VARCHAR(100),
    client_ip INET,
    previous_hash VARCHAR(64),
    current_hash VARCHAR(64) NOT NULL
);

-- Source health monitoring
CREATE TABLE source_health (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id VARCHAR(100) REFERENCES sources(source_id) ON DELETE CASCADE,
    check_timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    status VARCHAR(20) NOT NULL,
    response_time_ms INTEGER,
    error_message TEXT,
    details JSONB DEFAULT '{}'
);

-- Create indexes
CREATE INDEX idx_documents_source ON documents(source_id);
CREATE INDEX idx_documents_fingerprint ON documents(fingerprint);
CREATE INDEX idx_documents_deleted ON documents(is_deleted) WHERE is_deleted = false;
CREATE INDEX idx_documents_created ON documents(created_at);
CREATE INDEX idx_chunks_document ON document_chunks(document_id);
CREATE INDEX idx_audit_record ON document_audit_log(table_name, record_id);
CREATE INDEX idx_processing_status ON document_processing(status);

-- Create partial index for active documents
CREATE INDEX idx_documents_active ON documents(document_id, is_deleted) WHERE is_deleted = false;

-- Make audit log immutable
CREATE OR REPLACE FUNCTION prevent_audit_update()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Audit log entries cannot be modified';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_immutable ON document_audit_log;
CREATE TRIGGER audit_immutable
    BEFORE UPDATE OR DELETE ON document_audit_log
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_update();

-- Update timestamp function
CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply update triggers
CREATE TRIGGER update_sources_timestamp BEFORE UPDATE ON sources
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();
CREATE TRIGGER update_documents_timestamp BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();
CREATE TRIGGER update_processing_timestamp BEFORE UPDATE ON document_processing
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

SELECT 'Database schema created successfully!' as status;
SQL

    log_info "Database tables created!"
}

# Create Elasticsearch indices
create_es_indices() {
    log_info "Creating Elasticsearch indices..."
    
    # Documents index
    curl -s -X PUT "http://localhost:9200/gabi_documents" -H 'Content-Type: application/json' -d'{
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "analysis": {
                "analyzer": {
                    "portuguese": {
                        "type": "portuguese"
                    }
                }
            }
        },
        "mappings": {
            "properties": {
                "document_id": {"type": "keyword"},
                "source_id": {"type": "keyword"},
                "content": {"type": "text", "analyzer": "portuguese"},
                "content_type": {"type": "keyword"},
                "fingerprint": {"type": "keyword"},
                "metadata": {"type": "object"},
                "created_at": {"type": "date"},
                "updated_at": {"type": "date"},
                "is_deleted": {"type": "boolean"},
                "chunk_count": {"type": "integer"}
            }
        }
    }' | grep -q '"acknowledged":true' && log_info "  ✅ gabi_documents index created"
    
    # Search queries index
    curl -s -X PUT "http://localhost:9200/gabi_search_queries" -H 'Content-Type: application/json' -d'{
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {
            "properties": {
                "query": {"type": "text"},
                "user_id": {"type": "keyword"},
                "results_count": {"type": "integer"},
                "timestamp": {"type": "date"}
            }
        }
    }' | grep -q '"acknowledged":true' && log_info "  ✅ gabi_search_queries index created"
}

# Ingest sample data
ingest_data() {
    log_info "Ingesting sample TCU data..."
    
    python3 << 'PYTHON'
import asyncio
import sys
import os
sys.path.insert(0, 'src')

# Load env
from dotenv import load_dotenv
load_dotenv()

from gabi.pipeline.discovery import DiscoveryEngine, DiscoveryConfig
from gabi.pipeline.parser import get_parser
from gabi.pipeline.fingerprint import Fingerprinter
from gabi.pipeline.chunker import Chunker
from gabi.pipeline.contracts import FetchedContent, FetchMetadata
import asyncpg

async def ingest():
    # Sample TCU data
    csv_data = """ID,NUMERO,ANO,ORGAO,TEMA,ENUNCIADO
SUM-001,1,2012,TCU,SUMULA,E vedada a participacao de cooperativas em licitacoes publicas sem previsao legal.
SUM-002,2,2013,TCU,SUMULA,Licitacoes devem observar principios da legalidade e impessoalidade.
SUM-003,3,2014,TCU,SUMULA,Contratos administrativos sao regulados pela Lei 8.666 de 1993.
SUM-004,4,2015,TCU,SUMULA,Dispensa de licitacao requer fundamentacao explicita.
SUM-005,5,2016,TCU,SUMULA,Parcerias publico-privadas devem seguir regras do RDC."""
    
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
    print(f"  Parsed {len(result.documents)} documents")
    
    # Fingerprint and chunk
    fingerprinter = Fingerprinter()
    chunker = Chunker(max_tokens=100, overlap_tokens=10)
    
    conn = await asyncpg.connect('postgresql://gabi:gabidev@localhost:5432/gabi')
    
    # Insert source
    await conn.execute("""
        INSERT INTO sources (source_id, name, source_type, is_active)
        VALUES ('tcu_sumulas', 'TCU Sumulas', 'static_csv', true)
        ON CONFLICT (source_id) DO NOTHING
    """)
    
    for doc in result.documents:
        fp = fingerprinter.compute(doc)
        chunks = chunker.chunk(doc.content, metadata={'doc_id': doc.document_id})
        
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
            doc.metadata,
            len(chunks.chunks)
        )
        
        # Insert chunks with dummy embeddings (will be updated by TEI)
        for chunk in chunks.chunks:
            # 384-dimensional zero vector (placeholder)
            embedding = [0.0] * 384
            await conn.execute("""
                INSERT INTO document_chunks (document_id, chunk_index, chunk_text, embedding, embedding_model)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (document_id, chunk_index) DO UPDATE SET
                    chunk_text = EXCLUDED.chunk_text,
                    embedding = EXCLUDED.embedding
            """, doc.document_id, chunk.index, chunk.text, embedding, 'placeholder')
    
    await conn.close()
    print(f"  ✅ Ingested {len(result.documents)} documents with chunks")

asyncio.run(ingest())
PYTHON
}

# Start TEI container if not running
start_tei() {
    log_info "Checking TEI (Text Embeddings Inference)..."
    
    if ! docker ps --format "table {{.Names}}" | grep -q "^gabi_tei$"; then
        log_warn "TEI not running, starting it now..."
        log_warn "(This may take a while - downloading model...)"
        
        docker run -d \
            --name gabi_tei \
            --network host \
            -p 3000:80 \
            -e MODEL_ID=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 \
            --gpus all 2>/dev/null || \
        docker run -d \
            --name gabi_tei \
            --network host \
            -p 3000:80 \
            -e MODEL_ID=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
            
        log_info "TEI container started, waiting for model load..."
        sleep 30
    else
        log_info "  ✅ TEI is already running"
    fi
}

# Update embeddings with TEI
update_embeddings() {
    log_info "Updating embeddings with TEI..."
    
    python3 << 'PYTHON'
import asyncio
import asyncpg
import httpx

async def update_embeddings():
    conn = await asyncpg.connect('postgresql://gabi:gabidev@localhost:5432/gabi')
    
    # Get chunks without real embeddings
    rows = await conn.fetch("""
        SELECT id, chunk_text 
        FROM document_chunks 
        WHERE embedding_model = 'placeholder'
        LIMIT 10
    """)
    
    if not rows:
        print("  No chunks need embedding updates")
        await conn.close()
        return
    
    print(f"  Updating {len(rows)} chunks...")
    
    async with httpx.AsyncClient() as client:
        for row in rows:
            try:
                # Call TEI for embedding
                response = await client.post(
                    "http://localhost:3000/embed",
                    json={"inputs": row['chunk_text']},
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    embedding = response.json()
                    await conn.execute("""
                        UPDATE document_chunks 
                        SET embedding = $1, embedding_model = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
                        WHERE id = $2
                    """, embedding, row['id'])
                    print(f"    ✅ Updated chunk {row['id'][:8]}...")
                else:
                    print(f"    ⚠️  TEI returned {response.status_code}")
                    
            except Exception as e:
                print(f"    ⚠️  Error: {e}")
    
    await conn.close()
    print("  ✅ Embeddings updated")

asyncio.run(update_embeddings())
PYTHON
}

# Create startup script for API
create_startup_scripts() {
    log_info "Creating startup scripts..."
    
    cat > start_api.sh << 'EOF'
#!/bin/bash
echo "Starting GABI API Server..."
cd "$(dirname "$0")"
export $(cat .env | grep -v '^#' | xargs)
exec uvicorn gabi.api.main:app --host 0.0.0.0 --port 8000 --reload --workers 4
EOF
    chmod +x start_api.sh
    
    cat > start_worker.sh << 'EOF'
#!/bin/bash
echo "Starting GABI Celery Worker..."
cd "$(dirname "$0")"
export $(cat .env | grep -v '^#' | xargs)
exec celery -A gabi.workers.celery_app worker --loglevel=info --concurrency=4 -n worker1@%h
EOF
    chmod +x start_worker.sh
    
    cat > start_mcp.sh << 'EOF'
#!/bin/bash
echo "Starting GABI MCP Server..."
cd "$(dirname "$0")"
export $(cat .env | grep -v '^#' | xargs)
exec python -m gabi.mcp.server
EOF
    chmod +x start_mcp.sh
    
    log_info "  ✅ Startup scripts created"
}

# Main setup flow
main() {
    check_containers
    wait_for_postgres
    wait_for_elasticsearch
    create_tables
    create_es_indices
    ingest_data
    start_tei
    # update_embeddings  # Skip for now - TEI may take time to download
    create_startup_scripts
    
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo "✅ GABI YOLO SETUP COMPLETE!"
    echo "═══════════════════════════════════════════════════════════════"
    echo ""
    echo "📊 STATUS:"
    echo "  ✅ PostgreSQL + pgvector: Running with schema"
    echo "  ✅ Elasticsearch: Running with indices"
    echo "  ✅ Redis: Running"
    echo "  ✅ TEI: Running (or starting)"
    echo "  ✅ Sample data: Ingested (5 TCU sumulas)"
    echo ""
    echo "🚀 TO START SERVICES:"
    echo "  ./start_api.sh      # API on http://localhost:8000"
    echo "  ./start_worker.sh   # Celery workers"
    echo "  ./start_mcp.sh      # MCP Server on http://localhost:8080"
    echo ""
    echo "📚 API DOCUMENTATION:"
    echo "  http://localhost:8000/docs    # Swagger UI"
    echo "  http://localhost:8000/redoc   # ReDoc"
    echo ""
}

main "$@"
