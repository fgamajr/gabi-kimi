# Sprint 2: Source-Separated Raw Tables & Parser Architecture

**Status**: Pre-implementation  
**Date**: 2026-04-05  
**Scope**: Migrate from consolidated raw tables to 11 source-separated raw tables + design parser contract

---

## 1. Current State (Sprint 1 Complete)

### Existing Consolidated Raw Tables
```
raw.dou_documents              : 15.8M rows (typed + raw mixed)
raw.tcu_acordaos              : 547.5K rows (typed, two-family schema)
raw.tcu_acordaos_raw_data     : 547.5K rows (7 CSV sources consolidated, JSONB)
raw.tcu_btcu_raw_data         : 223.5K rows (JSONB)
raw.tcu_normas_raw_data       : 16.4K rows (JSONB)
raw.tcu_publicacoes_raw_data  : 667 rows (JSONB)
```

### Problem
- **7 TCU CSV sources share one physical table** → semantic brittleness
- **No schema isolation** → parsers must filter by tipo/source hints
- **Cross-source queries harder to reason about** → mixed `all_fields` JSONB

---

## 2. Target State (Sprint 2 Completion)

### 11 Source-Separated Raw Tables

#### DOU (1 table)
```sql
raw.dou_documents_raw
  ├─ id (text, PK)
  ├─ all_fields (JSONB) — art_type, pub_date, section, content_html, etc.
  ├─ source_type = 'dou_documents'
  └─ dumped_at (timestamp)
  
  Rows: 15,853,837
  Origin: INLABS/Liferay (scraped)
  Parsing (Sprint 2): 5 parsers by art_type_normalized (extrato, normativo, licitação, resultado, fallback)
```

#### TCU CSV Sources (7 tables)
Each source splits from consolidated `raw.tcu_acordaos_raw_data`:

```sql
raw.tcu_acordao_completo_raw
  Rows: 520,353 | tipo IN ('ACÓRDÃO', 'ACÓRDÃO DE RELAÇÃO', 'DECISÃO')
  Family: A | Primary text: acordao_texto | Parser: 1

raw.tcu_jurisprudencia_selecionada_raw
  Rows: 17,016 | tipo = 'JURISPRUDÊNCIA SELECIONADA'
  Family: B | Primary text: enunciado | Parser: 1

raw.tcu_resposta_consulta_raw
  Rows: 522 | tipo = 'RESPOSTA A CONSULTA'
  Family: B | Primary text: enunciado | Parser: 1

raw.tcu_sumula_raw
  Rows: 294 | tipo = 'SÚMULA'
  Family: B | Primary text: enunciado | Parser: 1

raw.tcu_boletim_jurisprudencia_raw
  Rows: 5,828 | tipo = 'BOLETIM JURISPRUDÊNCIA'
  Family: B | Primary text: enunciado | Parser: 1

raw.tcu_boletim_pessoal_raw
  Rows: 1,500 | tipo = 'BOLETIM PESSOAL'
  Family: B | Primary text: enunciado | Parser: 1

raw.tcu_boletim_informativo_lc_raw
  Rows: 1,977 | tipo = 'BOLETIM INFORMATIVO LC'
  Family: B | Primary text: enunciado | Parser: 1
```

#### TCU Non-CSV Sources (3 tables)
Each source copies from dedicated raw table:

```sql
raw.tcu_normas_raw
  Rows: 16,413 | Normas/Regulações (Portarias, INs, Resoluções, DNs)
  Primary text: titulo or texto_norma | Parser: 1

raw.tcu_btcu_raw
  Rows: 223,515 | Boletim de Jurisprudência (Cadernos: CE, Admin, Deliberações)
  Primary text: texto_completo or section_text | Parser: 1

raw.tcu_publicacoes_raw
  Rows: 667 | Publicações (livro, revista, cartilha, relatório, etc.)
  Primary text: body_plain or titulo | Parser: 1
```

**Total: 16.6M rows across 11 source-separated tables**

---

## 3. Migration Strategy

### Phase 1: Create New Raw Tables (Non-Destructive)
```bash
python -m ops.migrations.source_separate_raw --confirm
```

Execution:
1. Create DDL for all 11 tables (indexes, constraints)
2. Insert data from consolidated sources
3. Validate row counts match expected counts
4. Archive old tables with `_archive` suffix

### Phase 2: Update Typed Materialization
Current state: `raw.tcu_acordaos` (typed, two-family schema)

Post-Sprint 2: 11 typed tables (one per source)

Example for TCU jurisprudence:
```sql
CREATE TABLE raw.tcu_jurisprudencia_selecionada_typed (
    id TEXT PRIMARY KEY,
    enunciado TEXT,
    excerto TEXT,
    area TEXT,
    tema TEXT,
    autortese TEXT,
    raw_text_hash TEXT,
    all_fields JSONB,
    source_type TEXT = 'tcu_jurisprudencia_selecionada',
    materialized_at TIMESTAMP
);
```

---

## 4. Parser Architecture (Sprint 2)

### Parser Contract
Each parser is a Python module implementing:

```python
class DocumentParser(Protocol):
    """Interface for all source parsers."""
    
    def __init__(self, source: str):
        """Initialize parser for a specific source."""
        pass
    
    def parse(self, raw_doc: dict[str, Any]) -> dict[str, Any]:
        """
        Parse raw JSONB document into typed + structured format.
        
        Input:  all_fields (JSONB from raw table)
        Output: {
            'id': str,
            'source_type': str,
            'primary_text': str,     # For hashing, highlighting
            'sections': [
                {'tag': '<EMENTA>', 'label': 'Ementa', 'content': str, 'open': bool}
                ...
            ],
            'metadata': {'area': str, 'tema': str, ...},  # source-specific
            'materialized_at': datetime,
        }
        """
        pass
    
    def validate(self, parsed_doc: dict[str, Any]) -> bool:
        """Validate parsed document structure. Return True if valid."""
        pass
```

### Parser Implementations (11 total, Sprint 2)

#### DOU Parsers (5)
```
parsers/dou_parser.py
├─ parse_extrato()       — ~4.7M rows, PARTES/OBJETO/VALOR/VIGENCIA/FUNDAMENTO
├─ parse_normativo()     — ~3.9M rows, EMENTA/CONSIDERANDOS/ARTIGOS
├─ parse_licitacao()     — ~2.3M rows, OBJETO/MODALIDADE/ORGAO/DATAS/CONDICOES
├─ parse_resultado()     — ~0.7M rows, REFERENCIA/VENCEDOR/VALOR
└─ parse_fallback()      — ~3.6M unclassified, EMENTA/CORPO
```

#### TCU Acórdãos Parsers (1 + 7 CSV)
```
parsers/tcu_acordao_parser.py
├─ parse_acordao_completo()      — Family A: EMENTA/ASSUNTO/RELATORIO/VOTO/ACORDAO/QUORUM
├─ parse_acordao_relacao()       — Family A: EMENTA/ACORDAO
└─ parse_decisao()               — Family A: EMENTA/ACORDAO

parsers/tcu_jurisprudencia_parser.py
├─ parse_jurisprudencia_selecionada()
├─ parse_resposta_consulta()
├─ parse_sumula()
├─ parse_boletim_jurisprudencia()
├─ parse_boletim_pessoal()
└─ parse_boletim_informativo_lc()
```

#### TCU Non-CSV Parsers (3)
```
parsers/tcu_normas_parser.py     — TITULO/METADATA/TEXTO_NORMA/RELACIONADAS
parsers/tcu_btcu_parser.py       — SECTION_TITLE/TEMA/TEXTO_COMPLETO/ACORDAOS_CITADOS
parsers/tcu_publicacoes_parser.py — TITLE/PUB_TYPE/BODY_PLAIN
```

### Parser Registry & Dispatcher
```python
PARSERS = {
    'dou_documents': DouParser(),
    'tcu_acordao_completo': TcuAcordaoParser(),
    'tcu_jurisprudencia_selecionada': TcuJurisprudenciaParser(),
    # ... 8 more
}

def materialize_typed(raw_doc: dict, source: str) -> dict:
    """Dispatch to source-specific parser and materialize typed row."""
    parser = PARSERS[source]
    parsed = parser.parse(raw_doc)
    if not parser.validate(parsed):
        raise ValidationError(f"Invalid parsed doc for {source}")
    return parsed
```

---

## 5. Implementation Checklist (Sprint 2)

### Phase 1: Raw Table Migration
- [ ] Run `source_separate_raw.py` in dry-run mode locally
- [ ] Verify row counts for all 11 tables
- [ ] Execute on production with `--confirm`
- [ ] Validate parity between old + new tables
- [ ] Keep old tables for 2-week rollback period

### Phase 2: Create Typed Materialization Layer
- [ ] Design 11 typed tables (one per source)
- [ ] Implement `materialize_typed()` dispatcher
- [ ] Create index strategy (id, source_type, pub_date)

### Phase 3: Parser Implementation
- [ ] Implement DOU parsers (5 x art_type clusters)
- [ ] Implement TCU acórdãos parser (3 document types x 2 families)
- [ ] Implement TCU jurisprudence parsers (7 CSV sources)
- [ ] Implement TCU non-CSV parsers (normas, btcu, publicacoes)
- [ ] Add XML tag extraction for all sources
- [ ] Unit test each parser

### Phase 4: Validation & Performance
- [ ] Random sample validation (1K docs per source)
- [ ] Hash parity post-parsing (compare against Sprint 1 hashes)
- [ ] Materialization performance benchmark (target: <2s per 10K docs)
- [ ] Schema integrity checks

### Phase 5: Elasticsearch Re-indexing
- [ ] Clear ES alias `gabi_documents`
- [ ] Index all 16.6M typed documents
- [ ] Validate search quality (10-row comparison)
- [ ] Cutover

---

## 6. Open Questions (Decision Points)

| # | Question | Impact | Recommendation |
|----|----------|--------|---|
| 1 | DOU extratos (4.7M): parse PARTES as separate XML? | Schema growth | Yes, parse to `<PARTES>` tags for reuse |
| 2 | TCU BTCU (223K): group by `caderno` or flatten? | Parser complexity | Flatten; caderno becomes metadata field |
| 3 | TCU Publicações: include PDF parsing beyond body_plain? | Scope/effort | No for Sprint 2; body_plain only |
| 4 | Parser output: immutable NamedTuple or Pydantic? | Type safety | Pydantic v2 + ConfigDict for forward compat |
| 5 | Materialized typed tables: partitioned by source? | Query performance | No; single table per source is sufficient |
| 6 | XML tag escaping: entity-encode or CDATA? | Search correctness | Entity-encode (<, >, &) for ES safety |

---

## 7. Timeline Estimate

| Task | Effort | Est. Days |
|------|--------|-----------|
| Migration script + testing | 1d | 1 |
| Typed schema design (11 tables) | 0.5d | 0.5 |
| DOU parser (5 clusters) | 2d | 2 |
| TCU acórdãos parser (10 types) | 2d | 2 |
| TCU non-CSV parsers (3) | 1d | 1 |
| Unit tests + validation | 1.5d | 1.5 |
| Performance optimization | 0.5d | 0.5 |
| ES re-indexing + cutover | 1d | 1 |
| **Total** | | **9 days** |

---

## 8. Rollback Plan

If validation fails:
1. Keep old consolidated tables with `_archive` suffix
2. Stop new materialization
3. Revert ES index to previous version
4. Analyze root cause
5. Fix parsers in place
6. Re-materialize on next attempt

Archive tables kept for 2 weeks minimum before deletion.

---

## 9. Success Criteria (Definition of Done)

- [x] All 11 raw source tables created and populated
- [ ] Row counts match expected values (16.6M total)
- [ ] Hash parity validates (compare Spring 1 hashes)
- [ ] 11 parsers implemented with unit test coverage >80%
- [ ] All parsers produce valid XML-tagged output
- [ ] Materialized typed documents indexed in ES
- [ ] Search quality validated (random 10-doc audit)
- [ ] Performance benchmarks met (indexing <2s/10K docs)
- [ ] Rollback procedure documented and tested
