# Plano Consolidado v4 (Stabilization Program)

Data base: 15 de fevereiro de 2026  
Atualizado em: 18 de fevereiro de 2026

## 1. Findings To Address (atualizado)

1. Discovery payload decoding inconsistente (double-encoded JSON e perda de strategy/driver/http).
2. Materialização de fetch_items já falhou em cenário real (links > 0 sem fetch_items).
3. DLQ falhava com serialização JSONB de payload/stacktrace.
4. Retry policy ruidosa/inconsistente entre Hangfire/filter/runner.
5. Drift de compose/runtime e risco de fila zumbi (jobs antigos em processing).
6. Zero-kelvin podia travar por source sem progresso.
7. tcu_publicacoes: PDF entrando em parser CSV (stall/resultado incorreto).
8. tcu_notas_tecnicas_ti: config de web crawl incompleta no YAML (driver ausente).
9. camara_leis_ordinarias: discovery sob carga sem rate-limit/retry robusto (ECONNRESET).
10. Modelagem Câmara incompleta: falta cobrir projetos + múltiplos tipos normativos.

## 2. Plano por Prioridade

### P0 (crítico)

1. Discovery Config End-to-End Robustness
- Consolidar parse/config nos caminhos API + Hangfire.
- DiscoveryEngine com adapters: static_url, url_pattern, web_crawl, api_pagination.
- Acceptance: strategy/driver/http chegam íntegros ao executor.

2. Discovery Strategy Safety
- Validar estratégias suportadas em startup.
- Estratégia sem adapter: erro explícito (não completar com 0 silencioso).
- Acceptance: capability ausente sempre vira erro claro.

3. Fetch Item Materialization Invariant
- Garantir BulkUpsertAsync -> EnsurePendingForLinksAsync sobre links persistidos.
- Regra: links_total > 0 e fetch_items = 0 => discovery_run failed com mensagem explícita.
- Acceptance: tcu_acordaos 35 links -> 35 fetch_items pending.

4. DLQ JSON + Retry->DLQ Runtime Proof
- Persistência JSONB-safe de payload/stacktrace.
- Prova runtime com job determinístico falhando até o limite de retries.
- Acceptance: entrada válida em dlq_entries + RetryCount observado = política.

### P1 (estabilidade operacional)

5. Normalize Retry Policy
- Definir uma única fonte de verdade para retry (options + filter + runtime).
- Documentar política operacional.
- Acceptance: contagem de tentativas em log bate exatamente com configuração.

6. Compose + Runtime + Queue Hygiene
- Compose coerente por profiles, healthchecks confiáveis.
- Runbook/script para limpar jobs/locks zumbis sem corromper histórico.
- Acceptance: execução nova não fica presa em pending/processing antigo.

7. Native Capped Stress Mode
- max_docs_per_source nativo com finalização graciosa em status capped.
- Acceptance: tcu_acordaos encerra em 20.000 exatos sem cancelamento forçado.

8. Zero-Kelvin Stall Cutoff (all-sources)
- Cutoff de estagnação em discovery e fetch por source.
- Se estagnar: marcar WARN com error_summary estruturado e avançar para próxima source.
- Acceptance: run all-sources conclui sem bloqueio indefinido.

9. Fixes imediatos de fontes problemáticas
- tcu_notas_tecnicas_ti: manter driver curl_html_v1.
- tcu_publicacoes: detectar PDF por content-type/extensão e marcar skipped_format.
- camara_* (api_pagination): request_delay_ms + retry com backoff/jitter para 429/502/503 e erros transitórios.
- Acceptance: sem CSV parse em PDF, menos ECONNRESET, e execução segue mesmo com degradação.

### P2 (arquitetura e observabilidade)

10. Modelagem Câmara orientada a domínio
- Separar fontes: camara_projetos, camara_leis_ordinarias, camara_leis_complementares, camara_decretos_lei, camara_leis_delegadas, etc.
- Paginação por cursor/janela temporal (não só por ano).
- Vínculo projeto->resultado normativo em metadata.
- Acceptance: cobertura do funil legislativo completo (inclusive projetos não convertidos em lei).

11. Zero-Kelvin Report Estruturado
- Relatório por source: status, docs, pico memória, erro resumido.
- Acceptance: reprodução com 1 comando e comparabilidade entre runs.

12. Memory Guardrails + Telemetry
- Logs periódicos: docs, heap, RSS, counters de truncamento/parser limits.
- Acceptance: tendência de memória visível e acionável.

## 3. Sequência de Execução (v4)

1. P0.1 -> P0.2 -> P0.3 -> P0.4
2. P1.5 -> P1.6
3. P1.8 -> P1.9
4. P1.7
5. P2.10
6. P2.11 -> P2.12
7. Full zero-kelvin all-sources com cap e relatório final

## 4. Final Verification Gate (v4)

1. tcu_acordaos: links > 0, fetch_items = links, fetch capped em 20k.
2. tcu_publicacoes: PDFs marcados skipped_format, sem stall de parser CSV.
3. tcu_notas_tecnicas_ti: discovery funcional com web_crawl quando houver alvos.
4. camara_*: discovery estável com rate-limit/retry; sem recorrência dominante de ECONNRESET.
5. Retry->DLQ E2E comprovado com contagem correta de tentativas.
6. Zero-kelvin all-sources conclui sem bloqueio indefinido e com relatório reprodutível.
7. Envelope de memória validado por source e no agregado do run.

## 5. Status Atual (snapshot)

- P0: substancialmente implementado e validado por build/testes e runtime (manter validação contínua).
- P1.9 (parcialmente concluído):
  - `tcu_publicacoes`: `PDF -> skipped_format` validado em runtime (`290/290 skipped_format`).
  - `camara_leis_ordinarias`: aplicado `request_delay_ms` + retry/backoff no adapter; ainda depende de higiene de fila para evitar bloqueio por job zumbi.
  - `tcu_notas_tecnicas_ti`: mantém discovery funcional com web_crawl (`16 links` observados em run recente).
- P1.8 (parcialmente concluído):
  - Fetch stall cutoff já gera `WARN` (`fetch_stalled`).
  - Discovery not materialized já retorna `WARN` e segue para próxima source.
- P1.6 (concluído para ambiente de teste):
  - Script `scripts/queue-hygiene.sh` criado (dry-run/apply).
  - Integrado no `tests/zero-kelvin-test.sh` antes do stress targeted.
  - Runbook operacional: `docs/operations/queue-hygiene.md`.
- Zero-kelvin all-sources (18/02/2026):
  - Status final: `PASS` (suite), `WARN` (targeted all-sources: 2 sources com warning).
  - `tcu_publicacoes`: `PASS` com `0 docs` (PDFs tratados sem stall de parser CSV).
  - `camara_leis_ordinarias`: `WARN` por `discovery_not_materialized`.
  - `tcu_notas_tecnicas_ti`: `WARN` por `fetch_stalled`.
  - Pico de memória agregado observado: `443.4 MiB` (acima do envelope alvo de 300 MiB).
- P2: iniciar após fechamento de P1.6/P1.8/P1.9.

## 6. Plano Detalhado Imediato (incorporando pontos aproveitáveis do plano revisado)

### 6.1 Item 1: camara_leis_ordinarias com `discovery_not_materialized` (causa raiz)

Objetivo:
- Eliminar não materialização por buffering total e falha parcial destrutiva.

Mudanças obrigatórias:
1. `ApiPaginationDiscoveryAdapter` em falha parcial:
- trocar exceção terminal por parada graciosa da enumeração (`yield break`) para preservar itens já descobertos.
- manter log estruturado com `source_id`, `url`, `status_code`, `attempt`.
2. `SourceDiscoveryJobExecutor` com persistência incremental:
- remover padrão “coleta tudo em memória”.
- processar/persistir em lotes (`batchSize` inicial: 1000).
- por lote: `BulkUpsertAsync` -> obter links persistidos -> `EnsurePendingForLinksAsync`.
3. `discovery_runs` em tempo real:
- criar run no início com `Status=running`.
- atualizar `LinksTotal` e progresso por lote.
- finalizar sempre em `completed` ou `failed` (nunca pendurado).
4. `GabiJobRunner` no retry:
- limpar `ErrorMessage` e `CompletedAt` ao voltar para `processing`.

Critérios de aceite:
- `camara_leis_ordinarias` não fica indefinidamente em `processing`.
- em falha parcial de API, `discovered_links` e `fetch_items` já persistidos não se perdem.
- zero-kelvin não depende de timeout cego para seguir.

### 6.2 Item 2: `tcu_notas_tecnicas_ti` com `fetch_stalled` (detector de progresso)

Objetivo:
- remover falso stall em sources que podem gerar 0 documentos (ex.: PDF-only).

Mudanças obrigatórias:
1. Stall detector do zero-kelvin:
- progresso não deve olhar apenas `documents`.
- considerar também avanço de `fetch_items` em estado final:
  - `completed`, `skipped_format`, `skipped_unchanged`, `failed`, `capped`.
2. PDF handling no fetch:
- manter `skipped_format` para PDF suportado por URL/content-type.
- ajuste de robustez:
  - URL `.pdf` com HTTP `2xx/3xx` => `skipped_format`.
  - URL `.pdf` com HTTP `4xx/5xx` => `failed_http_pdf` (não mascarar endpoint quebrado).
3. Garantir finalização de item:
- nenhum item deve ficar preso em `processing` ao final.

Critérios de aceite:
- `tcu_notas_tecnicas_ti` não termina com `fetch_stalled`.
- run termina com status final explícito e breakdown consistente.
- relatório mostra progresso por itens processados, mesmo com `docs=0`.

### 6.3 Item 3: reduzir envelope de memória (alvo <= 300 MiB) com sequência realista

Objetivo:
- reduzir pico agregado de ~443 MiB sem sobreengenharia prematura.

Sequência de implementação:
1. Primeiro ganho estrutural (esperado maior impacto):
- aplicar 6.1 (batch incremental em discovery), que remove O(N) em memória.
2. Medição pós-6.1/6.2:
- reexecutar zero-kelvin e registrar `peak_heap_mb`, `peak_rss_mb`, `peak_container_mb` por source.
3. Somente se ainda acima da meta:
- batch adaptativo no fetch (warn/critical).
- persistência bulk por lote (COPY/multi-row).
4. Safety net opcional:
- limites `.Take()` apenas onde necessário e com log explícito de truncamento.
- não aplicar limite hardcoded silencioso em consultas críticas.

Metas por estágio:
- Stage 1: <= 380 MiB.
- Stage 2: <= 330 MiB.
- Stage 3 (meta final): <= 300 MiB.

Critérios de aceite:
- `tcu_normas` conclui sem OOM.
- pico agregado cai por estágio até a meta final.
- sem regressão funcional nas fontes pequenas.

## 7. Sequência de execução imediata (operacional revisada)

1. Implementar 6.1 completo (`adapter + executor batching + runner cleanup`).
2. Implementar 6.2 completo (`stall detector por itens + regra PDF robusta`).
3. Rodar zero-kelvin targeted (`camara_leis_ordinarias`, `tcu_notas_tecnicas_ti`).
4. Rodar zero-kelvin all-sources com monitoramento de memória.
5. Só então aplicar 6.3 etapa 3/4 (otimizações adicionais), se necessário.
6. Atualizar este plano com evidência por source (`PASS/WARN/FAIL`, memória, causa).

## 8. Definição de pronto (DoD) por item

Para considerar 6.1, 6.2 e 6.3 concluídos:
1. Build e testes direcionados passam (`Discover`, `Worker`, `Postgres`, `Jobs`).
2. Zero-kelvin all-sources conclui sem intervenção manual e sem bloqueio indefinido.
3. `camara_leis_ordinarias` com `discovered_links > 0` e `fetch_items > 0` (ou `failed` explícito com links parciais preservados).
4. `tcu_notas_tecnicas_ti` sem `fetch_stalled`.
5. Pico de memória por estágio registrado e meta final <= 300 MiB atingida.
6. Evidência anexada no plano:
- query SQL de status por source,
- trecho de log com causa final,
- métrica de memória por source e agregado.
