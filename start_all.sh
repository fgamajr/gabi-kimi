#!/bin/bash
# GABI MASTER STARTUP - YOLO MODE

cd "$(dirname "$0")"
export PYTHONPATH=src:$PYTHONPATH

# Carregar env
while IFS='=' read -r key val; do
    [[ -z "$key" || "$key" =~ ^# ]] && continue
    export "$key=$val"
done < .env

echo "═══════════════════════════════════════════════════════════"
echo "🚀 GABI - Modo YOLO Ativado"
echo "═══════════════════════════════════════════════════════════"

# Verificar containers (nomes podem ter hífen ou underscore)
echo ""
echo "📦 Verificando containers..."
for container in gabi-postgres gabi-elasticsearch gabi_redis; do
    if docker ps --format "{{.Names}}" | grep -q "^${container}$"; then
        echo "  ✅ $container"
    else
        echo "  ⚠️  Tentando iniciar $container..."
        docker start $container 2>/dev/null || echo "  ❌ Não foi possível iniciar $container"
    fi
done

# Verificar dados
echo ""
echo "📊 Verificando dados..."
PGPASSWORD=gabidev psql -h localhost -U gabi -d gabi -t -c "SELECT 'Documentos: ' || COUNT(*) FROM documents;" 2>/dev/null | xargs
PGPASSWORD=gabidev psql -h localhost -U gabi -d gabi -t -c "SELECT 'Chunks: ' || COUNT(*) FROM document_chunks;" 2>/dev/null | xargs

echo ""
echo "🌐 Endpoints disponíveis:"
echo "  • API:       http://localhost:8000"
echo "  • Docs:      http://localhost:8000/docs"
echo "  • Health:    http://localhost:8000/health"
echo "  • Metrics:   http://localhost:8000/metrics"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "🎯 Iniciando API..."
echo "═══════════════════════════════════════════════════════════"
echo ""

# Iniciar API
exec uvicorn gabi.main:app --host 0.0.0.0 --port 8000 --reload --workers 1
