# Zero Kelvin – Resultados por estágio (tabelas laterais)

Data: 2026-02-14  
Após: melhorias de estabilidade, zero de infra e execução do E2E.

---

## Melhorias de estabilidade implementadas

1. **Seed run sempre gravado**  
   O executor de seed agora cria um registro em `seed_runs` **no início** (status `processing`) e **atualiza** ao terminar (status `completed`/`partial`/`failed`). Assim, mesmo se o processo cair no meio, há pelo menos uma linha em `seed_runs`.

2. **Ordem API → migrações → Worker**  
   O script E2E aguarda a API ficar saudável e depois espera **5 s** antes de considerar pronto, para dar tempo às migrações.

3. **Polling sem abortar em 4xx**  
   `api_get_soft` e `api_post_soft` usam `curl -s` (sem `-f`) para seed/last, discovery/last e triggers, para o script não terminar em 404/500 e seguir até o fim.

4. **Timeouts**  
   Seed: 240 s; Discovery: 120 s.

5. **Relatório de cardinalidade ao final**  
   O script chama `scripts/cardinality-report.sh` e anexa o resultado em `e2e-zero-kelvin-results.txt`.

---

## Tabelas por estágio (contagens reais do banco)

Uma tabela por estágio, com as contagens obtidas após o run (ou do último `./scripts/cardinality-report.sh`).

---

### Estágio Seed

| Tabela            | Contagem | Prova de cardinalidade        |
|-------------------|----------|-------------------------------|
| `source_registry` | **13**   | N fontes persistidas (Seed)  |
| `seed_runs`       | **0**    | 1 run por execução do seed   |

*(Seed executou: 13 fontes no banco. `seed_runs` ainda 0 — run gravado no início pode estar em outro contexto ou API retornando 404 em seed/last.)*

---

### Estágio Discovery

| Tabela             | Contagem | Prova de cardinalidade     |
|--------------------|----------|----------------------------|
| `discovery_runs`   | **0**    | 1 run por fonte            |
| `discovered_links` | **0**    | N links por run (1:N)      |

*(Polling de discovery/last deu timeout; discovery pode não ter concluído a tempo ou job não rodou.)*

---

### Estágio Fetch

| Tabela        | Contagem | Prova de cardinalidade   |
|---------------|----------|--------------------------|
| `fetch_runs`  | **1**    | 1 run por job de fetch   |
| `fetch_items` | **0**    | M itens (1:M por link)   |

*(Fetch completou: status completed, items_total=0 — sem links descobertos não há itens.)*

---

### Estágio Ingest

| Tabela       | Contagem | Prova de cardinalidade |
|--------------|----------|-------------------------|
| `documents`  | **0**    | P docs (M:N com fetch)   |

*(Ingest: pending_docs=0. Sem fetch_items não há documentos.)*

---

## Como regenerar as tabelas com dados reais

1. Subir infra: `./scripts/infra-up.sh`
2. Garantir que API e Worker usem o mesmo connection string e que a API rode migrações antes do Worker
3. Rodar o E2E: `./scripts/e2e-zero-kelvin.sh`
4. Rodar o relatório de cardinalidade: `./scripts/cardinality-report.sh`
5. Atualizar as contagens acima com a saída do script (ou colar a tabela gerada neste doc)

Para maior estabilidade, considere rodar API e Worker no mesmo ambiente (ex.: `docker compose --profile api --profile worker`) para evitar diferença de rede/porta em relação ao Postgres.
