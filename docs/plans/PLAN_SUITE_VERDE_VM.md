# Plano: Suite 100% Verde na VM Ubuntu (Parallels)

**Objetivo:** Deixar a suíte completa de testes do GABI (incluindo Zero Kelvin e Reliability Lab) 100% verde na VM Ubuntu 24.04 com Docker estável.

**Contexto:** O build já está verde. Persistem 15 falhas de teste, agrupadas em três frentes: isolamento de dados nos testes do Postgres, 400 Bad Request no Zero Kelvin e flakiness no teste de API do Dashboard.

---

## 1. Isolar dados nos testes do Postgres

### Problema

Os testes que usam `[Collection("Postgres")]` compartilham um único container PostgreSQL ([PostgresFixture](tests/Gabi.Postgres.Tests/PostgresFixture.cs)). Vários testes inserem na tabela `source_registry` com o **mesmo ID** (ex.: `TestSourceId = "test_source_docs"` em [DocumentRepositoryTests](tests/Gabi.Postgres.Tests/DocumentRepositoryTests.cs), ou fontes fixas em [FetchItemRepositoryTests](tests/Gabi.Postgres.Tests/FetchItemRepositoryTests.cs), [JobQueueRepositoryHashTests](tests/Gabi.Postgres.Tests/JobQueueRepositoryHashTests.cs), [SourceDiscoveryJobExecutorMetadataTests](tests/Gabi.Postgres.Tests/SourceDiscoveryJobExecutorMetadataTests.cs)). Quando mais de um teste roda (em sequência ou em paralelo), ocorre **duplicate key value violates unique constraint "PK_source_registry"**.

### Opções de solução

| Abordagem | Prós | Contras |
|-----------|------|---------|
| **A) SourceId único por teste** | Simples; sem mudar fixture. | Requer passar `sourceId` em todos os testes que criam fonte; possível conflito se dois testes rodarem ao mesmo tempo no mesmo DB. |
| **B) SourceId único por test class (Guid ou nome)** | Isola por classe; baixo risco de colisão. | Cada classe deve gerar um prefixo único (ex.: `$"{Guid.NewGuid():N}"` ou `GetType().Name`) e usar em todos os `SourceRegistryEntity` e entidades relacionadas. |
| **C) Limpeza explícita no fixture (TRUNCATE entre classes)** | Estado limpo por classe. | Ordem de execução das classes não é garantida; TRUNCATE pode quebrar testes que rodam em paralelo. |
| **D) Um container/DB por classe de teste** | Isolamento total. | Mais lento e mais recurso; exige uma collection por projeto ou por classe. |

**Recomendação:** **B** — usar um `sourceId` único por test class (ex.: `$"docs_test_{Guid.NewGuid():N}"` no construtor de `DocumentRepositoryTests` e passar para todos os testes). Aplicar o mesmo padrão em `FetchItemRepositoryTests`, `JobQueueRepositoryHashTests`, `SourceDiscoveryJobExecutorMetadataTests` e em qualquer outro que insira em `source_registry`. Garantir que todas as entidades dependentes (links, documents, fetch_items, etc.) usem esse mesmo `sourceId`.

### Arquivos principais

- [tests/Gabi.Postgres.Tests/PostgresFixture.cs](tests/Gabi.Postgres.Tests/PostgresFixture.cs) — fixture compartilhada (manter; não criar um DB por teste).
- [tests/Gabi.Postgres.Tests/DocumentRepositoryTests.cs](tests/Gabi.Postgres.Tests/DocumentRepositoryTests.cs) — substituir `TestSourceId` constante por campo gerado no construtor.
- [tests/Gabi.Postgres.Tests/FetchItemRepositoryTests.cs](tests/Gabi.Postgres.Tests/FetchItemRepositoryTests.cs) — `CreateTestSource()` ou equivalente deve usar ID único por instância.
- [tests/Gabi.Postgres.Tests/JobQueueRepositoryHashTests.cs](tests/Gabi.Postgres.Tests/JobQueueRepositoryHashTests.cs) — idem.
- [tests/Gabi.Postgres.Tests/SourceDiscoveryJobExecutorMetadataTests.cs](tests/Gabi.Postgres.Tests/SourceDiscoveryJobExecutorMetadataTests.cs) — idem.
- [tests/Gabi.Postgres.Tests/EmbedAndIndexJobExecutorTests.cs](tests/Gabi.Postgres.Tests/EmbedAndIndexJobExecutorTests.cs) — usa InMemory; se falha por outro motivo (ex.: assertion), tratar à parte.

### Verificação

Após as mudanças: `dotnet test tests/Gabi.Postgres.Tests --no-build` deve passar todos os 72 testes.

---

## 2. Investigar o 400 no Zero Kelvin

### Problema

Os testes `Pipeline_ShouldRemainStable(100)` e `Pipeline_ShouldRemainStable(1000)` em [ZeroKelvinTests.cs](tests/System/Gabi.System.Tests/ZeroKelvinTests.cs) falham com **400 Bad Request**. O fluxo é: `EnvironmentManager` sobe Postgres/Redis/ES via Testcontainers → `ZeroKelvinWebApplicationFactory` inicia a API com essa conexão → [PipelineRunner](tests/System/Gabi.ZeroKelvinHarness/Pipeline/PipelineRunner.cs) chama `TriggerSeedAsync` (POST `/api/v1/dashboard/seed`), espera seed completar, depois `TriggerPhaseAsync` para `tcu_sumulas` (discovery, fetch, ingest). O primeiro `EnsureSuccessStatusCode()` que falha é reportado como “Response status code does not indicate success: 400 (Bad Request)”.

### Hipóteses

1. **Seed não roda / fonte não existe**  
   O seed é enfileirado via Hangfire (job `catalog_seed`). No teste **só a API** está em processo; o **Worker** (que executa `CatalogSeedJobExecutor`) não está rodando. O job fica enqueued e nunca é processado → `source_registry` vazio → ao disparar discovery para `tcu_sumulas`, o backend pode responder 400 ou 404 se a fonte não existir.

2. **Caminho do YAML**  
   [CatalogSeedJobExecutor](src/Gabi.Worker/Jobs/CatalogSeedJobExecutor.cs) resolve o path de `sources_v2.yaml` por `GABI_SOURCES_PATH` ou config. Na factory do Zero Kelvin não há `Gabi:SourcesPath` nem content root apontando para o repositório; em processo de teste o working directory pode não ser a raiz do repo, então o Worker (se fosse rodado) poderia não achar o arquivo.

3. **Payload ou validação**  
   [PipelineRunner](tests/System/Gabi.ZeroKelvinHarness/Pipeline/PipelineRunner.cs) envia para discovery/fetch body `new { max_docs_per_source = config.MaxDocs }`. Se o endpoint esperar outro formato (ex.: snake_case vs camelCase), pode devolver 400.

4. **Ordem das chamadas**  
   O endpoint [POST /api/v1/dashboard/sources/{sourceId}/phases/{phase}](src/Gabi.Api/Program.cs) retorna `Results.NotFound(result)` quando `result.Success` é false (fonte não encontrada). Se em algum caminho o código devolver 400 em vez de 404, será preciso inspecionar o handler e o `DashboardService.StartPhaseAsync`.

### Próximos passos (investigação)

1. **Capturar resposta exata do 400**  
   No teste ou em `PipelineRunner`, em vez de `EnsureSuccessStatusCode()`, logar/capturar: status code, headers, body. Isso dirá se o 400 vem de validação de modelo, rate limit ou outro motivo.

2. **Garantir que o seed rode no cenário Zero Kelvin**  
   - **Opção A:** Executar o seed **síncrono** no teste: após `TriggerSeedAsync`, invocar diretamente `CatalogSeedJobExecutor.ExecuteAsync` (ou um helper que leia `sources_v2.yaml` da raiz do repo e persista em `source_registry`) usando o mesmo `GabiDbContext` da API, depois continuar com discovery/fetch/ingest.  
   - **Opção B:** Configurar a factory para apontar `Gabi:SourcesPath` (ou `GABI_SOURCES_PATH`) para o path absoluto de `sources_v2.yaml` na raiz do repo e registrar/executar o Worker em processo (Hangfire server + job execution no mesmo processo). Mais pesado, mas fiel ao fluxo real.

3. **Confirmar presença de `tcu_sumulas`**  
   O arquivo [sources_v2.yaml](sources_v2.yaml) define `tcu_sumulas`. Se o seed for executado com esse YAML, a fonte existirá; caso contrário, discovery para `tcu_sumulas` falhará (404/400).

4. **Validar payload**  
   Verificar na API se o modelo `StartPhaseRequest` espera `max_docs_per_source` ou `MaxDocsPerSource` e se o JSON enviado está correto.

### Arquivos principais

- [tests/System/Gabi.System.Tests/ZeroKelvinTests.cs](tests/System/Gabi.System.Tests/ZeroKelvinTests.cs) — configura `SourceId = "tcu_sumulas"`.
- [tests/System/Gabi.System.Tests/ZeroKelvinWebApplicationFactory.cs](tests/System/Gabi.System.Tests/ZeroKelvinWebApplicationFactory.cs) — config da API; hoje não define `Gabi:SourcesPath` nem executa Worker.
- [tests/System/Gabi.ZeroKelvinHarness/Pipeline/PipelineRunner.cs](tests/System/Gabi.ZeroKelvinHarness/Pipeline/PipelineRunner.cs) — chamadas HTTP; ponto ideal para logar status/body em falha.
- [src/Gabi.Worker/Jobs/CatalogSeedJobExecutor.cs](src/Gabi.Worker/Jobs/CatalogSeedJobExecutor.cs) — seed que popula `source_registry` a partir do YAML.
- [src/Gabi.Api/Program.cs](src/Gabi.Api/Program.cs) (linha ~494) — endpoint phases; retorna Ok ou NotFound.

### Verificação

Após correções: `dotnet test tests/System/Gabi.System.Tests --filter "FullyQualifiedName~ZeroKelvinTests" --no-build` deve passar os 3 testes (incluindo os dois `Pipeline_ShouldRemainStable`).

---

## 3. Estabilizar o teste de API do Dashboard

### Problema

O teste **DashboardStrictCoverageFallbackTests** (ex.: `TriggerDiscovery_WhenSourceHasPipelineConfigStrictTrue_EnqueuesJobWithStrictCoverageTrue`) falha intermitentemente. A causa provável é uso de **connection string de ambiente**: se `ConnectionStrings__Default` estiver definido no ambiente (ex.: outro teste ou shell), a API pode configurar Hangfire/Postgres real e tentar conectar a 127.0.0.1:5432, gerando falha (Npgsql) em vez de usar apenas o InMemory do [CustomWebApplicationFactory](tests/Gabi.Api.Tests/CustomWebApplicationFactory.cs).

Já existe em CustomWebApplicationFactory a linha `["ConnectionStrings:Default"] = ""` para evitar que a config use um connection string real. A falha pode ser:

- Ordem de fontes de configuração (env var sobrescrevendo o in-memory).
- Outro teste ou processo definindo `ConnectionStrings__Default` e vazando para este teste.
- Factory compartilhada (`IClassFixture<CustomWebApplicationFactory>`) com estado residual.

### Próximos passos

1. **Garantir que ConnectionStrings:Default tenha precedência no teste**  
   Em `ConfigureAppConfiguration`, garantir que a coleção in-memory seja a **última** adicionada (ou usar `config.AddInMemoryCollection` com chave explícita e verificar que não há outra fonte definindo `ConnectionStrings:Default` depois). Se necessário, no início do teste (ou no construtor da factory) limpar temporariamente a env var:  
   `Environment.SetEnvironmentVariable("ConnectionStrings__Default", null);` (e restaurar no dispose/end do teste).

2. **Reprodução estável**  
   Rodar só o projeto de API com repetição:  
   `dotnet test tests/Gabi.Api.Tests --filter "FullyQualifiedName~DashboardStrictCoverageFallbackTests" --no-build -- RunConfiguration.TestSessionTimeout=60000`  
   (e, se possível, com múltiplas iterações para ver se a falha é intermitente).

3. **Isolamento por teste**  
   Se a factory for compartilhada e algum estado (ex.: conexão) vazar, considerar criar uma factory por teste (remover `IClassFixture` e instanciar `CustomWebApplicationFactory` no construtor do teste) para esse grupo de testes, aceitando custo maior de startup.

### Arquivos principais

- [tests/Gabi.Api.Tests/CustomWebApplicationFactory.cs](tests/Gabi.Api.Tests/CustomWebApplicationFactory.cs) — já define `ConnectionStrings:Default = ""`; revisar ordem de config e possível limpeza de env.
- [tests/Gabi.Api.Tests/DashboardStrictCoverageFallbackTests.cs](tests/Gabi.Api.Tests/DashboardStrictCoverageFallbackTests.cs) — usa `EnsureSourceWithStrictPipelineConfigAsync` e chama os endpoints de phases.

### Verificação

`dotnet test tests/Gabi.Api.Tests --filter "FullyQualifiedName~DashboardStrictCoverageFallbackTests" --no-build` deve passar de forma estável (várias execuções seguidas).

---

## Ordem sugerida de execução

1. **Item 3 (API Dashboard)** — mudança localizada na factory e/ou env; verificação rápida.
2. **Item 1 (Postgres)** — alterações em várias classes de teste; rodar só `Gabi.Postgres.Tests`.
3. **Item 2 (Zero Kelvin)** — investigar 400 (log de resposta, seed, YAML path) e implementar correção (seed síncrono ou Worker em processo + paths).

Ao final: `dotnet test GabiSync.sln` na raiz do repo deve reportar **0 Failed**.

---

## Referências

- [AGENTS.md](AGENTS.md) — comandos de build e teste, arquitetura.
- [tests/ReliabilityLab/README.md](tests/ReliabilityLab/README.md) — Reliability Lab e requisito Docker.
- Handover da sessão anterior (resumo das falhas: Postgres 11, Api 1, System 2, ReliabilityLab 1).
