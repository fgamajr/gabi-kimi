# Cardinalidade entre fases e resultados reais

A ordem do pipeline **não está invertida**: é **Seed → Discovery → Fetch → Ingest**.  
(Discovery vem antes do Fetch: primeiro descobrimos links, depois fazemos fetch do conteúdo desses links.)

---

## 1. Ordem das fases (correto)

| Ordem | Fase      | O que faz |
|-------|-----------|-----------|
| 0     | **Source** | Feed do catálogo (YAML `sources_v2.yaml`) — entrada externa. |
| 1     | **Seed**  | Lê o YAML, persiste fontes em `source_registry` e registra em `seed_runs`. |
| 2     | **Discovery** | Por fonte: descobre URLs (links) e grava em `discovery_runs` e `discovered_links`; cria `fetch_items` pendentes (replicação pending). |
| 3     | **Fetch** | Processa `fetch_items` (baixa/metadados), grava em `fetch_runs`; ao concluir item, cria documento em `documents` para ingest. |
| 4     | **Ingest** | Processa documentos (pending) e indexa. |

Não há “fetcher” antes de “discovery”: primeiro discovery (links), depois fetch (conteúdo).

---

## 2. Cardinalidade entre fases (tabela de referência)

| De          | Para       | Relação | Motivo | Tabelas / evidência |
|-------------|------------|---------|--------|----------------------|
| **Seed**    | **Discovery** | **1:1** (por fonte) | Uma fonte (source) → uma execução de discovery (run) que produz N links. | `source_registry` (N fontes) → 1 job discovery por fonte → `discovery_runs` (1 run por source) → `discovered_links` (N links por run). |
| **Discovery** | **Fetch** | **1:M** | Um link descoberto pode gerar vários itens de fetch (ex.: 1 URL índice → vários PDFs; ou 1 link → N recursos). Hoje o código faz 1 link → 1 `fetch_item`; o modelo permite 1:M. | `discovered_links` (1) → `fetch_items` (N). FK `fetch_items.DiscoveredLinkId` → `discovered_links.Id`. |
| **Fetch**   | **Ingest** | **M:N** | Vários fetch_items podem virar vários documentos (1→N); ou agregação (N→1). | `fetch_items` → `documents` (FK `documents.FetchItemId`). Hoje 1 fetch_item → 1 doc; modelo permite M:N. |

---

## 3. Resultados reais (prova com dados do banco)

A tabela abaixo deve ser preenchida com **contagens reais** das tabelas após rodar o pipeline (seed → discovery → fetch → ingest). Assim provamos que cada fase e a cardinalidade estão corretas.

### 3.1 Query para obter os números

Rode no Postgres (ou use o script abaixo):

```sql
SELECT 'source_registry' AS tabela, COUNT(*) AS total FROM source_registry
UNION ALL SELECT 'seed_runs', COUNT(*) FROM seed_runs
UNION ALL SELECT 'discovery_runs', COUNT(*) FROM discovery_runs
UNION ALL SELECT 'discovered_links', COUNT(*) FROM discovered_links
UNION ALL SELECT 'fetch_runs', COUNT(*) FROM fetch_runs
UNION ALL SELECT 'fetch_items', COUNT(*) FROM fetch_items
UNION ALL SELECT 'documents', COUNT(*) FROM documents
ORDER BY 1;
```

### 3.2 Tabela de resultados reais (preencher com a query acima)

| Fase / camada | Tabela             | Contagem real | Prova de cardinalidade |
|---------------|--------------------|---------------|-------------------------|
| **Source (feed)** | (YAML)          | N fontes no arquivo | Entrada do Seed. |
| **Seed**      | `source_registry`  | _____         | N fontes persistidas (Seed 1:N sources). |
| **Seed**      | `seed_runs`        | _____         | 1 run por execução do seed (1:1 com “uma rodada de seed”). |
| **Discovery** | `discovery_runs`   | _____         | 1 run por fonte executada (Seed→Discovery 1:1 por source). |
| **Discovery** | `discovered_links` | _____         | N links por run (Discovery 1:N links). |
| **Fetch**     | `fetch_runs`       | _____         | 1 run por job de fetch (por source). |
| **Fetch**     | `fetch_items`      | _____         | M itens (Discovery→Fetch 1:M; 1 link → 1 ou N fetch_items). |
| **Ingest**    | `documents`        | _____         | P documentos (Fetch→Ingest M:N). |

(Substitua _____ pelos números obtidos na query.)

**Script que gera a tabela com dados reais:** rode `./scripts/cardinality-report.sh` (com Postgres acessível). A saída é a tabela em Markdown com as contagens atuais do banco.

### 3.3 Exemplo preenchido (após um run bem-sucedido)

| Fase / camada | Tabela             | Contagem real | Prova de cardinalidade |
|---------------|--------------------|---------------|-------------------------|
| Source (feed) | (YAML)             | 13            | 13 fontes no catálogo. |
| Seed          | `source_registry`  | 13            | 13 fontes após seed. |
| Seed          | `seed_runs`        | 1             | 1 execução de seed. |
| Discovery     | `discovery_runs`   | 1             | 1 run para a fonte rodada (ex.: tcu_acordaos). |
| Discovery     | `discovered_links` | 34            | 34 links (1 run : 34 links, 1:N). |
| Fetch         | `fetch_runs`       | 1             | 1 run de fetch. |
| Fetch         | `fetch_items`      | 34            | 34 itens (1 link : 1 item no código atual). |
| Ingest        | `documents`        | 34            | 34 docs (1 fetch_item : 1 doc no código atual). |

---

## 4. O que está implementado hoje

| Fase      | Implementado | Observação |
|-----------|---------------|------------|
| **Seed**  | Sim           | `CatalogSeedJobExecutor`: YAML → `source_registry` + `seed_runs`. |
| **Discovery** | Sim       | `SourceDiscoveryJobExecutor`: engine → `discovery_runs` + `discovered_links` + `EnsurePendingForLinksAsync` (cria `fetch_items`). |
| **Fetch** | Sim           | `FetchJobExecutor`: `fetch_runs` + processa `fetch_items` e cria `documents` (pending). Fetch “real” (download remoto) pode ser stub. |
| **Ingest**| Sim           | Processa documentos (pending) e indexa. |

Discovery **está implementado**; a ordem correta é Seed → **Discovery** → **Fetch** → Ingest.

---

## 5. Estabilidade (melhorias sugeridas)

Para reduzir instabilidade em runs Zero Kelvin:

1. **Ordem de subida**: API (com migrações) sobe primeiro; Worker só depois, usando o mesmo connection string.
2. **Não reiniciar infra no meio**: Evitar `docker compose down -v` enquanto o Worker está processando (evita “terminating connection” e “relation does not exist”).
3. **Seed run sempre gravado**: Garantir que o executor de seed persiste `seed_runs` no mesmo contexto/transação em que atualiza o job (evita source_registry cheio e seed_runs vazio).
4. **Timeout e retry**: Aumentar timeouts do E2E e considerar retry no script quando seed/last ou discovery/last ainda não existirem.

Quando quiser, rode o script `scripts/cardinality-report.sh` (ver abaixo) e cole a saída na seção “Resultados reais” para documentar a prova com dados reais.
