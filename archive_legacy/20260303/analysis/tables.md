# DOU Structural Evidence Registry

## Corpus
- Scope: HTML publication pages and listing pages from DOU portal (`portal.in.gov.br/web/dou/-/...`) plus issue listing flow (`in.gov.br/leiturajornal?data=...`).
- Sample size: 12 heterogeneous document pages + issue/listing pages.
- Date spread sampled: recent (`2025`), mid (`2020`), older available in current portal corpus (`2020` baseline) and legacy viewer references (`2017`-era index patterns from older journal rendering).
- Sections sampled: section 1 and section 3 explicitly in page metadata/snippets; section variation handled by fallback container strategy.
- Act types sampled: decree, resolution, dispatch, ordinance/portaria, notice/aviso, tax consultation decision-like text.

Sampled URLs (structural only):
1. https://portal.in.gov.br/web/dou/-/aviso-de-denuncia-635432825
2. https://portal.in.gov.br/web/dou/-/aviso-de-denuncia-651954954
3. https://portal.in.gov.br/web/dou/-/aviso-de-denuncia-645385404
4. https://portal.in.gov.br/web/dou/-/resolucao-aneel-n-1.009-de-22-de-marco-de-2022-389604484
5. https://portal.in.gov.br/web/dou/-/decreto-n-11.427-de-2-de-marco-de-2023-467487718
6. https://portal.in.gov.br/web/dou/-/despacho-n-1.525-de-28-de-junho-de-2022-452775381
7. https://portal.in.gov.br/web/dou/-/portaria-interministerial-mec/ms-n-3-de-22-de-fevereiro-de-2022-437756126
8. https://portal.in.gov.br/web/dou/-/resolucao-crp-02-n-2-de-17-de-abril-de-2023-460765761
9. https://portal.in.gov.br/web/dou/-/decreto-n-11.250-de-9-de-novembro-de-2022-442990283
10. https://portal.in.gov.br/web/dou/-/portaria-n-173-de-7-de-janeiro-de-2020-257201388
11. https://portal.in.gov.br/web/dou/-/solucao-de-consulta-n-6.020-de-13-de-setembro-de-2022-447316402
12. https://portal.in.gov.br/web/dou/-/portaria-n-706-de-26-de-outubro-de-2022-444163476

---

## publication_issue

### FIELD: source_url
Observed patterns:
- Canonical page URL in browser location.
- Stable article permalink format `/web/dou/-/<slug>-<id>`.
Edge cases:
- Listing URL (`/leiturajornal?data=...`) differs from article permalink.
Chosen selector:
- `link[rel='canonical']::attr(href)` fallback `__page.url`.
Rationale:
- Canonical link is stable across page template shifts.

### FIELD: publication_date
Observed patterns:
- Label text `Publicado em:` in metadata block.
- Date rendered as `dd/mm/yyyy` and occasionally datetime token.
Edge cases:
- Date missing from some listing fragments.
Chosen selector:
- `time::attr(datetime)`, `time`, `p/span containing 'Publicado em:'`.
Rationale:
- Semantic label is consistent when date is not in `<time>`.

### FIELD: edition_number
Observed patterns:
- `Edição:` label in metadata region.
- Sometimes only `Nº` appears near title block.
Edge cases:
- Not always present in article pages.
Chosen selector:
- `p/span containing 'Edição:'` then `Nº` fallback.
Rationale:
- Semantic labels survive style changes.

### FIELD: edition_section
Observed patterns:
- `Seção 1` / `Seção 3` textual metadata.
- DOU masthead context indicates section block.
Edge cases:
- Section marker absent in some layouts/snippets.
Chosen selector:
- `p/span containing 'Seção'` with masthead fallback.
Rationale:
- Section text anchor is stable across years.

### FIELD: page_number
Observed patterns:
- `Página` label in metadata/footer in some templates.
Edge cases:
- Missing in many extracted article views.
Chosen selector:
- `p/span containing 'Página'`.
Rationale:
- Optional extraction with null fallback is safest.

### FIELD: publication_type
Observed patterns:
- DOU masthead and section phrase near top.
Edge cases:
- Could be absent in stripped or embedded rendering.
Chosen selector:
- masthead/title context + fallback constant.
Rationale:
- keeps canonical value when source omits explicit tag.

---

## document

### FIELD: document_type
Observed patterns:
- Heading starts with legal type keyword (`Decreto`, `Portaria`, `Resolução`, `Despacho`, `Aviso`).
- Occasionally appears in first strong paragraph.
Edge cases:
- Long compound headings.
Chosen selector:
- `__document.heading`, `__document.first_strong`.
Rationale:
- type keyword is semantic and location-invariant.

### FIELD: document_number
Observed patterns:
- Number inside heading (`nº`, `n.` or slash year forms).
- Sometimes omitted in notices.
Edge cases:
- acts without numbers.
Chosen selector:
- heading then paragraph regex extraction.
Rationale:
- regex tolerates punctuation and formatting variants.

### FIELD: document_year
Observed patterns:
- Year appears with number (`/2022`, `de 2023`).
Edge cases:
- missing when number absent.
Chosen selector:
- heading/paragraph regex.
Rationale:
- avoids positional dependency.

### FIELD: title
Observed patterns:
- Main heading text in article area.
- fallback first paragraph for minimal layouts.
Edge cases:
- heading fragmented with `<strong>`.
Chosen selector:
- heading then first non-empty paragraph.
Rationale:
- covers heading-first and paragraph-first variants.

### FIELD: summary
Observed patterns:
- optional ementa-like first paragraph.
- label `Ementa:` in some acts.
Edge cases:
- absent in many decrees/notices.
Chosen selector:
- first paragraph + `Ementa:` label fallback.
Rationale:
- optional field, no hard failure.

### FIELD: body_text
Observed patterns:
- paragraph blocks under article body container.
Edge cases:
- footer boilerplate appended.
Chosen selector:
- all paragraphs in document scope.
Rationale:
- robust to markup differences; normalize by boilerplate stripping.

### FIELD: issuing_authority
Observed patterns:
- ministry/agency lines in heading context or body intro.
Edge cases:
- authority split across multiple lines.
Chosen selector:
- keyword-based semantic lines (`Ministério`, `Secretaria`, `Agência`) + heading context.
Rationale:
- semantic detection works across sections.

### FIELD: issuing_organ
Observed patterns:
- organ labels in context (`Órgão`, branch labels, council/tribunal names).
Edge cases:
- organ implicit in signature block only.
Chosen selector:
- organ label lines + heading context fallback.
Rationale:
- captures explicit and inferred organ naming patterns.

### FIELD: source_occurrence / sequence_in_issue
Observed patterns:
- sequence inferred from split order within same page.
Edge cases:
- single-act page has only one sequence.
Chosen selector:
- derived from split iterator position.
Rationale:
- deterministic and independent of front-end IDs.

---

## document_identity

### FIELD: stable_hash
Observed patterns:
- no explicit HTML field; computed.
Edge cases:
- republications with same text but different wrappers.
Chosen selector:
- derived from canonical fields.
Rationale:
- stable dedup key across source occurrences.

### FIELD: natural_keys
Observed patterns:
- composed from type/number/year/date.
Edge cases:
- acts without number.
Chosen selector:
- object assembled from extracted fields.
Rationale:
- keeps optional identity components queryable.

### FIELD: identity_source
Observed patterns:
- source id is known from pipeline context.
Chosen selector:
- contextual constant.
Rationale:
- lineage support.

---

## document_participant

### FIELD: person_name
Observed patterns:
- uppercase names in paragraphs/signature-adjacent lines.
Edge cases:
- names embedded in long prose.
Chosen selector:
- regex on participant-role lines and all paragraphs.
Rationale:
- avoids brittle DOM assumptions.

### FIELD: role_label
Observed patterns:
- role tokens (`relator`, `requerente`, `interessado`, `advogado`, `procurador`).
Edge cases:
- multiple roles in same sentence.
Chosen selector:
- role keyword classifier in paragraph scope.
Rationale:
- typed roles from semantics, not position.

### FIELD: organization_name
Observed patterns:
- institution keywords in participant lines.
Edge cases:
- omitted for individuals.
Chosen selector:
- organization keyword regex.
Rationale:
- optional enrichment.

### FIELD: represents_entity
Observed patterns:
- representation phrases (`em nome de`, `representando`, `patrono de`).
Edge cases:
- nested punctuation and abbreviations.
Chosen selector:
- phrase capture regex.
Rationale:
- explicit representation relation extraction.

---

## document_signature

### FIELD: person_name
Observed patterns:
- `Assinado por:` label inline.
- signature names in footer lines.
Edge cases:
- inline signatures mixed with body text.
Chosen selector:
- both inline label paragraphs and footer paragraphs.
Rationale:
- handles inline vs footer variants.

### FIELD: role_title
Observed patterns:
- role appended after name or next line.
Edge cases:
- missing role title.
Chosen selector:
- role keyword capture in signature scope.
Rationale:
- optional field with resilient fallback.

### FIELD: sequence_in_document
Observed patterns:
- multiple signatures in order.
Chosen selector:
- ordinal position in extracted signature list.
Rationale:
- deterministic for N signatures.

---

## normative_reference

### FIELD: reference_text
Observed patterns:
- citations embedded in paragraph text.
- formats: law/decree/article/precedent abbreviations.
Edge cases:
- multiple citations in same paragraph.
Chosen selector:
- paragraph regex with non-overlapping extraction.
Rationale:
- citation text is semantic, not tied to dedicated tags.

### FIELD: reference_type
Observed patterns:
- inferred from matched token prefix.
Chosen selector:
- classifier from `reference_text`.
Rationale:
- normalizes heterogeneous citation forms.

### FIELD: reference_category
Observed patterns:
- maps from citation families (law/constitution/precedent/regulation/article/treaty).
Edge cases:
- ambiguous abbreviations.
Chosen selector:
- deterministic mapping with `unknown` fallback.
Rationale:
- keeps references queryable at coarse semantic level.

### FIELD: normalized_identifier
Observed patterns:
- optional normalized `type+number+year` forms.
Edge cases:
- malformed citations.
Chosen selector:
- normalization function over extracted text.
Rationale:
- joins and dedup across variants.

---

## procedure_reference

### FIELD: procedure_type
Observed patterns:
- legal procedure acronyms and procurement terms (`ADI`, `RE`, `pregão`, etc).
Edge cases:
- same document contains many procedure types.
Chosen selector:
- keyword classifier in paragraph scope.
Rationale:
- source-agnostic procedure family extraction.

### FIELD: procedure_identifier
Observed patterns:
- numeric/alphanumeric identifiers with separators.
Edge cases:
- identifier and jurisdiction combined.
Chosen selector:
- identifier regex capture.
Rationale:
- robust against punctuation variation.

### FIELD: jurisdiction
Observed patterns:
- court acronyms/state suffixes when present.
Edge cases:
- absent in administrative procedures.
Chosen selector:
- optional jurisdiction regex.
Rationale:
- non-blocking enrichment.

---

## document_event

### FIELD: event_type
Observed patterns:
- event verbs/nouns in body (`decisão`, `deliberação`, `homologação`, `revogação`, etc).
Edge cases:
- no explicit event marker.
Chosen selector:
- event keyword detector with fallback `publication_event`.
Rationale:
- generalizes judicial and administrative events.

### FIELD: event_date
Observed patterns:
- date literals in event paragraphs.
Edge cases:
- date only in session phrase.
Chosen selector:
- date regex (`dd/mm/yyyy` and ISO).
Rationale:
- date extraction independent of exact tag.

### FIELD: session_period
Observed patterns:
- textual `sessão de ...` phrases.
Edge cases:
- missing on non-collegiate acts.
Chosen selector:
- session phrase regex.
Rationale:
- captures event timing when calendar date absent.

### FIELD: event_text
Observed patterns:
- one or more paragraphs around event keywords.
Edge cases:
- multiple events in same document.
Chosen selector:
- paragraph subset matching event patterns.
Rationale:
- supports multi-event extraction.

### FIELD: outcome
Observed patterns:
- decision outcome tokens (`deferido`, `indeferido`, `provido`, etc).
Edge cases:
- absent in neutral publications.
Chosen selector:
- outcome keyword regex.
Rationale:
- optional classification with stable semantics.

### FIELD: sequence_in_document
Observed patterns:
- derived order for multiple events.
Chosen selector:
- ordinal position in event list.
Rationale:
- deterministic ordering.

---

## Edge-case Rules Implemented
1. Multiple acts inside one page: split by semantic heading + act-number patterns.
2. Signatures inline vs footer: merge both scopes before dedup.
3. Missing edition/page: nullable fields, no extraction failure.
4. Acts without numbers: keep type/title/body, number/year null.
5. Multiple events in same document: emit repeated `document_event` entries.
6. Citations embedded in prose: regex extraction from paragraph corpus.
7. Authority format drift: coalesce from heading context and labeled lines.
8. Section/year layout variation: fallback scopes (`main/article/body`) and semantic labels.
