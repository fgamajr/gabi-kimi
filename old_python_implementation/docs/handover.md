# Handover — Projeto GABI

**Data**: 2026-02-10  
**Autor**: Sessão assistida por IA (branch `kimi`)  
**Audiência**: Próximo agente / desenvolvedor que continuar o trabalho  

---

## 1. O Que é o GABI

**GABI — Gerador Automático de Boletins por Inteligência Artificial** é uma plataforma do TCU (Tribunal de Contas da União) para ingestão, indexação e busca semântica de documentos jurídicos. Acórdãos, normas, súmulas, publicações em PDF, leis da Câmara — tudo entra por um pipeline automatizado e fica disponível para busca híbrida (texto + vetorial) via API REST e integração MCP com o ChatTCU.

**Versão**: 2.1.0 (`pyproject.toml`)  
**Python**: ≥3.10 (rodando localmente no 3.10.12, spec original dizia 3.11+, relaxamos para funcionar na máquina de dev)  
**Branch ativa**: `kimi` — 238 arquivos alterados, 71.683 inserções à frente de `main`

---

## 2. Arquitetura do Projeto

### 2.1 Visão Geral

```
┌──────────────┐     ┌────────────────────────────────────────────────────┐     ┌──────────────┐
│   Fontes     │────▶│  Discovery → Fetch → Parse → Fingerprint → Dedup │────▶│   Storage    │
│  TCU/Câmara  │     │  → Chunk → Embed → Index                         │     │ PG + ES +    │
└──────────────┘     └────────────────────────────────────────────────────┘     │ Redis        │
                                                                               └──────┬───────┘
                                                                                      │
                     ┌─────────────┐     ┌──────────────┐                             │
                     │   ChatTCU   │◀────│  API / MCP   │◀────────────────────────────┘
                     └─────────────┘     └──────────────┘
```

### 2.2 Stack Tecnológica

| Componente | Tecnologia | Finalidade |
|---|---|---|
| **Web framework** | FastAPI 0.109.2 | API REST, lifespan, middleware stack |
| **ORM** | SQLAlchemy 2.0.28 (async) | Modelos, queries, sessões async |
| **Migrations** | Alembic 1.13.1 | 7 migrations (001–007), todas aplicadas |
| **Banco** | PostgreSQL 15 + pgvector | Documentos, chunks, vetores 384d |
| **Busca textual** | Elasticsearch 8.11.0 | BM25 full-text |
| **Cache/Broker** | Redis 6+ | Celery broker, rate limit, DLQ, cache |
| **Embeddings** | TEI (mock local) | `paraphrase-multilingual-MiniLM-L12-v2`, 384d (ADR-001 imutável) |
| **Task Queue** | Celery 5.3.6 | Pipeline assíncrono (sync tasks) |
| **CLI** | Typer 0.9.0 | `gabi ingest`, `gabi ingest-all`, `gabi status`, `gabi reindex` |
| **MCP** | JSON-RPC 2.0 / SSE | Integração com ChatTCU, porta 8001 |
| **Auth** | JWT RS256 / Keycloak | Desabilitado em dev, obrigatório em prod |

### 2.3 Estrutura de Diretórios

```
src/gabi/
├── api/            # Endpoints REST (admin, dashboard, documents, health, search, sources)
├── auth/           # JWT middleware, token revocation
├── cli.py          # CLI entry points (ingest, ingest-all, reindex, status)
├── config.py       # 80+ campos Pydantic Settings, prefixo GABI_
├── crawler/        # Base agent, metadata, navigator, orchestrator, politeness
├── db.py           # Engine SQLAlchemy async
├── dependencies.py # FastAPI dependency injection
├── exceptions.py   # Hierarquia de exceções com status codes
├── governance/     # Audit, catalog, lineage, quality checks
├── logging_config.py
├── main.py         # App factory FastAPI com lifespan e 6 middlewares
├── mcp/            # MCP server (resources, tools, server.py)
├── metrics.py      # Prometheus integration
├── middleware/      # Rate limit, request ID, security headers
├── models/         # SQLAlchemy models (document, chunk, source, execution, audit, lineage, DLQ, cache)
├── pipeline/       # O CORE: discovery, fetcher, parser, chunker, embedder, indexer, contracts, transforms
├── schemas/        # Pydantic request/response schemas
├── services/       # Lógica de negócio (search, elasticsearch setup, embedding, indexing, discovery)
├── tasks/          # Celery tasks (sync, DLQ, health, alerts)
├── types.py        # Enums globais (SourceType, DocumentStatus, etc.)
└── worker.py       # Celery worker config
```

### 2.4 Pipeline de Ingestão (`src/gabi/tasks/sync.py`)

O core do sistema. Cada source definida em `sources.yaml` passa por:

1. **Discovery** (`pipeline/discovery.py`): Descobre URLs a processar  
   - 5 modos: `static_url`, `url_pattern`, `api_pagination`, `crawler`, `api_query`
2. **Fetch** (`pipeline/fetcher.py`): Download HTTP com streaming, SSRF protection, circuit breaker  
   - Diskless: tudo em memória (sem temp files, compatível com Fly.io)
3. **Parse** (`pipeline/parser.py`): Extrai documentos estruturados  
   - 4 formatos: CSV, HTML, PDF (pdfplumber/pymupdf), JSON
4. **Fingerprint** (`pipeline/fingerprint.py`): SHA-256 do conteúdo para dedup
5. **Dedup** (`pipeline/deduplication.py`): Verifica duplicatas via fingerprint
6. **Chunk** (`pipeline/chunker.py`): Divide em pedaços semânticos  
   - Legal-document-aware: regex para ementa, acórdão, relatório, voto, artigo, parágrafo, inciso, alínea
7. **Embed** (`pipeline/embedder.py`): Gera vetores 384d via TEI  
   - Circuit breaker, request coalescing, retry
8. **Index** (`pipeline/indexer.py`): Persiste em PG + ES  
   - Saga pattern: escrita atômica com rollback compensatório

### 2.5 Busca Híbrida (`services/search_service.py`)

Combina BM25 (Elasticsearch) + Similaridade Cosseno (pgvector) via **Reciprocal Rank Fusion (RRF)**. Parâmetro `k=60` configurável. Suporta filtros por `source_id`, `document_type`, date range.

### 2.6 Sources (`sources.yaml`)

13 fontes declaradas, 11 habilitadas. Sistema **plugável** — basta adicionar YAML, pipeline trata automaticamente.

| Source | Formato | Discovery | Status |
|---|---|---|---|
| `tcu_acordaos` | CSV | url_pattern | ✅ 100 docs, 211 chunks |
| `tcu_normas` | CSV | static_url | ❌ OOM (ver §5) |
| `tcu_sumulas` | CSV | static_url | ✅ 100 docs, 156 chunks |
| `tcu_jurisprudencia_selecionada` | CSV | static_url | ✅ 100 docs, 158 chunks |
| `tcu_resposta_consulta` | CSV | static_url | ✅ 100 docs, 321 chunks |
| `tcu_informativo_lc` | CSV | static_url | ✅ 100 docs, 281 chunks |
| `tcu_boletim_jurisprudencia` | CSV | static_url | ✅ 100 docs, 100 chunks |
| `tcu_boletim_pessoal` | CSV | static_url | ✅ 100 docs, 100 chunks |
| `tcu_publicacoes` | PDF | crawler | ✅ 100 docs, 348 chunks |
| `tcu_notas_tecnicas_ti` | PDF | crawler | ✅ 7 docs, 443 chunks |
| `camara_leis_ordinarias` | JSON | api_query | ✅ 100 docs, 100 chunks |
| `stf_decisoes` | CSV | static_url | ⏸ Desabilitado (endpoints não funcionam) |
| `stj_acordaos` | CSV | url_pattern | ⏸ Desabilitado (endpoints não funcionam) |

**Total atual**: 907 documentos, 2.218 chunks, 10/11 sources ativas ingeridas com sucesso.

---

## 3. Infraestrutura Local Atual

| Serviço | Tipo | Acesso | Obs |
|---|---|---|---|
| PostgreSQL 15 + pgvector | Docker (`gabi-postgres-local`) | `127.0.0.1:15432` | Creds: `gabi:gabi`, DB: `gabi` |
| Elasticsearch 8.11.0 | Docker (`gabi-elastic-local`) | `127.0.0.1:9200` | ~1 GB RAM |
| Redis 6.0.16 | apt nativo | `127.0.0.1:6379` | |
| Mock TEI (embeddings) | FastAPI (`mock_tei.py`) | `127.0.0.1:8080` | Vetores 384d determinísticos |

**Variáveis de ambiente**:
```bash
GABI_DATABASE_URL='postgresql+asyncpg://gabi:gabi@127.0.0.1:15432/gabi'
GABI_ELASTICSEARCH_URL='http://127.0.0.1:9200'
GABI_REDIS_URL='redis://127.0.0.1:6379/0'
GABI_EMBEDDINGS_URL='http://127.0.0.1:8080'
GABI_AUTH_ENABLED=false
GABI_FETCHER_SSRF_ENABLED=false
GABI_PIPELINE_FETCH_MAX_SIZE_MB=30
```

**Máquina**: 7.6 GB RAM total. ~4.8 GB em uso (VS Code, Pylance, Elasticsearch, etc). **Livre ≈ 2.5–3 GB**.

---

## 4. Erros Encontrados, Como Corrigimos e Por Quê

### 4.1 Migrations: ENUM → VARCHAR (migration 006)

**Problema**: A migration 001 criou colunas com tipos `ENUM` nativos do PostgreSQL (`source_type`, `document_status`, etc.), mas os modelos SQLAlchemy usavam `mapped_column(String)`. Quando o Python enviava strings puras (ex: `"url_pattern"`), o PG rejeitava porque o valor não existia no tipo ENUM. Além disso, o enum Python `SourceType` tinha valores (`url_pattern`, `static_url`, `api_query`) que nunca foram adicionados ao DB.

**Decisão de design**: Converter **todos** os ENUM → VARCHAR (migration 006), em vez de só adicionar valores faltantes ao ENUM existente. Razão: o sistema é plugável — novos `SourceType`, `DocumentStatus`, etc. podem surgir conforme o projeto evolui. ENUMs exigem ALTER TYPE para cada novo valor, o que é uma bomba-relógio em produção. VARCHAR com CHECK constraints é mais flexível e alinhado com o padrão dos models SQLAlchemy.

**Complexidade**: A migration teve que: (1) dropar todos os índices em tabelas com ENUM (PG bake-a o tipo em WHERE parciais), (2) dropar views e functions que referenciavam ENUMs, (3) converter colunas, (4) dropar tipos ENUM, (5) recriar índices/triggers/constraints. Tudo em transação única.

### 4.2 Chunks: Soft delete ausente (migration 007)

**Problema**: O modelo `DocumentChunk` herda de `SoftDeleteBase` (que provê `is_deleted`, `deleted_at`, `deleted_reason`, `deleted_by`), mas a migration 001 não incluiu essas colunas na tabela `document_chunks`. Qualquer query com `.filter(is_deleted == false)` falhava.

**Fix**: Migration simples adicionando as 4 colunas com defaults corretos.

### 4.3 Discovery: `crawler` e `api_query` não existiam

**Problema**: `DiscoveryEngine` só tratava 3 modos (`static_url`, `url_pattern`, `api_pagination`). Três sources (`tcu_publicacoes`, `tcu_notas_tecnicas_ti`, `camara_leis_ordinarias`) usam `crawler` ou `api_query`. O fallback era o `PipelineOrchestrator`, que retornava apenas a `root_url` crua — o que para um crawler significava baixar 1 página HTML e obter 0 PDFs.

**Decisão de design**: Implementar os handlers diretamente no `DiscoveryEngine`, não criar um sistema separado de crawling. Razão: Discovery já tinha a arquitetura de handlers registrados por modo, extensível. Criar um crawler separado adicionaria complexidade sem benefício real — o que precisamos é descobrir URLs, não navegar sites complexos.

**O que foi implementado** (`discovery.py`):
- `_handle_crawler()`: HTTP-based (sem Playwright para simplificar). Suporta paginação via query param, extração de links via regex (convertido de seletores CSS), depth-2 crawling (listing → detail → asset), e dedup por URL visitada.
- `_handle_api_query()`: Dispatch por `driver`. Implementado `_discover_camara_api()` para a API v2 de Proposições da Câmara, com paginação ano-a-ano e limite configurável.
- `_selector_to_regex()`: Converte seletores CSS-like (`a[href$='.pdf']`) para regex de extração de href.
- `_resolve_url()`: Resolve URLs relativas contra base URL.

**Decisão explícita**: Usar httpx puro em vez de Playwright para crawling. Razão: o mock local não precisa renderizar JS, e as páginas do TCU são server-rendered. Playwright seria necessário só se JS dinâmico gerasse os links — o que não é o caso hoje. Se surgir esse caso, pode-se adicionar um handler `crawler_js` que use Playwright.

**Também em `sync.py`**:
- `_run_discovery()` agora passa `crawler_rules` e `api_query_config` direto do YAML para o `DiscoveryConfig`.
- Removido o fallback para `PipelineOrchestrator` (dead code, mal integrado).
- Lógica de `max_urls` por modo: `1` para `url_pattern` (cada CSV URL contém muitas rows), `max_documents_per_source` para `crawler`/`api_query` (cada URL = 1 documento).

### 4.4 CSS `:not()` quebrava conversão para regex

**Problema**: O seletor `a[href*='/publicacoes-institucionais/']:not([href$='todas'])` (do `tcu_publicacoes`) era passado para `_selector_to_regex()`. A heurística antiga `if "(" in selector: return selector` tratava como "já é regex" por causa dos parênteses de `:not()`. A string CSS crua usada como regex causava `bad character range s-i at position 20` porque `publicacoes-institucionais` dentro de `[...]` regex interpreta `s-i` como range de caracteres.

**Decisão de design**: Detecção inteligente em vez de parser CSS completo. A nova heurística: `if "(" in selector and not re.search(r':not\(|:has\(|a\[', selector)` — só trata como regex bruto se tiver parênteses E não parecer CSS. Para `:not()`, extrai a cláusula, processa o seletor base normalmente, e adiciona negative lookahead ao regex gerado.

**Alternativa rejeitada**: Usar um parser CSS real (cssselect/lxml). Overkill para 3 padrões que o sistema precisa converter. O custo de manutenção de uma dependência extra não justifica.

### 4.5 JSONParser: campo errado no `ParsedDocument`

**Problema**: O `JSONParser` (novo) passava `preview=self._create_preview(...)` ao construir `ParsedDocument`, mas o campo correto é `content_preview`. Também faltavam `source_id`, `title`, `url`. Resultado: 100 URLs da Câmara eram fetched e detectadas como JSON, mas o parser crashava com `TypeError: unexpected keyword argument 'preview'`.

**Fix**: Alinhar com a assinatura real de `ParsedDocument` em `contracts.py`. Erro de copiar estrutura de outro parser sem verificar o contrato.

### 4.6 Fetcher: Refactor para diskless (sessão anterior)

**Problema**: O fetcher original escrevia em disco para arquivos grandes (`_stream_to_temp_file()`). Fly.io (target de deploy) não tem disco persistente.

**Decisão de design**: `_stream_to_memory()` como único path. Todo conteúdo fica em bytes na RAM, hash SHA-256 computado incrementalmente durante streaming. O método antigo `_stream_to_temp_file()` permanece no código com `DeprecationWarning` — não removemos porque pode haver cenários futuros onde disco esteja disponível (K8s com volume mounted).

**Trade-off assumido**: Isso cria o problema de OOM para arquivos grandes (ver §5). É a razão direta pela qual `tcu_normas` falha. A decisão foi pragmática: funcionar no Fly.io agora, resolver streaming depois.

---

## 5. O Problema Não Resolvido: OOM em Fontes Grandes

### O que acontece

`tcu_normas` é um CSV único de ~200+ MB servido como uma URL estática. O pipeline:

1. **Fetcher** baixa tudo em RAM (diskless) → ~200 MB em `bytes`
2. **Parser** decodifica para `str` → ~400 MB (bytes + string na memória simultâneos)
3. **csv.DictReader** constrói todos os rows em memória → N rows × tamanho
4. `ParseResult.documents` acumula `List[ParsedDocument]` → tudo antes de processar
5. **Resultado**: pico de ~600 MB–1 GB para um arquivo de 200 MB

Com apenas ~2.5 GB livres na máquina, o processo é OOM-killed pelo kernel.

### Por que é um problema arquitetural

O sistema é **plugável** — qualquer pessoa pode adicionar uma fonte ao `sources.yaml` e o pipeline deve lidar. Não controlamos tamanho de arquivo, quantidade de rows, ou ambiente de deploy. A arquitetura atual é **batch-oriented**:

```
fetch TUDO → parse TUDO → processar TUDO → indexar TUDO
```

A memória viva é **O(N)** no total de documentos. Deveria ser **O(1)** — um documento por vez.

### Amplificação tripla de memória

```
HTTP bytes (N) → string decodificada (~2N) → objetos Python (~3-5N) → todos retidos simultaneamente
```

O `config.py` tem `pipeline_max_memory_mb=3584` (default), mas **não é enforced em lugar nenhum** — é um campo morto.

### Solução proposta: Pipeline Streaming

A correção exige streaming em cada estágio:

| Estágio | Estado Atual | Proposta |
|---|---|---|
| **Fetch** | Junta todos os chunks em um `bytes` | Pipe do HTTP stream direto ao parser (sem materializar inteiro) |
| **Parse (CSV)** | `content.get_content()` → `str` → `csv.DictReader` → `List[ParsedDocument]` | `parse_stream()` → `AsyncIterator[ParsedDocument]` (yield por row) |
| **Sync loop** | `for doc in parsed_result.documents` (lista completa) | `async for doc in parser.parse_stream(stream)` (generator) |
| **Memory budget** | `pipeline_max_memory_mb` existe mas é ignorado | Enforce com `psutil`, backpressure, abort graceful |

**Prioridades de implementação**:

| Task | Esforço | Impacto | Prioridade |
|---|---|---|---|
| CSV streaming parser (async generator por row) | Médio | Alto — resolve OOM para todos CSVs grandes | **P0** |
| Pipe HTTP stream → parser (sem materialização) | Médio | Alto — elimina 2× de memória na decodificação | **P0** |
| `sync.py` consumir `AsyncIterator[ParsedDocument]` | Baixo | Alto — só glue code | **P0** |
| Memory budget enforcement com `psutil` | Baixo | Médio — safety net | P1 |
| Spill-to-disk para formatos não-streamáveis (PDF) | Médio | Médio — PDFs geralmente < 50 MB | P2 |
| Streaming JSON parser (para APIs grandes futuras) | Baixo | Baixo — JSONs atuais são pequenos | P2 |
| Teste de integração com CSV 200 MB+ | Baixo | Alto — guarda de regressão | P1 |

---

## 6. Outros Problemas e Dívida Técnica Conhecidos

### 6.1 Config lie: `camara_leis_ordinarias`
O YAML diz `parse: input_format: html` mas a API retorna JSON. Funciona porque `_run_parse()` em `sync.py` checa o `Content-Type` header antes do YAML. Mas é uma mentira no config — deveria ser `input_format: json`.

### 6.2 Dead code: `PipelineOrchestrator`
O import foi removido de `sync.py`, mas `src/gabi/pipeline/orchestrator.py` provavelmente ainda existe. Dead code a limpar.

### 6.3 Dead code: `_stream_to_temp_file()` no fetcher
Método deprecated e unreachable no fluxo atual. Mantido por compatibilidade futura, mas polui o código.

### 6.4 Isolamento de memória entre sources
Python não devolve memória ao OS após free. A memória de source A vaza para source B quando rodam no mesmo processo. Workaround atual: scripts shell que rodam cada source em **processo separado** (`run_ingest_all.sh`). O CLI deveria suportar `ingest-all --isolate-per-source` nativo.

### 6.5 Sem tratamento graceful de OOM
Quando OOM-killed: zero feedback — nenhum resultado parcial salvo, manifest fica em `running` para sempre no banco. Necessário: watchdog ou pre-check de memória disponível vs estimada, fail fast com mensagem clara.

### 6.6 Quarantine desabilitado
`_DEFAULT_QUARANTINE_ENABLED = False` porque o servidor é diskless. Arquivos suspeitos não são quarentenados — apenas logados. Em ambientes com disco, deveria ser habilitado.

### 6.7 Spec com 316 problemas catalogados
`GABI_SPECS_FINAL_v1.md` (3811 linhas) identifica **316 problemas** (59 críticos) em 9 categorias: arquitetura, data model, pipeline, segurança, escalabilidade, deploy, observabilidade, integração. Muitos marcados "✅ Corrigido" no spec, mas nem todos validados em runtime.

### 6.8 Mock TEI em produção
O `mock_tei.py` gera vetores determinísticos baseados em hash SHA-512 — **não são embeddings reais**. Funciona para testar o pipeline, mas busca semântica não produz resultados significativos. Para produção, precisa do TEI real com o modelo `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.

### 6.9 Testes unitários existem mas não rodaram
`tests/unit/` tem ~30 arquivos de teste. Não foram executados nesta sessão. Algumas mudanças (novos handlers de discovery, JSONParser, remoção do PipelineOrchestrator) podem ter quebrado testes existentes.

---

## 7. Progressão do Projeto

### O que está implementado e funcionando

- ✅ **Infraestrutura completa**: PG + pgvector + ES + Redis + Mock TEI
- ✅ **7 migrations** aplicadas com sucesso (schema estável)
- ✅ **Pipeline completo**: Discovery → Fetch → Parse → Fingerprint → Dedup → Chunk → Embed → Index
- ✅ **5 modos de discovery** operacionais
- ✅ **4 parsers** (CSV, HTML, PDF, JSON)
- ✅ **10/11 sources** ingeridas com sucesso (907 docs, 2218 chunks)
- ✅ **API REST** com FastAPI (CRUD, health, search, admin, sources, documents)
- ✅ **MCP Server** para integração com ChatTCU
- ✅ **Auth** JWT RS256 com Keycloak (desabilitado em dev, validações de prod)
- ✅ **Security**: SSRF protection, circuit breaker, rate limiting, security headers
- ✅ **Governance**: Audit logging, data lineage, quality checks, data catalog
- ✅ **Chunker legal-aware**: Regex para estruturas legais brasileiras
- ✅ **Fetcher diskless**: Compatível com Fly.io (sem temp files)
- ✅ **CLI funcional**: `gabi ingest`, `gabi status`
- ✅ **Seed script**: `seed_sources.py` popula `source_registry` a partir de `sources.yaml`

### O que está parcial ou placeholder

- ⚠️ **Celery worker**: Configurado mas não testado em modo distribuído (usamos `asyncio.run()` direto)
- ⚠️ **Busca híbrida**: Código existe mas não testada end-to-end com dados reais (mock TEI gera vetores sem semântica)
- ⚠️ **Crawler module** (`src/gabi/crawler/`): Existem arquivos de base agent, navigator, orchestrator, politeness — mas os handlers de discovery usam httpx direto, não este módulo
- ⚠️ **Transforms** (`pipeline/transforms.py`): Referenciado no mapping do YAML mas execução real limitada a `strip_quotes`
- ⚠️ **Change detection** (`pipeline/change_detection.py`): Código existe, não testado — sempre roda full re-ingest
- ⚠️ **Dashboard API** (`api/dashboard.py`): Endpoints existem mas sem frontend
- ⚠️ **Testes**: ~30 arquivos de teste, não executados nesta sessão

### O que não está implementado

- ❌ **Streaming pipeline** (OOM fix) — ver §5
- ❌ **Memory budget enforcement** (`pipeline_max_memory_mb` é dead config)
- ❌ **tcu_normas** ingestão (depende do streaming)
- ❌ **TEI real** (só mock rodando)
- ❌ **Deploy Fly.io** (tem `fly.toml` mas não deployado)
- ❌ **K8s** (tem manifests em `k8s/` mas não validados)
- ❌ **Frontend / Dashboard UI**
- ❌ **Monitoramento real** (Prometheus config existe, alertas K8s existem, nada ativo)

---

## 8. Arquivos Criados ou Modificados — Por Que Cada Um

### 8.1 `alembic/versions/006_enum_to_varchar.py` — CRIADO

**Contexto**: A migration 001 (original, de outra sessão) criou colunas com tipos `ENUM` nativos do PostgreSQL (`source_type`, `document_status`, `execution_status`, etc.). Os modelos SQLAlchemy, porém, usam `mapped_column(String)` — strings puras. Quando o pipeline tentava inserir `"url_pattern"` numa coluna tipada como `ENUM source_type`, o PostgreSQL rejeitava porque esse valor não existia no ENUM. O Python `SourceType` tinha valores que nunca foram registrados no DB.

**Por que não simplesmente adicionar os valores faltantes ao ENUM**: Porque o sistema é plugável. Novos tipos de source, status, etc. podem surgir a qualquer momento conforme fontes são adicionadas ao `sources.yaml`. Manter ENUMs exige `ALTER TYPE ... ADD VALUE` para cada novo valor — em produção, isso é uma bomba-relógio. VARCHAR com CHECK constraints é mais flexível e alinhado com a decisão já tomada nos models SQLAlchemy.

**Complexidade da migration**: PostgreSQL embute o tipo da coluna em partial indexes (cláusulas WHERE), views materializadas, e funções. Não era possível simplesmente `ALTER COLUMN ... TYPE VARCHAR` sem antes dropar todos os objetos dependentes. A migration: (1) dropa dinamicamente todos os índices em tabelas com ENUM, (2) dropa views e functions de audit, (3) converte cada coluna ENUM→VARCHAR, (4) dropa os tipos ENUM, (5) recria todos os índices, constraints e triggers. Tudo em transação única para garantir atomicidade.

---

### 8.2 `alembic/versions/007_chunks_soft_delete.py` — CRIADO

**Contexto**: O modelo Python `DocumentChunk` herda de `SoftDeleteBase`, que provê `is_deleted`, `deleted_at`, `deleted_reason`, `deleted_by`. Mas a migration 001 não incluiu essas colunas na tabela `document_chunks`. Qualquer query com `.filter(DocumentChunk.is_deleted == false)` (que é o padrão do SoftDeleteBase) falhava com "column does not exist".

**Por que uma migration separada em vez de corrigir a 001**: Porque a 001 já foi aplicada no banco. Alterar uma migration já executada é perigoso — Alembic rastreia pelo revision ID, não pelo conteúdo. Uma nova migration é a forma correta de evoluir o schema.

**Fix**: Simples `op.add_column()` para as 4 colunas, com `server_default='false'` para `is_deleted` garantir retrocompatibilidade com rows existentes.

---

### 8.3 `src/gabi/pipeline/contracts.py` — MODIFICADO

**Contexto**: O `FetchedContent` dataclass tinha campos `content_path` (caminho para temp file) e `is_streamed` (flag indicando se conteúdo está em disco). Após o refactor diskless do fetcher (§4.6), esses campos nunca são populados — conteúdo sempre fica em `self.content` (bytes em memória).

**O que mudou**: Marcamos `content_path` e `is_streamed` como DEPRECATED nos docstrings e comentários. Atualizamos `get_content()` para deixar claro que o fallback de leitura de arquivo é legacy. `cleanup()` virou noop documentado. Não removemos os campos para manter backward compatibility — código antigo que referencia esses campos não quebra, simplesmente recebe `None`/`False`.

**Por que não remover de vez**: O `contracts.py` é importado por muitos módulos (sync, fetcher, parser, indexer, tests). Remover campos causaria erros de importação em código que pode referenciá-los em type hints ou destructuring. O custo de deprecation é zero; o custo de quebra é alto.

---

### 8.4 `src/gabi/pipeline/discovery.py` — MODIFICADO (substancial)

**Contexto**: O `DiscoveryEngine` original só tratava 3 modos: `static_url`, `url_pattern`, `api_pagination`. Três sources no `sources.yaml` usam modos diferentes: `tcu_publicacoes` e `tcu_notas_tecnicas_ti` usam `crawler`, `camara_leis_ordinarias` usa `api_query`. Sem handlers para esses modos, o pipeline caía num fallback silencioso via `PipelineOrchestrator` que retornava a root URL crua — para um crawler, isso significava baixar uma página HTML de listagem e obter 0 PDFs úteis.

**O que foi adicionado**:

- **`_handle_crawler()`** (~100 linhas): Handler HTTP-based que: faz paginação via query param (`?pagina=N`), extrai links de assets (PDFs) via regex, suporta depth-2 (listing → detail page → asset), dedup por URL visitada, rate limiting. Usa httpx puro em vez de Playwright — decisão consciente porque as páginas do TCU são server-rendered (sem JS dinâmico gerando links).

- **`_handle_api_query()`** (~30 linhas): Dispatcher por `driver`. Para `camara_api_v1`, delega para `_discover_camara_api()`. Para `generic`, retorna a URL direta.

- **`_discover_camara_api()`** (~70 linhas): Pagina pela API v2 de Proposições da Câmara dos Deputados (dados abertos). Itera por ano (mais recente primeiro), página por página, extraindo URI de cada proposição. Respeita `max_urls` e `rate_limit_delay`.

- **`_selector_to_regex()`** reescrito: Converte seletores CSS-like (`a[href$='.pdf']`, `a[href*='/publicacoes/']:not([href$='todas'])`) para regex de extração de href. O rewrite foi necessário porque a versão anterior tinha um bug: tratava qualquer string com `(` como "já é regex", mas `:not()` do CSS contém parênteses. A nova versão detecta inteligentemente CSS vs regex.

- **`_resolve_url()`**: Helper para resolver URLs relativas contra base URL. Necessário porque links extraídos de HTML frequentemente são relativos (`/path/to/file.pdf`).

- **`DiscoveryConfig` expandido**: Adicionados campos `crawler_rules` e `api_query_config` para passar configuração do YAML direto ao engine.

---

### 8.5 `src/gabi/pipeline/fetcher.py` — MODIFICADO

**Contexto**: O fetcher original tinha dois paths: `_stream_to_memory()` para arquivos pequenos e `_stream_to_temp_file()` para grandes. O deploy target (Fly.io) não tem disco persistente — temp files falham silenciosamente ou causam erros de I/O.

**O que mudou**: O método `fetch()` agora **sempre** usa `_stream_to_memory()`, independente do `Content-Length`. A branching logic que decidia entre memória e disco foi removida. `_stream_to_temp_file()` foi mantido mas marcado como deprecated com `warnings.warn()`.

**Trade-off documentado**: Isso causa OOM para arquivos muito grandes (ver §5 — `tcu_normas` de ~200 MB). A decisão foi pragmática: funcionar no Fly.io **agora**, resolver streaming depois. O método deprecated permanece no código como opção para ambientes com disco (K8s com volume mounted).

---

### 8.6 `src/gabi/pipeline/parser.py` — MODIFICADO (substancial)

**Contexto**: O parser registry tinha 3 formatos: CSV, HTML, PDF. A source `camara_leis_ordinarias` retorna JSON (mesmo o YAML dizendo `html` — auto-detection pelo Content-Type header salva). Precisávamos de um `JSONParser` para processar corretamente as respostas da API da Câmara.

**O que foi adicionado**:

- **`JSONParser`** (~140 linhas): Parser completo para respostas JSON de APIs. Suporta: resposta direta (um doc por JSON), array de objetos, aninhamento via `data_path` (ex: `"dados"` para API da Câmara). Conteúdo textual construído concatenando campos configuráveis ou auto-detectando campos string. Registrado como `"json"` no parser registry.

- **Bug fix `preview` → `content_preview`**: O JSONParser inicialmente usava `preview=` ao construir `ParsedDocument`, mas o campo correto no dataclass é `content_preview`. Também faltavam `source_id`, `title`, `url`. Corrigido alinhando com `contracts.py`.

- **Quarantine disabled by default**: Mudou `_DEFAULT_QUARANTINE_ENABLED` de `True` para `False` e o env check de `"true"` para `"false"`. Razão: servidor diskless não pode escrever arquivos quarentenados. Apenas logamos suspeitas.

---

### 8.7 `src/gabi/tasks/sync.py` — MODIFICADO

**Contexto**: O `sync.py` é o orquestrador do pipeline — monta o fluxo Discovery→Fetch→Parse→...→Index. Precisava ser atualizado para suportar os novos modos de discovery e o novo parser JSON.

**O que mudou**:

- **`_run_discovery()` refatorado**: Antes usava um fallback para `PipelineOrchestrator` quando o modo era `crawler` ou `api_query`. Esse fallback foi removido (importava uma classe mal integrada que retornava URLs inúteis). Agora passa `crawler_rules` e `api_query_config` direto do YAML para `DiscoveryConfig`, deixando o `DiscoveryEngine` tratar tudo.

- **`max_urls` por modo**: Para `url_pattern` (CSV), `max_urls=1` porque cada URL contém milhares de rows. Para `crawler`/`api_query`, `max_urls=max_documents_per_source` porque cada URL = 1 documento.

- **JSON detection em `_run_parse()`**: Adicionado `elif "json" in content_type` que roteia para o `JSONParser` com configuração de `data_path`, `text_fields`, `id_field`, `title_field` extraídos do parse config.

- **Remoção do import `PipelineOrchestrator`**: Dead code eliminado.

---

### 8.8 `mock_tei.py` — CRIADO

**Contexto**: O pipeline de ingestão requer um serviço de embeddings (TEI — Text Embeddings Inference) para gerar vetores 384-dimensionais de cada chunk de texto. O TEI real (container HuggingFace) precisa de GPU ou pelo menos 4 GB de RAM dedicados — impossível na máquina de dev com ~2.5 GB livres.

**O que é**: Um servidor FastAPI mínimo (84 linhas) que implementa os endpoints `/embed` (TEI-compatible) e `/v1/embeddings` (OpenAI-compatible). Gera vetores **determinísticos** de 384 dimensões a partir de SHA-512 do texto de entrada, normalizados para vetor unitário. Mesmo texto = mesmo vetor, sempre.

**Por que determinístico**: Para garantir que re-ingestão do mesmo conteúdo produz os mesmos embeddings — essencial para testar deduplicação e fingerprinting sem ruído estocástico.

**Limitação**: Os vetores **não carregam semântica real**. Textos similares não produzem vetores próximos. Busca vetorial retorna resultados, mas sem relevância semântica. Para produção, substituir pelo TEI real com o modelo `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.

---

### 8.9 `seed_sources.py` — CRIADO

**Contexto**: O pipeline lê `sources.yaml` para saber quais fontes existem, mas busca na tabela `source_registry` do PostgreSQL para rastrear estado (status, contagem de documentos, erros, schedule). Sem registros no banco, `gabi ingest --source tcu_acordaos` não encontra a source.

**O que faz**: Lê `sources.yaml`, e para cada source habilitada: gera um `source_type` inferido do modo de discovery, computa um `config_hash` SHA-256 do YAML, e faz `INSERT ... ON CONFLICT DO UPDATE` na `source_registry`. Se a source já existe, apenas atualiza `config_hash` e `config_json` (para refletir mudanças no YAML).

**Por que um script separado em vez de fazer isso no startup da API**: Separação de concerns. O seed é uma operação administrativa (rodar uma vez após setup), não algo que a API deveria fazer em cada boot. Também evita race conditions quando múltiplos workers iniciam simultaneamente.

---

### 8.10 `handover.md` — CRIADO

**Contexto**: Ao fim de cada sessão de trabalho, é essencial documentar o estado completo para a próxima sessão/agente. Sem isso, o próximo agente perde ~30 minutos re-descobrindo: o que foi feito, por quê, o que funciona, o que está quebrado, e qual é a próxima tarefa.

**O que contém**: Visão completa do projeto (arquitetura, stack, pipeline), erros encontrados com decisões de design detalhadas, problema OOM não resolvido com análise e proposta de solução, dívida técnica catalogada, estado de progressão, instruções para retomar.

---

### 8.11 `run_ingest_all.sh` — CRIADO

**Contexto**: O comando `gabi ingest-all` roda todas as sources no mesmo processo Python. Problema: Python não devolve memória ao OS após `free()` (arena allocator). Memória consumida pela source A permanece alocada quando source B começa, causando crescimento monotônico até OOM.

**O que faz**: Executa cada source em um **processo Python separado** via loop bash. Quando o processo termina, o OS reclaim 100% da memória. Inclui: timeout por source, detecção de OOM-kill (exit code 137), contagem de docs/chunks do JSON de output, e query SQL final para resumo do banco.

**Por que shell script em vez de fix no CLI**: Workaround rápido enquanto o CLI não suporta `--isolate-per-source`. O script resolve o problema imediato sem alterar código Python.

---

### 8.12 `run_remaining.sh` — CRIADO

**Contexto**: Depois de ingerir `tcu_acordaos` (a primeira source testada), precisávamos continuar com as 10 restantes. Mas não queríamos re-ingerir `tcu_acordaos` que já estava ok.

**O que faz**: Mesmo padrão do `run_ingest_all.sh`, mas com a lista de sources excluindo `tcu_acordaos`. Timeout de 120s por source. Usado uma vez — pode ser deletado.

---

### 8.13 `run_fix_sources.sh` / `run_fix_sources2.sh` — CRIADOS

**Contexto**: Após implementar `_handle_crawler()` e `_handle_api_query()`, precisávamos re-ingerir especificamente `tcu_publicacoes` e `camara_leis_ordinarias` (as duas que falhavam antes dos novos handlers). A v1 (`run_fix_sources.sh`) incluía uma query SQL de contagem inline que tinha um bug (tabela `chunks` em vez de `document_chunks`). A v2 simplificou para só rodar ingestão e mostrar output.

**Podem ser deletados**: Serviram apenas para testar os fixes. Funcionalidade coberta pelo `run_ingest_all.sh`.

---

### 8.14 `run_reingest.sh` — CRIADO

**Contexto**: Terceira iteração de re-ingestion. Após corrigir o bug do CSS `:not()` em `_selector_to_regex()` e o bug `preview`→`content_preview` no JSONParser, precisávamos re-testar as 3 sources afetadas (`tcu_notas_tecnicas_ti`, `tcu_publicacoes`, `camara_leis_ordinarias`) com detecção de timeout (300s) e OOM (exit 137).

**Pode ser deletado**: Serviu para a rodada final de validação. Funcionalidade coberta pelo `run_ingest_all.sh`.

---

## 9. Como Retomar

### Quick start (serviços assumidos rodando)

```bash
cd /home/fgamajr/dev/gabi-kimi
source .venv/bin/activate

# Verificar serviços
docker ps                               # postgres + elasticsearch
redis-cli ping                          # PONG
curl -s http://127.0.0.1:8080/health    # mock TEI

# Verificar estado do DB
python -m gabi.cli status

# Ingerir uma source específica
python -m gabi.cli ingest --source tcu_acordaos --max-docs-per-source 10
```

### Se os serviços não estiverem rodando

```bash
# PostgreSQL + Elasticsearch
docker start gabi-postgres-local gabi-elastic-local

# Redis
sudo service redis-server start

# Mock TEI
python mock_tei.py &

# Variáveis de ambiente
export GABI_DATABASE_URL='postgresql+asyncpg://gabi:gabi@127.0.0.1:15432/gabi'
export GABI_ELASTICSEARCH_URL='http://127.0.0.1:9200'
export GABI_REDIS_URL='redis://127.0.0.1:6379/0'
export GABI_EMBEDDINGS_URL='http://127.0.0.1:8080'
export GABI_AUTH_ENABLED=false
export GABI_FETCHER_SSRF_ENABLED=false
export GABI_PIPELINE_FETCH_MAX_SIZE_MB=30
```

### Próxima tarefa: Streaming pipeline

1. Em `src/gabi/pipeline/parser.py`: adicionar `parse_stream()` ao `CSVParser` que aceita async byte iterator e yield `ParsedDocument` um por vez
2. Em `src/gabi/tasks/sync.py`: consumir o async generator em vez de `List[ParsedDocument]`
3. Testar com `tcu_normas`:
   ```bash
   GABI_PIPELINE_FETCH_MAX_SIZE_MB=300 python -m gabi.cli ingest \
     --source tcu_normas --max-docs-per-source 100
   ```
4. Deve completar sem OOM em máquina com ~2.5 GB livres

---

## 10. Referência Rápida do Schema

```
Tables: documents, document_chunks, source_registry, audit_log,
        data_catalog, dlq_messages, execution_manifests,
        change_detection_cache, lineage_edges, lineage_nodes

Chaves:
  documents:       id (UUID), document_id, source_id, title, content, fingerprint, is_deleted
  document_chunks: id (UUID), document_id, chunk_index, content, embedding (vector 384), is_deleted
  source_registry: id (VARCHAR), name, config_json (JSONB), status, is_deleted
```

Query rápida de contagem:
```sql
SELECT d.source_id, COUNT(d.id) as docs
FROM documents d WHERE d.deleted_at IS NULL
GROUP BY d.source_id ORDER BY d.source_id;
```

---

## 11. Histórico de Commits (branch `kimi`)

```
ee1bb89 Staged
8a2372d Add ingest-all aggregate classification and sync pipeline hardening
389b68b Commit
afe8dda Claude says it is finished
81e5596 Fixing Commit 2
74fa0b5 Fixing Commit 1
8975088 Fixing Commit
29615df (main) commit 1
b8d8dd7 WAVE 1 FIX
b21b425 WAVE 1: Foundation
dc0a284 first commit
f57e1a8 FASE ZERO
7199253 Initial commit
```

**Estado Git**: 238 files changed, 71,683 insertions ahead de `main`. Alterações unstaged incluem os fixes desta sessão (discovery, parser, sync, fetcher, contracts, migrations, pyproject).
