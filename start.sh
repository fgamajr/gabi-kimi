cd /home/fgamajr/dev/gabi-kimi

# 1. Parar tudo e remover volumes
docker compose --profile infra --profile all down -v

# 2. Limpar diretórios de dados bind-mount
sudo rm -rf data/postgres/* data/elasticsearch/* data/redis/*

# 3. Recriar diretórios com permissões
mkdir -p data/{postgres,elasticsearch,redis,tei/model}
chmod 777 data/elasticsearch

# 4. Subir infra do zero (lê .env automaticamente)
docker compose --profile infra up -d

# 5. Esperar containers ficarem healthy
echo "Aguardando containers..." && sleep 30
docker ps --format 'table {{.Names}}\t{{.Status}}'

# 6. Verificar banco gabi e extensões
docker exec gabi-postgres psql -U gabi -d gabi -c "SELECT extname, extversion FROM pg_extension;"

# 7. Rodar migrations
source .venv/bin/activate
GABI_DATABASE_URL='postgresql+asyncpg://gabi:gabi_dev_password@localhost:5432/gabi' alembic upgrade head
alembic current

# 8. Criar índice ES
curl -s -X PUT "http://localhost:9200/gabi_documents_v1" -H 'Content-Type: application/json' -d '{
  "settings": {
    "number_of_shards": 1, "number_of_replicas": 0,
    "analysis": {
      "analyzer": { "pt_br_custom": { "type": "custom", "tokenizer": "standard", "filter": ["lowercase", "brazilian_stop", "brazilian_stemmer"] } },
      "filter": { "brazilian_stop": { "type": "stop", "stopwords": "_brazilian_" }, "brazilian_stemmer": { "type": "stemmer", "language": "brazilian" } }
    }
  },
  "mappings": {
    "properties": {
      "id": { "type": "keyword" },
      "content": { "type": "text", "analyzer": "pt_br_custom", "fields": { "keyword": { "type": "keyword" } } },
      "content_vector": { "type": "dense_vector", "dims": 384, "index": true, "similarity": "cosine" },
      "title": { "type": "text", "analyzer": "pt_br_custom", "fields": { "keyword": { "type": "keyword" } } },
      "source": { "type": "keyword" }, "source_type": { "type": "keyword" }, "url": { "type": "keyword" },
      "created_at": { "type": "date" }, "updated_at": { "type": "date" }, "metadata": { "type": "object" }
    }
  }
}'

# 9. Smoke test TEI
echo "" && curl -s http://localhost:8080/embed -X POST -H 'Content-Type: application/json' -d '{"inputs": "teste"}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'TEI OK: {len(d[0])} dims')"

# 10. Resumo final
echo "=== STATUS FINAL ===" && docker ps --format 'table {{.Names}}\t{{.Status}}'