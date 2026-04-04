
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

TCU Acórdão Completo:

Seção	Tag	Default
Ementa	<EMENTA>	Aberta
Assunto	<ASSUNTO>	Colapsada
Relatório	<RELATORIO>	Colapsada (até 48K chars)
Voto	<VOTO>	Colapsada
Acórdão	<ACORDAO>	Aberta
Quórum	<QUORUM>	Colapsada
TCU Acórdão de Relação: Ementa (aberta) + Acórdão (aberto)

DOU Extrato (~4.7M): <PARTES> <OBJETO> <VALOR> <VIGENCIA> <FUNDAMENTO>

DOU Normativo (~3.9M): <EMENTA> <CONSIDERANDOS> <ARTIGOS>

DOU Licitação (~2.3M): <OBJETO> <MODALIDADE> <ORGAO> <DATAS> <CONDICOES>

DOU Resultado (~0.7M): <REFERENCIA> <VENCEDOR> <VALOR>

DOU Genérico (fallback): <EMENTA> <CORPO>

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
#	Pergunta	Sprint
1	Gemini Flash vs Qwen local para <RESUMO>?	3
2	tcu_normas/publicacoes/btcu — que campos têm?	2
3	~3.6M DOU sem cluster — que tipos?	2
4	Threshold de discordância para cutover?	5
5	Canonicalização HTML antes do hash?	1
6	Validação estratificada vs aleatória?	1
Esse é o documento completo no formato Overview → Páginas → Componentes → Comportamentos. Quando as ferramentas de escrita voltarem, colo em specs/SPEC.md. Quer que eu ajuste algo?