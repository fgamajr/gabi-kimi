# GABI Source Data Flow - Operations Runbook (v2)

Foco: operação, diagnóstico e correção rápida por fase do pipeline por source.

## 0) Objetivo operacional
- Confirmar rapidamente onde um source está parado.
- Identificar se o problema é `config`, `adapter/driver`, `queue`, `DB` ou `runtime`.
- Restaurar execução sem intervenção manual destrutiva.

## 1) Fases e critérios de sucesso

## 1.1 Seed
- Entrada: `sources_v2.yaml`
- Sucesso:
  - `source_registry` contém source com `DiscoveryStrategy` e `DiscoveryConfig` corretos.

Checks:
```bash
# Source existe e está habilitado?
docker compose exec -T postgres psql -U gabi -d gabi -c \
"SELECT \"Id\", \"Enabled\", \"DiscoveryStrategy\" FROM source_registry WHERE \"Id\"='tcu_publicacoes';"

# DiscoveryConfig completo (driver/rules/http/endpoint_template)?
docker compose exec -T postgres psql -U gabi -d gabi -c \
"SELECT \"DiscoveryConfig\" FROM source_registry WHERE \"Id\"='camara_leis_ordinarias';"
```

## 1.2 Discovery enqueue
- Entrada: refresh API por source
- Sucesso:
  - novo `job_registry` com `JobType=source_discovery`
  - status evolui `pending -> processing -> completed|failed`

Checks:
```bash
TOKEN=$(curl -s -X POST http://localhost:5100/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"operator","password":"op123"}' | jq -r .token)

curl -s -X POST "http://localhost:5100/api/v1/dashboard/sources/tcu_publicacoes/refresh" \
  -H "Authorization: Bearer $TOKEN"

# Status do último job da fonte
docker compose exec -T postgres psql -U gabi -d gabi -c \
"SELECT \"JobId\",\"Status\",\"ProgressMessage\",\"StartedAt\",\"CompletedAt\" \
 FROM job_registry WHERE \"SourceId\"='tcu_publicacoes' ORDER BY \"CreatedAt\" DESC LIMIT 1;"
```

## 1.3 Discovery execution (adapter/driver)
- Sucesso:
  - `ProgressMessage` cresce (`Descobrindo... (N links)`)
  - `discovery_runs.LinksTotal > 0` para fontes suportadas

Checks:
```bash
# Progresso em tempo real
docker compose exec -T postgres psql -U gabi -d gabi -c \
"SELECT \"Status\",\"ProgressMessage\" FROM job_registry \
 WHERE \"SourceId\"='camara_leis_ordinarias' ORDER BY \"CreatedAt\" DESC LIMIT 1;"

# Resultado final
docker compose exec -T postgres psql -U gabi -d gabi -c \
"SELECT \"Status\",\"LinksTotal\",\"ErrorSummary\",\"StartedAt\",\"CompletedAt\" \
 FROM discovery_runs WHERE \"SourceId\"='camara_leis_ordinarias' \
 ORDER BY \"StartedAt\" DESC LIMIT 1;"
```

## 1.4 Discovery persistência
- Sucesso:
  - `discovered_links` > 0
  - `fetch_items` materializados automaticamente

Checks:
```bash
# Links descobertos
docker compose exec -T postgres psql -U gabi -d gabi -c \
"SELECT COUNT(*) FROM discovered_links WHERE \"SourceId\"='tcu_publicacoes';"

# Fetch items criados
docker compose exec -T postgres psql -U gabi -d gabi -c \
"SELECT \"Status\", COUNT(*) FROM fetch_items \
 WHERE \"SourceId\"='tcu_publicacoes' GROUP BY \"Status\" ORDER BY \"Status\";"
```

## 1.5 Fetch
- Sucesso:
  - `fetch_items` avançam de `pending/failed` para `completed|capped|failed`
  - `documents` cresce

Checks:
```bash
# Último fetch run
docker compose exec -T postgres psql -U gabi -d gabi -c \
"SELECT \"Status\",\"ItemsTotal\",\"ItemsCompleted\",\"ItemsFailed\",\"ErrorSummary\" \
 FROM fetch_runs WHERE \"SourceId\"='tcu_acordaos' ORDER BY \"StartedAt\" DESC LIMIT 1;"

# Docs gerados
docker compose exec -T postgres psql -U gabi -d gabi -c \
"SELECT COUNT(*) FROM documents WHERE \"SourceId\"='tcu_acordaos';"
```

## 2) Matriz de sintomas -> causa provável -> ação

| Sintoma | Causa provável | Ação |
|---|---|---|
| Refresh retorna “Job already in progress” e nada anda | job_registry preso (`pending/processing`) | Marcar stale como `failed` (somente jobs antigos), reenfileirar |
| Discovery `completed` com `0 links` e sem erro técnico | source sem adapter/driver correto ou seletor inadequado | validar `DiscoveryConfig`, `strategy`, `driver`, `rules` |
| `tcu_publicacoes` com 0 links no modo web_crawl comum | challenge anti-bot na resposta | usar `driver: curl_html_v1` |
| Câmara sem resultados | endpoint fixo inadequado ou range/config não aplicado | usar `driver: camara_api_v1` + `endpoint_template` no YAML |
| links > 0 mas `fetch_items=0` | quebra na materialização pós-upsert | validar invariante no discovery executor e repository path |
| fetch OOM em arquivo grande | buffers/string growth/tracking | streaming + batch pequeno + cap + telemetria memória |

## 3) Runbook de recuperação rápida (não destrutivo)

## 3.1 Limpar lock lógico de uma fonte
```bash
docker compose exec -T postgres psql -U gabi -d gabi -c \
"UPDATE job_registry
 SET \"Status\"='failed', \"CompletedAt\"=NOW(), \"ErrorMessage\"=COALESCE(\"ErrorMessage\",'stale cleanup')
 WHERE \"SourceId\"='tcu_publicacoes' AND \"Status\" IN ('pending','processing');"
```

## 3.2 Reexecutar discovery da fonte
```bash
TOKEN=$(curl -s -X POST http://localhost:5100/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"operator","password":"op123"}' | jq -r .token)

curl -s -X POST "http://localhost:5100/api/v1/dashboard/sources/tcu_publicacoes/refresh" \
  -H "Authorization: Bearer $TOKEN"
```

## 3.3 Verificação mínima de sucesso
```bash
docker compose exec -T postgres psql -U gabi -d gabi -c \
"SELECT \"Status\",\"LinksTotal\" FROM discovery_runs
 WHERE \"SourceId\"='tcu_publicacoes' ORDER BY \"StartedAt\" DESC LIMIT 1;"

docker compose exec -T postgres psql -U gabi -d gabi -c \
"SELECT COUNT(*) FROM discovered_links WHERE \"SourceId\"='tcu_publicacoes';"
```

## 4) Perfil operacional por source crítico

## 4.1 `tcu_publicacoes`
- Strategy: `web_crawl`
- Driver recomendado: `curl_html_v1`
- Indicador saudável: discovery termina com ~centenas de links (não zero)

## 4.2 `camara_leis_ordinarias`
- Strategy: `api_pagination`
- Driver: `camara_api_v1`
- Config essencial: `endpoint_template` + `parameters.start_year`
- Indicador saudável: progresso cresce em lotes (`Descobrindo... (N links)`)

## 4.3 `tcu_acordaos` (stress)
- Strategy: `url_pattern`
- Controle de stress: `max_docs_per_source`
- Indicador saudável: fetch `capped` em 20k sem cancelamento forçado

## 5) Checklist pré-Zero Kelvin final
- [ ] `docker compose ps` com `api/worker/postgres/redis` saudáveis
- [ ] `source_registry` atualizado com drivers/config por source
- [ ] discovery de `tcu_publicacoes` > 0 links
- [ ] discovery de `camara_leis_ordinarias` > 0 links
- [ ] materialização `fetch_items` consistente com `discovered_links`
- [ ] DLQ sem erro JSON em falhas reais
- [ ] retry policy observada bate com configuração
- [ ] modo capped habilitado para stress (`max_docs_per_source=20000`)

## 6) Arquivos-chave de operação
- `sources_v2.yaml`
- `src/Gabi.Worker/Jobs/CatalogSeedJobExecutor.cs`
- `src/Gabi.Worker/Jobs/SourceDiscoveryJobExecutor.cs`
- `src/Gabi.Discover/WebCrawlDiscoveryAdapter.cs`
- `src/Gabi.Discover/ApiPaginationDiscoveryAdapter.cs`
- `src/Gabi.Postgres/JobPayloadParser.cs`
- `src/Gabi.Worker/Jobs/FetchJobExecutor.cs`
