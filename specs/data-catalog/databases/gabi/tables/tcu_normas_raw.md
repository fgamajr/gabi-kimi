# Tabela: `raw.tcu_normas_raw`

**Criticidade:** 🟢 ATIVA  
**Linhas (live):** 16.443  
**Tamanho total:** 98 MB  
**Origem:** TCU Dados Abertos — CSV `normas` via `tcu_csv_raw_pg.py`  
**Última ingestão:** 2026-04-05

---

## Descrição

Tabela colunar de **normas internas do TCU** — portarias, resoluções, instruções normativas e atos administrativos emitidos pelas unidades do Tribunal. Cada linha representa uma norma vigente ou revogada, com links para o BTCU e DOU quando aplicável.

---

## Colunas

| # | Coluna | Tipo | PK | Descrição |
|---|--------|------|----|-----------|
| 1 | `id` | `text` | ✅ | ID gerado pelo pipeline (ex: `NORMA-45816`) |
| 2 | `source_type` | `text` | — | Sempre `"tcu_normas"` |
| 3 | `dumped_at` | `timestamptz` | — | Timestamp da inserção |
| 4 | `KEY` | `text` | — | Chave natural do CSV |
| 5 | `UNIDADEBASICAAUTORA` | `text` | — | Unidade organizacional emissora |
| 6 | `ORIGEM` | `text` | — | Origem/fonte da norma |
| 7 | `NUMNORMA` | `text` | — | Número da norma |
| 8 | `ANONORMA` | `text` | — | Ano da norma |
| 9 | `TIPONORMA` | `text` | — | Tipo: Portaria, Resolução, Instrução Normativa, etc. |
| 10 | `NUMEROPROCESSO` | `text` | — | Número do processo TCU |
| 11 | `NUMEROPROCESSOFORMATADO` | `text` | — | Número do processo formatado |
| 12 | `TITULO` | `text` | — | Título da norma |
| 13 | `ASSUNTO` | `text` | — | Assunto da norma |
| 14 | `TEXTONORMA` | `text` | — | Texto completo da norma |
| 15 | `DATAINICIOVIGENCIA` | `text` | — | Data de início da vigência |
| 16 | `DATAFIMVIGENCIA` | `text` | — | Data de encerramento da vigência (null se vigente) |
| 17 | `SITUACAO` | `text` | — | Vigente, Revogada, etc. |
| 18 | `LINKBTCU` | `text` | — | URL no portal BTCU |
| 19 | `TEXTOANEXO` | `text` | — | Texto do anexo da norma |
| 20 | `ARQUIVONORMA` | `text` | — | Nome do arquivo PDF da norma |
| 21 | `PAGINABTCU` | `text` | — | Página no BTCU |
| 22 | `TEMA` | `text` | — | Tema temático |
| 23 | `TAGSVCE` | `text` | — | Tags do VCE (Vocabulário Controlado de Entidades) |
| 24 | `NORMARELACIONADA` | `text` | — | Normas relacionadas |
| 25 | `NUMDOU` | `text` | — | Número da edição do DOU |
| 26 | `NUMSECAODOU` | `text` | — | Seção do DOU |
| 27 | `NUMPAGINADOU` | `text` | — | Página do DOU |
| 28 | `DATADOU` | `text` | — | Data de publicação no DOU |
| 29 | `INFOSGERAIS` | `text` | — | Informações gerais adicionais |

---

## Índices

| Índice | Tipo | Coluna |
|--------|------|--------|
| `tcu_normas_raw_pkey` | UNIQUE BTREE | `id` |
| `ix_raw_tcu_normas_raw_dumped_at` | BTREE | `dumped_at DESC` |

---

## Notas

- 🥇 **Excelente candidata para RAG** — textos curtos e precisos, ideais para recuperação contextual
- ℹ️ Relacionamento implícito com `dou_documents_raw_data` via `NUMDOU` + `NUMSECAODOU` + `DATADOU`
- ℹ️ `SITUACAO` permite filtrar normas vigentes sem precisar de JSONB parse
- ℹ️ `TEXTONORMA` + `TEXTOANEXO` são os campos principais para RAG

---

## Classificação de Sensibilidade

**Público** — normas TCU são documentos oficiais de acesso público.
