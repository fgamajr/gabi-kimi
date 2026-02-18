# Plano de Correção - Sources Problemáticas

## Diagnóstico Consolidado

| Source | Problema | Impacto |
|--------|----------|---------|
| `camara_leis_ordinarias` | Discovery timeout (100s) | 0 links novos por run |
| `tcu_notas_tecnicas_ti` | Web_crawl sem driver | 0 links sempre |
| `tcu_publicacoes` | Fetch idempotência (duplicate key) | 67% fetch_items failed |

---

## 1. camara_leis_ordinarias

### Sintoma
```
discovery_runs.ErrorSummary: "The request was canceled due to the configured HttpClient.Timeout of 100 seconds elapsing."
LinksTotal: 0 (runs recentes)
```

### Causa Raiz
- API da Câmara pode ser lenta (>100s para respostas grandes)
- HttpClient timeout hardcoded no adapter

### Solução
**Ajustar timeout no HttpClient por request** (usar config.http.timeout do YAML)

**Arquivos a modificar:**
1. `src/Gabi.Discover/ApiPaginationDiscoveryAdapter.cs`
   - Ler `http.timeout` do config (já existe no YAML: "180s")
   - Aplicar timeout customizado no HttpRequestMessage

**Validação:**
```bash
# Após correção
docker compose exec -T postgres psql -U gabi -d gabi -c "DELETE FROM discovered_links WHERE \"SourceId\"='camara_leis_ordinarias';"
curl -X POST http://localhost:5100/api/v1/dashboard/sources/camara_leis_ordinarias/refresh \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json"
# Monitor discovery_runs por 5 min
```

---

## 2. tcu_notas_tecnicas_ti

### Sintoma
```
discovery_runs.Status: completed
discovery_runs.LinksTotal: 0
discovery_runs.ErrorSummary: "0 links discovered (check strategy implementation)"
```

### Causa Raiz
- `strategy: web_crawl` sem `driver` especificado
- WebCrawlDiscoveryAdapter requer driver (ex: `curl_html_v1`)

### Solução
**Adicionar driver curl_html_v1 no sources_v2.yaml**

**Arquivo a modificar:**
1. `sources_v2.yaml` (seção tcu_notas_tecnicas_ti)
   ```yaml
   discovery:
     strategy: web_crawl
     config:
       driver: curl_html_v1  # ADICIONAR
       root_url: "https://portal.tcu.gov.br/tecnologia-da-informacao/notas-tecnicas"
       rules:
         max_depth: "1"
         asset_selector: "a[href$='.pdf']"
       http:
         timeout: "180s"
   ```

**Validação:**
```bash
# Após correção
curl -X POST http://localhost:5100/api/v1/dashboard/sources/tcu_notas_tecnicas_ti/refresh \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json"
# Verificar discovered_links > 0
```

---

## 3. tcu_publicacoes

### Sintoma
```
fetch_items.Status: failed (194/290 = 67%)
fetch_items.LastError: "duplicate key value violates unique constraint IX_Documents_SourceId_ExternalId_Active"
documents COUNT: 7 (muito abaixo de 290)
```

### Causa Raiz
- Fetch/Ingest não é idempotente
- Ao reprocessar links já ingeridos, falha com duplicate key
- Deveria usar UPSERT ou ignorar silenciosamente

### Solução
**Implementar upsert idempotente no documento ingestion**

**Arquivos a modificar:**
1. `src/Gabi.Ingest/DocumentIngestionService.cs` (ou equivalente)
   - Usar `INSERT ... ON CONFLICT DO UPDATE` ou
   - Verificar existência antes de inserir
   - Marcar fetch_item como completed (não failed) quando documento já existe

2. `src/Gabi.Fetch/FetchExecutor.cs` (ou equivalente)
   - Capturar duplicate key exception
   - Marcar item como completed com warning (não failed)

**Validação:**
```bash
# Após correção
curl -X POST http://localhost:5100/api/v1/dashboard/sources/tcu_publicacoes/phases/fetch \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"max_docs_per_source": 500}'
# Verificar fetch_items.failed = 0 e documents COUNT próximo de discovered_links
```

---

## Priorização

| Ordem | Source | Esforço | Criticidade |
|-------|--------|---------|-------------|
| 1 | tcu_notas_tecnicas_ti | Baixo (YAML only) | Alta (dados jurídicos) |
| 2 | tcu_publicacoes | Médio (C# ingest) | Alta (reprocessamento) |
| 3 | camara_leis_ordinarias | Médio (C# adapter) | Média (já tem 105k links) |

---

## Comandos de Diagnóstico Rápido

```bash
# Status geral das 3 sources
docker compose exec -T postgres psql -U gabi -d gabi -c "
SELECT s.\"Id\", 
       COALESCE(dr.\"Status\", 'no_run') AS discovery_status,
       COALESCE(dr.\"LinksTotal\", 0) AS links,
       (SELECT COUNT(*) FROM discovered_links dl WHERE dl.\"SourceId\" = s.\"Id\") AS discovered,
       (SELECT COUNT(*) FROM fetch_items fi WHERE fi.\"SourceId\" = s.\"Id\") AS fetch_items,
       (SELECT COUNT(*) FROM documents d WHERE d.\"SourceId\" = s.\"Id\") AS docs
FROM source_registry s
LEFT JOIN discovery_runs dr ON dr.\"SourceId\" = s.\"Id\" 
  AND dr.\"StartedAt\" = (SELECT MAX(\"StartedAt\") FROM discovery_runs WHERE \"SourceId\" = s.\"Id\")
WHERE s.\"Id\" IN ('camara_leis_ordinarias','tcu_notas_tecnicas_ti','tcu_publicacoes')
ORDER BY s.\"Id\";
"

# Erros recentes por source
docker compose exec -T postgres psql -U gabi -d gabi -c "
SELECT \"SourceId\", \"Status\", \"ErrorSummary\", \"StartedAt\"
FROM discovery_runs
WHERE \"SourceId\" IN ('camara_leis_ordinarias','tcu_notas_tecnicas_ti','tcu_publicacoes')
ORDER BY \"StartedAt\" DESC LIMIT 10;
"
```

---

## Próximos Passos

1. [ ] Implementar fix tcu_notas_tecnicas_ti (YAML)
2. [ ] Implementar fix tcu_publicacoes (C# idempotência)
3. [ ] Implementar fix camara_leis_ordinarias (C# timeout)
4. [ ] Rodar Zero Kelvin novamente para validar
