# GABI (Gerador Automático de Boletins por Inteligência Artificial) - Antigravity Reference

Este documento serve como o `/.init` ou `claude.md` principal do repositório, consolidando regras operacionais, arquitetura, stack e comandos fundamentais para que o agente (Antigravity/Kimi/Claude) atue com precisão máxima no projeto.

## 1. Visão Geral e Arquitetura

O **GABI** é um pipeline de ingestão em massa (bulk ingestion) para dados do **Diário Oficial da União (DOU)**. Ele automatiza o download de arquivos ZIP (da Imprensa Nacional), faz parse do XML estruturado em objetos (dataclasses), normaliza, aplica extração via NLP (assinaturas, processos, leis), gera auditorias criptográficas (CRSS-1 Merkle Tree) e persiste tudo em um **PostgreSQL**. O acesso final aos dados ocorre via uma API **FastAPI** que inclui rotas de Full-Text Search (BM25 two-pass) e um chat integrado com rotas LLM, suportada por um frontend SPA nativo (Alpine.js + Tailwind CSS).

### Fluxo de Dados Core:
`in.gov.br ZIPs` → `XML Parser (DOUArticle)` → `Normalização / NLP Extractions` → `Commitment CRSS-1` → `PostgreSQL` → `FastAPI BM25 Search / Chat`

## 2. Estrutura de Diretórios 

* **`ingest/`**: Core pipeline (`bulk_pipeline.py`, `sync_pipeline.py`). Regras para parseamento (`xml_parser.py`), ingestão (`dou_ingest.py`), NLP e metadata extraction (`html_extractor.py`), indexação text-search (`bm25_indexer.py`). Automacao total via `orchestrator.py` e `auto_discovery.py`.
* **`dbsync/`**: Schemas declarativos do Postgres (`dou_schema.sql`, `bm25_schema.sql`) e sinc de banco.
* **`commitment/`**: Lógica de audit trail, CRSS-1, Merkle trees, serialização canônica. Arquivos puramente funcionais e sem interação direta de BD.
* **`infra/`**: Docker e scripts (`infra_manager.py`) que levantam a base local isolada na porta 5433.
* **`web_server.py` & `web/`**: Aplicação de API search/chat FastAPI e o frontend base (single file Alpine/Tailwind).
* **`mcp_server.py`**: Model Context Protocol integration expondo functions de search, docs e stats ao modelo.
* **`tests/`**: Suite modular sem Pytest. Scripts de teste standalone executados pelo python padrão.
* **`data/`**: Pasta de dados no .gitignore com assets baixados do INLabs e registries (`dou_catalog_registry.json`).
* **`scripts/`**: Automatização crua do servidor (Systemd timers/services em `scripts/deploy.sh` e cron em `daily_sync.sh`).

## 3. Diretrizes de Código (Python & SQL)

### Estilo e Tipagem (Python 3.10+)
- **Imports:** A primeira linha de todo arquivo Python deve ser `from __future__ import annotations`. Agrupe imports na ordem: Stdlib → Third-party → Locais. 
- **Type Hints:** Use obrigatoriamente tipagem moderna (ex: `list[str]`, `dict[str, Any]`, e sintaxe pipe `| None` no lugar de `Optional`).
- **Nomenclatura:** `snake_case` para vars e funções, `PascalCase` para classes/exceções e `_under_score` para métodos e funções privadas. Argumentos de CLI separados por traços (`--max-articles`).
- **Classes de Dados:** Prefira `@dataclass(slots=True)`. Listas e mutáveis devem usar `field(default_factory=list)`.
- **Tratamento de Exceções:** Contextualize os erros logando com `loguru`. Use exceções especificas do contexto caso precise subir a stack de erro (ex: `class ApplyError(RuntimeError)`).

### SQL e Persistência
- **Porta do BD:** O DB **sempre** opera na porta **5433** (`host=localhost port=5433 dbname=gabi user=gabi password=gabi`) e NÃO na 5432!  
- **TSVector:** Atributos como `body_tsvector` nas tabelas operacionais (ex. `dou.document`) são gerados através de triggers do BD on INSERT. Nunca inclua-os manualmente no fluxo INSERT do Python.
- **Views:** Views materializadas como `dou.suggest_cache` e `dou.bm25_corpus_stats` comandam o frontend e o chat. Após alterar volume de publicações, lembre de emitir `REFRESH MATERIALIZED VIEW CONCURRENTLY`.

## 4. Workflows & Comandos Principais

### Testes (Zero Pytest!)
A suíte não utiliza py.test. Rodam-se módulos nativos:
* CRSS-1 (Pure Functions): `python3 tests/test_commitment.py`
* Bulk e Parsing: `python3 tests/test_bulk_pipeline.py`
* Ingest geral: `python3 tests/test_dou_ingest.py`
* Checar conversão de XML sem banco associado: `python3 -m ingest.bulk_pipeline --days 7 --parse-only`

### Operações Diárias / Ingestão
* **Auto Discovery (Busca de Novos Arquivos):** `python3 -m ingest.auto_discovery --days 7 --dry-run`
* **Sync de Novos Publicações e Banco:** `python3 -m ingest.sync_pipeline`
* **Criar Schemas Zero (Wipe/Reset):** 
   ```bash
   python3 infra/infra_manager.py reset_db
   psql -h localhost -p 5433 -U gabi -d gabi -f dbsync/dou_schema.sql
   ```

### Search / Index
* **Rodar manual index BM25:** `python3 -m ingest.bm25_indexer build` (ou `refresh` se for atualização)
* **API Start:** `python3 web_server.py`

## 5. Práticas para LLM/Commit
- **Secreções e Chaves:** Nunca registre API_KEYs ou chaves LLM no repo. Todas devem vir do `.env` e opcionalmente via arg injection.
- **Git Commits:** Descrições assertivas via imperativo (`Fix pipeline bugs`, `Add API rate limit`).  Descreva causa/efeito e os módulos afetados nas PRs.
- **Documentação Local:** Evite comentários vazios. Documente escopos públicos (Módulo e Classes públicas) com docstrings Python padrão `"""Descricao aqui."""`. Se a logica for complexa justifique o *por que* foi feito assim, e não o "o que" faz.

Este conhecimento anula presunções padronizadas. O Antigravity deve referenciar estas definições para arquitetar novas features, propor refactoring, e manipular a tool chain de execução shell no terminal do usuário.

## 6. Modelagem de Dados e Mapeamento Core

### Entidade Principal: Publicação / Ato Legal
A pipeline converte XMLs INLabs em um dataclass `DOUArticle` (`ingest/xml_parser.py`) que eventualmente vira um registro em `dou.document` e `dou.edition`.

* **DOUArticle (Python)**: Contém identificadores `id_materia`, meta-dados como `art_type` (ex: "Portaria"), `art_category` (árvore do órgão emissor), e strings limpas de `identifica`, `ementa` e `texto` (HTML).
* **dou.document (DB)**: O registro inserido via `dou_ingest.py` ou `bulk_pipeline.py`. 
    * `body_html` guarda a view rica.
    * `body_plain` serve de base textual.
    * `body_tsvector` é a coluna gerada (`GENERATED ALWAYS`) base de toda busca FTS BM25 na API.
    * Entidades filhas (extraídas via NLP regex no module `html_extractor.py`): `document_media` (imagens isoladas em base64/bytea), `document_signature` (assinantes), `normative_reference` e `procedure_reference`.

### API & Chat (`web_server.py`)
* A API serve as tabelas através de `dou.v_document_full`.
* O Chatbot baseia-se em heurísticas Python nativas (Regex) antes de acionar a LLM externa (`QWEN_API_KEY`). 
* Padrões de órgão, pessoa, limite (count) e data são processados localmente.
* Falhas do Chat para achar órgãos quase sempre indicam dessincronização na view materializada `dou.suggest_cache`.
