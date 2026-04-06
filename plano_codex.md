## Plano Revisado (Pronto para Execução): H1/H2 + parsed.*
  por fonte + tagging por spans

  ### Resumo

  Arquitetura mantida e trancada:

  - RAW imutável.
  - H1 somente DOU (classificação tipo/subtipo).
  - Parser estrutural por source (11 parsers, 11 tabelas
    parsed.*).
  - H2 para todas as fontes com span tagging
    ({tag,start,end}) e geração determinística de XML.
  - Fila assíncrona para enrichment e fallback de baixa
    confiança do H1.

  Ajustes incorporados:

  - Performance de query em tags (TEXT[] desnormalizado +
    GIN).
  - Timeout/recuperação de lock na queue.
  - Vocabulário de tags versionado em código (fonte da
    verdade).
  - body_tagged_xml definido como campo IA-only (não indexar
    para busca textual).

  ### Mudanças de Contrato e DDL

  1. Em cada parsed.<source>:

  - tag_spans JSONB NOT NULL DEFAULT '[]'::jsonb
  - tags_flat TEXT[] NOT NULL DEFAULT '{}'  (derivado de
    tag_spans)
  - body_tagged_xml TEXT (uso LLM/readability; fora do índice
    textual de busca)
  - summary_*, legal_entities, topics, chunk_summaries
  - parser_version, h1_version (DOU), h2_version,
    prompt_version
  - content_hash, enrichment_input_hash, enrichment_status

  2. Índices:

  - GIN(tags_flat) para filtro por tag.
  - Índices de campos estruturais por fonte (datas, número de
    acórdão, órgão, etc.).
  - Sem índice textual em body_tagged_xml.

  3. parsed.enrichment_queue:

  - Colunas: status, next_retry_at, attempts, locked_by,
    locked_at, last_error, priority.
  - Índices: (status, next_retry_at, priority), (locked_by,
    locked_at).
  - Regra de recuperação de lock morto: worker considera
    disponível quando locked_at < now() - interval '10
    minutes'.

  ### Implementação por Fases

  1. Phase 0 — Amostragem DOU (10k estratificada):

  - Estratos: seção, período, órgão, hints de tipo.
  - Entregáveis: dataset de calibração + relatório de
    cobertura por estrato.

  2. Phase 1 — Migração SQL:

  - Criar schema parsed, tabelas por source, queue, índices.
  - Adicionar métricas/telemetria de cobertura por campo/tag.

  3. Phase 2 — H1 DOU:

  - Taxonomia 2 níveis (tipo + subtipo).
  - Regras determinísticas + confiança.
  - UNKNOWN entra em fallback assíncrono LLM via queue (sem
    bloquear parser).

  4. Phase 3 — 11 parsers estruturais:

  - Um parser por source, tipagem forte, ON CONFLICT DO
    UPDATE.
  - DOU usa saída H1 para escolher trilha de extração.
  - TCU segue por source uniforme.

  5. Phase 4 — H2 enrichment:

  - Gerar tags_flat e body_tagged_xml deterministicamente.

  - Vocabulário de tags: em código, versionado
    (allowed_tags_version) por source.
  - Parser/H2 validam contra vocabulário; rejeitam tag fora
    da lista.
  - Prompt versionado e auditável (prompt_version, hash do
    prompt/few-shots).
  - Reprocessamento seletivo por mudança de hash/versão.

  ### Testes e Aceite

  - H1: avaliação estratificada na amostra 10k, matriz de
    confusão, taxa de UNKNOWN.
  - Parsers: contrato de tipos, idempotência, cobertura de
    campos obrigatórios.
  - H2: validação de spans (sem overlap, bounds válidos, tags
    permitidas), retry e lock recovery.
  - Regressão: alarmes de fill-rate e cobertura de tags por
    parser_version/h2_version.

  ### Assunções

  - body_tagged_xml é artefato para consumo de IA e
    auditoria, não para ranking textual.
  - Busca textual permanece baseada em campos limpos
    (search_all/equivalentes), não em XML anotado.
  - Fases 3 e 4 serão sequenciais (H2 só após estabilidade
    mínima dos parsers).