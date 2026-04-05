
Vou mapear o frontend atual do GABI e o que o RAG rebuild muda em termos de funcionalidade visível, depois rodo um painel dev-converge para validar a spec com os 4 modelos, e gero o documento estruturado em /specs.

Lendo as páginas e componentes principais do frontend + rotas de API para completar o mapa funcional.

Vou ler a API client (tipos exportados) e o SearchBar/ResultCard para completar o mapa de componentes.

Tenho o mapa completo agora. Lendo os sprints 2-5 do ROADMAP para capturar funcionalidades futuras que afetam a spec.

Read ROADMAP.md, lines 175 to 400

Tenho todo o contexto necessário: frontend (3 pages + componentes), backend (20+ endpoints), ROADMAP (5 sprints), e a revisão do dev-converge. Agora vou rodar o painel dev-converge para validar a spec antes de gerar, depois crio o documento.

Terminal está desabilitado agora. Vou gerar a spec diretamente com base no mapeamento completo que já fiz do frontend, backend e ROADMAP — e incorporar as recomendações do painel dev-converge anterior.

Creating SPEC.md (455 lines)

Ferramentas de escrita e terminal estão desabilitadas neste momento. Vou entregar a spec completa aqui mesmo — é só copiar para specs/SPEC.md.

GABI RAG Rebuild — Application Spec
Version: 1.0 | Date: 2026-04-02 | Status: Pre-implementation
Fonte: ROADMAP.md + dev-converge panel consensus (qwen/kimi/minimax/claude)

1. OVERVIEW
GABI é uma plataforma de busca full-text para documentos legais do governo brasileiro com duas fontes:

DOU (Diário Oficial da União): ~16M documentos, 2002–2026
TCU (Tribunal de Contas da União): ~520K acórdãos, 1992–2026
Stack: React 18/Vite + FastAPI + Elasticsearch 8.15.4 + MongoDB 7 → migrando para Postgres 16/pgvector como source of truth.

O que o rebuild muda:

De	Para
MongoDB SoT	Postgres + pgvector
2 pipelines de embedding incompatíveis	Gemini embedding unificado (3072 dims)
ES com BM25 + dense_vector	ES somente BM25 + pgvector kNN via RRF
Texto plano para LLM	Parsing estruturado com tags XML por tipo de documento
Sem resumos	Enriquecimento LLM com <RESUMO> para docs elegíveis
5 Sprints: 0 ✅ Decisões → 1 ETL raw → 2 Parsers → 3 LLM Enrichment → 4 Embeddings + Query v2 → 5 Cutover

## 1.1 Sources & Metadata

Cada source tem metadata padrão, plus campos específicos:

| Collection | Sub-tipo (`tipo`) | Source CSV | Rows | Sprint 1 Status | Key Metadata | Parser Sprint |
|-----------|-------------------|-----------|------|-----------------|--------------|------|
| **DOU (documents)** | — | INLABS/Liferay | ~15.8M | ✅ Raw dump | pub_date, section, art_type | 2 |
| **tcu_acordaos** — _Family A_ | ACÓRDÃO DE RELAÇÃO | acordao-completo-{ano}.csv | 357,718 | ✅ Raw + typed | data_sessao, colegiado, relator | 2 |
| **tcu_acordaos** — _Family A_ | ACÓRDÃO | acordao-completo-{ano}.csv | 143,133 | ✅ Raw + typed | data_sessao, colegiado, has_relatorio | 2 |
| **tcu_acordaos** — _Family A_ | DECISÃO | acordao-completo-{ano}.csv | 19,502 | ✅ Raw + typed | data_sessao, colegiado | 2 |
| **tcu_acordaos** — _Family B_ | JURISPRUDÊNCIA SELECIONADA | jurisprudencia-selecionada.csv | 17,016 | ✅ Raw + typed | data_sessao, area, tema, enunciado_hash | 2 |
| **tcu_acordaos** — _Family B_ | BOLETIM (jurisprudência) | boletim-jurisprudencia.csv | 5,828 | ✅ Raw + typed | colegiado, area, enunciado_hash | 2 |
| **tcu_acordaos** — _Family B_ | BOLETIM (informativo LC) | boletim-informativo-lc.csv | 1,977 | ✅ Raw + typed | area, enunciado_hash | 2 |
| **tcu_acordaos** — _Family B_ | BOLETIM (pessoal) | boletim-pessoal.csv | 1,500 | ✅ Raw + typed | area, numero_referencia, enunciado_hash | 2 |
| **tcu_acordaos** — _Family B_ | RESPOSTA A CONSULTA | resposta-consulta.csv | 522 | ✅ Raw + typed | data_sessao, colegiado, area, enunciado_hash | 2 |
| **tcu_acordaos** — _Family B_ | SÚMULA | sumula.csv | 294 | ✅ Raw + typed | area, vigente, numero_referencia, enunciado_hash | 2 |
| **tcu_normas** | Portaria, IN, Resolução, DN, Res. Administrativa | normas.csv | 16,413 | ✅ Raw JSONB | data_inicio_vigencia, vigente, tipo_norma | 2 |
| **tcu_btcu** | Controle Externo, Administrativo, Deliberações, Especial | (scraped, not CSV) | 223,515 | ✅ Raw JSONB | caderno, section_type, data_publicacao, tema | 2 |
| **tcu_publicacoes** | livro, revista, caderno temático, cartilha, relatório, sumário executivo | (scraped, not CSV) | 667 | ✅ Raw JSONB | pub_type, pub_date, page_count, pdf_urls | 2 |

**Total: ~16.6M documentos**

### Family A vs Family B — Typed Column Mapping

| Column | Family A (acordao-completo) | Family B (jurisprudencia/boletim/sumula/resposta) |
|--------|----|----|
| `raw_text_hash` | SHA256(`acordao_texto`) | SHA256(`enunciado`) |
| `has_relatorio` | ✅ | null |
| `has_voto` | ✅ | null |
| `relator` | ✅ | null |
| `situacao` | ✅ | null |
| `tipoprocesso` | ✅ | null |
| `area` | null | ✅ |
| `tema` | null | ✅ |
| `subtema` | null | ✅ |
| `numero_referencia` | null | ✅ (número da súmula/boletim) |
| `vigente` | null | ✅ (súmulas only) |
| `autortese` | null | ✅ (jurisprudência selecionada) |
| `source_type` | `tcu_acordao` | `tcu_jurisprudencia` / `tcu_sumula` / `tcu_boletim_*` / `tcu_resposta_consulta` |

Todas as sources guardam Mongo _id em `raw.{source}_raw_data.id`, mais JSONB completo em `all_fields`.

Todos os tipos têm:
- `pub_date` ou `data_*` (para ordering recente)
- `source_type` (metadado universal)
- `search_all` (texto indexável)
- Determinista hash para parity validation

2. PÁGINAS
2.1 HomePage (/)
Mudança no rebuild: Nenhuma estrutural. Backend troca internamente.

Finalidade: Landing page com busca central, métricas, trending, destaques.

Zona	Conteúdo
Hero	SearchBar central + seletor de fonte (DOU/TCU/Todos)
Stats	Total de documentos, última atualização, faixa temporal
Trending	6 cards de tópicos em alta
Recentes	8 cards de destaques recentes
Editorial	Carrossel de curadoria editorial
Tópicos sugeridos	Chips clicáveis
2.2 SearchPage (/search?q=...)
Mudança no rebuild: Ranking muda (Sprint 4). Novos campos nos resultados (Sprint 2+3).

Finalidade: Resultados paginados com filtros avançados.

Zona	Conteúdo
Topo	Header + SearchBar compacto
Filtros	Seção DOU, tipo doc, fonte, período, presets
Resultados	Lista de ResultCards (20/página)
Footer	Paginação numérica
Mobile	BottomSheet para filtros
Filtros:

Filtro	Tipo	Valores
Seção DOU	select	S1, S2, S3, Extra, Todas
Fonte	toggle	DOU, TCU, Todos
Tipo documento	select	Lista dinâmica (/api/types)
Data início	date	yyyy-mm-dd
Data fim	date	yyyy-mm-dd
Presets	chip	30 dias, 6 meses
2.3 DocumentPage (/document/:id)
Mudança no rebuild: Conteúdo evolui de texto plano para documento estruturado com seções (Sprint 2), e ganha resumo LLM (Sprint 3).

Finalidade: Visualização completa de documento legal com metadados e media.

Zona	Conteúdo
Nav	Breadcrumb + botão voltar
Meta	Órgão, data, seção, tipo, badges
Resumo LLM (Sprint 3)	Card com resumo gerado, disclaimer IA
Corpo estruturado (Sprint 2)	Seções colapsáveis por tag XML
Media	Imagens/PDF trailing
Ações	Compartilhar, copiar, PDF
Seções por tipo de documento:

**TCU Acórdão Completo** (143K):

| Seção | Tag | Default |
|-------|-----|---------|
| Ementa | <EMENTA> | Aberta |
| Assunto | <ASSUNTO> | Colapsada |
| Relatório | <RELATORIO> | Colapsada (até 48K chars, lazy render) |
| Voto | <VOTO> | Colapsada |
| Acórdão | <ACORDAO> | Aberta |
| Quórum | <QUORUM> | Colapsada |

**TCU Acórdão de Relação** (357K):
<EMENTA> (aberta) + <ACORDAO> (aberto)

**TCU Decisão** (19K):
<EMENTA> (aberta) + <ACORDAO> (aberto)

**TCU Jurisprudência Selecionada** (17K) — `source: tcu_jurisprudencia`:
<ENUNCIADO> (aberto) + <EXCERTO> (aberto, se presente) — fields: area, tema, autortese

**TCU Boletim** (9.3K = jurisprudência 5.8K + informativo LC 2K + pessoal 1.5K) — `source: tcu_boletim_*`:
<ENUNCIADO> (aberto) + <TEXTO_ACORDAO> (colapsada, se presente) — fields: num, area, caderno

**TCU Resposta a Consulta** (522) — `source: tcu_resposta_consulta`:
<ENUNCIADO> (aberto) + <EXCERTO> (aberto, se presente) — fields: area, colegiado, data_sessao

**TCU Súmula** (294) — `source: tcu_sumula`:
<ENUNCIADO> (aberto) — fields: numero_referencia, area, vigente (badge Vigente/Revogada)

**TCU Norma** (16K, sub-tipos: Portaria, IN, Resolução, DN):
<TITULO> (aberto) + <METADATA> (tipo_norma, vigente, vigência) + <TEXTO_NORMA> (aberto) + <RELACIONADAS> (colapsada)

**TCU BTCU — Boletim de Jurisprudência** (223K, cadernos: Controle Externo, Administrativo, Deliberações):
<SECTION_TITLE> (aberto) + <TEMA> (aberto) + <TEXTO_COMPLETO> (aberto) + <ACORDAOS_CITADOS> (colapsada)

**TCU Publicações** (667, tipos: livro, revista, caderno temático, cartilha, relatório, sumário executivo):
<TITLE> (aberto) + <PUB_TYPE> (aberto) + <BODY_PLAIN> (aberto) + link PDF se houver

**DOU Extrato** (~4.7M):
<PARTES> <OBJETO> <VALOR> <VIGENCIA> <FUNDAMENTO>

**DOU Normativo** (~3.9M):
<EMENTA> <CONSIDERANDOS> <ARTIGOS>

**DOU Licitação** (~2.3M):
<OBJETO> <MODALIDADE> <ORGAO> <DATAS> <CONDICOES>

**DOU Resultado** (~0.7M):
<REFERENCIA> <VENCEDOR> <VALOR>

**DOU Genérico (fallback):**
<EMENTA> <CORPO>

2.4 Admin/Ops Dashboard
Decisão: NÃO CRIAR. Time de 1 pessoa. Monitoramento via CLI, logs Docker, raw.migration_log, scripts em ops, MCP tools.

3. COMPONENTES
3.1 Existentes (sem mudança)
Componente	Finalidade
Header	Barra superior com logo + search compacto
Footer	Rodapé
SearchBar	Input com autocomplete (debounce 200ms)
ResultCard	Card de resultado de busca
FilterChip / SectionBadge	Badges de filtro e seção
EditorialHighlights	Carrossel de destaques
BottomSheet	Sheet mobile para filtros
DocImage	Imagem/media de documento
ThemeToggle	Dark/light mode
Skeletons	Loading placeholders
3.2 Novos / Modificados
ResultCard — Evolução (Sprint 2)
O que muda: Exibe seção de origem do match.

Prop nova	Tipo	Descrição
matched_section	string | null	Ex: "RELATÓRIO", "ARTIGOS"
parser_name	string | null	Parser que gerou conteúdo
Visual: Badge extra abaixo do snippet: "encontrado em RELATÓRIO"

DocumentBody — Novo (Sprint 2)
Finalidade: Renderizar corpo com seções colapsáveis a partir de tags XML.

Prop	Tipo	Descrição
body_clean	string	Texto com tags XML
sections	SectionDef[]	{ tag, label, default_open }
highlight_query	string	Termos para highlight
Regras:

Parseia tags XML → blocos colapsáveis
Seções >2000 chars iniciam colapsadas
Ementa e Acórdão sempre abertos
Highlight de termos dentro de cada seção
LlmSummaryCard — Novo (Sprint 3)
Finalidade: Card de resumo gerado por IA.

Prop	Tipo	Descrição
resumo	string	Texto do resumo
llm_model	string	Modelo que gerou
generated_at	string	Data ISO
Visual: Ícone ✨ + texto + disclaimer fixo: "Gerado por IA — verifique a fonte original"

SearchModeIndicator — Novo (Sprint 4)
Finalidade: Indicar modo de busca ativo.

Prop	Tipo	Descrição
mode	'bm25' | 'hybrid'	Modo atual
is_shadow	boolean	Shadow mode ativo?
Visual: Pill no topo dos resultados: "Busca textual" / "Busca híbrida". Shadow: "⚡ Testando novo ranking"

4. COMPORTAMENTOS
4.1 Busca (HomePage + SearchPage)
#	Ação	Componente	Resultado	API
B1	Digita query	SearchBar	Debounce 200ms → dropdown autocomplete	GET /api/autocomplete?q=
B2	Seleciona sugestão	SearchBar	Navega /search?q={s}	—
B3	Enter	SearchBar	Submete → SearchPage	—
B4	Clica trending	HomePage	Navega /search?q={t}&is_trending=true	—
B5	Clica topic sugerido	HomePage	Navega /search?q={t}	—
B6	Clica editorial	HomePage	Navega /document/{id}	—
4.2 Resultados (SearchPage)
#	Ação	Componente	Resultado	API
R1	Página carrega	SearchPage	Busca automática	GET /api/search?q=...&max=20
R2	Muda seção	Filtro	Re-busca com section=	idem
R3	Muda fonte	Toggle	Re-busca com source=	idem
R4	Seleciona tipo	Select	Re-busca com art_type=	idem
R5	Define período	Date inputs	Re-busca com date_from/to=	idem
R6	Clica preset 30d/6m	Chip	Calcula datas, aplica	—
R7	Clica resultado	ResultCard	Navega /document/{id}?q=	—
R8	Muda página	Pagination	Re-busca com page=N	idem
R9	Abre filtros mobile	Button	Abre BottomSheet	—
4.3 Documento (DocumentPage)
#	Ação	Componente	Resultado	API
D1	Página carrega	DocumentPage	Fetch doc completo	GET /api/document/{id}
D2	Termos presentes	DocumentPage	Highlight client-side	—
D3	Breadcrumb "Busca"	Breadcrumb	Volta à search com query	—
D4	Ver PDF	Button	Nova aba com PDF	GET /api/document/{id}/pdf
D5	Compartilhar	Button	Copia URL clipboard	—
4.4 Novos Comportamentos (Sprint 2+)
#	Ação	Componente	Resultado
D6	Toggle seção	DocumentBody	Expand/collapse seção
D7	Relatório TCU (48K)	DocumentBody	Lazy render, inicia colapsado
D8	Highlight em seção	DocumentBody	Termos destacados por seção
D9	Resumo LLM visível	LlmSummaryCard	Exibido acima do corpo (Sprint 3)
D10	Disclaimer IA	LlmSummaryCard	Texto fixo sempre visível
S1	Modo busca indicado	SearchModeIndicator	Badge "Textual"/"Híbrida" (Sprint 4)
S2	Seção de origem	ResultCard	Badge "encontrado em RELATÓRIO" (Sprint 2)
5. PERGUNTAS ABERTAS

| # | Pergunta | Sprint |
|----|----------|--------|
| 1 | Gemini Flash vs Qwen local para <RESUMO>? | 3 |
| 2 | Parser para tcu_normas/btcu/publicacoes — prioridade com DOU clusters? | 2 |
| 3 | ~3.6M DOU sem cluster — que tipos dominam (extratos não-licitação, retificações)? | 2 |
| 4 | Threshold de discordância para cutover? | 5 |
| 5 | Canonicalização HTML antes do hash? | 1 |
| 6 | Validação estratificada vs aleatória? | 1 |
| 7 | TCU BTCU: agrupar por `section_type` ou parser monolítico? | 2 |
| 8 | TCU Publicações: suportar PDF parsing além de body_plain? | 2 |

## INVENTORY: Sprint 1 Complete

✅ **Implemented:**
- All 4 Mongo collections → Postgres raw tables (+ documents/DOU)
- DOU typed layer (Sprint 1: raw dump complete, ~15.8M rows)
- TCU acórdãos: **two-family typed schema** (Family A: acordao-completo; Family B: jurisprudencia/boletim/sumula/resposta)
	- `raw_text_hash` correctly maps SHA256(`acordao_texto`) for Family A, SHA256(`enunciado`) for Family B
	- Family B empty-hash rows resolved: `0` across all subtypes
	- New typed columns: `source_type`, `area`, `tema`, `subtema`, `numero_referencia`, `vigente`, `autortese`, `relator`, `situacao`, `tipoprocesso`
- tcu_normas / tcu_btcu / tcu_publicacoes raw JSONB dumps
- Hash-based validation (~15.8M DOU + 547,490 TCU acordaos parity verified)

📋 **Mapped (but not yet parsed — Sprint 2):**

| Collection | Sub-tipos | Parser needed |
|-----------|-----------|--------------|
| tcu_acordaos | Family A: ACÓRDÃO, ACÓRDÃO DE RELAÇÃO, DECISÃO | 1 parser (shared fields: acordao_texto, relatorio, voto) |
| tcu_acordaos | Family B: JURISPRUDÊNCIA SELECIONADA, RESPOSTA A CONSULTA | 1 parser (enunciado + excerto) |
| tcu_acordaos | Family B: BOLETIM (3 sub-sources) | 1 parser (enunciado + texto_acordao) |
| tcu_acordaos | Family B: SÚMULA | 1 parser (enunciado, vigente badge) |
| tcu_normas | Portaria, IN, Resolução, DN, Resolução Administrativa | 1 parser |
| tcu_btcu | Controle Externo, Administrativo, Deliberações, Especial | 1 parser |
| tcu_publicacoes | livro, revista, caderno temático, cartilha, relatório, sumário executivo | 1 parser |
| dou_documents | extrato, normativo, licitação, resultado, retificação, fallback | 5 parsers |

⏳ **Sprint 2 scope: 12 document types across 5 parsers (or fewer, grouping compatible tipos)**