# Revisão: trabalho do Codex vs planos

Data: 2026-02-13  
Referências: `codex_full_plan_back_in_time.md`, `codex_plan.md`, `hard_times.md`, plano de pipeline resiliente (`.cursor/plans/`).

---

## 1. O que o Codex fez (resumo)

- **JobQueueRepository**: transições de estado (Complete, Fail, Heartbeat, UpdateProgress) passaram a usar `ExecuteUpdateAsync` por `Id`, sem carregar entidade, para evitar conflitos de concorrência otimista (xmin) entre heartbeat/progress e Complete/Fail.
- **FailAsync**: continua lendo `Attempts`/`MaxAttempts` com `AsNoTracking` + `FirstOrDefaultAsync`; em seguida aplica `ExecuteUpdateAsync` para retry ou failed.
- **EnqueueAsync**: hash de idempotência com `IdempotencyKey` ou payload (`job|type|sourceId|payloadJson`).
- **ReleaseLeaseAsync** e **CancelAsync**: não foram alterados (continuam Find + SaveChanges).
- Relatório Zero Kelvin: script manual com seed, discovery, fetch e ingest em 2 rodadas + fail-safe (discovery sem seed); gerado `zero-kelvin-stage-report.md`.

---

## 2. Alinhamento com os planos

### 2.1 codex_full_plan_back_in_time.md

| Aspecto | Esperado | Status |
|--------|----------|--------|
| Transições atômicas / sem conflito de versão | Evitar races em estado de job | **Atendido** (ExecuteUpdateAsync por Id) |
| Idempotência por fase | Chaves/hash definidos antes de codar | **Parcial**: hash em EnqueueAsync existe; PayloadHash único causa 500 ao reenfileirar ingest (mesmo payload) |
| Run vs item | Runs e itens explícitos | **Fora do escopo** desta sessão (fetch_items/fetch_runs já previstos no plano, não implementados pelo Codex aqui) |
| Zero Kelvin obrigatório | 3 cenários (normal, idempotente, fail-safe) | **Parcial**: script rodou mas R1/R2 falharam por 500 no refresh, discovery failed, 500 no ingest; R3 fail-safe ok (404) |

### 2.2 codex_plan.md

| Aspecto | Esperado | Status |
|--------|----------|--------|
| fetch_runs / fetch_items | Modelo com camada fetch | **Não alterado** pelo Codex (migrações/tabelas já existentes no repo) |
| Replicação pending | Discovery→Fetch e Fetch→Ingest com itens pending | **Não validado** (discovery não completou com links) |
| Smart/Manual Resume | Políticas e APIs | **Fora do escopo** desta sessão |
| Zero Kelvin em 3 cenários | Rodada 1, 2 e fail-safe | **Executado** pelo script; **resultado** mostra 3 bloqueios (refresh, discovery config, ingest enqueue) |

### 2.3 hard_times.md

| Aspecto | Esperado | Status |
|--------|----------|--------|
| Barreira: meio do pipeline | fetch stub, sem fetch_items completo | **Não resolvido** (foco do Codex foi fila de jobs, não fetch_items) |
| Pipeline confiável seed→discovery→fetch→ingest | Fluxo estável | **Ainda não**: discovery falha (config), refresh 500 (binding), ingest 500 (PayloadHash) |

### 2.4 Plano de pipeline resiliente (Partes 1–7)

- **Parte 1–2**: Modelo e contratos idempotentes – alinhado em intenção; falhas atuais são de implementação (binding, config no seed, hash único).
- **Parte 3–4**: TDD e ordem de implementação – Codex não implementou novas fases; corrigiu fila.
- **Parte 5–7**: Zero Kelvin e critérios – script executado; bloqueios identificados no relatório.

---

## 3. Lacunas e incorreções

1. **Refresh 500**  
   - Erro: "Failed to read parameter RefreshSourceRequest request from the request body as JSON."  
   - Causa provável: body vazio, Content-Type incorreto ou binding obrigatório sem default.  
   - **Ação**: Aceitar body opcional e tratar como `Force = true` quando ausente.

2. **Discovery failed (URL required for StaticUrl)**  
   - O seed persiste `DiscoveryConfig` como `{ url, template, parameters }` **sem** `strategy`.  
   - Na deserialização, `Strategy` default é `"static_url"` → engine usa StaticUrl e exige `Url`, que está vazio (dado em `template`).  
   - **Ação**: Persistir `strategy` (ex.: `"url_pattern"`) no JSON do seed para `tcu_acordaos` e demais fontes com template.

3. **Ingest 500 (SaveChanges em EnqueueAsync)**  
   - Índice único em `PayloadHash`.  
   - Segundo POST em `/phases/ingest` para a mesma fonte gera mesmo payload `{ "phase": "ingest" }` → mesmo hash → violação de unique.  
   - **Ação**: Usar idempotência por request para jobs de fase (ex.: `IdempotencyKey` único por chamada) ou política explícita (ex.: um job pendente por source+phase).

4. **ReleaseLeaseAsync / CancelAsync**  
   - Ainda usam Find + SaveChanges; podem sofrer do mesmo tipo de conflito xmin em cenários de corrida.  
   - **Ação**: Considerar migrar para `ExecuteUpdateAsync` em tarefa futura, após validar Zero Kelvin.

---

## 4. Conclusão

- O trabalho do Codex está **alinhado** com a intenção dos planos no que diz respeito a:
  - transições atômicas na fila (Complete/Fail/Heartbeat/UpdateProgress),
  - uso de hash para idempotência em Enqueue,
  - e execução de um fluxo Zero Kelvin com relatório.
- **Não está alinhado** ainda com o resultado “pipelines verde” porque:
  - refresh retorna 500 (binding),
  - discovery falha por config sem strategy no seed,
  - ingest falha ao reenfileirar por PayloadHash único.
- As correções acima (binding opcional, strategy no seed, idempotência/IdempotencyKey para ingest) devem permitir rodar Zero Kelvin em nível “industry standard” (R1 e R2 verdes, R3 fail-safe controlado) após implementação e nova execução do script.
