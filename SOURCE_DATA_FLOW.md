# GABI Source Data Flow (by source)

Este arquivo explica o fluxo de dados ponta a ponta por source, desde `sources_v2.yaml` até `documents`.

## 1) Fluxo geral (caixinhas)

```mermaid
flowchart TD
  A[sources_v2.yaml\n(source.identity/discovery/fetch/parse/pipeline)] --> B[CatalogSeedJobExecutor]
  B --> C[source_registry\nDiscoveryStrategy + DiscoveryConfig(JSONB)]

  C --> D[Dashboard/API Refresh\ncria job source_discovery]
  D --> E[job_registry\njob_type=source_discovery + payload]
  E --> F[GabiJobRunner]
  F --> G[SourceDiscoveryJobExecutor]
  G --> H[DiscoveryEngine]

  H --> I{DiscoveryAdapterRegistry\nresolve por strategy}
  I --> I1[static_url]
  I --> I2[url_pattern]
  I --> I3[web_crawl]
  I --> I4[api_pagination]

  I3 --> I3a[driver: default HttpClient]
  I3 --> I3b[driver: curl_html_v1]
  I4 --> I4a[driver: generic]
  I4 --> I4b[driver: camara_api_v1\nendpoint_template + year range]

  I1 --> J[DiscoveredSource[]]
  I2 --> J
  I3a --> J
  I3b --> J
  I4a --> J
  I4b --> J

  J --> K[discovered_links\nbulk upsert]
  K --> L[fetch_items\nEnsurePendingForLinksAsync]
  G --> M[discovery_runs\nstatus/links_total/errors]

  L --> N[job fetch]
  N --> O[FetchJobExecutor\nHTTP streaming + CSV row-by-row]
  O --> P[documents\nraw SQL insert em batch]
  O --> Q[fetch_runs\nstatus/items/docs/capped]
```

## 2) Fluxo textual (grafo simples)

```text
graph GABI {
  sources_v2.yaml -> source_registry
  source_registry + refresh(source_id) -> job_registry(source_discovery)
  job_registry -> SourceDiscoveryJobExecutor
  SourceDiscoveryJobExecutor -> DiscoveryEngine(strategy)
  DiscoveryEngine -> Adapter(strategy, driver)
  Adapter -> DiscoveredSource(url, metadata, discovered_at)
  DiscoveredSource -> discovered_links
  discovered_links -> fetch_items(pending)
  discovery job -> discovery_runs

  fetch_items(pending|failed) -> FetchJobExecutor
  FetchJobExecutor -> HTTP stream (ResponseHeadersRead)
  HTTP stream -> CsvStreamingParser(row by row)
  row + parseConfig(transforms) -> DocumentEntity
  DocumentEntity(batch) -> documents
  fetch job -> fetch_runs
}
```

## 3) Dados por fase (o que entra e sai)

## 3.1 Seed
- Entrada: `sources_v2.yaml`.
- Saída principal: `source_registry`.
- Campos-chave persistidos:
  - `Id`
  - `DiscoveryStrategy`
  - `DiscoveryConfig` (JSONB; inclui `strategy`, `driver`, `rules`, `http`, `endpoint_template`, etc.)
  - `Enabled`

## 3.2 Discovery enqueue/runner
- Entrada: `source_id` (API dashboard refresh).
- Saída intermediária:
  - `job_registry` (`JobType=source_discovery`, payload com `discoveryConfig`).
- Runner resolve `DiscoveryConfig` do payload e envia ao `DiscoveryEngine`.

## 3.3 Discovery adapters
- Contrato de saída: `DiscoveredSource`:
  - `Url`
  - `SourceId`
  - `Metadata` (ex.: `strategy`, `driver`, `year`, `api_page`, `crawl_depth`, `parent_url`)
  - `DiscoveredAt`

## 3.4 Discovery persistência
- `discovered_links` (upsert por hash URL).
- `fetch_items` criados/garantidos em `pending` para os links persistidos.
- `discovery_runs`:
  - `Status`
  - `LinksTotal`
  - `ErrorSummary`

## 3.5 Fetch
- Entrada: `fetch_items` (`pending`/`failed`) + `source_registry.parse` (do YAML).
- Processo:
  - download HTTP com `ResponseHeadersRead`
  - parse CSV em streaming (linha a linha)
  - mapping/transforms por `parse.fields`
  - insert em `documents` (raw SQL batch)
- Saída:
  - `documents`
  - `fetch_runs` (status, itens, docs, capped, erros)

## 4) Matriz de strategy/adapter/driver

| Strategy | Adapter | Driver | Config chave |
|---|---|---|---|
| `static_url` | `StaticUrlDiscoveryAdapter` | n/a | `url` |
| `url_pattern` | `UrlPatternDiscoveryAdapter` | n/a | `template`, `parameters.year` |
| `web_crawl` | `WebCrawlDiscoveryAdapter` | default | `root_url`, `rules.link_selector`, `rules.asset_selector`, `rules.pagination_param` |
| `web_crawl` | `WebCrawlDiscoveryAdapter` | `curl_html_v1` | igual ao acima + `driver: curl_html_v1` |
| `api_pagination` | `ApiPaginationDiscoveryAdapter` | generic | `endpoint`/`url` |
| `api_pagination` | `ApiPaginationDiscoveryAdapter` | `camara_api_v1` | `driver`, `parameters.start_year`, `endpoint_template` |

## 5) Sources com adapters novos

## 5.1 `tcu_publicacoes`
- `strategy: web_crawl`
- `driver: curl_html_v1`
- Motivo: bypass de challenge anti-bot observado no modo HTTP padrão.
- Resultado runtime validado: discovery com links reais (não 0).

## 5.2 `camara_leis_ordinarias`
- `strategy: api_pagination`
- `driver: camara_api_v1`
- Agora plugável por YAML com `endpoint_template` (não fixo em código).
- Range anual vem de `parameters.start_year`.

## 6) Invariantes importantes
- Se `links_total > 0`, discovery deve materializar `fetch_items` para links persistidos.
- `driver` e configs extras do YAML devem sobreviver no payload de job (`JobPayloadParser`).
- Source sem adapter suportado deve falhar explicitamente na validação de startup (não sucesso silencioso).

## 7) Onde olhar no código
- Seed: `src/Gabi.Worker/Jobs/CatalogSeedJobExecutor.cs`
- Discovery executor: `src/Gabi.Worker/Jobs/SourceDiscoveryJobExecutor.cs`
- Engine/registry:
  - `src/Gabi.Discover/DiscoveryEngine.cs`
  - `src/Gabi.Discover/DiscoveryAdapterRegistry.cs`
- Adapters:
  - `src/Gabi.Discover/WebCrawlDiscoveryAdapter.cs`
  - `src/Gabi.Discover/ApiPaginationDiscoveryAdapter.cs`
  - `src/Gabi.Discover/StaticUrlDiscoveryAdapter.cs`
  - `src/Gabi.Discover/UrlPatternDiscoveryAdapter.cs`
- Fetch executor: `src/Gabi.Worker/Jobs/FetchJobExecutor.cs`
- Payload parser: `src/Gabi.Postgres/JobPayloadParser.cs`
