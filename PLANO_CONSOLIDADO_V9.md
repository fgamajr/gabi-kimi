# Plano Consolidado v9 (Fonte Única de Execução)

Data base: 24 de fevereiro de 2026
Status: ativo
Escopo: substituir e consolidar V5, V6, V7, V8, TODO, matriz de fontes, gaps e code notes.

---

## 1. Objetivo do v9

Manter um único plano operacional, orientado por evidência, para:
1. fechar os gaps bloqueantes de produção;
2. preservar arquitetura em camadas e budget de memória (300MB efetivo no Worker);
3. evitar divergência documental entre planos antigos.

Regras do plano:
1. toda decisão precisa de evidência de código, teste ou execução;
2. itens devem estar em um único estado: `feito`, `em_andamento`, `pendente`, `descartado`;
3. qualquer item novo entra neste documento, não em arquivos paralelos.

---

## 2. Document Governance

Objetivo: manter o repositório com **fonte única de plano** e separar claramente documentos ativos vs. históricos.

Documentos canônicos ativos:
1. `PLANO_CONSOLIDADO_V9.md` (execução e priorização).
2. `AGENTS.md` (regras operacionais de engenharia/arquitetura).

Diretório `grounding_docs/`:
1. Top-level deve conter apenas referências aprovadas e úteis para contexto histórico técnico.
2. Todo material de plano antigo, rascunho de agente ou sprint desatualizado deve ir para `grounding_docs/archive/`.
3. Artefatos binários (ex.: instaladores `.deb`) não devem ficar em `grounding_docs/` como guia; devem ser removidos ou movidos para local técnico dedicado.

Status consolidado de `grounding_docs`:
1. `ARCHITECTURE_OVERVIEW.md`: referência aprovada (histórico arquitetural).
2. `c#.md`: referência aprovada (viabilidade e decisões de stack).
3. `PLANEJAMENTO_GABI_SYNC_v2.md`: referência aprovada (baseline histórico).
4. `pipeline.md`: arquivado (conteúdo absorvido no V9).
5. `claude_plan.md`: arquivado (plano antigo).
6. `DAY_SPRINT.md`: arquivado (cronograma antigo).
7. `kimi.md`: arquivado (resumo antigo).
8. `packages-microsoft-prod.deb`: removido do diretório de guias.
9. `old_python_implementation/`: removido do repositório ativo; salvage técnico preservado em `grounding_docs/archive/legacy-python/`.

---

## 3. Snapshot Atual (factual)

### 3.1 Pipeline

| Etapa | Estado | Evidência principal |
|---|---|---|
| Seed | feito | `CatalogSeedJobExecutor` + endpoints de dashboard |
| Discovery | feito | adapters `static_url`, `url_pattern`, `web_crawl`, `api_pagination` |
| Fetch | feito | `FetchJobExecutor` com streaming + hardening |
| Ingest v1 (normalização + projeção de mídia) | feito | `IngestJobExecutor` normaliza texto e projeta mídia |
| Ingest v2 (chunk/embed/index real) | em_andamento | `IngestJobExecutor` executa chunk/embed/index local com metadados v2 |
| Search API funcional | em_andamento | endpoint `GET /api/v1/search` com filtro/paginação já disponível |

### 3.2 Estado arquitetural

1. Contratos e testes de arquitetura existem e continuam mandatórios.
2. Há progresso de robustez operacional (DLQ/replay, telemetria, cap por source).
3. Ainda há dívida para completar a cadeia `ingest -> index -> search`.

---

## 4. Consolidação do que já foi feito

### 4.1 Entregas confirmadas recentes

1. Fase opcional `media-projection` integrada ao zero-kelvin:
- `tests/zero-kelvin-test.sh`
- `tests/e2e-media-projection.sh`

2. Evidência de execução informada e validada na trilha atual:
- `zero-kelvin` targeted `media-projection`: `PASS 15/15`, `docs_processed=1`, `status_breakdown=media_projection=1`.
- `zero-kelvin` full `tcu_acordaos` cap 200: `PASS 15/15`, com `capped` e `pending` coerentes com cap operacional.

3. Correções de robustez no fetch já aplicadas:
- reset de stuck `processing` no início do fetch;
- release explícito de itens `processing` quando cap interrompe processamento.

4. Correções concluídas hoje:
- `DEF-06` (atomicidade no enqueue por `source+jobType`) em `HangfireJobQueueRepository`;
- `DEF-18` (progress sem swallow) em `GabiJobRunner` com pump por canal e logging de falhas;
- `DEF-08` (idempotência de insert em `documents`) com upsert por conflito em `SourceId+ExternalId`;
- `DEF-07` (runner/progress context) com pump de progresso usando contexto dedicado e sem churn de scope por update.

5. Entregas adicionais (v2 mínimo viável):
- `HashEmbedder` e `LocalDocumentIndexer` criados em `Gabi.Ingest`;
- `IngestJobExecutor` atualizado para fluxo real `normalize -> chunk -> embed -> index -> persist`;
- endpoint `GET /api/v1/search` implementado em `Gabi.Api`;
- teste de integração adicionado: `SearchEndpointTests`.

6. Cobertura de testes adicionada para os pontos acima:
- `HangfireJobQueueRepositoryConcurrencyTests`;
- `GabiJobRunnerProgressTests`;
- `SearchEndpointTests`.

7. Correção de bloqueio de build:
- ambiguidades de `Split` corrigidas em `FixedSizeChunker`.

### 4.2 Execução de testes (24/02/2026)

Comandos executados:

```bash
dotnet build GabiSync.sln --nologo -m:1
dotnet test tests/Gabi.Api.Tests/Gabi.Api.Tests.csproj \
  --filter "FullyQualifiedName~SearchEndpointTests" --nologo
dotnet test tests/Gabi.Postgres.Tests/Gabi.Postgres.Tests.csproj \
  --filter "FullyQualifiedName~HangfireJobQueueRepositoryConcurrencyTests|FullyQualifiedName~GabiJobRunnerProgressTests|FullyQualifiedName~FetchDocumentMetadataMergeTests|FullyQualifiedName~FetchCapOptionsTests|FullyQualifiedName~JobQueueRepositoryHashTests|FullyQualifiedName~HangfireRetryPolicyTests" \
  --nologo
sudo ./tests/zero-kelvin-test.sh docker-only \
  --source tcu_acordaos \
  --phase full \
  --max-docs 200 \
  --report-json /tmp/zk_tcu_acordaos_full_200_after_cleanup.json
```

Resultado:
1. `Build: sucesso (0 erros)`
2. `API tests: Passed 2/2`
3. `Postgres tests: Passed 23/23`
4. `Failed: 0`
5. `Skipped: 0`
6. `Zero-kelvin targeted full (tcu_acordaos): PASS 16/16, docs_processed=200, status_breakdown=completed,200`
7. `Busca pós-ingest (GET /api/v1/search?q=2007&sourceId=tcu_acordaos&page=1&pageSize=5): total=200, hits=5`

---

## 5. Inventário Consolidado de Status (DEF)

Referência: avaliação forense acumulada (V8 + revisão recente + execução atual).

### 5.1 `feito`

1. `DEF-05` (obsoleto/corrigido na trilha atual).
2. `DEF-06` (enqueue atômico por `source+jobType` com lock transacional).
3. `DEF-07` (runner ajustado para persistência de progresso robusta e determinística).
4. `DEF-08` (upsert em `documents` evita conflito/retry por unicidade ativa).
5. `DEF-13` (obsoleto/corrigido).
6. `DEF-15` (stuck pós-cap no fetch corrigido).
7. `DEF-18` (progresso sem swallow, com observabilidade de falha).

### 5.2 `em_andamento` / `parcial`

1. `DEF-01`: ingest v2 mínimo viável implementado (chunk/embed/index local); falta integração com indexador externo para fechamento completo.
2. `DEF-10`: validações de mídia evoluíram, ainda sem fechamento completo de startup guards em todos cenários.
3. `DEF-11`: progresso parcial.
4. `DEF-12`: progresso parcial.
5. `DEF-02`: endpoint de busca básico entregue; falta indexador externo e ranking.
6. `DEF-03`: busca funcional local entregue; integração plena com infraestrutura de busca ainda pendente.

### 5.3 `pendente`

1. `DEF-04`
2. `DEF-09`
3. `DEF-14`
4. `DEF-16`
5. `DEF-17`
6. `DEF-19`

### 5.4 `ajustado` (diagnóstico revisado)

1. `DEF-08` foi reclassificado corretamente: não era “duplicação silenciosa” e sim risco de conflito/retry por unicidade.
2. Mitigação aplicada: `upsert` com `ON CONFLICT ("SourceId","ExternalId") WHERE "RemovedFromSourceAt" IS NULL`.

---

## 6. Backlog Único Priorizado (v9)

## P0 (bloqueante de produto)

1. Consolidar `DEF-01`: trocar indexação local por provider externo configurável e validar sob carga.
2. Consolidar `DEF-02/03`: evoluir busca para índice externo com relevância e telemetria.
3. Fechar `DEF-19`: fail-fast de startup para configurações essenciais ausentes em produção.

Aceite P0:
1. documento entra no pipeline e aparece em busca sem intervenção manual;
2. rerun não cria conflito operacional (idempotência comprovada);
3. suíte targeted de regressão passa.

## P1 (robustez operacional)

1. Fechar `DEF-14`: padronizar escrita de documentos via repositório dedicado.
2. Fechar `DEF-04`: alinhar estratégia de rate limiting/distribuição conforme infra real.
3. Fechar `DEF-16/17`: observabilidade e resiliência adicionais com métricas acionáveis.

Aceite P1:
1. testes de falha/replay cobrindo casos críticos;
2. sem falhas silenciosas em progress/retry/path críticos.

## P2 (excelência e expansão)

1. Itens avançados de V7 (property-based, chaos, DORA, hardening extensivo de runbook/security).
2. Evoluções de relevância (reranker/melhorias semânticas) após P0/P1 estáveis.

---

## 7. Itens Descartados/Despriorizados

1. Manter múltiplos planos ativos em paralelo (`V5/V6/V7/V8/TODO/gaps/matriz/code`) -> descartado.
2. Tratar ingest atual como “noop total” -> descartado; hoje há ingest v1 útil (texto + projeção de mídia).
3. Tratar `DEF-08` como duplicação silenciosa primária -> descartado; foco correto é conflito/idempotência de insert.
4. Executar bloco “world-class V7” antes de fechar bloqueios de pipeline/search -> despriorizado.
5. Remoções estruturais amplas de assemblies sem validação incremental -> despriorizado até fechamento de P0.

---

## 8. Sequência de Execução Recomendada (próximo passo)

Pré-condição obrigatória:
1. definições por source devem estar em `sources_v2.yaml` (sem regras hardcoded por `source_id` no código).

Checklist de execução (conversão pré-ingest):
1. [x] Fazer matriz source-by-source com “formato real recebido” e “conversor necessário”.
- Evidência: `reports/ingest_conversion_plan/source_conversion_matrix_2026-02-24.csv`
- Evidência: `reports/ingest_conversion_plan/source_conversion_matrix_2026-02-24.md`
2. [~] Implementar camada de conversão (JSON/HTML/PDF/PPTX/media) para produzir `content_text + metadata`.
- Andamento: `json/html/pdf` implementados no fetch `link_only` via `fetch.converter` declarativo em `sources_v2.yaml`; pendente `pptx/media`.
3. [x] Só enfileirar ingest para fontes `text_ready`.
- Implementado de forma declarativa: `IngestJobExecutor` carrega política de `sources_v2.yaml` por source e usa fallback de `defaults.pipeline.ingest`.
4. [x] Marcar `metadata_only` quando não houver texto (sem tratar como falha).
- Implementado no ingest via `pipeline.ingest.empty_content_action=metadata_only` (sem hardcode por `source_id`).
5. [x] Ajustar zero-kelvin para cobrar ingest apenas de fontes `text_ready`.
- Implementado: `tests/zero-kelvin-test.sh` consulta `pipeline.ingest.readiness` no `sources_v2.yaml` e marca `ingest_not_required` para fontes `metadata_only`.

Próxima execução imediata:
1. implementar conversores prioritários das fontes `metadata_only_until_converter` (pdf/json/html).
2. atualizar asserts da suíte zero-kelvin por perfil de source.
3. rodar zero-kelvin por amostra multi-source para validar classificação `text_ready` vs `metadata_only`.

---

## 9. Governança de Execução do Plano

1. Este arquivo é a única fonte de planejamento operacional corrente.
2. Qualquer atualização deve alterar:
- `Snapshot Atual`;
- `Inventário DEF`;
- `Backlog Único`.
3. Evidência mínima para mover item a `feito`:
- diff de código + teste automatizado ou execução comprovada.
