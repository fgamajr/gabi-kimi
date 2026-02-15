---

## Avaliação dos relatórios do projeto

| Documento | O que agrega para a migração Hangfire |
|-----------|----------------------------------------|
| **codex_full_plan_back_in_time.md** | Arquitetura alvo (fases, cardinalidade, smart/manual resume). Não conflita com Hangfire; define o "que" do pipeline. Hangfire é a camada de transporte. Útil para depois: garantir que job_registry/GetLatest* continuem servindo o dashboard e que manual-resume (quando existir) use a mesma abstração. |
| **codex_plan.md** | Ordem de execução (fetch_items, ingest real, manual-resume). Migração Hangfire é ortogonal; completa a infra de fila. O "main blocker" de hard_times (fetch layer) continua sendo tratado em outro plano. |
| **hard_times.md** | Bloqueio principal: fetch stub, sem fetch_items. Hangfire não resolve isso; resolve só a fila. Deixar explícito: migração Hangfire primeiro, depois completar pipeline (fetch_items + fetch/ingest real). |
| **why_fails.md** | **Causa raiz do Zero Kelvin**: Worker não acha `sources_v2.yaml` porque `GABI_SOURCES_PATH` é relativo e o working directory do processo não é o repo. **Correção P0**: path absoluto ou `ResolveSourcesPath()` robusto (ver Wave 0 abaixo). Sem isso, Zero Kelvin continua falhando mesmo após Hangfire. |
| **e2e-zero-kelvin-results.txt** | Confirma: seed_runs=0, source_registry=13, discovery timeout; fail-safe 404 OK. Coerente com "Sources file not found" nos logs. |
| **ZERO_KELVIN_REPORT.md** / **ZERO_KELVIN_RESULTADOS.md** | Critérios de sucesso e como rodar. Não mudam o plano Hangfire; validação pós-migração deve seguir os mesmos critérios. |
| **zero-kelvin-stage-report.md** | Em algum run: seed_runs=1, discovery_runs executaram (status failed). Mostra que com ambiente certo (path, DB) o fluxo grava; o problema é ambiente (path) e config discovery, não só a fila. |

**Conclusão**: Os relatórios validam que (1) é essencial corrigir **GABI_SOURCES_PATH** (P0) para Zero Kelvin passar; (2) Hangfire não substitui a conclusão do pipeline (fetch_items, fetch/ingest real), mas desbloqueia a operação da fila e do E2E com seed/discovery.

---

## Comparação com o plano externo (Hangfire Migration — Implementation Plan)

| Aspecto | Plano externo | Nosso plano | Recomendação |
|---------|----------------|-------------|--------------|
| **IJobQueueRepository** | Remove; usa BackgroundJob + IMonitoringApi. | Mantém; HangfireJobQueueRepository + job_registry. | Manter nossa abordagem: menos invasão; GetLatestForSource por sourceId é trivial com job_registry. IMonitoringApi não indexa por sourceId. |
| **Job types** | Uma classe por fase (CatalogSeedJob, etc.) com [Queue("seed")]. | Um GabiJobRunner que despacha para IJobExecutor. | Adotar **filas** (seed, discovery, fetch, ingest) no nosso runner; opcional evoluir para uma classe por fase depois. |
| **Polly** | Remove. | Não mencionado. | **Manter Polly** nos executors para retries dentro do job; Hangfire para retry do job inteiro. |
| **P0 GABI_SOURCES_PATH** | Inclui .env absoluto + ResolveSourcesPath robusto. | Não estava. | **Incorporar como Wave 0** (abaixo). |
| **Pacotes** | Hangfire.AspNetCore. | Só Core + PostgreSql. | Usar **Hangfire.AspNetCore** na API. |

**Incorporar**: (1) Wave 0 — P0 path do seed; (2) Hangfire.AspNetCore; (3) filas por JobType; (4) documentar que Polly fica para retries internos.

---

## Wave 0 — P0: Resolver path do seed (pré-requisito para Zero Kelvin)

Causa raiz em why_fails.md: Worker não encontra `sources_v2.yaml` (GABI_SOURCES_PATH relativo / CWD errado). Fazer antes da migração Hangfire:

1. **CatalogSeedJobExecutor.ResolveSourcesPath()**: se env/config for path **absoluto**, usar; se **relativo**, resolver com `Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", path)` ou equivalente. Fallback para config; null se vazio.
2. **e2e-zero-kelvin.sh**: exportar `GABI_SOURCES_PATH` com path **absoluto** (ex. `$GABI_ROOT/sources_v2.yaml` com GABI_ROOT absoluto) antes de subir o Worker.
3. **Validação**: rodar Zero Kelvin após Wave 0; esperar seed_runs >= 1 antes de validar Hangfire.
