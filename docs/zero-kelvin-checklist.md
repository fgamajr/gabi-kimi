# Zero Kelvin Test - Checklist

**Data**: 2026-02-13  
**Versão**: 1.0  
**Propósito**: Validar que o GABI pode ser reconstruído do estado fundamental (Zero Kelvin)

---

## 📋 O que é o Teste Zero Kelvin?

Como a temperatura **Zero Kelvin** é o estado fundamental da matéria, este teste leva o sistema ao seu estado fundamental:

1. **Destruir tudo** - Containers, volumes, processos, logs
2. **Reconstruir** - Apenas com `./scripts/setup.sh`
3. **Validar** - Todos os serviços funcionam corretamente

**Critério de Sucesso**: O sistema deve subir e funcionar 100% sem intervenção manual.

---

## 🚀 Execução Rápida

```bash
cd /home/fgamajr/dev/gabi-kimi
./tests/zero-kelvin-test.sh
```

Para testar idempotência:
```bash
./tests/zero-kelvin-test.sh idempotency
```

---

## ✅ Checklist de Verificações

### Fase 1: Destruição Completa

| Verificação | Comando | Resultado Esperado |
|-------------|---------|-------------------|
| Parar containers | `docker compose down -v` | Containers removidos, volumes deletados |
| Verificar portas livres | `lsof -i :5100 :3000 :5433 :9200` | Nenhum processo nas portas |
| Limpar processos | `pkill -f "dotnet\|vite"` | Processos terminados |
| Limpar temporários | `rm -rf /tmp/gabi-*` | Diretórios removidos |
| Validar zero | `docker ps -a \| grep gabi` | Nenhum resultado |

### Fase 2: Setup

| Verificação | Comando | Resultado Esperado |
|-------------|---------|-------------------|
| Executar setup | `./scripts/setup.sh` | Sucesso em < 5 minutos |
| Build passar | Ver output do setup | `Build succeeded` |
| Migrations aplicar | Ver output do setup | `Done.` |
| Infra saudável | `docker compose ps` | Postgres, ES, Redis `healthy` |

### Fase 3: Inicialização

| Verificação | Comando | Resultado Esperado |
|-------------|---------|-------------------|
| Iniciar apps | `./scripts/dev app start` | Retorna imediatamente (detached) |
| API responder | `curl http://localhost:5100/health` | `Healthy` em < 60s |
| Web responder | `curl -I http://localhost:3000` | `HTTP/1.1 200 OK` |
| Status geral | `./scripts/dev app status` | API: ✅, Web: ✅ |

### Fase 4: Verificações Funcionais

| Verificação | Comando | Resultado Esperado |
|-------------|---------|-------------------|
| Health check | `curl http://localhost:5100/health` | `Healthy` |
| Swagger UI | `curl -I http://localhost:5100/swagger/index.html` | `HTTP 200` |
| Login | `POST /api/v1/auth/login` | Token JWT retornado |
| Dashboard stats | `GET /api/v1/dashboard/stats` | JSON com sources |
| Sources list | `GET /api/v1/sources` | Array de fontes |
| Source detail | `GET /api/v1/sources/tcu_sumulas` | Detalhes da fonte |
| Links paginados | `GET /api/v1/sources/tcu_sumulas/links` | Lista paginada |
| Discovery trigger | `POST /api/v1/dashboard/sources/{id}/refresh` | Job criado |
| Web UI | `curl http://localhost:3000` | HTML da aplicação React |

---

## 🔄 Teste de Idempotência

### O que é?

Idempotência significa que **executar N vezes produz o mesmo resultado**.

### Por que importa?

- **CI/CD**: Pipelines podem rodar setup múltiplas vezes
- **Reparos**: Rodar setup não deve quebrar sistema existente
- **Segurança**: Segunda execução deve ser rápida (nada a fazer)

### Como testar

```bash
# Primeira execução (baseline)
time ./scripts/setup.sh 2>&1 | tee setup-1.log
# Notar o tempo (ex: 120s)

# Segunda execução (idempotência)
time ./scripts/setup.sh 2>&1 | tee setup-2.log
# Deve ser mais rápido (ex: 15s)
# Deve mostrar: "Already up-to-date", "Nothing to do"

# Verificar que sistema ainda funciona
./scripts/dev app status
curl http://localhost:5100/health
```

### Critérios de Sucesso

| Critério | Métrica |
|----------|---------|
| Segunda execução mais rápida | < 50% do tempo da primeira |
| Ou: segunda execução rápida | < 60 segundos |
| Sistema funcional | Health check passa |
| Nenhum erro | Exit code 0 em ambas |

### Comando automatizado

```bash
./tests/zero-kelvin-test.sh idempotency
```

---

## 📝 Comandos Detalhados (para Debug)

### Login e obter token

```bash
TOKEN=$(curl -s -X POST http://localhost:5100/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "viewer", "password": "view123"}' \
  | grep -o '"token":"[^"]*"' | cut -d'"' -f4)

echo "Token: $TOKEN"
```

### Testar endpoints protegidos

```bash
# Stats
curl -s http://localhost:5100/api/v1/dashboard/stats \
  -H "Authorization: Bearer $TOKEN" | jq .

# Sources
curl -s http://localhost:5100/api/v1/sources \
  -H "Authorization: Bearer $TOKEN" | jq '.data | length'

# Links de uma source
curl -s "http://localhost:5100/api/v1/sources/tcu_sumulas/links?page=1&pageSize=5" \
  -H "Authorization: Bearer $TOKEN" | jq .
```

### Verificar infraestrutura

```bash
# PostgreSQL
docker compose exec postgres psql -U gabi -d gabi -c "SELECT COUNT(*) FROM source_registry;"

# Elasticsearch
curl http://localhost:9200/_cluster/health | jq .status

# Redis
docker compose exec redis redis-cli ping
```

---

## ❌ O que fazer se falhar?

### Falha na Fase 1 (Destruição)

```bash
# Forçar limpeza manual
docker system prune -af --volumes
sudo pkill -9 -f "dotnet\|vite"
sudo rm -rf /tmp/gabi-*
```

### Falha na Fase 2 (Setup)

```bash
# Ver logs detalhados
cat /tmp/gabi-zero-kelvin.log

# Problemas comuns:
# 1. Porta em uso → matar processo: sudo lsof -ti:5100 | xargs kill -9
# 2. Docker não rodando → sudo systemctl start docker
# 3. Permissões → sudo chown -R $USER:$USER .
```

### Falha na Fase 3 (Inicialização)

```bash
# Ver logs
./scripts/dev app logs

# Verificar portas
lsof -i :5100
lsof -i :3000

# Restart manual
./scripts/dev app stop
./scripts/dev app start
```

### Falha na Fase 4 (Verificações)

```bash
# Verificar se API está rodando
./scripts/dev app status

# Testar health
curl -v http://localhost:5100/health

# Ver logs da API
cat /tmp/gabi-logs/api.log | tail -50

# Ver logs do web
cat /tmp/gabi-logs/web.log | tail -50
```

---

## 📊 Critérios de Aceitação do Zero Kelvin

| Aspecto | Critério | Peso |
|---------|----------|------|
| Destruição | Containers e processos terminados | Obrigatório |
| Setup | Completa sem erros em < 5min | Obrigatório |
| Inicialização | Serviços prontos em < 60s | Obrigatório |
| Health | Retorna "Healthy" | Obrigatório |
| Auth | Login retorna token JWT | Obrigatório |
| API | Endpoints respondem 200 | Obrigatório |
| Web | Frontend acessível | Obrigatório |
| Idempotência | 2º setup mais rápido que 1º | Recomendado |

**Nota**: Todos os itens "Obrigatórios" devem passar para o teste ser considerado sucesso.

---

## 🎯 Quando Executar

### Obrigatório

- [ ] Após alterações em `docker-compose.yml`
- [ ] Após alterações em `scripts/setup.sh`
- [ ] Após novas migrations de banco
- [ ] Antes de merge para `main`
- [ ] Antes de release

### Recomendado

- [ ] Após alterações significativas na arquitetura
- [ ] Semanalmente (CI/CD)
- [ ] Após atualizações de dependências (NuGet, npm)

---

## 🔗 Relacionado

- [README.md](../README.md#-teste-zero-kelvin) - Conceito e metáfora
- [PLANO_24_AGENTES.md](../PLANO_24_AGENTES.md) - Requisito Zero Kelvin em cada sprint
- [syncronizacao.md](../syncronizacao.md) - Regra transversal Zero Kelvin
- [tests/zero-kelvin-test.sh](../tests/zero-kelvin-test.sh) - Script automatizado

---

**Mantenha este checklist atualizado** conforme novos endpoints ou requisitos forem adicionados.
