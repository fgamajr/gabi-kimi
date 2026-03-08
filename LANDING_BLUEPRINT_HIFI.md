# Blueprint Hi-Fi: GABI DOU Product Surfaces

## Escopo
Blueprint de alta fidelidade para superfícies de produto (nao landing de marketing), alinhado aos conceitos visuais fornecidos:
- Home operacional com busca e cards
- Busca com filtros e resultados
- Leitor de documento longo com TOC
- Dashboard analitico com series temporais

Sem execucao de codigo. Documento para design e implementacao posterior.

## 1. Direcao Visual
1. Estilo: `Dark Operational Editorial`
2. Tom: ferramenta profissional de auditoria, nao campanha
3. Estrutura: densidade media-alta, foco em leitura/consulta
4. Destaques visuais: acento roxo, estados semanticos, micrograficos

## 2. Mapa de Telas
1. `T1 Home`: busca central, chips, documentos em destaque, vistos recentemente, KPI cards com sparkline
2. `T2 Search`: query + filtros + lista de resultados + paginacao/infinite load
3. `T3 Document`: cabecalho editorial, corpo legal longo, indice lateral ativo
4. `T4 Analytics`: series temporais para auditoria (6 familias de grafico)

## 3. Grid e Proporcoes por Breakpoint
### Mobile (360-767)
- Base: coluna unica
- Largura util: 100% com `padding-x: 16-20`
- Sequencia: busca > chips > lista > vistos > KPI
- Documento: TOC em sheet

### Tablet (768-1279)
- Grid: 8 colunas, `gutter: 16`
- Home: coluna principal `5/8`, lateral `3/8` apenas para KPI/resumo
- Documento: TOC compacta lateral ou sheet

### Desktop (1280+)
- Grid: 12 colunas, `gutter: 20`
- Home: rail `1/12` + conteudo `11/12`
- Document: `conteudo 8/12` + `indice 3/12` + margem/acoes `1/12`
- Analytics: cards full-width em stack, cada grafico com altura consistente

## 4. Tokens (Compativeis com o app atual)
### Cores (HSL)
- `--background: 225 14% 7%`
- `--surface-elevated: 225 12% 13%`
- `--surface-sunken: 225 14% 5%`
- `--text-primary: 220 10% 94%`
- `--text-secondary: 220 8% 58%`
- `--text-tertiary: 220 6% 38%`
- `--primary: 256 96% 67%`
- `--do1: 217 91% 60%`
- `--do2: 263 70% 58%`
- `--do3: 330 81% 60%`
- `--status-ok: 160 60% 45%`
- `--status-warn: 43 96% 56%`
- `--status-error: 0 72% 63%`

### Tipografia
- UI: `Inter`/`Manrope` (sans)
- Documento: `Source Serif 4` opcional no corpo (toggle), mantendo sans no chrome
- Mono: `IBM Plex Mono`/`JetBrains Mono`
- Escala recomendada:
- `--t-title: clamp(1.5rem, 2vw, 2.125rem)`
- `--t-h2: clamp(1.2rem, 1.4vw, 1.5rem)`
- `--t-body: clamp(0.95rem, 1vw, 1.05rem)`
- `--t-meta: 0.78rem`

### Espacamento e forma
- `--radius: 0.625rem`
- Blocos verticais: `24/32/48` por densidade
- Cards: padding `16-20`

## 5. Blueprint por Tela

### T1 Home (Produto)
Objetivo: iniciar consulta rapidamente e retomar contexto recente.

Blocos:
1. Top bar leve + identidade
2. Search bar primaria
3. Chips de busca popular (scroll horizontal)
4. Lista "Documentos em destaque"
5. Bloco "Vistos recentemente"
6. KPI cards com sparklines (publicacoes, ingestao, latencia)

ASCII - Desktop
```text
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ RAIL │ GABI · DOU                                                                    │
│      │ [SEARCH BAR --------------------------------------------------------------]   │
│      │ [chip] [chip] [chip] [chip] [chip]                                           │
│      │                                                                               │
│      │ DOCUMENTOS EM DESTAQUE                                                        │
│      │ ┌──────────────────────────────────────────────────────────────────────────┐   │
│      │ │ Secao 1 | data      PORTARIA ...                         ANVISA         │   │
│      │ └──────────────────────────────────────────────────────────────────────────┘   │
│      │ ┌──────────────────────────────────────────────────────────────────────────┐   │
│      │ │ Secao 1 | data      DECRETO ...                          Presidencia    │   │
│      │ └──────────────────────────────────────────────────────────────────────────┘   │
│      │                                                                               │
│      │ VISTOS RECENTEMENTE                                                           │
│      │ ┌──────────────────────────────────────────────────────────────────────────┐   │
│      │ │ estado vazio / lista de acessos                                         │   │
│      │ └──────────────────────────────────────────────────────────────────────────┘   │
│      │                                                                               │
│      │ ┌──────── KPI 1 ────────┐ ┌──────── KPI 2 ────────┐ ┌──────── KPI 3 ─────┐   │
│      │ │ valor + sparkline     │ │ valor + sparkline     │ │ valor + sparkline  │   │
│      │ └───────────────────────┘ └───────────────────────┘ └────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

### T2 Search
Objetivo: refinamento e triagem de resultados.

Blocos:
1. Query + clear
2. Filtros (secao, tipo, orgao, periodo)
3. Chips de filtros ativos
4. Result cards com snippet
5. Paginacao/carregar mais

ASCII - Desktop
```text
┌───────────────────────────────────────────────────────────────────────────────┐
│ [SEARCH ---------------------------------------------------------------] [x] │
│ [secao] [tipo ato] [orgao] [periodo]                              [limpar]   │
│ filtros ativos: [DO1] [ANVISA] [2024]                                         │
├───────────────────────────────────────────────────────────────────────────────┤
│ RESULTADO 1                                                                   │
│ titulo                                                                         │
│ metadados | orgao                                         badge secao          │
│ snippet com highlight                                                          │
├───────────────────────────────────────────────────────────────────────────────┤
│ RESULTADO 2 ...                                                                │
└───────────────────────────────────────────────────────────────────────────────┘
```

### T3 Document (Leitura)
Objetivo: leitura profunda com navegacao por indice.

Blocos:
1. Header utilitario (voltar, compartilhar, salvar)
2. Metadata de cabecalho (secao, data, orgao)
3. Titulo e ementa
4. Corpo legal longo
5. TOC lateral com item ativo

ASCII - Desktop
```text
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ [voltar]                                                     [share] [download]      │
├───────────────────────────────┬──────────────────────────────────────────────────────┤
│ INDICE (3/12)                 │ DOCUMENTO (8/12)                                     │
│ Art. 1                        │ Diario Oficial da Uniao                              │
│ Art. 2                        │ Secao 1 | data | pagina                              │
│ Art. 3 [ativo]                │ TITULO DO ATO                                        │
│ Art. 4                        │ orgao emissor                                        │
│ Art. 5                        │ ementa                                               │
│                               │ --------------------------------------------------   │
│                               │ Art. 1o ...                                           │
│                               │ paragrafo longo ...                                   │
│                               │ Art. 2o ...                                           │
│                               │ paragrafo longo ...                                   │
└───────────────────────────────┴──────────────────────────────────────────────────────┘
```

### T4 Analytics (Time Series)
Objetivo: auditoria e deteccao de padroes/anomalias.

Blocos (6 cards empilhados):
1. Volume de publicacoes (stacked bars + media + anomalia)
2. Atividade por orgao (stacked area)
3. Tipos de ato ao longo do tempo (linhas + red flag)
4. Saude do pipeline (estilo grafana)
5. KPI sparklines compactos
6. Heatmap de atividade anual

ASCII - Card tipo
```text
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ ① Volume de Publicacoes DOU                                   [ALTA PRIORIDADE]     │
│ descricao curta de uso para auditoria                                                 │
│                                                                                       │
│ eixo y                                                                               │
│ 400 ─────────────────────────────────────────────────────────                         │
│ 300 ───── stacked bars + banda + media + marcador de anomalia ─── LIVE              │
│ 200 ─────────────────────────────────────────────────────────                         │
│   0 ───────────────────────────────────────────────────────── jan ... dez             │
│ legenda: DO1 DO2 DO3 media                                                           │
│ tags: [Audit scoping] [Anomalias] [Sazonalidade]                                     │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

## 6. Regras de Densidade e Leitura
1. Home: alta escaneabilidade, sem hero promocional
2. Search: filtro sempre visivel acima de resultados
3. Documento: largura de texto `65-72ch` no desktop
4. TOC: destaque de item ativo com contraste claro
5. Analytics: um grafico por card, sem misturar 2 narrativas no mesmo painel

## 7. Motion Budget
1. Entrada de cards: 180-260ms
2. Hover: micro deslocamento (`-1px`/`-2px`)
3. Pulse apenas em marcadores de anomalia/live
4. `prefers-reduced-motion`: desabilitar animacoes nao essenciais

## 8. Criterios de Aprovacao
1. Alinhamento com conceito visto nas capturas (product-first)
2. Home inicia fluxo em busca em menos de 1 segundo cognitivo
3. Documento privilegia leitura continua sem ruido
4. Analytics comunica risco/auditoria com clareza sem overload visual

## 9. Referencias de Origem
1. Capturas de Home e Document compartilhadas nesta conversa
2. `GABI_DOU_TimeSeries_Concepts.html`
3. Tokens e base de tema existentes no frontend atual

## 10. Observacoes
1. Este arquivo substitui a orientacao de landing narrativa anterior.
2. Nao ha implementacao de codigo nesta etapa.
