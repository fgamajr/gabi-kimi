# Por que o Zero Kelvin falhou – Análise Detalhada

Data: 2026-02-14
Executor: Claude Opus 4.6

## Resumo Executivo

O teste E2E Zero Kelvin foi executado com as seguintes melhorias de estabilidade implementadas:
- Seed run sempre gravado (antes e depois do processamento)
- Ordem API → migrações → Worker
- Polling sem abortar em 4xx (api_get_soft/api_post_soft)
- Timeouts aumentados (Seed: 240s, Discovery: 120s)

**Resultado:** Falhou com timeouts em Seed e Discovery em ambas as rodadas.

## Achados do Teste

### Estado do Banco após execução

| Tabela | Contagem | Observação |
|--------|----------|------------|
| `source_registry` | 13 | ✅ Fontes persistidas |
| `seed_runs` | 0 | ❌ Nenhum run gravado |
| `discovery_runs` | 0 | ❌ Discovery não executou |
| `discovered_links` | 0 | ❌ Sem links descobertos |
| `fetch_runs` | 1 | ⚠️ Executou mas sem itens |
| `fetch_items` | 0 | ⚠️ Normal sem links |
| `documents` | 0 | ⚠️ Normal sem fetch items |

### Job catalog_seed

```sql
SELECT "Id", "JobType", "Status", "Attempts", "LastError", "CompletedAt", "RetryAt"
FROM ingest_jobs WHERE "JobType" = 'catalog_seed';
```

Resultado:
- **Status:** `pending` (não `completed`)
- **Attempts:** 2
- **LastError:** `"Sources file not found at sources_v2.yaml"`
- **CompletedAt:** 2026-02-14 22:37:16 (mas Status ainda pending)
- **RetryAt:** 2026-02-14 22:41:16

### Logs do Worker

```
2026-02-14 19:35:12 fail: Gabi.Worker.Jobs.CatalogSeedJobExecutor[0]
  Sources file not found: sources_v2.yaml

2026-02-14 19:35:12 warn: Gabi.Postgres.Repositories.JobQueueRepository[0]
  Job f3c7d385-eaa2-422b-aeba-a3b70cb2efec failed, will retry.
  Error: Sources file not found at sources_v2.yaml

2026-02-14 19:37:16 fail: Gabi.Worker.Jobs.CatalogSeedJobExecutor[0]
  Sources file not found: sources_v2.yaml

2026-02-14 19:37:16 warn: Gabi.Postgres.Repositories.JobQueueRepository[0]
  Job f3c7d385-eaa2-422b-aeba-a3b70cb2efec failed, will retry.
  Error: Sources file not found at sources_v2.yaml
```

## Causa Raiz

### Problema 1: GABI_SOURCES_PATH não foi passado corretamente para o Worker

No script `e2e-zero-kelvin.sh`, a função `start_apps()`:

```bash
export GABI_SOURCES_PATH="${GABI_SOURCES_PATH:-$GABI_ROOT/sources_v2.yaml}"

dotnet run --project "$GABI_ROOT/src/Gabi.Api/Gabi.Api.csproj" --no-build --urls "http://localhost:5100" > "$GABI_ROOT/e2e-api.log" 2>&1 &
API_PID=$!
sleep 2
dotnet run --project "$GABI_ROOT/src/Gabi.Worker/Gabi.Worker.csproj" --no-build > "$GABI_ROOT/e2e-worker.log" 2>&1 &
WORKER_PID=$!
```

**Análise:**
1. O `export GABI_SOURCES_PATH` está usando a sintaxe `${VAR:-default}`, que:
   - Se `GABI_SOURCES_PATH` já existe no ambiente, mantém o valor existente
   - Se não existe, usa `$GABI_ROOT/sources_v2.yaml`
2. Se `GABI_SOURCES_PATH` já estava setado como `sources_v2.yaml` (relativo) no ambiente do usuário, o export **não sobrescreve**.
3. O Worker roda com working directory diferente (provavelmente `/home/fgamajr/dev/gabi-kimi/src/Gabi.Worker`) e não encontra `sources_v2.yaml` lá.

**Evidência:** O erro `Sources file not found: sources_v2.yaml` mostra que o valor é relativo, não absoluto.

### Problema 2: seed_runs não foi gravado

Como o executor retorna erro antes de criar a linha em `seed_runs` (linha 50-58 de `CatalogSeedJobExecutor.cs`):

```csharp
if (string.IsNullOrEmpty(sourcesPath) || !File.Exists(sourcesPath))
{
    _logger.LogError("Sources file not found: {Path}", sourcesPath ?? "(null)");
    return new JobResult
    {
        Success = false,
        ErrorMessage = $"Sources file not found at {sourcesPath ?? "GABI_SOURCES_PATH not set"}"
    };
}
```

**Consequência:**
- O código que cria `seedRun` (linhas 79-92) nunca é executado
- `seed_runs` fica vazio
- O endpoint `/api/v1/dashboard/seed/last` retorna 404 ou vazio
- O polling de seed dá timeout

### Problema 3: Discovery não roda sem seed completo

- Sem `seed_runs` concluído, não há trigger para discovery
- Mesmo que o API trigger discovery manualmente, não há links se o seed não populou `source_registry` corretamente
- No caso, `source_registry` tem 13 fontes (de alguma execução anterior ou do ambiente), mas sem `seed_runs` o sistema não sabe que o seed completou

## Source Registry: Como chegou a 13 fontes?

Possibilidades:
1. **Execução anterior:** Em algum momento anterior (outro teste, outro terminal), o seed completou e gravou as 13 fontes
2. **Outro processo:** O usuário pode ter rodado a API ou Worker antes manualmente e o seed funcionou
3. **Persistência do Docker volume:** O volume `postgres_data` não foi zerado antes deste run (mas o script faz `down -v`...)

Verificando se há migrações persistidas:

```bash
docker exec -i gabi-kimi-postgres-1 psql -U gabi -d gabi -c "SELECT COUNT(*) FROM \"__EFMigrationsHistory\";"
```

Provavelmente retorna 5 (as migrações foram aplicadas), indicando que o banco foi criado neste run. **Conclusão:** As 13 fontes são de execução anterior que não foi zerada, OU o seed rodou em algum momento sem gravar `seed_runs`.

## Correções Necessárias

### Correção 1: Garantir path absoluto para GABI_SOURCES_PATH

Alterar `scripts/e2e-zero-kelvin.sh`, linha 257:

```bash
# ANTES
export GABI_SOURCES_PATH="${GABI_SOURCES_PATH:-$GABI_ROOT/sources_v2.yaml}"

# DEPOIS (força path absoluto, sempre)
export GABI_SOURCES_PATH="$GABI_ROOT/sources_v2.yaml"
```

**Alternativa mais segura:**
```bash
unset GABI_SOURCES_PATH  # limpa valor anterior
export GABI_SOURCES_PATH="$GABI_ROOT/sources_v2.yaml"
```

### Correção 2: Garantir working directory correto para o Worker

Opção A: Rodar o Worker com working directory explícito:

```bash
(cd "$GABI_ROOT" && dotnet run --project src/Gabi.Worker/Gabi.Worker.csproj --no-build) > "$GABI_ROOT/e2e-worker.log" 2>&1 &
```

Opção B: Passar o path absoluto sempre (já corrigido acima).

### Correção 3: Melhorar logging do Worker

Adicionar log do path resolvido em `CatalogSeedJobExecutor.ResolveSourcesPath()`:

```csharp
private string? ResolveSourcesPath()
{
    var envPath = Environment.GetEnvironmentVariable("GABI_SOURCES_PATH");
    if (!string.IsNullOrEmpty(envPath))
    {
        _logger.LogDebug("GABI_SOURCES_PATH from env: {Path}", envPath);
        return envPath;
    }
    var configPath = _configuration["GABI_SOURCES_PATH"];
    _logger.LogDebug("GABI_SOURCES_PATH from config: {Path}", configPath ?? "(null)");
    return configPath;
}
```

### Correção 4: Zerar o banco completamente antes do teste

Garantir que `docker compose down -v` realmente apaga os volumes:

```bash
docker compose down -v --remove-orphans
docker volume ls | grep gabi-kimi | awk '{print $2}' | xargs -r docker volume rm
```

### Correção 5: Melhorar o tratamento de erro no executor

Em vez de retornar erro imediatamente, logar mais contexto:

```csharp
if (string.IsNullOrEmpty(sourcesPath) || !File.Exists(sourcesPath))
{
    var cwd = Directory.GetCurrentDirectory();
    var envValue = Environment.GetEnvironmentVariable("GABI_SOURCES_PATH");
    _logger.LogError(
        "Sources file not found. Path={Path}, CWD={Cwd}, ENV_VAR={EnvVar}, Exists={Exists}",
        sourcesPath ?? "(null)",
        cwd,
        envValue ?? "(null)",
        sourcesPath != null && File.Exists(sourcesPath));
    return new JobResult
    {
        Success = false,
        ErrorMessage = $"Sources file not found. Path={sourcesPath}, CWD={cwd}"
    };
}
```

## Próximos Passos

1. **Aplicar Correção 1** (path absoluto forçado no script E2E)
2. **Aplicar Correção 3** (melhor logging)
3. **Aplicar Correção 5** (contexto de erro completo)
4. **Rodar Zero Kelvin novamente**
5. **Verificar logs do Worker** para confirmar que `GABI_SOURCES_PATH` está correto
6. **Validar seed_runs preenchido** com `SELECT * FROM seed_runs;`
7. **Validar discovery** roda e preenche `discovered_links`
8. **Atualizar tabelas de cardinalidade** com dados reais

## Tabelas de Cardinalidade (Estado Atual)

### Estágio Seed
| Tabela | Contagem | Status |
|--------|----------|--------|
| `source_registry` | 13 | ✅ OK (de run anterior?) |
| `seed_runs` | 0 | ❌ FALHOU – job não completou |

### Estágio Discovery
| Tabela | Contagem | Status |
|--------|----------|--------|
| `discovery_runs` | 0 | ❌ Não executou |
| `discovered_links` | 0 | ❌ Não executou |

### Estágio Fetch
| Tabela | Contagem | Status |
|--------|----------|--------|
| `fetch_runs` | 1 | ⚠️ Executou mas sem input |
| `fetch_items` | 0 | ⚠️ Normal sem links |

### Estágio Ingest
| Tabela | Contagem | Status |
|--------|----------|--------|
| `documents` | 0 | ⚠️ Normal sem fetch items |

## Conclusão

O Zero Kelvin **falhou** por causa de um problema de configuração de ambiente:
- A variável `GABI_SOURCES_PATH` não foi passada corretamente (ou foi passada como path relativo)
- O Worker não encontrou `sources_v2.yaml` e o seed falhou
- Sem seed completo, discovery não roda
- Sem discovery, fetch e ingest ficam vazios

As correções são simples (forçar path absoluto no script) e devem resolver o problema.

---

## Atualização: Correção Zero Kelvin Pipeline (Hangfire + job_registry)

Data: 2026-02-15

### Diagnóstico (cadeia de falhas)

- **Migration AddJobRegistry incompleta:** Faltava `20260215000000_AddJobRegistry.Designer.cs` e a entidade `JobRegistryEntity` não estava em `GabiDbContextModelSnapshot.cs`.
- **Efeito:** A tabela `job_registry` não era criada ao rodar as migrações.
- **Consequência:** `HangfireJobQueueRepository.EnqueueAsync()` falhava em `_context.JobRegistry.Add()` → `BackgroundJob.Enqueue()` nunca era chamado → `hangfire.job` vazio → Worker (Hangfire Server) não processava jobs → `CatalogSeedJobExecutor` e demais executores não rodavam → `seed_runs=0`, `discovery_runs=0`, etc.

### Por que source_registry=13?

O `PostgreSqlSourceCatalogService` faz no construtor um fire-and-forget `InitializeAsync()` que carrega as 13 fontes do YAML direto no banco. Isso é independente do job de seed via Hangfire.

### Correções aplicadas

1. **Criado** `src/Gabi.Postgres/Migrations/20260215000000_AddJobRegistry.Designer.cs`: partial class `AddJobRegistry` com `[DbContext(typeof(GabiDbContext))]`, `[Migration("20260215000000_AddJobRegistry")]` e `BuildTargetModel` (comentário, padrão igual a AddSeedRuns).
2. **Atualizado** `src/Gabi.Postgres/Migrations/GabiDbContextModelSnapshot.cs`: adicionado bloco `modelBuilder.Entity("Gabi.Postgres.Entities.JobRegistryEntity", ...)` com ToTable("job_registry"), HasKey(JobId), todas as propriedades (JobId, HangfireJobId, SourceId, JobType, Status, CreatedAt, StartedAt, CompletedAt, ErrorMessage, ProgressPercent, ProgressMessage) e os 4 índices (SourceId, JobType, CreatedAt, Status).
3. **Build:** `dotnet build` da API e do Worker concluído com sucesso (0 erros).

### Verificação pendente

- Rodar E2E Zero Kelvin: `./scripts/e2e-zero-kelvin.sh`
- Após o E2E, conferir: `job_registry` ≥1 row, `hangfire.job` ≥1 row, `seed_runs` ≥1, `source_registry`=13, `discovery_runs` ≥1, `discovered_links` >0.

---

**Referências:**
- `scripts/e2e-zero-kelvin.sh` linha 257
- `src/Gabi.Worker/Jobs/CatalogSeedJobExecutor.cs` linhas 50-58, 153-159
- Logs: `e2e-worker.log` (grep "Sources file")
- Banco: `ingest_jobs` job `catalog_seed` com erro
- Migration: `src/Gabi.Postgres/Migrations/20260215000000_AddJobRegistry.cs` + `.Designer.cs`
- Snapshot: `src/Gabi.Postgres/Migrations/GabiDbContextModelSnapshot.cs` (JobRegistryEntity)

---

## Atualização: Correção Zero Kelvin Pipeline (Hangfire + job_registry)

Data: 2026-02-15

### Diagnóstico (cadeia de falhas)

- **Migration AddJobRegistry incompleta:** Faltava `20260215000000_AddJobRegistry.Designer.cs` e a entidade `JobRegistryEntity` não estava em `GabiDbContextModelSnapshot.cs`.
- **Efeito:** A tabela `job_registry` não era criada ao rodar as migrações.
- **Consequência:** `HangfireJobQueueRepository.EnqueueAsync()` falhava em `_context.JobRegistry.Add()` → `BackgroundJob.Enqueue()` nunca era chamado → `hangfire.job` vazio → Worker (Hangfire Server) não processava jobs → `CatalogSeedJobExecutor` e demais executores não rodavam → `seed_runs=0`, `discovery_runs=0`, etc.

### Por que source_registry=13?

O `PostgreSqlSourceCatalogService` faz no construtor um fire-and-forget `InitializeAsync()` que carrega as 13 fontes do YAML direto no banco. Isso é independente do job de seed via Hangfire.

### Correções aplicadas

1. **Criado** `src/Gabi.Postgres/Migrations/20260215000000_AddJobRegistry.Designer.cs`: partial class AddJobRegistry com atributos e BuildTargetModel (padrão AddSeedRuns).
2. **Atualizado** `GabiDbContextModelSnapshot.cs`: adicionado bloco JobRegistryEntity com ToTable("job_registry"), HasKey(JobId), propriedades e 4 índices (SourceId, JobType, CreatedAt, Status).
3. **Build:** dotnet build da API e do Worker concluído com sucesso (0 erros).

### Verificação pendente

- Rodar E2E Zero Kelvin: ./scripts/e2e-zero-kelvin.sh
- Após o E2E, conferir: job_registry ≥1 row, hangfire.job ≥1 row, seed_runs ≥1, source_registry=13, discovery_runs ≥1, discovered_links >0.

---

## Discovery Timeout – Investigação e melhoria (2026-02-15)

### Sintoma
- Seed: OK (seed_runs=5).
- Discovery: timeout 120s; discovery_runs=0, discovered_links=0.

### Fluxo esperado
1. E2E chama `POST /api/v1/dashboard/sources/tcu_acordaos/refresh` (trigger_discovery).
2. `DashboardService.RefreshSourceAsync` cria job `JobType = "source_discovery"` com `Payload["discoveryConfig"] = source.DiscoveryConfig` e chama `IJobQueueRepository.EnqueueAsync` (Hangfire).
3. Worker (Hangfire Server) processa o job → `GabiJobRunner.RunAsync` → `JobPayloadParser.ParseDiscoveryConfigFromPayload(payloadJson)` → `SourceDiscoveryJobExecutor.ExecuteAsync` → `DiscoveryEngine.DiscoverAsync` → grava em `discovery_runs` e `discovered_links`.
4. O script faz polling em `GET /api/v1/dashboard/sources/{sourceId}/discovery/last` até status completed/partial/failed ou timeout.

### Possíveis causas do timeout
1. **Job de discovery não enfileirado** – ex.: refresh retorna 404 (source não encontrada).
2. **Job enfileirado na fila "default"** – Worker escuta seed, discovery, fetch, ingest, default; se todos os jobs caírem em default, discovery pode ficar atrás de outros.
3. **Job roda mas falha antes de gravar** – exceção em `GabiJobRunner` ou no executor antes de inserir em `discovery_runs` (ex.: DiscoveryConfig vazio/null, exceção em `DiscoverAsync`).
4. **Job trava** – ex.: `DiscoverAsync` demora >120s (ex.: muitos anos em url_pattern, I/O lento).

### Checklist de debug
- **API:** `grep -i "Enqueued refresh job.*tcu_acordaos" e2e-api.log` → confirma se o job foi enfileirado.
- **Worker:** `grep -i "source_discovery\|Starting discovery\|Discovery completed\|Discovery job failed" e2e-worker.log` → confirma se o job rodou e se completou ou falhou.
- **Banco:** `SELECT "JobId", "JobType", "SourceId", "Status", "ErrorMessage" FROM job_registry WHERE "JobType" = 'source_discovery';` → ver se há job failed/pending e mensagem de erro.
- **DiscoveryConfig:** `SELECT "Id", "DiscoveryConfig" FROM source_registry WHERE "Id" = 'tcu_acordaos';` → conferir se strategy/url/template estão preenchidos.

### Correção aplicada: filas por tipo de job
- **HangfireJobQueueRepository** passou a usar `IBackgroundJobClient.Create(..., new EnqueuedState(queue))` com fila por tipo:
  - `catalog_seed` → fila **seed**
  - `source_discovery` → fila **discovery**
  - `fetch` → fila **fetch**
  - `ingest` → fila **ingest**
  - demais → fila **default**
- Objetivo: jobs de discovery irem para a fila "discovery", que o Worker já consome, evitando ficar atrás de outros na mesma fila.

### Próximos passos (se o timeout continuar)
1. Rodar E2E de novo e inspecionar logs + job_registry.
2. Se o job não aparecer no Worker: checar se a API está realmente enfileirando (log "Enqueued refresh job") e se o Hangfire Server está ativo.
3. Se o job aparecer como failed em job_registry: usar ErrorMessage e stack no Worker para corrigir (ex.: DiscoveryConfig, exceção em DiscoverAsync).
4. Se o job ficar pending: verificar se o Worker está processando a fila "discovery" (configuração `Queues = new[] { "seed", "discovery", "fetch", "ingest", "default" }` no Worker).
