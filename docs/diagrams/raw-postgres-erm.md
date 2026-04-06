# Diagrama estilo ERM — schema `raw.*` (Postgres)

**SoT:** onze tabelas canónicas (`raw.dou_documents_raw` + oito `raw.tcu_*_raw` de CSV + `raw.tcu_normas_raw` + `raw.tcu_btcu_raw` + `raw.tcu_publicacoes_raw`) + `raw.tcu_csv_fetch_meta`. Ingest activo não deve escrever em `*_raw_data` (legado — arquivar após backfill).

Sem linhas de relacionamento (não há FKs declaradas entre estas tabelas). Duas formas de armazenamento TCU coexistem no código:

| Padrão | Onde | Colunas |
|--------|------|---------|
| **Envelope JSONB** | `ops/migrations/source_separate_raw.py`, staging `*_raw_data` | `id`, `all_fields` (JSONB), `source_type` (quando aplicável), `dumped_at` / `migrated_at` |
| **Colunar CSV** | `src/backend/ingest/tcu_csv_raw_pg.py` (`ensure_source_table`) | `id`, `source_type`, `dumped_at` + uma coluna `TEXT` por cabeçalho do CSV TCU |

Os nomes de entidade abaixo usam alias Mermaid (sem ponto). O nome físico completo é `raw.<nome>`.

---

## 1. Visão geral — todas as tabelas `raw.*` relevantes

```mermaid
erDiagram
  DOU_DOCUMENTS_RAW_DATA {
    text id PK
    date pub_date
    text section
    text source_zip
    text art_type
    text content_html
    text raw_html_hash
    jsonb all_fields
    timestamptz migrated_at
  }

  DOU_DOCUMENTS_RAW {
    text id PK
    jsonb all_fields
    text source_type
    timestamptz dumped_at
  }

  TCU_ACORDAOS_RAW_DATA {
    text id PK
    jsonb all_fields
    timestamptz dumped_at
  }

  TCU_NORMAS_RAW_DATA {
    text id PK
    jsonb all_fields
    timestamptz dumped_at
  }

  TCU_BTCU_RAW_DATA {
    text id PK
    jsonb all_fields
    timestamptz dumped_at
  }

  TCU_PUBLICACOES_RAW_DATA {
    text id PK
    jsonb all_fields
    timestamptz dumped_at
  }

  TCU_CSV_FETCH_META {
    text url PK
    text content_sha256
    bigint bytes_size
    timestamptz fetched_at
    text response_etag
  }

  TCU_ACORDAO_COMPLETO_RAW {
    text id PK
    jsonb all_fields
    text source_type
    timestamptz dumped_at
  }

  TCU_JURISPRUDENCIA_SELECIONADA_RAW {
    text id PK
    jsonb all_fields
    text source_type
    timestamptz dumped_at
  }

  TCU_RESPOSTA_CONSULTA_RAW {
    text id PK
    jsonb all_fields
    text source_type
    timestamptz dumped_at
  }

  TCU_SUMULA_RAW {
    text id PK
    jsonb all_fields
    text source_type
    timestamptz dumped_at
  }

  TCU_BOLETIM_JURISPRUDENCIA_RAW {
    text id PK
    jsonb all_fields
    text source_type
    timestamptz dumped_at
  }

  TCU_BOLETIM_PESSOAL_RAW {
    text id PK
    jsonb all_fields
    text source_type
    timestamptz dumped_at
  }

  TCU_BOLETIM_INFORMATIVO_LC_RAW {
    text id PK
    jsonb all_fields
    text source_type
    timestamptz dumped_at
  }

  TCU_NORMAS_RAW {
    text id PK
    jsonb all_fields
    text source_type
    timestamptz dumped_at
  }

  TCU_BTCU_RAW {
    text id PK
    jsonb all_fields
    text source_type
    timestamptz dumped_at
  }

  TCU_PUBLICACOES_RAW {
    text id PK
    jsonb all_fields
    text source_type
    timestamptz dumped_at
  }
```

---

## 2. `raw.tcu_acordao_completo_raw` — colunas do CSV (acórdão completo)

Fonte: `CSV_COLUMNS` em `src/backend/ingest/tcu_processor.py`.

```mermaid
erDiagram
  TCU_ACORDAO_COMPLETO_RAW_COL {
    text id PK
    text source_type
    timestamptz dumped_at
    text KEY
    text TIPO
    text TITULO
    text NUMACORDAO
    text ANOACORDAO
    text NUMATA
    text COLEGIADO
    text DATASESSAO
    text RELATOR
    text SITUACAO
    text PROC
    text ACORDAOSRELACIONADOS
    text TIPOPROCESSO
    text INTERESSADOS
    text ENTIDADE
    text RELATORDELIBERACAORECORRIDA
    text MINISTROREVISOR
    text MINISTROAUTORVOTOVENCEDOR
    text REPRESENTANTEMP
    text UNIDADETECNICA
    text ADVOGADO
    text ASSUNTO
    text SUMARIO
    text ACORDAO
    text DECISAO
    text QUORUM
    text MINISTROALEGOUIMPEDIMENTOSESSAO
    text RECURSOS
    text RELATORIO
    text VOTO
    text DECLARACAOVOTO
    text VOTOCOMPLEMENTAR
    text VOTOMINISTROREVISOR
  }
```

---

## 3. `raw.tcu_jurisprudencia_selecionada_raw`

```mermaid
erDiagram
  TCU_JURIS_SEL_RAW_COL {
    text id PK
    text source_type
    timestamptz dumped_at
    text KEY
    text NUMACORDAO
    text ANOACORDAO
    text COLEGIADO
    text AREA
    text TEMA
    text SUBTEMA
    text ENUNCIADO
    text EXCERTO
    text NUMSUMULA
    text DATASESSAOFORMATADA
    text AUTORTESE
    text FUNCAOAUTORTESE
    text TIPOPROCESSO
    text TIPORECURSO
    text INDEXACAO
    text INDEXADORESCONSOLIDADOS
    text PARAGRAFOLC
    text REFERENCIALEGAL
    text PUBLICACAOAPRESENTACAO
    text PARADIGMATICO
  }
```

---

## 4. `raw.tcu_resposta_consulta_raw`

```mermaid
erDiagram
  TCU_RESPOSTA_CONSULTA_RAW_COL {
    text id PK
    text source_type
    timestamptz dumped_at
    text KEY
    text NUMACORDAO
    text ANOACORDAO
    text COLEGIADO
    text NUMACORDAOFORMATADO
    text AREA
    text TEMA
    text SUBTEMA
    text ENUNCIADO
    text EXCERTO
    text DATASESSAOFORMATADA
    text AUTORTESE
    text FUNCAOAUTORTESE
    text TIPOPROCESSO
    text TIPORECURSO
    text INDEXACAO
    text INDEXADORESCONSOLIDADOS
    text PARAGRAFOLC
    text REFERENCIALEGAL
    text PUBLICACAOAPRESENTACAO
  }
```

---

## 5. `raw.tcu_sumula_raw`

```mermaid
erDiagram
  TCU_SUMULA_RAW_COL {
    text id PK
    text source_type
    timestamptz dumped_at
    text KEY
    text NUMERO
    text ENUNCIADO
    text TIPOPROCESSO
    text AREA
    text TEMA
    text SUBTEMA
    text APROVACAO
    text NUMAPROVACAO
    text ANOAPROVACAO
    text COLEGIADO
    text FUNCAOAUTORTESE
    text AUTORTESE
    text INDEXACAO
    text VIGENTE
    text DATASESSAOFORMATADA
    text EXCERTO
    text REFERENCIALEGAL
    text INDEXADORESCONSOLIDADOS
    text PUBLICACAO
  }
```

---

## 6. `raw.tcu_boletim_jurisprudencia_raw`

```mermaid
erDiagram
  TCU_BOLETIM_JURIS_RAW_COL {
    text id PK
    text source_type
    timestamptz dumped_at
    text KEY
    text TITULO
    text ENUNCIADO
    text REFERENCIA
    text TEXTOACORDAO
  }
```

---

## 7. `raw.tcu_boletim_pessoal_raw`

```mermaid
erDiagram
  TCU_BOLETIM_PESSOAL_RAW_COL {
    text id PK
    text source_type
    timestamptz dumped_at
    text KEY
    text TITULO
    text ENUNCIADO
    text NUMERO
    text REFERENCIA
    text TEXTOACORDAO
  }
```

---

## 8. `raw.tcu_boletim_informativo_lc_raw`

```mermaid
erDiagram
  TCU_BOLETIM_LC_RAW_COL {
    text id PK
    text source_type
    timestamptz dumped_at
    text KEY
    text TITULO
    text COLEGIADO
    text TEXTOACORDAO
    text ENUNCIADO
    text NUMERO
    text TEXTOINFO
  }
```

---

## 9. `raw.tcu_normas_raw` (norma.csv)

```mermaid
erDiagram
  TCU_NORMAS_RAW_COL {
    text id PK
    text source_type
    timestamptz dumped_at
    text KEY
    text UNIDADEBASICAAUTORA
    text ORIGEM
    text NUMNORMA
    text ANONORMA
    text TIPONORMA
    text NUMEROPROCESSO
    text NUMEROPROCESSOFORMATADO
    text TITULO
    text ASSUNTO
    text TEXTONORMA
    text DATAINICIOVIGENCIA
    text DATAFIMVIGENCIA
    text SITUACAO
    text LINKBTCU
    text TEXTOANEXO
    text ARQUIVONORMA
    text PAGINABTCU
    text TEMA
    text TAGSVCE
    text NORMARELACIONADA
    text NUMDOU
    text NUMSECAODOU
    text NUMPAGINADOU
    text DATADOU
    text INFOSGERAIS
  }
```

---

## 10. `raw.tcu_btcu_raw` e `raw.tcu_publicacoes_raw`

Ingestão por scrape → documento Mongo → `all_fields` JSONB. Chaves variam por documento; não há catálogo fixo de colunas SQL no repo.

```mermaid
erDiagram
  TCU_BTCU_PUBLICACOES_RAW {
    text id PK
    jsonb all_fields
    text source_type
    timestamptz dumped_at
  }
```

---

## Referências no código

- Catálogo CSV + cabeçalhos: `src/backend/ingest/tcu_csv_raw_catalog.py`
- DDL colunar: `ensure_source_table` em `src/backend/ingest/tcu_csv_raw_pg.py`
- DDL envelope + lista de tabelas separadas: `ops/migrations/source_separate_raw.py`
- DOU: `ops/migrations/dou_documents.py`
- Staging TCU: `ops/migrations/tcu_acordaos.py`, `tcu_normas.py`, `tcu_btcu.py`, `tcu_publicacoes.py`
