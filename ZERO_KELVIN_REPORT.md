# Zero Kelvin - Relatório Industry Standard

Data: 2026-02-13  
Referência: `codex_full_plan_back_in_time.md`, `codex_plan.md`, script `scripts/e2e-zero-kelvin.sh`.

---

## 1. Cenários (3 rodadas)

| Cenário | Descrição | Critério de sucesso |
|--------|-----------|----------------------|
| **R1** | Infra limpa → Seed → Discovery → Fetch → Ingest | seed/last status completed ou partial; discovery/fetch/ingest concluem; contagens DB consistentes |
| **R2** | Mesmo ambiente → Seed de novo → Discovery → Fetch → Ingest | Idempotência: sem duplicação indevida; status completed/partial |
| **R3 (fail-safe)** | Infra limpa (sem seed) → Discovery | Resposta controlada: 404 ou erro “Source not found”; nenhum dado inconsistente |

---

## 2. Revisão do trabalho do Codex

- **Documento**: `.cursor/REVISAO_CODEX_VS_PLANOS.md`
- **Resumo**: Codex aplicou transições atômicas no `JobQueueRepository` (ExecuteUpdateAsync por Id), alinhado aos planos. O relatório Zero Kelvin dele expôs 3 bloqueios: (1) refresh 500 por binding do body, (2) discovery failed por config sem `strategy` no seed, (3) ingest 500 por PayloadHash único ao reenfileirar.

---

## 3. Correções aplicadas (esta sessão)

| # | Problema | Correção |
|---|----------|----------|
| 1 | Refresh 500 – “Failed to read parameter RefreshSourceRequest from body” | `Program.cs`: parâmetro `RefreshSourceRequest? request`; uso de `request ?? new RefreshSourceRequest { Force = true }`. |
| 2 | Discovery failed – “URL is required for StaticUrl mode” | Seed persiste `strategy` (e `urlTemplate`) em `DiscoveryConfig` no `CatalogSeedJobExecutor` para que a engine use UrlPattern e o template. |
| 3 | Ingest 500 – SaveChanges em EnqueueAsync (unique PayloadHash) | `DashboardService.StartPhaseAsync`: `IdempotencyKey = Guid.NewGuid().ToString()` ao criar job de fetch/ingest para que cada trigger gere hash distinto. |

---

## 4. Script E2E

- **Arquivo**: `scripts/e2e-zero-kelvin.sh`
- **Timeouts**: Seed 180s, Discovery 120s (ajustados para ambiente com 13 fontes).
- **Saída**: `e2e-zero-kelvin-results.txt` (resultados 1ª e 2ª rodada + fail-safe).

---

## 5. Como rodar

1. Infra: `./scripts/infra-up.sh` (ou o script E2E sobe sozinho).
2. Build: `dotnet build src/Gabi.Api/Gabi.Api.csproj` e `dotnet build src/Gabi.Worker/Gabi.Worker.csproj`.
3. Executar: `./scripts/e2e-zero-kelvin.sh`.
4. Conferir: `e2e-zero-kelvin-results.txt` e logs em `e2e-api.log` / `e2e-worker.log` em caso de falha.

---

## 6. Critérios pass/fail (industry standard)

- **R1**: Seed completed/partial; discovery completed/partial/failed com resposta HTTP 200 no trigger; fetch/ingest sem 500 no trigger; DB com seed_runs ≥ 1, source_registry preenchido.
- **R2**: Mesmos critérios; idempotência (segundo ingest não retorna 500).
- **R3**: HTTP 404 ou corpo com “Source not found”; seed_runs=0; sem exceções não tratadas.

Após as correções acima, uma nova execução completa do script deve permitir atestar pass/fail por rodada com base neste relatório.
