# Codex Plan - Smart Resume, Manual Resume, Rollback e Cardinalidade do Pipeline

Data: 2026-02-14

## 1. Objetivo
Evoluir o pipeline `seed -> discovery -> fetch -> ingest` para um padrão resiliente de produção, com:
- `smart-resume` automático por fase/item.
- `manual-resume` por source/fase/item.
- rollback lógico seguro (sem apagar histórico útil).
- modelagem correta para cardinalidade `1:1`, `1:M`, `M:N`.
- validação E2E com Zero Kelvin (rodada normal, rodada idempotente e rodada fail-safe).

## 2. Estado Atual (baseline real do código)
- Seed está assíncrono via job `catalog_seed`, com `seed_runs` e retry por fonte.
- Discovery já grava `discovery_runs` e links em `discovered_links`.
- `discovered_links` já possui `DiscoveryStatus`, `FetchStatus`, `IngestStatus`.
- `fetch` ainda é stub (`FetchJobExecutor` sem persistência real).
- Não existe `fetch_items` (ponto crítico para cardinalidade 1:M e M:N).
- `ingest_jobs` e `documents` ainda apontam direto para `link_id`.

## 3. Decisões Arquiteturais
1. Status por fase em `discovered_links` sozinho não é suficiente para modelar `Discovery -> Fetch (1:M)` e `Fetch -> Ingest (M:N)`.
2. Será criada a camada explícita `fetch_items` (obrigatória).
3. Rollback principal será lógico (`failed`, `stale`, `cancelled`, `skipped`) com trilha auditável, evitando deletes destrutivos em runtime.
4. `smart-resume` sempre reaproveita progresso confirmado (`completed`) e reprocessa apenas `pending/failed` elegíveis.
5. `manual-resume` será API-first, com filtros por `source`, `phase`, `status`, `run`, `item`.

## 4. Modelo de Dados Alvo
## 4.1 Tabelas
- `source_registry`
- `seed_runs`
- `discovery_runs`
- `discovered_links`
- `fetch_runs` (nova)
- `fetch_items` (nova)
- `ingest_runs` (nova, se necessário para auditoria por execução)
- `ingest_jobs`
- `documents`
- `pipeline_actions` (nova, para comando manual + auditoria)

## 4.2 Relacionamentos
- `source_registry (1) -> (N) discovered_links`
- `discovered_links (1) -> (N) fetch_items`
- `fetch_items (N) -> (N) ingest_jobs` (via tabela de junção se necessário)
- `fetch_items (N) -> (N) documents` (direto ou via ingest job, conforme regra final)

## 4.3 Status por fase
- `discovered_links.discovery_status`
- `fetch_items.fetch_status`
- `ingest_jobs.ingest_status` (ou equivalente no documento, conforme fluxo final)
- Status derivado `overall_complete` será calculado por query/view (não armazenado inicialmente).

## 5. Regras de Replicação de Pending
1. `Discovery -> Fetch`:
- Ao confirmar link no discovery, criar `fetch_items` com `fetch_status = pending`.
- Se link já existe, criar apenas fetch_items novos (idempotência por hash/chave natural).
2. `Fetch -> Ingest`:
- Ao `fetch_item` completar, criar jobs/itens de ingest com status inicial `pending`.
- Proteger duplicação com chave de idempotência (`payload_hash` + contexto de fase).
3. Nunca "resetar" `completed` automaticamente sem comando explícito.

## 6. Smart Resume (automático)
## 6.1 Escopo
- Granularidade primária: por item (`link`, `fetch_item`, `ingest_job`).
- Granularidade secundária: por source/run para coordenação.

## 6.2 Política
- Reprocessar somente:
  - `pending` vencido (stuck timeout),
  - `failed` dentro da política de retry,
  - `processing` órfão após crash detectado.
- Não reprocessar `completed` por padrão.

## 6.3 Priorização
- Ordem recomendada:
  1. `failed` recentes com baixo custo.
  2. `pending` mais antigos.
  3. backlog restante por fairness entre sources.
- Antistarvation com fatia mínima por source.

## 7. Manual Resume
## 7.1 Casos suportados
- Reexecutar por:
  - source inteira,
  - fase específica (`discovery/fetch/ingest`),
  - somente itens `failed`,
  - item individual (`link_id` / `fetch_item_id`).

## 7.2 Mudança de `sources_v2.yaml`
- Fonte nova: criar em `source_registry` e habilitar pipeline do zero.
- Fonte existente alterada: atualizar metadados/config e criar execução incremental (não apagar histórico).
- Fonte removida/inativa: marcar `enabled=false` e interromper novas execuções.

## 8. Rollback e Fail-safe
1. Rollback padrão: lógico, por status e motivo.
2. Compensação por fase:
- discovery falhou: run `failed`, sem remover links válidos já persistidos.
- fetch falhou parcialmente: manter itens concluídos; pendentes/failed seguem para resume.
- ingest falhou parcialmente: manter documentos válidos; falhos seguem para retry/manual resume.
3. Rollback físico (delete) só em manutenção controlada, nunca no caminho normal de runtime.

## 9. Plano de Execução (ordem)
1. Especificar contratos e regras de estado (ADR curta + checklist de idempotência).
2. Criar migrações de dados (`fetch_runs`, `fetch_items`, ajustes de FKs em `ingest_jobs/documents`, `pipeline_actions`).
3. Implementar repositórios e consultas de resume.
4. Implementar executor real de `fetch` com persistência em `fetch_items`.
5. Ajustar ingest para consumir `fetch_items` e propagar status.
6. Implementar APIs de manual-resume e controle operacional.
7. Adicionar observabilidade (métricas por fase, itens stuck, retries, taxa de sucesso).
8. Endurecer testes (unit + integração + E2E Zero Kelvin).
9. Executar validação em 3 cenários e consolidar relatório final.

## 10. Estratégia de Testes (TDD-first)
1. Testes de modelo:
- cardinalidade correta e constraints de idempotência.
2. Testes de serviço/executor:
- smart-resume não reprocessa `completed`.
- criação de pending na fase seguinte.
- retry/backoff e transições corretas.
3. Testes de API:
- endpoints de manual-resume e erros previsíveis.
4. Teste E2E Zero Kelvin:
- rodada 1: seed -> discovery -> valida DB.
- rodada 2: seed -> discovery novamente -> valida idempotência.
- rodada 3: discovery sem seed (ambiente zerado) -> falha controlada/fail-safe.

## 11. Critérios de Aceite
- Nenhuma duplicação indevida entre fases com mesmo input.
- Resume automático comprovado após interrupção simulada.
- Resume manual funcional por source/fase/item.
- Status por fase auditável e consistente com cardinalidade real.
- Relatório final com resultados objetivos das rodadas E2E.

## 12. Fora de Escopo desta iteração de planejamento
- Otimizações avançadas de scheduling por custo preditivo.
- Estratégias de ranking/retrieval (MCP/Elastic híbrido).
- Ajustes de UX frontend além do necessário para acionar/resumir fases.
