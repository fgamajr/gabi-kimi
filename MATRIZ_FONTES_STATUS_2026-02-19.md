# Matriz de Fontes e Evidência Runtime

Data: 2026-02-19  
Base de evidência: `ZERO_KELVIN_FULL_REPORT_2026-02-18.md` + status de implementação em `sources_v2.yaml` e código (`ApiPaginationDiscoveryAdapter`, `WebCrawlDiscoveryAdapter`, `FetchJobExecutor`).

## Legenda de status
- `PASS`: evidência runtime recente de materialização esperada para a fase atual.
- `WARN`: evidência runtime recente com degradação conhecida (sem bloquear totalmente a suite).
- `SEM_RUN_RECENTE`: fonte configurada/implementada, sem evidência runtime recente no último full report.

## Matriz por fonte

| Fonte | Strategy | Driver | Fetch Strategy | Status Evidência | Última evidência | Notas |
|---|---|---|---|---|---|---|
| `tcu_acordaos` | `url_pattern` | n/a | csv | PASS | 2026-02-18 | 35 links, 35 fetch_items, cap 20k docs no run full. |
| `tcu_normas` | `static_url` | n/a | csv | PASS | 2026-02-18 | 1 link, ingest pesado; principal pressão de memória. |
| `tcu_sumulas` | `static_url` | n/a | csv | PASS | 2026-02-18 | 1 link, materialização estável. |
| `tcu_jurisprudencia_selecionada` | `static_url` | n/a | csv | PASS | 2026-02-18 | 1 link, alto volume de docs no fetch. |
| `tcu_resposta_consulta` | `static_url` | n/a | csv | PASS | 2026-02-18 | 1 link, estável. |
| `tcu_informativo_lc` | `static_url` | n/a | csv | PASS | 2026-02-18 | 1 link, estável. |
| `tcu_boletim_jurisprudencia` | `static_url` | n/a | csv | PASS | 2026-02-18 | 1 link, estável. |
| `tcu_boletim_pessoal` | `static_url` | n/a | csv | PASS | 2026-02-18 | 1 link, estável. |
| `tcu_publicacoes` | `web_crawl` | `curl_html_v1` | `link_only` | PASS | 2026-02-18 | 290 links, 290 `skipped_format` (esperado na fase discovery/link catalog). |
| `tcu_notas_tecnicas_ti` | `web_crawl` | `curl_html_v1` | `link_only` | PASS | 2026-02-18 | 16 links; stall mitigado por progresso por `fetch_items`. |
| `tcu_btcu_administrativo` | `api_pagination` | `btcu_api_v1` | `link_only` | PASS | 2026-02-18 | 2121 links descobertos (catálogo de PDFs). |
| `tcu_btcu_especial` | `api_pagination` | `btcu_api_v1` | `link_only` | PASS | 2026-02-18 | 286 links descobertos. |
| `tcu_btcu_controle_externo` | `api_pagination` | `btcu_api_v1` | `link_only` | PASS | 2026-02-18 | 1397 links descobertos. |
| `tcu_btcu_deliberacoes` | `api_pagination` | `btcu_api_v1` | `link_only` | PASS | 2026-02-18 | 1732 links descobertos. |
| `tcu_btcu_deliberacoes_extra` | `api_pagination` | `btcu_api_v1` | `link_only` | PASS | 2026-02-18 | 5507 links descobertos. |
| `camara_leis_ordinarias` | `api_pagination` | `camara_api_v1` | `link_only` | WARN | 2026-02-18 | Materializa links (42k), mas janela de teste marcou `discovery_not_materialized` por timing. |
| `camara_projetos_lei_complementar` | `api_pagination` | `camara_api_v1` | `link_only` | SEM_RUN_RECENTE | n/a | Implementada em YAML/código, sem evidência no último full report. |
| `camara_propostas_emenda_constitucional` | `api_pagination` | `camara_api_v1` | `link_only` | SEM_RUN_RECENTE | n/a | Implementada em YAML/código, sem evidência no último full report. |
| `camara_medidas_provisorias` | `api_pagination` | `camara_api_v1` | `link_only` | SEM_RUN_RECENTE | n/a | Implementada em YAML/código, sem evidência no último full report. |
| `camara_projetos_decreto_legislativo` | `api_pagination` | `camara_api_v1` | `link_only` | SEM_RUN_RECENTE | n/a | Implementada em YAML/código, sem evidência no último full report. |
| `camara_projetos_resolucao` | `api_pagination` | `camara_api_v1` | `link_only` | SEM_RUN_RECENTE | n/a | Implementada em YAML/código, sem evidência no último full report. |
| `camara_projetos_lei_conversao` | `api_pagination` | `camara_api_v1` | `link_only` | SEM_RUN_RECENTE | n/a | Implementada em YAML/código, sem evidência no último full report. |
| `senado_legislacao_leis_ordinarias` | `api_pagination` | `senado_legislacao_api_v1` | `link_only` | SEM_RUN_RECENTE | n/a | Driver implementado e validado pontualmente, faltando evidência no full report consolidado. |
| `senado_legislacao_leis_complementares` | `api_pagination` | `senado_legislacao_api_v1` | `link_only` | SEM_RUN_RECENTE | n/a | Configurada; pendente de zero-kelvin targeted/full com evidência. |
| `senado_legislacao_decretos_lei` | `api_pagination` | `senado_legislacao_api_v1` | `link_only` | SEM_RUN_RECENTE | n/a | Configurada; pendente de evidência runtime recente. |
| `senado_legislacao_leis_delegadas` | `api_pagination` | `senado_legislacao_api_v1` | `link_only` | SEM_RUN_RECENTE | n/a | Configurada; pendente de evidência runtime recente. |
| `stf_decisoes` | `static_url` | n/a | csv | WARN | 2026-02-18 | No snapshot do full report apareceu 0 links/0 docs; precisa verificação de URL/fonte. |
| `stj_acordaos` | `url_pattern` | n/a | csv | WARN | 2026-02-18 | No snapshot do full report apareceu 0 links/0 docs; precisa verificação de config/expansão. |

## Resumo agregado
- Total de fontes catalogadas no YAML: **28**.
- Com evidência runtime recente no full report: **18**.
- `PASS`: **15**.
- `WARN`: **3** (`camara_leis_ordinarias`, `stf_decisoes`, `stj_acordaos`).
- `SEM_RUN_RECENTE`: **10** (expansão Câmara + bloco Senado).

## Gap para fechar objetivo "catalogar todos os links na discovery"
1. Rodar `targeted/full` para as 10 fontes `SEM_RUN_RECENTE` e transformar em `PASS/WARN` com evidência.
2. Fechar os dois `WARN` estruturais (`stf_decisoes`, `stj_acordaos`) para voltar a materializar links.
3. Revalidar `camara_leis_ordinarias` em janela maior de observação para remover falso `discovery_not_materialized`.
