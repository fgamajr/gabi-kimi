# GABI Ingestion Production Plan

Data: 2026-02-11  
Escopo: Evoluir a ingestão de um fluxo sequencial frágil para um modelo robusto, paralelo, priorizado e incremental.

## 1. Problema Atual

Hoje a ingestão depende de execução sequencial por source. Isso gera efeitos ruins:

- Uma source lenta/travada bloqueia todas as próximas.
- Sources grandes (ex.: `tcu_acordaos`) atrasam sources menores e críticas.
- Timeout/retry/circuit breaker estão parcialmente no shell (`.sh`) e não no domínio Python/worker.
- Manifestos podem ficar `running` sem `completed_at` em falhas abruptas.
- O comportamento incremental não está centralizado como política obrigatória por source.

Resultado: baixa previsibilidade operacional e baixa eficiência para produção.

## 2. Objetivos Essenciais (10 requisitos consolidados)

### Bloco A (mensagem “produção-like”)

1. Job por source (fila), sem loop bloqueante.
2. Processamento paralelo com limite de concorrência.
3. Timeout/retry por source com continuação das demais.
4. Prioridade por source (rápidas/críticas primeiro).
5. Incremental/watermark para não reprocessar acórdãos massivos.

### Bloco B (mensagem “sh vs Python”)

1. `start_ingestion.sh` como launcher operacional, não orquestrador principal.
2. Orquestração central em Python (`cli` + tasks).
3. Paralelismo e jobs no worker (Celery), não no shell.
4. Tratamento de erro e resiliência no pipeline Python.
5. Estado e reprocessamento controlados por modelo/manifest/checkpoint no backend.

## 3. Arquitetura Alvo

## 3.1 Componentes

- Launcher: `scripts/start_ingestion.sh`
- Scheduler de ingestão: `src/gabi/cli.py` (`ingest-schedule`)
- Worker de execução por source: `src/gabi/tasks/sync.py`
- Estado operacional:
  - `source_registry` (status, erro, últimos syncs)
  - `execution_manifests` (run status, stats, tempo, erro)

## 3.2 Filas e prioridade

- Fila `gabi.sync.high`: sources críticas/rápidas (normas, súmulas, jurisprudência selecionada).
- Fila `gabi.sync.normal`: sources padrão.
- Fila `gabi.sync.bulk`: sources grandes (`tcu_acordaos`).

Regra: cada source entra em uma fila com prioridade explícita.  
`tcu_acordaos` não bloqueia normas/súmulas.

## 3.3 Paralelismo

- Concurrency por fila (exemplo inicial):
  - `high`: 4
  - `normal`: 3
  - `bulk`: 1
- Ajustável por ambiente (local/staging/prod).

## 3.4 Timeout, retry e circuit breaker

- Timeout por source no worker (soft/hard).
- Retry com backoff exponencial para erros transitórios.
- Circuit breaker por source:
  - ao atingir limiar de falhas consecutivas, source muda para `error`/`paused`.
  - scheduler não reenfileira até janela de cooldown.

## 3.5 Incremental/watermark

- Persistir checkpoint por source (`checkpoint` no manifest e/ou metadado derivado no source).
- Discovery/fetch limitados ao delta desde `last_success_at` ou watermark específico.
- Backfill grande (acórdãos) separado de sync incremental diário.

## 4. Mudanças por Arquivo

## 4.1 `scripts/start_ingestion.sh`

Transformar para launcher:

- Verifica infra e dependências.
- Opcionalmente roda smoke tests.
- Chama apenas:
  - `python -m gabi.cli reset-stale-manifests` (opcional)
  - `python -m gabi.cli ingest-schedule ...`
- Não executa loop de source no shell.

## 4.2 `src/gabi/cli.py`

Adicionar comandos:

- `ingest-schedule`
  - lê `sources.yaml`
  - aplica política de prioridade
  - decide lote incremental vs bulk
  - enfileira 1 task por source
- `reset-stale-manifests`
  - marca `running/pending` antigos como `cancelled` ou `failed` por TTL
- `ingest-status-summary`
  - resumo por source/run para operação

## 4.3 `src/gabi/tasks/sync.py`

Evoluções:

- Receber metadados de execução (priority lane, timeout profile, incremental mode).
- Aplicar timeout/retry no nível da task.
- Atualizar manifest e source com granularidade de fase.
- Persistir checkpoint/watermark após sucesso parcial/total.

## 4.4 `src/gabi/models/*`

- Reforçar uso de:
  - `SourceRegistry`: `consecutive_errors`, `last_sync_at`, `last_success_at`, `last_error_at`.
  - `ExecutionManifest`: `status`, `started_at`, `completed_at`, `stats`, `checkpoint`.
- Sem quebra de schema obrigatória inicialmente; expandir só se faltar campo para watermark.

## 5. Política Operacional Recomendada

## 5.1 Execução diária

- Rodada A (críticas): `high + normal`, incremental, SLA curto.
- Rodada B (bulk): `tcu_acordaos`, janela dedicada.

## 5.2 Tratamento de falhas

- Transitório (rede/timeout): retry automático.
- Persistente por source: circuit breaker + alerta + cooldown.
- Manifesto órfão: reset automático por comando agendado.

## 5.3 Governança de capacidade

- Limitar concorrência de fontes com fetch externo para não saturar rede.
- Limitar embeddings em paralelo para não saturar TEI.
- Separar orçamento de recursos entre `bulk` e `high`.

## 6. Plano de Implementação por Fases

## Fase 1 (rápida, baixo risco)

- Implementar `ingest-schedule` e `reset-stale-manifests`.
- Mover orquestração principal para Python.
- Manter compatibilidade com fluxo atual (feature flag).

Entrega: jobs por source + prioridade + reset de travados.

## Fase 2 (resiliência)

- Timeout/retry padronizados por source no worker.
- Circuit breaker baseado em erro consecutivo.
- Resumo operacional em CLI.

Entrega: pipeline não bloqueia inteiro por 1 source ruim.

## Fase 3 (eficiência)

- Incremental/watermark robusto por source.
- Separar backfill bulk de sync diário.
- Ajustar concorrência por fila com métricas reais.

Entrega: redução de custo/tempo e SLA previsível.

## 7. Estratégia de Rollout

- Flag `INGEST_MODE=sequential|queued` (default inicial: `sequential`).
- Staging com `queued` por 1 semana.
- Produção gradual:
  - Semana 1: `high` apenas
  - Semana 2: `high + normal`
  - Semana 3: `bulk` com janela dedicada
- Fallback imediato: voltar para `sequential`.

## 8. Plano de Testes

## 8.1 Unitários

- Priorização de sources.
- Enfileiramento correto por fila.
- Retry/circuit breaker.
- Reset de manifest stale por TTL.

## 8.2 Integração

- N sources em paralelo, 1 travando, demais concluindo.
- Timeout por source sem matar lote inteiro.
- Atualização consistente de `execution_manifests` e `source_registry`.

## 8.3 E2E operacional

- Rodada completa com sources externas lentas/inacessíveis.
- Verificar que fontes críticas terminam mesmo com falhas em bulk.

## 9. Riscos e Mitigações

- Risco: sobrecarga do TEI com alto paralelismo.
  - Mitigação: limitar concorrência de embedding e usar fila dedicada.
- Risco: aumento de complexidade de operação.
  - Mitigação: CLI de status e runbook claro.
- Risco: inconsistência de estado em interrupções.
  - Mitigação: finalização defensiva de manifest e reset stale automatizado.

## 10. Definition of Done

Considerar concluído quando:

- `start_ingestion.sh` não tem orquestração complexa de source.
- `ingest-schedule` enfileira jobs por source com prioridade.
- Workers processam sources em paralelo com limite configurável.
- Timeout/retry/circuit breaker operam por source.
- Incremental/watermark ativo para `tcu_acordaos` e demais fontes elegíveis.
- Manifestos travados são recuperáveis automaticamente.
- Testes unit/integration novos cobrindo o fluxo.
- Runbook e comandos operacionais documentados.

## 11. Comandos Alvo (após implementação)

```bash
# Reset de manifestos órfãos (TTL 2h)
python -m gabi.cli reset-stale-manifests --stale-minutes 120

# Enfileirar ingestão com prioridade e modo incremental
python -m gabi.cli ingest-schedule --sources-file sources.yaml --mode incremental

# Resumo operacional da última janela
python -m gabi.cli ingest-status-summary --since-hours 6
```

---

Este documento é o plano-base para implementar os 10 requisitos essenciais de ingestão em produção com confiabilidade, throughput e isolamento de falhas.
