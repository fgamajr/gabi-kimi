# Avaliação: Dashboard (user-first-view) vs API Gabi

Documento de avaliação do que o projeto de referência **user-first-view** exige em termos de contratos e endpoints, comparado ao que o Gabi já tem e ao que foi planejado.

---

## 1. O que o user-first-view realmente consome

Extraído de `dashboard-data.ts` e dos componentes (Dashboard.tsx, PipelineOverview, ActivityFeed, SourcesTable, SystemHealth).

### 1.1 Dados de estatísticas (stats)

| Campo / tipo | Uso no UI |
|--------------|-----------|
| `sources[]` | Tabela de fontes, métrica "Active Sources", cards |
| `sources[].id` | Identificador |
| `sources[].description` | Nome legível na tabela |
| `sources[].source_type` | Tipo (ex.: csv_http) |
| `sources[].enabled` | Status Active/Disabled |
| `sources[].document_count` | Coluna "Documents" |
| `total_documents` | Card "Total Documents" |
| `elasticsearch_available` | SystemHealth (Elasticsearch connected/offline) |

**Fonte no mock:** `StatsResponse` = `{ sources, total_documents, elasticsearch_available }`.  
O Dashboard também usa um `lastUpdate` (string ISO) para "Updated X ago" — pode vir do servidor ou do cliente.

### 1.2 Dados de jobs (jobs)

| Campo / tipo | Uso no UI |
|--------------|-----------|
| `sync_jobs[]` | ActivityFeed (lista de jobs recentes) |
| `sync_jobs[].source` | Nome da fonte |
| `sync_jobs[].year` | Ano (number ou string) |
| `sync_jobs[].status` | synced \| pending \| failed \| in_progress |
| `sync_jobs[].updated_at` | "X min ago" |
| `elastic_indexes` | Record<nome índice, quantidade> (opcional no mock) |
| `total_elastic_docs` | Card "Indexed Documents" |

**Fonte no mock:** `JobsResponse` = `{ sync_jobs, elastic_indexes, total_elastic_docs }`.

### 1.3 Pipeline (estágios)

| Campo / tipo | Uso no UI |
|--------------|-----------|
| `name` | harvest \| sync \| ingest \| index (chave) |
| `label` | "Harvest", "Sync", etc. |
| `description` | Texto curto sob o label |
| `count` / `total` | Barra de progresso e "X of Y documents" |
| `status` | active \| idle \| error (indicador visual) |
| `lastActivity` | "Last activity: X" |

**Fonte no mock:** array de `PipelineStage[]`.

### 1.4 Resumo de “endpoints” implícitos no reference

- **GET stats** → `StatsResponse` (sources, total_documents, elasticsearch_available).  
  Opcional: incluir `last_update` na resposta.
- **GET jobs** → `JobsResponse` (sync_jobs, elastic_indexes, total_elastic_docs).
- **GET pipeline** → array de estágios (ou mesclar em um único **GET dashboard** com stats + jobs + pipeline).

Não há no reference chamadas explícitas a “/sources” ou “/sources/:id” no Dashboard principal; a tabela de fontes usa `stats.sources`. Para detalhe de uma fonte (ex.: tela "Details"), um **GET /sources/:id** continua necessário.

---

## 2. O que o Gabi já tem (contratos e API)

### 2.1 DTOs (Gabi.Contracts.Api)

- **SourceSummaryDto:** Id, Name, Provider, Strategy, Enabled, DocumentCount (opcional).  
  Equivalente a “fonte” do stats; falta um campo explícito tipo `source_type` (pode ser Strategy ou Provider).
- **SourceDetailDto:** detalhe completo + links + metadata. OK para tela de detalhe.
- **SystemStatsDto:** Sources (lista de summary), TotalDocuments, ElasticsearchAvailable, LastUpdate.  
  Alinhado ao `StatsResponse` (LastUpdate já existe).
- **SyncJobDto:** SourceId, Year, Status, UpdatedAt. Alinhado a `sync_jobs[]` (nome de propriedade: SourceId vs source).
- **PipelineStageDto:** Name, Label, Description, Count, Total, Status, LastActivity. Alinhado ao reference.

### 2.2 Interface ISourceCatalog

- `ListSourcesAsync` → lista de SourceSummaryDto.
- `GetSourceAsync(id)` → SourceDetailDto.
- `RefreshSourceAsync(id)` → RefreshResult.
- **ListSyncJobsAsync** → lista de SyncJobDto (planejado).
- **GetSystemStatsAsync** → SystemStatsDto (planejado).
- **GetPipelineStagesAsync** → lista de PipelineStageDto (planejado).

### 2.3 Rotas expostas (Program.cs)

- GET `/api/v1/sources` → lista.
- GET `/api/v1/sources/{sourceId}` → detalhe.
- POST `/api/v1/sources/{sourceId}/refresh` → refresh.
- GET `/api/v1/jobs/{sourceId}/status` → status do job de uma fonte (IJobQueue).

**Não expostos até agora:**

- GET `/api/v1/stats` (ou equivalente).
- GET `/api/v1/jobs` (lista de todos os sync jobs + elastic_indexes + total_elastic_docs).
- GET `/api/v1/pipeline` (estágios do pipeline).

### 2.4 Implementação (PostgreSqlSourceCatalogService)

- **ListSourcesAsync**, **GetSourceAsync**, **RefreshSourceAsync** estão implementados.
- **ListSyncJobsAsync**, **GetSystemStatsAsync**, **GetPipelineStagesAsync** **não** estão implementados (só na interface).

---

## 3. Lacunas e recomendações

### 3.1 Endpoints faltando

| Endpoint sugerido | Retorno | Observação |
|-------------------|--------|------------|
| GET `/api/v1/stats` | SystemStatsDto | Fonte única para stats do dashboard (sources resumidas, total_documents, elasticsearch, last_update). |
| GET `/api/v1/jobs` | Objeto com SyncJobs + ElasticIndexes + TotalElasticDocs | Equivalente a JobsResponse. Pode ser um DTO `JobsResponseDto` ou envelope. |
| GET `/api/v1/pipeline` | PipelineStageDto[] | Estágios para o componente PipelineOverview. |

Alternativa: **GET `/api/v1/dashboard`** que devolva num único payload `{ stats, jobs, pipeline }` para reduzir round-trips e manter consistência de snapshot.

### 3.2 Contrato JobsResponse

O reference tem `elastic_indexes: Record<string, number>` e `total_elastic_docs`. No Gabi:

- SystemStatsDto já tem TotalDocuments (pode ser o mesmo que total_elastic_docs se não houver outro repositório).
- Se a UI precisar de “documentos por índice”, é necessário um DTO com um dicionário de índice → contagem; caso contrário, só TotalDocuments pode bastar.

Recomendação: definir um **JobsResponseDto** (ou ampliar o envelope de jobs) com:

- `SyncJobs: SyncJobDto[]`
- `TotalElasticDocs: long`
- `ElasticIndexes: IReadOnlyDictionary<string, long>` (opcional, se for usar por índice).

### 3.3 Nomenclatura JSON (camelCase)

O reference usa snake_case nos mocks; APIs em .NET costumam serializar em camelCase. Definir que a API responde em **camelCase** e que o frontend (React) usa camelCase evita confusão (ex.: `sourceId`, `updatedAt`, `totalDocuments`, `elasticIndexes`).

### 3.4 Nome dos estágios do pipeline

Reference: **harvest**, **sync**, **ingest**, **index**.  
Gabi (Pipeline): Discovery, Sync, Ingest, Index (ou similar). Recomendação: mapear no DTO para os nomes que o frontend já espera (harvest = primeiro estágio de “download”, ex. discovery), para não quebrar PipelineOverview.

### 3.5 Source_type na listagem

A tabela do reference usa `source_type` (ex.: csv_http). Em SourceSummaryDto temos Provider e Strategy. Decisão: usar **Strategy** como `source_type` na resposta, ou adicionar um campo explícito `SourceType` derivado (Provider + Strategy), para a coluna "Type" da tabela.

### 3.6 Implementação dos 3 métodos no PostgreSqlSourceCatalogService

Para os novos endpoints funcionarem é necessário:

- **GetSystemStatsAsync:** agregar fontes (ListSourcesAsync já existe; pode reutilizar), total de documentos (por exemplo contagem de chunks/documentos na base ou em repositório dedicado), Elasticsearch (health check ou flag), LastUpdate (última atualização conhecida).
- **ListSyncJobsAsync:** ler da fila de jobs ou tabela de histórico (ex.: IJobQueue ou repositório de jobs concluídos) e mapear para SyncJobDto (source, year, status, updated_at).
- **GetPipelineStagesAsync:** pode ser stub inicial (contagens fixas ou derivadas de agregados) até o pipeline real expor métricas; importante é retornar os 4 estágios com Name/Label/Description/Count/Total/Status/LastActivity.

---

## 4. Checklist para “dashboard igual ao reference”

- [x] **ApiRoutes:** adicionar constantes para Stats, Jobs (lista), Pipeline (ex.: `/api/v1/stats`, `/api/v1/jobs`, `/api/v1/pipeline`).
- [x] **DTO:** definir JobsResponseDto (sync_jobs + total_elastic_docs + elastic_indexes) se for usar por índice; senão, só envelope com lista de SyncJobDto + TotalElasticDocs.
- [x] **Program.cs:** registrar GET para stats, GET para jobs (lista), GET para pipeline (ou um GET dashboard agregado).
- [x] **PostgreSqlSourceCatalogService:** implementar GetSystemStatsAsync, ListSyncJobsAsync, GetPipelineStagesAsync (stub ou real conforme dados disponíveis).
- [x] **SourceSummaryDto:** garantir DocumentCount preenchido na listagem; decidir e expor source_type (Strategy ou campo dedicado).
- [x] **PipelineStageDto:** garantir nomes harvest/sync/ingest/index e mapeamento a partir do pipeline real (quando existir).
- [x] **Serialização:** confirmar camelCase para JSON (padrão em ASP.NET Core).
- [ ] **Frontend (Gabi.Web):** quando migrar para o dashboard do user-first-view, trocar mocks por chamadas a `/api/v1/stats`, `/api/v1/jobs`, `/api/v1/pipeline` (ou `/api/v1/dashboard`) e ajustar nomes de campos se necessário (camelCase).

---

## 5. Conclusão

- **Sim, dá para inferir os contratos e endpoints** necessários a partir do user-first-view: os tipos em `dashboard-data.ts` e o uso nos componentes formam um blueprint claro (stats, jobs, pipeline; opcionalmente um único endpoint dashboard).
- O que foi planejado (DTOs + métodos em ISourceCatalog) está alinhado na maior parte; faltam:
  1. **Expor** as rotas GET stats, GET jobs (lista), GET pipeline na API.
  2. **Implementar** os três métodos no PostgreSqlSourceCatalogService.
  3. **Definir** o formato de resposta de “jobs” (incluindo elastic_indexes se for usado).
  4. Pequenos ajustes (source_type na listagem, nomes dos estágios, camelCase).

Com isso, a implementação fica bem direcionada e o dashboard do reference pode ser alimentado pela API do Gabi.
