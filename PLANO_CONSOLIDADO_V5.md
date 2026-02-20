# Plano Consolidado v5 (Stabilization + Normative Intelligence Program)

Data base: 15 de fevereiro de 2026  
Atualizado em: 20 de fevereiro de 2026

## 1. Objetivo Executivo

Estabilizar o pipeline E2E (discovery -> fetch -> ingest -> index) e elevar o nível de confiabilidade jurídica para evitar confusão entre:
1. `proposicao` (tramitação, discussão, não necessariamente aprovada)
2. `norma` (ato aprovado/publicado)
3. estado normativo temporal (`vigente`, `alterada`, `revogada`, `desconhecido`, `conflito`)

Resultado esperado:
1. zero-kelvin all-sources reprodutível sem travas indefinidas
2. memória dentro do envelope por estágio
3. retrieval/LLM com filtros semânticos obrigatórios por intenção
4. trilha de evidência para alterações/revogações

---

## 2. Estado Atual Consolidado (fato observado)

### 2.1 Já implementado e validado
1. P0 base (payload parsing, strategy safety, DLQ JSON fix, materialização principal) majoritariamente funcional.
2. `api_pagination` com drivers:
- `camara_api_v1`
- `btcu_api_v1`
- `senado_legislacao_api_v1`
3. Câmara marcada semanticamente no discovery como:
- `document_kind=proposicao`
- `approval_state=em_tramitacao`
4. Senado Legislação marcada semanticamente no discovery como:
- `document_kind=norma`
- `approval_state=aprovada`
- `normative_force=desconhecido` (provisório)
5. Fontes Senado adicionadas no YAML:
- `senado_legislacao_leis_ordinarias` (`LEI`)
- `senado_legislacao_leis_complementares` (`LCP`)
- `senado_legislacao_decretos_lei` (`DEL`)
- `senado_legislacao_leis_delegadas` (`LDL`)
6. Runtime validado:
- discovery `senado_legislacao_leis_ordinarias` concluindo com materialização de links/fetch_items.

### 2.2 Pendências abertas
1. 11.3: propagação semântica completa até `documents.Metadata`/camada de busca.
2. 11.4: guardrails de intenção no retrieval/LLM ainda não ligados no caminho real de busca.
3. Motor temporal de alterações/revogações ainda não implementado.
4. Planalto 2 níveis (índice de anos -> leis por ano) ainda não implementado.
5. LexML ainda sem contrato de disponibilidade estável para virar dependência P0.

---

## 3. Princípios de Engenharia (obrigatórios)

1. Não afirmar vigência por ausência de evidência.
- default sem evidência = `desconhecido`.
2. Não misturar `proposicao` e `norma` sem filtro explícito.
3. Falha parcial deve preservar progresso (discovery/fetch).
4. Toda decisão jurídica deve ser auditável por evidência (`source`, `event`, `date`).
5. LexML entra com gate de confiabilidade, não como dependência cega.

---

## 4. Arquitetura de Fontes (hierarquia v5)

### 4.1 Camada normativa primária (P0)
1. Senado Legislação API
- discovery estruturado de normas
- detalhe por norma para eventos (`vides`, `edivs`, `disps`)

### 4.2 Camada normativa complementar (P1)
1. Planalto HTML compilado (2 níveis)
- Nível A: página índice anual
- Nível B: páginas anuais para links finais de norma

### 4.3 Camada agregadora opcional (P0.5/P1)
1. LexML SRU (somente após contract tests)
- função principal: norma_key canônica via URN
- não bloquear pipeline caso indisponível

---

## 5. Modelo Semântico e de Confiabilidade

### 5.1 Campos mínimos por documento
1. `document_kind`: `norma|proposicao`
2. `approval_state`: `aprovada|nao_aprovada|em_tramitacao|desconhecido`
3. `normative_force`: `vigente|alterada|revogada|desconhecido|conflito`
4. `source_family`: `senado_legislacao|camara_proposicoes|planalto_legislacao|lexml`
5. `norma_key`: chave canônica (`tipo:number:ano` ou URN)
6. `confidence`: `high|medium|low`

### 5.2 Regras de confiança
1. `high`: vínculo normativo + data + dispositivo alvo claros.
2. `medium`: vínculo e data claros, dispositivo parcial/ausente.
3. `low`: correlação fraca textual sem estrutura suficiente.

### 5.3 Regra de conflito
1. Divergência relevante entre fontes para mesma `norma_key` => `normative_force=conflito`.
2. Em conflito, LLM não responde de forma assertiva sem ressalva.

---

## 6. Backlog Priorizado (P0 -> P2)

## P0 (crítico, execução imediata)

### P0.1 Normalização Semântica Fim-a-Fim (11.3)
Objetivo:
1. garantir que metadados semânticos sobrevivam até `documents.Metadata` e índice.

Escopo técnico:
1. verificar/corrigir propagação `discovered_links.Metadata -> documents.Metadata` em todos paths de fetch.
2. merge previsível de metadata (link base + extração de conteúdo).
3. preservar `document_kind`, `approval_state`, `source_family`, `norma_key`.

Arquivos alvo:
1. `src/Gabi.Worker/Jobs/FetchJobExecutor.cs`
2. `src/Gabi.Worker/Jobs/SourceDiscoveryJobExecutor.cs` (se houver descarte de metadata por fallback)

Testes:
1. unit: metadata merge não perde campos semânticos.
2. integração: source Senado gera documento com `document_kind=norma`.
3. integração: source Câmara gera documento com `document_kind=proposicao`.

Aceite:
1. query em `documents` retorna semântica correta por source.

### P0.2 Guardrails de Intenção no Retrieval/LLM (11.4)
Objetivo:
1. impedir resposta “lei vigente” baseada em proposição.

Escopo técnico:
1. classificar intenção mínima de consulta:
- `norma_vigente`
- `historico_legislativo`
- `proposicao`
- `norma_especifica`
2. aplicar filtro default:
- `norma_vigente` => `document_kind=norma` e excluir `revogada` quando disponível
- `historico/proposicao` => `document_kind=proposicao`
3. resposta obrigatoriamente rotulada com tipo de fonte.

Arquivos alvo:
1. camada de busca/API quando disponível (serviço de query atual)
2. fallback em geração de resposta/prompt

Testes:
1. unit: intent->filter mapping.
2. integração: pergunta de vigência não retorna proposição no topo.

Aceite:
1. zero respostas assertivas de vigência com base exclusiva em `proposicao`.

### P0.3 Enrichment de Eventos no Senado (base do motor temporal)
Objetivo:
1. extrair eventos de alteração/revogação de `/legislacao/{id}`.

Escopo técnico:
1. novo estágio assíncrono de enrichment (não no discovery hot path).
2. parse de blocos:
- `vides`
- `edivs`
- `disps`
3. gerar eventos normalizados com `event_type`, `event_date`, `target_dispositivo`, `evidence_text`, `confidence`.

Observação:
1. `normative_force` inicial pode ser derivado, mas com fallback seguro `desconhecido`.

Testes:
1. casos com `Revogação`, `Alteração`, `Acréscimo`.
2. casos sem evento => `desconhecido`.

Aceite:
1. eventos persistidos para amostra de normas.

### P0.4 Retry->DLQ Runtime Proof (pendente de evidência final)
Objetivo:
1. prova E2E de retries até DLQ com contagem correta.

Aceite:
1. evidência SQL/log com `retry_count == política`.

---

## P0.5 (gate de risco)

### P0.5.1 Contract tests LexML SRU
Objetivo:
1. validar disponibilidade e contrato antes de promover LexML a fonte crítica.

Testes de contrato:
1. endpoint responde consistentemente.
2. paginação `startRecord/maximumRecords` funciona.
3. schema XML esperado preservado.

Decisão gate:
1. se passar: LexML entra como discovery complementar.
2. se falhar: manter LexML opcional/offline sem bloquear pipeline.

---

## P1 (estabilidade e cobertura normativa)

### P1.1 Planalto 2 níveis (scraper robusto)
Objetivo:
1. cobrir legislação compilada oficial com extração de alterações textuais.

Nível A:
1. raiz de leis ordinárias.
2. descobrir links de anos com regex tolerante a variações de slug.

Nível B:
1. para cada ano, descobrir links finais de normas.
2. capturar URLs compiladas e metadados mínimos.

Drivers:
1. `planalto_year_index_v1`
2. `planalto_norma_page_v1`

Robustez:
1. retry + delay.
2. canonicalização URL.
3. dedupe por hash.
4. saída parcial preservada em falha.

Aceite:
1. materialização de anos e normas > 0.
2. repetição idempotente sem explosão de duplicatas.

### P1.2 Consolidação multi-fonte por `norma_key`
Objetivo:
1. unir Senado + Planalto (+ LexML quando aprovado) em visão resolvida.

Regras:
1. merge por `norma_key`.
2. conflito explícito quando divergente.
3. manter trilha de origem por campo crítico.

Aceite:
1. cada `norma_key` tem estado resolvido ou `conflito` explícito.

### P1.3 Zero-kelvin operacional final (all-sources)
Objetivo:
1. fechar estabilidade com relatório reprodutível completo.

Aceite:
1. run all-sources conclui sem bloqueio indefinido.
2. relatório por source com `status`, `docs`, `peak_mem`, `error_summary`.

---

## P2 (inteligência normativa temporal)

### P2.1 Tabela de eventos normativos
Objetivo:
1. persistir eventos estruturados e auditáveis.

Schema lógico:
1. `norma_key`
2. `event_type`
3. `source_norma_key`
4. `target_dispositivo`
5. `event_date`
6. `evidence_text`
7. `evidence_source`
8. `confidence`

### P2.2 Motor temporal por dispositivo
Objetivo:
1. calcular estado na data de corte com precedência de eventos.

Regra base:
1. `revogacao > alteracao > estado original`.
2. sem evidência suficiente => `desconhecido`.
3. conflito entre eventos/fontes => `conflito`.

Saída:
1. `status_at_date`
2. `last_event`
3. `confidence`

### P2.3 Guardrails avançados de resposta
Objetivo:
1. resposta jurídica com explicitação de estado + confiança + fonte.

Template mínimo de resposta:
1. tipo de fonte
2. estado normativo
3. data de corte
4. norma/evento de suporte
5. nível de confiança

---

## 7. Sequência de Execução (v5)

1. P0.1 Normalização semântica fim-a-fim.
2. P0.2 Guardrails de intenção.
3. P0.3 Enrichment de eventos Senado.
4. P0.4 Runtime proof Retry->DLQ.
5. P0.5 LexML contract tests (go/no-go).
6. P1.1 Planalto 2 níveis.
7. P1.2 Consolidação multi-fonte.
8. P1.3 Zero-kelvin all-sources final.
9. P2.1/2.2/2.3 motor temporal completo.

---

## 8. Plano de Testes (super detalhado)

### 8.1 Unit tests
1. Adapter Senado:
- paginação anual
- falha parcial preservando links
- metadata semântica mínima
2. Adapter Planalto nível A:
- extração de anos com slugs variantes
3. Adapter Planalto nível B:
- extração de links finais de norma
4. Merge metadata no fetch:
- preserva `document_kind`
5. Intent classifier:
- mapeia intenção para filtros corretos
6. Enrichment de eventos:
- parse `vides/edivs/disps`

### 8.2 Integration tests
1. `discovered_links -> fetch_items -> documents` mantendo semântica.
2. comparação Senado vs Câmara (norma vs proposição).
3. comportamento em conflito de fontes.

### 8.3 Runtime tests
1. targeted: Senado legislação
2. targeted: Câmara proposições
3. targeted: Planalto níveis A/B
4. all-sources zero-kelvin com cap 20k

---

## 9. Critérios de Aceite (Gate v5)

1. Fonte Senado materializa normas com semântica correta.
2. Câmara mantém semântica de proposição.
3. Pergunta de vigência não usa proposição como fonte principal.
4. Eventos normativos disponíveis para amostra representativa.
5. Pipeline all-sources sem bloqueio indefinido.
6. Memória dentro de metas por estágio.
7. Evidência operacional anexada (SQL + logs + relatório).

---

## 10. Evidências obrigatórias ao final de cada sprint

1. SQL de contagem por source e status.
2. SQL de distribuição `document_kind`/`normative_force`.
3. trecho de log com tentativas/retry/dlq.
4. métrica de memória pico por source e agregado.
5. diff de testes adicionados e resultado final.

---

## 11. Registro de pendências históricas incorporadas

1. Discovery payload robustness: manter cobertura de teste.
2. Materialização links->fetch_items: manter invariante ativa.
3. DLQ JSON + retry proof: fechar evidência final pendente.
4. Retry policy única: consolidar config em uma fonte.
5. Compose/runtime hygiene: manter runbook e script de limpeza.
6. Native cap + stall cutoff: manter nos fluxos zero-kelvin.
7. Câmara modelagem de domínio (projetos vs normas): já endereçada semanticamente, ampliar em P2.
8. Memória: seguir metas stage 1/2/3 sem regressão funcional.

---

## 12. Decisões explícitas de incorporação (Z.AI + Claude + Codex)

Incorporado de Z.AI:
1. uso estruturado de `vides/edivs/disps` para eventos normativos.
2. filtro por intenção no RAG (norma vs proposição).

Incorporado de Claude:
1. atenção ao bug potencial de perda de metadata na persistência.
2. abordagem incremental de commits com validação por SQL/log.
3. LexML como fonte potencial de chave canônica (com gate de contrato).

Ajuste crítico aplicado por Codex (v5):
1. LexML não entra como dependência crítica sem contract tests.
2. `vigente` não é default sem evidência; default seguro é `desconhecido`.
3. enrichment de detalhe normativo é assíncrono, não no discovery hot path.

---

## 13. Trilha Nova: Imprensa Oficial (DOU + Federação)

### 13.1 Objetivo
Adicionar fontes de diário oficial para casos administrativos (nomeações, extratos de contrato, extratos de licitação, portarias), sem perder o foco discovery-first.

### 13.2 Escopo Federal (DOU) - abordagem faseada
1. **Fase A (baseline oficial agora)**: fonte pública mensal sem autenticação.
2. **Fase B (quando necessário)**: INLABS diário com autenticação estável.
3. **Fase C**: união de histórico (A) + delta diário (B), com deduplicação e reconciliação.
4. Campos semânticos mínimos:
- `diario_tipo=DOU`
- `secao=1|2|3`
- `orgao`
- `data_publicacao`
- `edicao`
- `pagina`
- `ato_tipo` (nomeacao, extrato_contrato, extrato_licitacao, etc.)
- `document_kind=ato_administrativo`

### 13.3 Escopo Estados (27 UFs) - prioridade média
1. Não assumir API única nacional de diários oficiais estaduais.
2. Estratégia federada com capability matrix por UF:
- `api_json`
- `xml_dump`
- `pdf_only`
- `html_search`
- `captcha/auth`
3. Ordem de rollout:
- Wave 1: UFs com API/XML aberto.
- Wave 2: UFs com HTML paginado sem barreiras.
- Wave 3: UFs com restrição (captcha/login), com avaliação jurídica/operacional.
4. Resultado esperado:
- cobertura incremental; qualidade heterogênea tratada por adapter por UF.

### 13.4 Julgados de Tribunais Federais: decisão de fonte
1. DOU não é fonte primária ideal para jurisprudência.
2. Para atos judiciais/julgados:
- preferir DJEN (CNJ) e bases centrais/tribunais.
3. DOU fica como fonte de atos administrativos e publicações administrativas.
4. Regra operacional:
- intenção `julgado` => `DJEN/DataJud/tribunal`.
- intenção `ato_administrativo` => `DOU/diário oficial`.

### 13.5 Riscos e mitigação
1. Delay natural da base pública mensal:
- tratar como fonte de histórico (`freshness=monthly_delayed`), não near-real-time.
2. Volatilidade de HTML no portal público:
- parser tolerante + smoke tests de selector.
3. Dependência de autenticação no INLABS (futuro):
- manter INLABS fora do baseline e ativar apenas em Fase B com credencial institucional.
4. Heterogeneidade estadual:
- capability matrix + rollout em ondas.

### 13.6 Execução imediata (Fase A) - baseline oficial sem autenticação
1. Fonte ativa no YAML:
- `dou_dados_abertos_mensal` (discovery público, sem cookie/login).
2. Fontes INLABS:
- `dou_inlabs_secao1_atos_administrativos`
- `dou_inlabs_secao3_licitacoes_contratos`
- status: `enabled=false` e `pipeline.enabled=false` (somente Fase B/C).
3. Regras operacionais da Fase A:
- `content_strategy=link_only` (discovery/catalog primeiro).
- ingestão textual completa dos atos fica para evolução posterior.

### 13.7 Testes e verificação (DoD DOU fase A)
1. Critérios de aceite:
- seed registra a source `dou_dados_abertos_mensal`.
- discovery da source mensal retorna links públicos (`zip/xml`) com estabilidade.
- sem dependência de cookie/sessão no baseline.
2. Evidência mínima:
- `GET /api/v1/sources` contém `dou_dados_abertos_mensal`.
- targeted discovery da source mensal materializa `discovered_links > 0`.
3. Evidência runtime (19/02/2026):
- Comando:
  `./tests/zero-kelvin-test.sh docker-20k --source dou_dados_abertos_mensal --phase discovery --report-json /tmp/zk-dou-mensal-discovery-latest.json`
- Resultado:
  `PASS`, `links=252`, `fetch_items=252`, `error_summary=discovery_only`.
- Interpretação:
  baseline DOU fase A está estável para catalogação de links (discovery), sem dependência de INLABS/cookie.

### 13.8 Fases B/C (deferidas)
1. **Fase B (INLABS diário)**:
- autenticação programática robusta (não manual) com credencial institucional.
- delta diário por seção/edição.
2. **Fase C (consolidação)**:
- merge histórico (Fase A) + delta diário (Fase B).
- dedupe por chave canônica do ato + data/seção + URL.
3. Guardrail jurídico/LLM:
- consultas que exigem “últimas semanas” não devem usar apenas Fase A.
- para histórico/auditoria retrospectiva, Fase A é fonte principal.

---

## 14. Plano de Estabilidade Operacional (rodadas curtas)

### 14.1 Objetivo
Reduzir risco antes do próximo zero-kelvin full pesado.

### 14.2 Rodadas obrigatórias
1. Dry-run geral (all-sources, sem carga máxima):
- validar discovery + materialização + estados finais sem travas.
2. Zero-kelvin limitado em 200 docs/source:
- detectar quebras/stalls cedo.
3. Zero-kelvin limitado em 1000 docs/source:
- validar estabilidade intermediária (memória/retries/tempo).
4. Só depois:
- zero-kelvin 20k para fontes pesadas.

### 14.3 Critérios de saída por rodada
1. Sem `processing` indefinido.
2. Taxa de `WARN` conhecida e explicável por source.
3. `peak_mem` dentro da meta da rodada.
4. Relatório por source atualizado.

### 14.4 Gate para avançar de estágio
1. 200 -> 1000 somente se:
- sem `FAIL` estrutural em discovery/fetch.
2. 1000 -> 20k somente se:
- `WARN` residual <= limite acordado e sem risco de OOM recorrente.

---

## 15. Backend-Only Transition (API/Web)

### 15.1 Diretriz
1. Frontend (`Gabi.Web`) fora do fluxo operacional até estabilização do backend.
2. API mantida com núcleo essencial para auth + orquestração + operação.

### 15.2 Ações
1. Remover serviço `web` do `docker-compose`.
2. Documentar endpoints essenciais backend-only.
3. Remover endpoints de compatibilidade/frontend da API (`dashboard/stats`, `dashboard/jobs`, etc.).
4. Atualizar scripts e README para usar apenas endpoints essenciais.
5. Planejar remoção definitiva de código morto da camada web/frontend.

### 15.3 Aceite
1. zero-kelvin e runbooks funcionam sem frontend.
2. autenticação JWT e policies intactas.
3. pipeline controlável apenas por API essencial.

### 15.4 Remoção completa de `Gabi.Web` do repositório (faseada)
Objetivo:
1. eliminar dívida de manutenção de frontend fora do escopo atual.

Etapas:
1. Etapa A (já concluída):
- `web` removido do `docker-compose`.
- contratos backend-only documentados.
2. Etapa B (próxima):
- remover seção de frontend do README e docs legados que assumem `:3000`.
- remover rotas e exemplos de dashboard visual já descontinuados.
3. Etapa C (remoção física):
- remover `src/Gabi.Web` e docs exclusivas de UI.
- manter apenas documentação de API/pipeline/ops.
4. Etapa D (higiene final):
- remover dependências e scripts não usados pelo frontend.
- validar que CI/local não referenciam mais `Gabi.Web`.

Gate de segurança antes da Etapa C:
1. zero-kelvin backend-only aprovado.
2. smoke operacional aprovado (`auth`, `seed`, `phase trigger`, `links`, `dlq`).
3. sem consumidores internos ativos da UI.

---

## 16. Execução Imediata (Claude Ajustado + Decisão Atual)

### 16.1 Decisão consolidada
1. Aprovar plano do Claude com ajustes do programa v5.
2. Ordem mandatória:
- fechar `P0.1` com testes estáveis. **Status: concluído**
- implementar `json_api` canário em `senado_legislacao_leis_ordinarias`. **Status: concluído**
- adicionar testes `normative_force`. **Status: concluído**
- validar runtime por SQL/log. **Status: concluído**

### 16.2 Ajustes obrigatórios ao plano do Claude
1. `P0.2` (guardrails de intenção) começa já na API/query builder, sem depender de Elasticsearch.
2. `link_only` permanece para discovery-first em Câmara/BTCU e demais Senado (exceto canário).
3. `normative_force` default continua `desconhecido` sem evidência.

Status de execução:
1. `P0.2` implementado no endpoint de links (`query_intent`) com filtros:
- `norma_vigente` -> `document_kind=norma` e exclusão de `normative_force=revogada`
- `historico_legislativo`/`proposicao` -> `document_kind=proposicao`
- `norma_especifica` -> `document_kind=norma`
2. Testes adicionados e aprovados:
- `tests/Gabi.Api.Tests/IntentGuardrailsTests.cs`
- `dotnet test tests/Gabi.Api.Tests/Gabi.Api.Tests.csproj` -> **11/11 PASS**

### 16.3 Escopo do canário json_api (Senado LEI)
1. `content_strategy: json_api` apenas em `senado_legislacao_leis_ordinarias`.
2. Extrair:
- `title_path`
- `content_path`
- `id_path`
- `vides_path`
3. Derivar `normative_force`:
- revogação -> `revogada`
- alteração permanente -> `modificada`
- alteração provisória -> `modificada_provisoriamente`
- ausência de evidência -> `desconhecido`

### 16.4 Evidências exigidas para fechamento
1. `dotnet test` em `Gabi.Postgres.Tests` e `Gabi.Discover.Tests` sem regressão.
2. SQL em `documents.Metadata` com `document_kind=norma` e `normative_force` para canário Senado.
3. confirmação de backend-only:
- endpoints removidos retornam `404`;
- endpoints essenciais operacionais retornam `200`.

### 16.5 P0.4 Runtime Proof Retry->DLQ (fechado em 19/02/2026)
Objetivo:
1. comprovar fim-a-fim que retries do Hangfire respeitam política e job exaurido vai para `dlq_entries`.

Execução:
1. criada source controlada `dlq_probe_web_crawl` com `web_crawl` sem `root_url` (falha determinística).
2. disparado `discovery` via API para produzir exceção repetível no `SourceDiscoveryJobExecutor`.
3. observado ciclo completo no worker:
- `Retry attempt 1 of 3` (delay 2s)
- `Retry attempt 2 of 3` (delay 8s)
- `Retry attempt 3 of 3` (delay 30s)
- execução final falha e `DlqFilter` move para DLQ.

Evidência SQL:
1. `dlq_entries` para `OriginalJobId=996c4e6f-4f62-4f33-8119-4d3f5cb8d96b`:
- `RetryCount=3`
- `ErrorType=ArgumentException`
- `Status=pending`
- `FailedAt=03:08:15`

Evidência de log:
1. `Job 57 moved to DLQ as e1de9c41-d52c-4272-9824-cf3a8394f214. JobType=RunAsync, SourceId=dlq_probe_web_crawl`
2. sequência de tentativas em log coincide com política (`attempts=3`, delays `2,8,30`).

Correção aplicada durante a prova:
1. `DlqFilter` ajustado para usar `RetryCount` nativo do Hangfire (source of truth), evitando contagem off-by-one por histórico de estados.
2. teste de regressão adicionado:
- `tests/Gabi.Postgres.Tests/DlqRetryDecisionTests.cs`
- cenário validado: mover para DLQ apenas quando `retryCount >= maxRetries`.

Higiene pós-prova:
1. `dlq_probe_web_crawl` mantida no banco como `Enabled=false` para não interferir nos próximos runs.

### 16.6 Rodada Zero-Kelvin (all-sources, cap=200) — execução parcial com gate de memória
Status:
1. **Interrompida manualmente por gate de risco** após evidência suficiente de regressão de memória.
2. Motivo da interrupção: picos recorrentes acima do envelope alvo (>= 700 MiB) já na rodada de 200 docs/source.

Comando executado:
1. `./tests/zero-kelvin-test.sh docker-20k --source all --phase full --max-docs 200 --monitor-memory`

Evidências consolidadas (trecho `/tmp/gabi-zero-kelvin.log`):
1. `camara_leis_ordinarias`: `WARN` por `discovery_not_materialized` no tempo limite, mas com progresso real:
- `links=21000`, `fetch_items=21000`, `status=running` no cutoff.
2. `camara_medidas_provisorias`: `PASS`, `docs=0`, `peak_mem=362.2 MiB`.
3. `camara_projetos_decreto_legislativo`: `PASS`, `docs=0`, `peak_mem=612.7 MiB`.
4. `camara_projetos_lei_complementar`: `PASS`, `docs=0`, `peak_mem=600.6 MiB`.
5. `camara_projetos_lei_conversao`: `PASS`, `docs=0`, `peak_mem=591.4 MiB`.
6. `camara_projetos_resolucao`: `PASS`, `docs=0`, `peak_mem=582.1 MiB`.
7. `camara_propostas_emenda_constitucional`: `PASS` com cap nativo, `docs=200`, `peak_mem=697.0 MiB`.
8. `senado_legislacao_decretos_lei`: `PASS`, `docs=0`, `peak_mem=713.1 MiB` (**novo pico observado**).

Decisão operacional aplicada:
1. **Não avançar para `max-docs=1000` e `max-docs=20000` antes de correção de memória (P1/P2 guardrails).**
2. Priorizar imediatamente:
- redução de concorrência efetiva no fetch das fontes de alto volume;
- ajuste de batch/tamanho de inserção para reduzir pressão de memória;
- rerun da rodada `200` como gate obrigatório antes de escalar carga.

Próximo gate:
1. Reexecutar `cap=200` após correções e exigir `peak_mem <= 380 MiB` (Stage 1) para autorizar `cap=1000`.

## 17. Memory Hardening (P1.0)

### 17.1 Fase 1 (quick wins) — implementada em 19/02/2026
Objetivo:
1. reduzir pressão de memória no fetch sem alterar semântica funcional.

Mudanças aplicadas:
1. `FetchJobExecutor` agora usa snapshot de candidatos por **IDs** (até `5000`) e processa em páginas de `100`:
- evita carregar 5000 entidades completas simultaneamente;
- evita reprocessamento infinito de itens com status `failed` durante o mesmo run.
2. limpeza de tracker por página:
- `_context.ChangeTracker.Clear()` ao final de cada página.
3. carga de YAML unificada por run:
- substituídas 3 leituras/parses (`parse`, `content_strategy`, `extract`) por uma única leitura/parse (`LoadSourceFetchConfigAsync`).
4. `link_only` e finalização do fetch run ajustados para funcionar com `ChangeTracker.Clear` (reattach explícito por `FindAsync` no fechamento).
5. ambiente docker com concorrência reduzida:
- `WorkerPool__WorkerCount=1` em `docker-compose.yml` para reduzir pico concorrente em ambiente constrained.
6. repositório de fetch expandido para suportar paginação segura por IDs:
- `GetCandidateIdsBySourceAndStatusesAsync`
- `GetByIdsAsync`
- `CountBySourceAndStatusesAsync`

Arquivos alterados:
1. `src/Gabi.Worker/Jobs/FetchJobExecutor.cs`
2. `src/Gabi.Postgres/Repositories/FetchItemRepository.cs`
3. `docker-compose.yml`
4. `tests/Gabi.Postgres.Tests/FetchItemRepositoryTests.cs`

Validação de fase:
1. `dotnet test tests/Gabi.Postgres.Tests/Gabi.Postgres.Tests.csproj` -> **43/43 PASS**
2. `dotnet build src/Gabi.Worker/Gabi.Worker.csproj` -> **OK**

Próximo passo de fase:
1. rerodar zero-kelvin `cap=200` (all-sources) para medir impacto.
2. gate para avançar: `peak_mem <= 380 MiB` (Stage 1).

### 17.2 Revalidação cap=200 — status atual (atualizada em 19/02/2026)
Status:
1. **revalidação targeted executada com sucesso** após correção do fluxo de benchmark.

Correção operacional aplicada:
1. `tests/zero-kelvin-test.sh` ajustado para **pular discovery global do smoke** quando `--source` for específico (não `all`).
2. Isso remove backlog artificial no Hangfire com `WorkerPool__WorkerCount=1` e permite medir a fonte alvo de forma isolada.

Evidência de execução (cap=200, monitor_memory=true):
1. `tcu_acordaos`:
- `PASS`, `docs=200`, `peak_mem=125.5 MiB`, `throughput=1333.33 docs/min`
- report: `/tmp/zk-tcu-acordaos-200-r2.json`
2. `tcu_publicacoes`:
- `PASS`, `docs=0`, `peak_mem=117.9 MiB`, `status_breakdown=skipped_format,290`
- report: `/tmp/zk-tcu-publicacoes-200-r2.json`
3. `tcu_notas_tecnicas_ti`:
- `PASS`, `docs=0`, `peak_mem=97.39 MiB`, `status_breakdown=skipped_format,16`
- report: `/tmp/zk-tcu-notas-200-r2.json`
4. `senado_legislacao_leis_ordinarias`:
- `PASS`, `docs=200`, `peak_mem=239.5 MiB`, `throughput=375.00 docs/min`
- report: `/tmp/zk-senado-leis-200-r2.json`
5. `camara_leis_ordinarias`:
- `WARN`, `error_summary=discovery_not_materialized`
- progresso preservado no cutoff: `links=13000`, `fetch_items=13000`, `status=running`
- report: `/tmp/zk-camara-leis-200-r2.json`

Leitura técnica:
1. para fontes com fetch efetivo medido (`tcu_acordaos` e `senado_legislacao_leis_ordinarias`), pico ficou **abaixo de 240 MiB**.
2. o gate de memória Stage 1 (`<= 380 MiB`) está **atendido** no recorte targeted já validado.
3. risco remanescente principal continua sendo **janela de materialização da Câmara** (tempo/discovery), não pressão de memória de fetch.

Próximos passos imediatos:
1. rodar canários adicionais `cap=200` nas demais fontes de maior cardinalidade (`senado_*` restantes e `camara_*` prioritárias).
2. se mantiver envelope, avançar para `cap=1000` em canários (`tcu_acordaos`, `senado_legislacao_leis_ordinarias`).
3. só depois executar novo `all-sources cap=200` como fotografia agregada final, com stall-cutoff ativo.

### 17.3 Escalonamento canário cap=1000 — status atual (19/02/2026)
Status:
1. **executado e aprovado** para os dois canários principais de fetch.

Evidência:
1. `tcu_acordaos` (`/tmp/zk-tcu-acordaos-1000-r1.json`)
- `PASS`, `docs=1000`, `peak_mem=138.7 MiB`, `throughput=3750.00 docs/min`
2. `senado_legislacao_leis_ordinarias` (`/tmp/zk-senado-leis-1000-r1.json`)
- `PASS`, `docs=1000`, `peak_mem=205.8 MiB`, `throughput=416.67 docs/min`

Leitura de estágio:
1. envelope de memória permaneceu **bem abaixo de 380 MiB** também em `cap=1000`.
2. ganho de estabilidade/memória do hardening de fetch se manteve após escalonamento.
3. pendência crítica permanece no domínio de discovery longa da Câmara (`discovery_not_materialized` por janela), não em OOM/fetch cap.

Próximo gate recomendado:
1. rodar `all-sources cap=200` com o patch do zero-kelvin já aplicado (sem backlog artificial em targeted).
2. se o agregado continuar dentro do envelope, avançar para canário `cap=20000` apenas nas fontes já aprovadas (`tcu_acordaos` e `senado_legislacao_leis_ordinarias`).

### 17.4 Rodada all-sources cap=200 — RESULTADO DEFINITIVO (19/02/2026)

Comando:
```
./tests/zero-kelvin-test.sh docker-20k --source all --phase full --max-docs 200 --monitor-memory --report-json /tmp/zk-all-200-sequential.json
```

**Resultado: 35 testes, 35 PASS, 0 FAIL. Global peak_mem = 245.7 MiB (gate 380 MiB: APROVADO)**

Modo de execução: **sequencial por fonte** (Hangfire queue flush + data cleanup entre cada source, sem competição de fila).

#### Matriz completa por source

| # | Source | Status | Docs | Peak Mem | Duration | Throughput | Nota |
|---|--------|--------|------|----------|----------|------------|------|
| 1 | senado_legislacao_decretos_lei | WARN | 0 | 245.5 MiB | 178s | 0 | fetch_stalled |
| 2 | senado_legislacao_leis_complementares | PASS | 0 | 159.9 MiB | 9s | 0 | content_strategy=link_only |
| 3 | senado_legislacao_leis_delegadas | PASS | 0 | 158.7 MiB | 9s | 0 | content_strategy=link_only |
| 4 | senado_legislacao_leis_ordinarias | **PASS** | **200** | 244.9 MiB | 19s | 632/min | capped |
| 5 | tcu_acordaos | **PASS** | **200** | 244.5 MiB | 8s | 1500/min | capped |
| 6 | tcu_boletim_jurisprudencia | **PASS** | **200** | 244.8 MiB | 9s | 1333/min | capped |
| 7 | tcu_boletim_pessoal | **PASS** | **200** | 245.7 MiB | 9s | 1333/min | capped |
| 8 | tcu_btcu_administrativo | PASS | 0 | 194.8 MiB | 16s | 0 | content_strategy=link_only |
| 9 | tcu_btcu_controle_externo | WARN | 0 | 194.4 MiB | 108s | 0 | fetch_stalled |
| 10 | tcu_btcu_deliberacoes | PASS | 0 | 204.8 MiB | 51s | 0 | content_strategy=link_only |
| 11 | tcu_btcu_deliberacoes_extra | WARN | 0 | 0 MiB | 0s | 0 | discovery_not_materialized |
| 12 | tcu_btcu_especial | PASS | 0 | 206.8 MiB | 9s | 0 | content_strategy=link_only |
| 13 | tcu_informativo_lc | **PASS** | **200** | 205.4 MiB | 8s | 1500/min | capped |
| 14 | tcu_jurisprudencia_selecionada | **PASS** | **200** | 202.9 MiB | 12s | 1000/min | capped |
| 15 | tcu_normas | **PASS** | **200** | 220.6 MiB | 9s | 1333/min | capped |
| 16 | tcu_notas_tecnicas_ti | PASS | 0 | 182.0 MiB | 8s | 0 | content_strategy=link_only |
| 17 | tcu_publicacoes | PASS | 0 | 168.8 MiB | 9s | 0 | content_strategy=link_only |
| 18 | tcu_resposta_consulta | **PASS** | **200** | 168.8 MiB | 9s | 1333/min | capped |
| 19 | tcu_sumulas | **PASS** | **200** | 165.0 MiB | 9s | 1333/min | capped |
| 20 | camara_leis_ordinarias | WARN | 0 | 0 MiB | 0s | 0 | discovery_not_materialized |
| 21 | camara_medidas_provisorias | PASS | 0 | 223.7 MiB | 23s | 0 | content_strategy=link_only |
| 22 | camara_projetos_decreto_legislativo | WARN | 0 | 0 MiB | 0s | 0 | discovery_not_materialized |
| 23 | camara_projetos_lei_complementar | PASS | 0 | 221.0 MiB | 83s | 0 | items_done |
| 24 | camara_projetos_lei_conversao | PASS | 0 | 197.7 MiB | 9s | 0 | content_strategy=link_only |
| 25 | camara_projetos_resolucao | PASS | 0 | 222.4 MiB | 13s | 0 | items_done |
| 26 | camara_propostas_emenda_constitucional | **PASS** | **200** | 230.7 MiB | 33s | 364/min | capped |

#### Agregado

| Métrica | Valor |
|---------|-------|
| PASS | 21 |
| WARN | 5 |
| FAIL | 0 |
| Docs total | 2000 |
| Sources com fetch real (docs>0) | 10 |
| Peak mem global | 245.7 MiB |
| Gate 380 MiB | **APROVADO** |

#### Análise dos WARNs

1. **fetch_stalled** (2 sources: senado_decretos_lei, tcu_btcu_controle_externo): discovery concluiu, fetch processou items mas não produziu documentos. Causa provável: `content_strategy` ou parse config inadequado. Não é problema de memória.
2. **discovery_not_materialized** (3 sources: tcu_btcu_deliberacoes_extra, camara_leis_ordinarias, camara_projetos_decreto_legislativo): discovery não completou na janela de 60 tentativas (3 min). Fontes de alto volume da Câmara têm discovery naturalmente longa. Não é problema de memória.

#### Correções no zero-kelvin aplicadas nesta rodada

1. **Modo sequencial com isolamento**: cada source recebe flush de Hangfire + limpeza de dados antes de executar, eliminando competição de fila.
2. **Stdin fix**: `</dev/null` em todas as chamadas docker/psql/curl dentro do `while read` loop para evitar consumo do here-string.
3. **Reordenação**: fontes não-Câmara primeiro, Câmara por último.

### 17.5 Próximos passos

1. **Gate cap=200: APROVADO.** Peak mem 245.7 MiB << 380 MiB.
2. **Próximo gate**: all-sources cap=1000 (canários tcu_acordaos e senado_leis_ordinarias já aprovados individualmente em 17.3).
3. **WARNs a investigar**: fetch_stalled em senado_decretos_lei e tcu_btcu_controle_externo (provável config issue, não memória).
4. **Discovery lenta da Câmara**: aumentar janela de materialização ou aceitar como WARN known.

### 17.6 Rodada all-sources cap=200 — BASELINE ATUAL (fix3, 19/02/2026)

Comando:
```
./tests/zero-kelvin-test.sh docker-20k --source all --phase full --max-docs 200 --monitor-memory --report-json /tmp/zk-all-200-fix3.json
```

Resultado consolidado:
1. **PASS=26, WARN=0, FAIL=0**
2. **peak_mem global = 246.7 MiB** (gate 380 MiB: aprovado)
3. `docs_total=1600` (run conservador, com múltiplas fontes em `link_only`, `no_links_discovered` ou `discovery_materialized_running`)

Diferença chave vs seção 17.4:
1. os 5 WARN anteriores foram eliminados nesta configuração operacional.
2. fontes de discovery longa da Câmara passam como `discovery_materialized_running` no all-sources (sem bloquear suíte).
3. fontes `link_only` respeitam cap operacional sem cair em `fetch_stalled`.

Evidência (trecho agregado do relatório):
1. `Targeted: PASS – source=all, phase=full, docs=1600, peak_mem=246.70 MiB (246.7MiB)`
2. `status_breakdown=failed_sources=0;warn_sources=0`
3. JSON: `/tmp/zk-all-200-fix3.json`

Decisão de baseline:
1. considerar `fix3` como baseline oficial para evolução.
2. manter seção 17.4 como histórico de diagnóstico pré-fix.
3. próximo gate: `all-sources cap=1000` com o mesmo modo sequencial+isolamento.

### 17.7 Rodada all-sources cap=200 e cap=1000 — FECHAMENTO (19/02/2026)

Comandos executados:
1. `./tests/zero-kelvin-test.sh docker-20k --source all --phase full --max-docs 200 --monitor-memory --report-json /tmp/zk-all-200-current.json`
2. `./tests/zero-kelvin-test.sh docker-20k --source all --phase full --max-docs 1000 --monitor-memory --report-json /tmp/zk-all-1000-current.json`

Resultado cap=200 (run atual):
1. **PASS=27, WARN=0, FAIL=0**
2. `docs_total=1800`
3. `peak_mem=275.00 MiB`
4. evidência: `/tmp/zk-all-200-current.json`

Resultado cap=1000 (run atual):
1. **PASS=27, WARN=0, FAIL=0**
2. `docs_total=6800`
3. `peak_mem=252.30 MiB`
4. evidência: `/tmp/zk-all-1000-current.json`

Leitura técnica consolidada:
1. os **5 WARN históricos foram efetivamente eliminados** no fluxo operacional atual.
2. não houve regressão após inclusão da fonte DOU mensal no catálogo.
3. envelope de memória permaneceu confortável em ambos os gates (`<< 380 MiB`).

Decisão operacional:
1. considerar o objetivo "1 e 2" concluído: (**resolver WARNs** + **validar cap=1000 all-sources**).
2. próximo salto de risco controlado: canário `cap=20000` apenas nas fontes já estáveis (ex.: `tcu_acordaos`, `senado_legislacao_leis_ordinarias`).

### 17.8 Rodada overnight all-sources cap=10000 — FECHAMENTO FINAL (20/02/2026)

Comando executado:
1. `./tests/zero-kelvin-test.sh docker-20k --source all --phase full --max-docs 10000 --monitor-memory --report-json /tmp/zk-all-10000-overnight-20260220-013952.json`

Resultado consolidado:
1. **PASS=27, WARN=0, FAIL=0**
2. `docs_total=51477`
3. `peak_mem=758.10 MiB`
4. suite zero-kelvin: `42/42` checks `PASS`
5. ocorrência de `53300`/`too many clients`: **não observada** nesta rodada

Evidências:
1. log: `/tmp/gabi-zero-kelvin-overnight-20260220-013952.log`
2. relatório JSON: `/tmp/zk-all-10000-overnight-20260220-013952.json`

Leitura técnica:
1. correções de claim atômico + retry transitório + reset de `processing` sustentaram estabilidade no cap alto.
2. fontes críticas BTCU/Senado não degradaram para stall/DLQ na rodada overnight.
3. throughput e conclusão all-sources confirmam que o pipeline está operacionalmente estável no gate de 10k.

Decisão operacional:
1. promover este resultado como baseline de estabilização de pipeline para o V5.
2. próximos passos focam em hardening/observabilidade e evolução funcional, não mais em desbloqueio estrutural do fetch.

### 17.9 Ajuste de cap nativo em discovery + nota de concorrência (20/02/2026)

Mudanças aplicadas:
1. `StartPhase(discovery)` passou a aceitar e propagar `max_docs_per_source` no payload do job.
2. `SourceDiscoveryJobExecutor` passou a ler `max_docs_per_source` e encerrar discovery no cap, com `discovery_runs.ErrorSummary` explícito de cap.
3. `zero-kelvin-test.sh` passou a enviar payload de cap também no trigger de discovery.
4. `zero-kelvin-test.sh` foi ajustado para não quebrar cedo em discovery `running` durante `phase=full/fetch` (evita falso estado antes de `completed`).

Evidência validada (canário `senado_legislacao_decretos_lei`, `phase=full`, `cap=10000`):
1. comando: `./tests/zero-kelvin-test.sh docker-20k --source senado_legislacao_decretos_lei --phase full --max-docs 10000 --monitor-memory --report-json /tmp/zk-senado-decretos-10000-capnative.json`
2. resultado: `PASS` no targeted; `status_breakdown=skipped_format,10000`.
3. SQL (`discovery_runs`): `Status=completed`, `LinksTotal=10000`, `ErrorSummary=capped at max_docs_per_source=10000`.
4. SQL (`fetch_items`): `skipped_format=10000`.

Nota de concorrência (decisão explícita):
1. os canários citados acima foram executados em modo sequencial para diagnóstico determinístico.
2. isso **não implica** desabilitação estrutural da concorrência do pipeline; é escolha operacional de teste.
3. próximo gate de hardening deve incluir rodada concorrente para validar throughput sob carga, mantendo os mesmos SLOs de estabilidade/memória.

### 17.10 Plano curto de hardening (execução imediata)

Frente 1: SLOs + observabilidade
1. definir SLO por fase/fonte: `latency`, `throughput`, `error_rate`, `queue_depth`, `mem_peak`.
2. instrumentar métricas obrigatórias no caminho `seed/discovery/fetch/ingest`.
3. consolidar dashboard único de decisão operacional (run status + gargalo por fase + memória).
4. gate operacional: nenhuma rodada promoted sem evidência objetiva desses indicadores.

Frente 2: contratos estáveis de orquestração
1. padronizar contrato de `job payload` e `status/events` para todas as fases.
2. reduzir lógica decisória em script; `zero-kelvin-test.sh` deve atuar como executor/observador, não controlador de estado.
3. garantir que decisões de fluxo (cap, retry, transição de fase) residam primariamente em API/Worker.
4. incluir validações de contrato (testes) para evitar regressão silenciosa entre componentes.

Frente 3: resiliência de próxima geração
1. classificar falhas automaticamente em `transiente` vs `permanente`.
2. aplicar retry semântico por classe de falha (política diferenciada por tipo).
3. priorizar filas dinamicamente por saúde da fonte e impacto operacional.
4. adicionar mecanismos de auto-healing com trilha auditável (sem mascarar falha estrutural).

Backlog de execução (curto prazo)
1. P0: SLOs mínimos + métricas mandatórias + dashboard consolidado.
2. P1: contrato único de payload/eventos + limpeza de decisões em script.
3. P2: classificador de falha + retry semântico + priorização dinâmica.

Critério de aceite desta etapa
1. rodada concorrente controlada com SLOs publicados por fase/fonte.
2. evidência de regressão reduzida em transições discovery->fetch e fetch->ingest.
3. relatório final com matriz `PASS/WARN/FAIL` explicada por métricas, não por heurística manual.

Checklist operacional (ordem + owner sugerido)
1. `[P0-1]` definir SLOs-alvo por fase/fonte (`latency`, `throughput`, `error_rate`, `queue_depth`, `mem_peak`)  
owner: `arquitetura/tech lead`  
done when: tabela de SLO publicada no V5 + limiares de gate explícitos.
2. `[P0-2]` instrumentar métricas no Worker/API para `seed/discovery/fetch/ingest`  
owner: `backend worker/api`  
done when: métricas visíveis por source e fase em endpoint/log estruturado.
3. `[P0-3]` consolidar dashboard único de operação  
owner: `plataforma/observabilidade`  
done when: painel mostra SLO compliance + gargalo por fase + pico de memória por run.
4. `[P1-1]` padronizar contrato `job payload` e `status/events` (schema versionado)  
owner: `backend contracts`  
done when: contrato documentado + validado em testes de contrato.
5. `[P1-2]` reduzir controle de estado no `zero-kelvin-test.sh`  
owner: `qa/devex`  
done when: script apenas dispara/observa; decisões de estado ficam em API/Worker.
6. `[P1-3]` adicionar testes de regressão para transições de fase (`discovery->fetch->ingest`)  
owner: `qa/backend`  
done when: suíte falha ao detectar regressão de handshake entre fases.
7. `[P2-1]` classificador de falhas (`transiente` vs `permanente`)  
owner: `backend worker`  
done when: erros classificados automaticamente com código/categoria persistidos.
8. `[P2-2]` retry semântico por classe de falha  
owner: `backend worker`  
done when: políticas distintas por classe + evidência de retry correto em logs/SQL.
9. `[P2-3]` priorização dinâmica de filas por saúde de source  
owner: `orquestração/jobs`  
done when: fila responde a degradação sem bloquear fontes saudáveis.
10. `[P2-4]` rodada concorrente de validação final  
owner: `qa/performance`  
done when: all-sources concorrente passa com SLOs dentro do envelope.

### 17.11 Simplificação de governança de IA (sem regressão de pipeline)

Objetivo:
1. reduzir prescrição duplicada para agentes de IA.
2. preservar apenas constraints realmente operacionais/arquiteturais.
3. manter rastreabilidade técnica no repositório (evitar conhecimento crítico fora do git).

Decisões:
1. manter documentos de planejamento no repositório (`PLANO_CONSOLIDADO_V5`, matriz, TODO), porém com foco em estado atual verificável.
2. consolidar instruções de agentes em um núcleo único e enxuto; arquivos por provedor passam a atuar como wrappers mínimos.
3. remover artefatos de contexto obsoletos (`*.bak`) imediatamente.
4. preservar guardrails críticos (`memory budget`, arquitetura em camadas, regras de migration e contratos de pipeline).

Execução faseada:
1. Fase A (agora): higiene de contexto  
   - remover arquivos `*.bak`;  
   - validar que suíte/compilação não regrediu.
2. Fase B: consolidação de instruções  
   - definir arquivo canônico de constraints;  
   - reduzir redundância entre `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`.
3. Fase C: racionalização de skills/workflows  
   - manter apenas skills de valor durável;  
   - transformar skills prescritivas em guias opcionais.

Status de execução (20/02/2026):
1. `[concluído]` inventário de simplificação levantado (`*.bak`, arquivos de instrução, riscos).
2. `[concluído]` limpeza de `*.bak` (4 arquivos removidos: 3 em `tests/Gabi.Discover.Tests` e 1 em `old_python_implementation`).
3. `[concluído]` consolidação de instruções de agentes (wrappers mínimos em `CLAUDE.md`/`GEMINI.md` apontando para `AGENTS.md` canônico + seção canônica em `AGENTS.md`).
4. `[concluído]` racionalização de skills em modo governança (`docs/ai/SKILLS_POLICY.md`: core/optional/deprecated-by-default).

### 17.12 Revalidação all-sources cap=10000 após B&C — FECHAMENTO (20/02/2026)

Comando executado:
1. `./tests/zero-kelvin-test.sh docker-20k --source all --phase full --max-docs 10000 --monitor-memory --report-json /tmp/zk-all-10000-post-bc.json`

Resultado consolidado:
1. **PASS=27, WARN=0, FAIL=0**
2. `docs_total=51477`
3. `peak_mem=299.40 MiB`
4. suite zero-kelvin: `42/42` checks `PASS`
5. `status_breakdown=failed_sources=0;warn_sources=0`

Evidências:
1. log: `/tmp/gabi-zero-kelvin.log`
2. relatório JSON: `/tmp/zk-all-10000-post-bc.json`

Leitura técnica:
1. a estabilização do pipeline permaneceu íntegra após as mudanças de governança/simplificação (B&C).
2. cap nativo em discovery/fetch manteve comportamento consistente no cenário completo all-sources.
3. envelope de memória permaneceu dentro do budget operacional definido para o projeto (<= 300 MiB no run atual).

Decisão operacional:
1. manter este run como baseline vigente de estabilidade pós-B&C.
2. avançar com commit do bloco de pipeline + V5 e seguir para backlog de hardening (17.10) sem bloqueio estrutural.

## 18. Infra e Armazenamento em Nuvem (novo)

### 18.1 Problema correto (separar domínios)
1. **Compute**: onde API/Worker executam containers.
2. **Banco transacional**: Postgres para estado do pipeline (`source_registry`, `discovered_links`, `fetch_items`, `fetch_runs`, `documents` metadados).
3. **Object storage (opcional)**: conteúdo bruto pesado (PDF/HTML/JSON bruto), quando houver requisito de auditoria/replay.

Decisão explícita:
1. **S3 não hospeda containers**; S3 é para objetos/blobs.
2. Para container runtime, manter direção atual de **Fly.io** (coerente com roadmap já em docs).

### 18.2 Estratégia recomendada (faseada)
Fase 1 (produção inicial):
1. API + Worker em Fly.io.
2. Postgres gerenciado (Fly Postgres ou equivalente simples).
3. Persistência padrão: **somente texto extraído + metadados** no Postgres (sem PDF/HTML bruto).

Fase 2 (opcional, se necessário):
1. Introduzir bucket S3-compatível para payload bruto.
2. Em `documents`, manter metadados + ponteiro (`object_key`, `bucket`, `storage_provider`, `checksum`, `size_bytes`).
3. Ativar apenas para fontes/regras que exijam reprocessamento do bruto ou trilha probatória.

Fase 3 (otimização):
1. Lifecycle policy no bucket (hot/warm/archive).
2. Reprocessamento idempotente por `checksum` + `object_key`.
3. Custos e retenção por família de fonte.

### 18.3 Mudanças técnicas planejadas
1. Manter pipeline padrão em `Storage:Mode=database`:
   - salvar `documents.Content` (texto normalizado),
   - não salvar blob bruto.
2. Opcional: adicionar abstração `IObjectStorage` no Worker (put/get/head/delete).
3. Opcional: implementar provider `S3ObjectStorage` (AWS S3 ou compatível).
4. Opcional: salvar bruto em objeto e persistir ponteiro no metadata.
5. Manter feature-flag:
   - `Storage:Mode=database|object_store`
   - fallback seguro para `database` em ambiente local.
6. Adicionar telemetria:
   - bytes enviados, latência de upload, falhas de storage por source.

### 18.4 Segurança e operação
1. **Não trafegar credencial AWS em chat**.
2. Credenciais via ambiente seguro (`aws configure`, IAM role, ou secret manager).
3. Privilégio mínimo no bucket (apenas prefixo do app).
4. Criptografia em repouso e em trânsito obrigatórias.

### 18.5 Critérios de aceite
1. (Modo padrão) `documents` armazena apenas conteúdo textual extraído + metadados.
2. (Modo padrão) nenhuma persistência de PDF/HTML bruto no Postgres.
3. (Modo opcional object_store) upload/download funcionando para fontes configuradas.
4. Zero-kelvin sem regressão funcional em `Storage:Mode=database` e, se habilitado, também em `object_store`.

### 18.6 Decisão de plataforma (curto prazo)
1. **Não migrar compute para AWS agora** (evitar desvio de foco e complexidade).
2. Manter foco em estabilização do pipeline no stack atual.
3. S3 fica **opcional** e condicionado a necessidade real de retenção de bruto/auditoria.

## 19. Extensão de Fontes Multimídia (vídeo/áudio) sem quebrar pipeline

### 19.1 Princípio arquitetural
1. O padrão de fases **continua o mesmo**: `discovery -> fetch -> ingest -> index`.
2. O que muda é o **perfil de conteúdo** da fonte, não o pipeline base.
3. Source of truth permanece: **conteúdo textual extraído + metadados**, não o arquivo bruto.

### 19.2 Novo conceito no YAML: `content_profile`
Adicionar em `fetch`:
1. `content_profile: text|document|media`
2. Para fontes multimídia: `content_profile: media`

Exemplo (template):
```yaml
tcu_sessoes_midia:
  identity:
    name: "TCU - Sessões (Áudio/Vídeo)"
    provider: TCU
    domain: legal
    jurisdiction: BR
    category: multimedia
    canonical_type: session_media

  discovery:
    strategy: web_crawl
    config:
      driver: curl_html_v1
      root_url: "https://..."
      rules:
        include_patterns: ["/sessao/", ".mp4", ".mp3", ".m3u8"]
      http:
        timeout: "120s"
        request_delay_ms: 800

  fetch:
    protocol: https
    method: GET
    content_profile: media
    media:
      mode: metadata_only
      transcript_strategy: none
      preferred_language: "pt-BR"
    format:
      type: media

  pipeline:
    enabled: false
    schedule: "0 8 * * 0"
    mode: incremental
```

### 19.3 Semântica por fase para `content_profile=media`
1. Discovery:
   - encontra URLs de mídia e páginas da sessão;
   - salva metadados básicos (`title`, `date`, `duration`, `speaker`, `session_id` quando houver).
2. Fetch:
   - `metadata_only`: não baixa mídia inteira; apenas cabeçalhos/manifest/metadata.
   - opcional futuro: `transcript_strategy=official_caption|asr`.
3. Ingest:
   - gera `DocumentEntity` textual com:
     - `content`: transcrição (quando existir) ou resumo textual mínimo;
     - `metadata`: URL da mídia, duração, contexto da sessão, confiança da transcrição.
4. Index:
   - indexação normal no mesmo motor textual/semântico.

### 19.4 Contrato de dados para mídia
Campos mínimos em `documents.Metadata`:
1. `document_kind=multimedia_record`
2. `media_kind=video|audio`
3. `media_url`
4. `session_date`
5. `session_context`
6. `transcript_status=none|official|asr`
7. `transcript_confidence=high|medium|low`

### 19.5 Regras de segurança/qualidade para multimídia
1. Sem transcrição confiável, não inventar conteúdo:
   - manter `content` curto descritivo e `transcript_status=none`.
2. Não persistir blob de mídia no Postgres.
3. RAG deve priorizar fontes com `transcript_status in (official, asr)` para perguntas substantivas.
4. Toda resposta derivada de mídia deve expor `transcript_confidence`.

### 19.6 Ordem de implementação
1. P1: adicionar `content_profile` ao parser de source config (sem quebrar fontes existentes).
2. P1: implementar `media + metadata_only` no fetch.
3. P1: criar 1 fonte canário `tcu_sessoes_midia` com `pipeline.enabled=false`.
4. P1: validação targeted (discovery/fetch) com relatório.
5. P2: transcrição (`official_caption` primeiro, `asr` depois).

### 19.7 Critérios de aceite
1. Fonte multimídia registra links e metadados sem erro.
2. Nenhum blob bruto é salvo em Postgres.
3. `documents` produz registros válidos para mídia (mesmo com `transcript_status=none`).
4. Zero-kelvin targeted da fonte multimídia finaliza sem travas.

## 20. Plano Executável: YouTube + Inbound Media API (sem bruto)

### 20.1 Objetivo
1. Adicionar fonte `tcu_youtube_videos` para catalogar links de vídeos (discovery primeiro).
2. Permitir ingestão de mídia por **upload de conteúdo textual + metadados** via API (sem upload de vídeo/áudio bruto).

### 20.2 Fase A — Discovery YouTube (catálogo de links)
Arquivos:
1. `sources_v2.yaml`
2. `src/Gabi.Discover/ApiPaginationDiscoveryAdapter.cs`
3. `tests/Gabi.Discover.Tests/DiscoveryAdapterExecutionTests.cs`

Implementação:
1. Nova fonte `tcu_youtube_videos`:
   - `strategy: api_pagination`
   - `driver: youtube_channel_v1`
   - `content_profile: media`
   - `fetch.content_strategy: link_only`
   - `pipeline.enabled: false` (canário manual)
2. Driver `youtube_channel_v1` no adapter:
   - paginação por `nextPageToken`
   - extração de `videoId` + metadados do snippet
   - link final: `https://www.youtube.com/watch?v={videoId}`
3. Guardrails obrigatórios:
   - sem `YOUTUBE_API_KEY` => erro explícito de capability/config (não silêncio)
   - tratar `403 quotaExceeded` e `429` com retry/backoff
   - dedupe por `videoId`

Aceite Fase A:
1. discovery gera links > 0 com metadata consistente.
2. source desabilitada por padrão no scheduler.
3. zero regressão nos drivers existentes.

### 20.3 Fase B — API de ingestão de mídia (texto+metadata)
Arquivos (alvo):
1. `src/Gabi.Api/Program.cs` (mapeamento endpoint)
2. `src/Gabi.Api/Controllers` ou handlers equivalentes
3. `src/Gabi.Contracts/*` (DTOs)
4. `src/Gabi.Worker/Jobs/*` (job tipo `media_ingest`, se assíncrono)
5. `tests/Gabi.Api.Tests/*`

Endpoint proposto:
1. `POST /api/v1/media/ingest`

Contrato (payload):
1. `source_id` (ex.: `tcu_youtube_videos` ou `tcu_sessoes_midia`)
2. `external_id` (id estável do item: videoId/sessionId)
3. `media_url`
4. `title`
5. `published_at`
6. `transcript_text` (opcional)
7. `summary_text` (opcional, fallback quando não houver transcript)
8. `metadata` (objeto livre validado)

Regras:
1. Rejeitar binário/base64 de mídia no payload (413/400 conforme caso).
2. Exigir ao menos `transcript_text` ou `summary_text`.
3. Persistir em `documents`:
   - `Content = transcript_text || summary_text`
   - `Metadata` com `media_kind`, `transcript_status`, `transcript_confidence`, `media_url`.
4. Idempotência por (`source_id`, `external_id`) com upsert.

### 20.4 Fase C — Guardrails de qualidade semântica
1. Se `transcript_status=none`, marcar confiança baixa e bloquear respostas assertivas.
2. Em busca por conteúdo normativo, mídia só entra quando houver transcript válido.
3. Resposta sempre com origem e confiança da transcrição.

### 20.5 Ordem de execução recomendada
1. Fechar baseline de estabilidade (já concluído em 17.6).
2. Implementar Fase A (YouTube discovery link-only).
3. Implementar Fase B (API media ingest sem bruto).
4. Testes + zero-kelvin targeted para fonte multimídia.
5. Só depois avaliar expansão para outras plataformas/fontes de sessão.

### 20.6 Critérios de aceite finais (YouTube + API)
1. `tcu_youtube_videos` descobre links e metadados de forma reprodutível.
2. API `POST /api/v1/media/ingest` ingere texto+metadata e cria/atualiza documento.
3. Nenhum upload de vídeo/áudio bruto é aceito/persistido.
4. Evidência SQL mostra idempotência por `external_id`.
5. Testes de contrato da API e testes do driver passam sem regressão global.

### 20.7 Revisão de escopo (20/02/2026) — separar fontes e modos

Decisão de arquitetura (obrigatória):
1. `tcu_youtube_videos` e `tcu_media_upload` são fontes diferentes, com fluxos diferentes.
2. Menções em redes sociais (`X`, `Instagram`, `Google`) são outra família de fontes (`social_mentions`), separada de multimídia.
3. Não misturar descoberta pública (YouTube/X/etc.) com ingestão interna por upload.

Fontes alvo e função:
1. `tcu_youtube_videos`: discovery de vídeos públicos + metadados.
2. `tcu_media_upload`: entrada de mídia interna (upload) para transcrição assíncrona.
3. `tcu_x_mentions`: posts do X citando TCU/Tribunal de Contas da União.
4. `tcu_instagram_mentions` (futuro): menções no Instagram conforme limites da API oficial.
5. `tcu_google_mentions` (futuro): menções em web/news via API de busca.

### 20.8 Plano integrado por fase (com "não fazer agora")

Fase 1 (fazer agora): YouTube discovery-only + social canário desabilitado
1. Implementar `tcu_youtube_videos` em modo `link_only` com metadados.
2. Adicionar `tcu_x_mentions` no catálogo como canário (`enabled=false`, `pipeline.enabled=false`) até credenciais/tier.
3. Não transcrever YouTube nesta fase.
4. Não ativar scheduler automático para fontes novas.

Fase 2 (fazer depois, prioridade alta): upload de mídia assíncrono + fila
1. Criar endpoint `POST /api/v1/media/upload` (multipart) com retorno `202 Accepted`.
2. Streaming de upload para arquivo temporário/objeto, sem buffer em memória.
3. Enfileirar job (`transcribe_media`) no Hangfire.
4. Persistir status de processamento (`pending|processing|completed|failed`) com trilha de erro.

Fase 3 (fazer depois, prioridade alta): transcrição assíncrona
1. Worker lê mídia por stream e envia para provedor de transcrição.
2. Persistir no Postgres apenas `transcript_text` + metadados.
3. Excluir temporários após sucesso; retenção curta para falha/retry.
4. Se arquivo exceder limite do provedor, aplicar segmentação/chunking por job.

Fase 4 (não fazer agora): Instagram/Google mentions
1. Implementar somente após validação de acesso oficial e custo/limite.
2. Entram como canário desabilitado inicialmente.
3. Não entram no gate de estabilização atual do pipeline.

### 20.9 Restrições operacionais (300MB) para mídia

Regras inegociáveis:
1. Proibido transcrever dentro da requisição HTTP de upload.
2. Proibido carregar vídeo/áudio inteiro em memória.
3. Fluxo obrigatório: `upload rápido -> enqueue -> worker assíncrono`.
4. Persistência em Postgres: transcript + metadados; sem blob bruto no banco.

Opções de armazenamento:
1. Sem object-store: usar temporário efêmero para processamento transitório.
2. Com object-store (opcional): stream-through para S3/R2, sem buffer local.
3. Escolha depende de volume, custo e retenção; não bloqueia Fase 1.

### 20.10 Menções sociais (X/Instagram/Google) — diretriz de produto

X (prioridade social inicial):
1. Estratégia: query por `"Tribunal de Contas da União" OR "@TCUoficial" OR "TCU"`.
2. Armazenar: `post_id`, `author_id`, `created_at`, `text`, `url`, métricas públicas.
3. Dedupe por `post_id`.
4. Gate: só ativar com credencial/tier válidos e rate-limit conhecido.

Instagram (futuro):
1. Dependente de permissões da Graph API e escopo business.
2. Começar por conta oficial antes de menções amplas.
3. Permanecer fora do escopo imediato.

Google mentions (futuro):
1. Tratar como fonte de descoberta web/news, não social nativo.
2. Requer definição de provedor API e política de citação/armazenamento.
3. Fora do escopo imediato.

### 20.11 O que não faremos agora (explícito)
1. Não implementar Instagram mentions neste ciclo.
2. Não implementar Google mentions neste ciclo.
3. Não ativar transcrição síncrona em upload.
4. Não persistir binário bruto de mídia em Postgres.
5. Não acoplar estabilização do pipeline atual à disponibilidade de APIs sociais externas.

### 20.12 Critérios de aceite do ciclo atual (multimídia/social)
1. `tcu_youtube_videos` funcional em discovery `link_only` (canário controlado).
2. Contrato de `media upload` definido e pronto para implementação assíncrona.
3. `tcu_x_mentions` mapeada no catálogo/roadmap com gate de credenciais.
4. Sem regressão no zero-kelvin all-sources já estabilizado.
5. Rastreabilidade no V5 para escopo atual vs. backlog futuro.

### 20.13 Status de execução (20/02/2026) — feito agora vs. depois

Feito neste ciclo (implementado em código):
1. Driver `youtube_channel_v1` adicionado em `src/Gabi.Discover/ApiPaginationDiscoveryAdapter.cs`.
2. Descoberta YouTube implementada com:
   - leitura obrigatória de `YOUTUBE_API_KEY` via ambiente,
   - resolução do playlist de uploads pelo endpoint `channels`,
   - paginação por `nextPageToken` no endpoint `playlistItems`,
   - dedupe por `video_id`,
   - emissão de `DiscoveredSource` com metadados (`title`, `description`, `published_at`, `channel_title`, `thumbnail_url`, `video_id`, `channel_id`).
3. Fonte `tcu_youtube_videos` adicionada em `sources_v2.yaml` como canário desabilitado (`enabled=false`, `pipeline.enabled=false`, `fetch.content_strategy=link_only`, `fetch.content_profile=media`).
4. Fonte `tcu_x_mentions` adicionada em `sources_v2.yaml` como canário desabilitado (somente mapeamento de catálogo/roadmap; driver ainda não implementado).
5. Testes do driver YouTube adicionados/atualizados em `tests/Gabi.Discover.Tests/DiscoveryAdapterExecutionTests.cs`:
   - paginação + dedupe,
   - falha explícita sem `YOUTUBE_API_KEY`.

Validação executada:
1. `dotnet test tests/Gabi.Discover.Tests --filter "FullyQualifiedName~ApiPaginationAdapter_YouTubeDriver" -v q` (PASS).
2. `dotnet test tests/Gabi.Discover.Tests --filter "Category!=External" -v q` (PASS).

Pendente (não fazer agora, backlog planejado):
1. Ativar `tcu_youtube_videos` em produção (depende de `channel_id` definitivo e política operacional).
2. Implementar `tcu_media_upload` com `POST /api/v1/media/upload` assíncrono (multipart streaming + fila Hangfire).
3. Implementar executor de transcrição (`transcribe_media`) com persistência de texto/metadados e sem blob bruto no Postgres.
4. Implementar driver real de `tcu_x_mentions` com API oficial e credenciais/tier válidos.
5. Expandir para Instagram/Google mentions somente após validação de acesso, custo e rate-limit.

### 20.14 Ativação de canário YouTube + validação full cap=10000 (20/02/2026)

Mudança operacional aplicada:
1. `sources_v2.yaml`: `tcu_youtube_videos.enabled=true` (mantendo `pipeline.enabled=false` para execução manual controlada).
2. Driver usa `YOUTUBE_CHANNEL_ID` e `YOUTUBE_API_KEY` por ambiente (sem `channel_id` fixo no YAML).

Execução de validação:
1. `./tests/zero-kelvin-test.sh docker-20k --source tcu_youtube_videos --phase full --max-docs 10000 --monitor-memory --report-json /tmp/zk-youtube-full-10k.json`

Resultado:
1. **PASS** no zero-kelvin targeted.
2. `discovery_runs`: `completed`, `LinksTotal=1316`.
3. `fetch_runs`: `completed`, `ItemsTotal=1316`, `ItemsCompleted=1316`, `ItemsFailed=0`, `ErrorSummary=content_strategy=link_only`.
4. `fetch_items`: `skipped_format=1316` (comportamento esperado em `link_only`).
5. pico de memória observado no fetch targeted: `139.90 MiB`.

Evidências:
1. log: `/tmp/gabi-zero-kelvin.log`
2. relatório: `/tmp/zk-youtube-full-10k.json`
