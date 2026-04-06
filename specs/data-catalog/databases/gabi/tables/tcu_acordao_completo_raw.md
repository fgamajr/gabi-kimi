# Tabela: `raw.tcu_acordao_completo_raw`

**Criticidade:** 🔴 CRÍTICA — Tabela canônica de acórdãos TCU (Sprint 2)  
**Linhas (live):** 520.595  
**Tamanho total:** 4,0 GB  
**Cobertura temporal:** 1973 → 2026  
**Origem:** TCU Dados Abertos — CSV `acordao-completo` via `tcu_csv_raw_pg.py`  
**Última ingestão:** 2026-04-05

---

## Descrição

Tabela colunar de **acórdãos do Tribunal de Contas da União (TCU)**, ingerida diretamente do CSV fonte disponibilizado no portal de dados abertos. Cada coluna corresponde a um header do CSV original (maiúsculas). Contém somente os tipos legítimos: **ACÓRDÃO**, **ACÓRDÃO DE RELAÇÃO** e **DECISÃO** — demais tipos de ato TCU estão em tabelas próprias.

---

## Colunas

| # | Coluna | Tipo | PK | Descrição |
|---|--------|------|----|-----------|
| 1 | `id` | `text` | ✅ | ID canônico gerado (ex: `ACORDAO-COMPLETO-1319104`) |
| 2 | `source_type` | `text` | — | Sempre `"tcu_acordao_completo"` |
| 3 | `dumped_at` | `timestamptz` | — | Timestamp da inserção |
| 4 | `KEY` | `text` | — | Chave natural do CSV |
| 5 | `TIPO` | `text` | — | Tipo do ato: ACÓRDÃO, ACÓRDÃO DE RELAÇÃO, DECISÃO |
| 6 | `TITULO` | `text` | — | Título completo do acórdão |
| 7 | `NUMACORDAO` | `text` | — | Número do acórdão |
| 8 | `ANOACORDAO` | `text` | — | Ano do acórdão |
| 9 | `NUMATA` | `text` | — | Número da ata da sessão |
| 10 | `COLEGIADO` | `text` | — | Órgão colegiado: Plenário, Primeira Câmara, Segunda Câmara |
| 11 | `DATASESSAO` | `text` | — | Data da sessão de julgamento |
| 12 | `RELATOR` | `text` | — | Ministro relator |
| 13 | `SITUACAO` | `text` | — | Situação processual |
| 14 | `PROC` | `text` | — | Número do processo |
| 15 | `ACORDAOSRELACIONADOS` | `text` | — | IDs de acórdãos relacionados (separados por vírgula) |
| 16 | `TIPOPROCESSO` | `text` | — | Tipo de processo TCU (ex: TOMADA DE CONTAS ESPECIAL) |
| 17 | `INTERESSADOS` | `text` | — | Partes interessadas no processo |
| 18 | `ENTIDADE` | `text` | — | Entidade jurisdicionada |
| 19 | `RELATORDELIBERACAORECORRIDA` | `text` | — | Relator da deliberação recorrida (em recursos) |
| 20 | `MINISTROREVISOR` | `text` | — | Ministro revisor |
| 21 | `MINISTROAUTORVOTOVENCEDOR` | `text` | — | Ministro autor do voto vencedor |
| 22 | `REPRESENTANTEMP` | `text` | — | Representante do Ministério Público junto ao TCU |
| 23 | `UNIDADETECNICA` | `text` | — | Unidade técnica responsável |
| 24 | `ADVOGADO` | `text` | — | Advogados das partes |
| 25 | `ASSUNTO` | `text` | — | Assunto do processo |
| 26 | `SUMARIO` | `text` | — | Ementa/sumário do acórdão |
| 27 | `ACORDAO` | `text` | — | Texto dispositivo do acórdão |
| 28 | `DECISAO` | `text` | — | Texto da decisão (quando aplicável) |
| 29 | `QUORUM` | `text` | — | Composição do quórum da sessão |
| 30 | `MINISTROALEGOUIMPEDIMENTOSESSAO` | `text` | — | Ministro que alegou impedimento |
| 31 | `RECURSOS` | `text` | — | Recursos interpostos |
| 32 | `RELATORIO` | `text` | — | Texto do relatório do relator |
| 33 | `VOTO` | `text` | — | Texto do voto do relator |
| 34 | `DECLARACAOVOTO` | `text` | — | Declaração de voto |
| 35 | `VOTOCOMPLEMENTAR` | `text` | — | Voto complementar |
| 36 | `VOTOMINISTROREVISOR` | `text` | — | Voto do ministro revisor |

---

## Distribuição por `TIPO`

| TIPO | Registros |
|------|----------|
| ACÓRDÃO DE RELAÇÃO | ~357.700 |
| ACÓRDÃO | ~143.100 |
| DECISÃO | ~19.500 |

---

## Distribuição por `COLEGIADO`

| Colegiado | Registros |
|-----------|----------|
| Primeira Câmara | ~224.000 |
| Segunda Câmara | ~220.000 |
| Plenário | ~95.000 |

---

## Índices

| Índice | Tipo | Coluna |
|--------|------|--------|
| `tcu_acordao_completo_raw_pkey` | UNIQUE BTREE | `id` |
| `ix_raw_tcu_acordao_completo_raw_dumped_at` | BTREE | `dumped_at DESC` |

---

## Notas

- 🥇 **Principal fonte para RAG TCU** — campos `SUMARIO`, `ACORDAO`, `VOTO`, `RELATORIO`
- ℹ️ Colunas em MAIÚSCULAS refletem headers originais do CSV TCU
- ℹ️ Campos de texto longo (`RELATORIO`, `VOTO`, `ACORDAO`) podem ser nulos para acórdãos antigos
- ℹ️ `ACORDAOSRELACIONADOS` é string delimitada por vírgula — não normalizada

---

## Classificação de Sensibilidade

**Público** — acórdãos TCU são documentos de acesso público.  
Atenção: `INTERESSADOS` e `ADVOGADO` contêm nomes de pessoas físicas → **Interno** para fins de LGPD se necessário.
