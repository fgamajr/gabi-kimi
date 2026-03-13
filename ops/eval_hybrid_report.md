# Hybrid Search Quality Evaluation Report

**Queries evaluated**: 100 / 100
**Grader model**: kimi-k2.5
**Date**: 2026-03-13 09:00
**Embedding coverage**: ~366K / 16.3M docs (2.2%)

## Overall Scores (1-5 scale)

| Mode | Relevance | Diversity | Ranking | Avg |
|------|-----------|-----------|---------|-----|
| bm25 | 4.04 | 3.11 | 3.98 | 3.71 |
| semantic | 1.89 | 2.15 | 2.01 | 2.02 |
| hybrid | 2.84 | 2.74 | 2.91 | 2.83 |

## Best Mode Distribution

- **BM25 wins**: 80 (80%)
- **Semantic wins**: 4 (4%)
- **Hybrid wins**: 15 (15%)

## Query Difficulty

- Easy: 58, Medium: 34, Hard: 8

## Operational Notes

- Semantic fallbacks (embedding server down): 0
- Zero-result queries — BM25: 7, Semantic: 10, Hybrid: 13

## Per-Query Details

| # | Query | Best | BM25 | Sem | Hyb | Difficulty |
|---|-------|------|------|-----|-----|------------|
| 1 | reforma tributária regulamentação | bm25 | 4 | 2 | 3 | medium |
| 2 | lei de licitações e contratos administrativos | bm25 | 5 | 2 | 3 | easy |
| 3 | programa bolsa família reajuste | bm25 | 3 | 1 | 2 | hard |
| 4 | salário mínimo 2024 | bm25 | 2 | 2 | 2 | medium |
| 5 | política nacional de resíduos sólidos | bm25 | 5 | 2 | 3 | easy |
| 6 | código florestal alterações | bm25 | 4 | 1 | 3 | easy |
| 7 | estatuto da criança e do adolescente | bm25 | 5 | 1 | 2 | easy |
| 8 | marco legal das startups | bm25 | 5 | 1 | 2 | easy |
| 9 | lei geral de proteção de dados pessoais | bm25 | 5 | 1 | 3 | easy |
| 10 | reforma da previdência social | bm25 | 4 | 2 | 3 | medium |
| 11 | nomeação cargo comissionado | bm25 | 5 | 1 | 3 | easy |
| 12 | concurso público edital | hybrid | 5 | 4 | 5 | easy |
| 13 | licitação pregão eletrônico | hybrid | 5 | 4 | 5 | easy |
| 14 | contrato administrativo extrato | hybrid | 5 | 3 | 4 | easy |
| 15 | convênio transferência voluntária | bm25 | 4 | 1 | 3 | medium |
| 16 | portaria normativa instrução | bm25 | 5 | 2 | 3 | easy |
| 17 | resolução conselho nacional | bm25 | 5 | 2 | 3 | easy |
| 18 | decreto regulamentar execução | semantic | 2 | 4 | 3 | medium |
| 19 | medida provisória conversão lei | bm25 | 4 | 1 | 2 | medium |
| 20 | instrução normativa receita federal | bm25 | 5 | 3 | 4 | easy |
| 21 | covid vacinação emergencial | bm25 | 4 | 1 | 4 | easy |
| 22 | auxílio emergencial pagamento | bm25 | 5 | 1 | 5 | easy |
| 23 | olimpíadas rio segurança pública | bm25 | 3 | 1 | 3 | medium |
| 24 | copa do mundo infraestrutura | bm25 | 5 | 1 | 5 | easy |
| 25 | programa minha casa minha vida | bm25 | 5 | 1 | 5 | easy |
| 26 | privatização empresa estatal | hybrid | 1 | 1 | 1 | easy |
| 27 | nomeação magistrado tribunal | bm25 | 1 | 1 | 1 | easy |
| 28 | resultado julgamento licitação | bm25 | 1 | 1 | 1 | medium |
| 29 | extrato contrato prestação serviços | none | 1 | 1 | 1 | easy |
| 30 | despacho indeferimento recurso | hybrid | 1 | 1 | 1 | medium |
| 31 | meio ambiente licenciamento ambiental | bm25 | 5 | 2 | 3 | easy |
| 32 | importação exportação comércio exterior | bm25 | 5 | 2 | 3 | easy |
| 33 | concessão aposentadoria servidor | bm25 | 4 | 1 | 2 | medium |
| 34 | energia elétrica tarifa reajuste | hybrid | 4 | 5 | 5 | medium |
| 35 | transporte rodoviário regulamentação | bm25 | 5 | 2 | 2 | easy |
| 36 | proteção dos direitos indígenas demarcação te | bm25 | 5 | 3 | 4 | medium |
| 37 | combate à corrupção transparência pública | hybrid | 5 | 2 | 4 | medium |
| 38 | sustentabilidade ambiental desenvolvimento ec | bm25 | 4 | 2 | 3 | medium |
| 39 | inclusão digital acesso à internet | bm25 | 4 | 1 | 2 | medium |
| 40 | segurança alimentar combate à fome | semantic | 4 | 5 | 4 | easy |
| 41 | violência contra a mulher medidas protetivas | bm25 | 5 | 1 | 2 | easy |
| 42 | direitos das pessoas com deficiência acessibi | hybrid | 4 | 4 | 4 | medium |
| 43 | liberdade de imprensa sigilo de fonte | bm25 | 2 | 2 | 2 | hard |
| 44 | autonomia universitária ensino superior | bm25 | 4 | 2 | 3 | medium |
| 45 | regulação mercado financeiro banco central | bm25 | 4 | 2 | 4 | medium |
| 46 | Petrobras conselho administração | bm25 | 4 | 1 | 2 | easy |
| 47 | IBAMA multa infração ambiental | bm25 | 4 | 2 | 3 | easy |
| 48 | ANVISA registro medicamento | bm25 | 5 | 2 | 3 | easy |
| 49 | INSS benefício previdenciário | bm25 | 5 | 2 | 3 | easy |
| 50 | Banco do Brasil licitação | hybrid | 4 | 3 | 4 | easy |
| 51 | FUNAI terra indígena | hybrid | 4 | 3 | 4 | medium |
| 52 | CAPES bolsa pesquisa | bm25 | 5 | 1 | 2 | easy |
| 53 | CNPq fomento ciência tecnologia | bm25 | 5 | 3 | 4 | easy |
| 54 | ANATEL telecomunicações frequência | hybrid | 2 | 3 | 3 | medium |
| 55 | ANEEL energia elétrica distribuidora | bm25 | 4 | 2 | 3 | medium |
| 56 | parceria público-privada infraestrutura sanea | bm25 | 5 | 2 | 3 | easy |
| 57 | zona franca de manaus incentivo fiscal | bm25 | 5 | 2 | 3 | easy |
| 58 | sistema único de saúde financiamento | bm25 | 3 | 3 | 3 | medium |
| 59 | fundo de manutenção educação básica FUNDEB | bm25 | 5 | 1 | 2 | easy |
| 60 | programa nacional alimentação escolar PNAE | bm25 | 5 | 2 | 3 | easy |
| 61 | consórcio intermunicipal resíduos sólidos | bm25 | 4 | 2 | 3 | medium |
| 62 | agência reguladora autonomia financeira | bm25 | 4 | 1 | 1 | medium |
| 63 | contratação temporária excepcional interesse  | bm25 | 4 | 1 | 3 | medium |
| 64 | regime diferenciado contratações RDC | bm25 | 5 | 1 | 3 | easy |
| 65 | pregão eletrônico sistema registro preços | hybrid | 5 | 4 | 5 | easy |
| 66 | aposentadoria | bm25 | 5 | 1 | 3 | easy |
| 67 | nomeação | bm25 | 5 | 1 | 2 | easy |
| 68 | exoneração | bm25 | 5 | 1 | 2 | easy |
| 69 | licitação | bm25 | 5 | 1 | 3 | easy |
| 70 | portaria | bm25 | 2 | 2 | 2 | hard |
| 71 | autorização para funcionamento de curso de gr | bm25 | 2 | 2 | 2 | hard |
| 72 | homologação resultado final concurso público  | hybrid | 5 | 4 | 5 | easy |
| 73 | declaração de utilidade pública para fins de  | bm25 | 5 | 3 | 4 | medium |
| 74 | credenciamento instituição de educação superi | bm25 | 5 | 2 | 3 | easy |
| 75 | concessão pensão civil vitalícia dependente s | bm25 | 4 | 2 | 3 | medium |
| 76 | xyznonexistentterm12345 | bm25 | 1 | 1 | 1 | easy |
| 77 | bitcoin criptomoeda regulação | bm25 | 1 | 1 | 1 | hard |
| 78 | inteligência artificial regulamentação | bm25 | 4 | 1 | 2 | medium |
| 79 | 5G leilão espectro radiofrequência | hybrid | 3 | 2 | 3 | medium |
| 80 | energia solar fotovoltaica geração distribuíd | bm25 | 5 | 2 | 3 | easy |
| 81 | marco temporal terras indígenas STF | bm25 | 3 | 1 | 1 | hard |
| 82 | reforma administrativa servidor público | bm25 | 2 | 1 | 2 | hard |
| 83 | teto de gastos emenda constitucional | bm25 | 3 | 2 | 2 | medium |
| 84 | arcabouço fiscal regra despesa | bm25 | 3 | 1 | 1 | medium |
| 85 | imposto seletivo produtos nocivos | semantic | 1 | 2 | 1 | hard |
| 86 | cessão servidor público órgão | bm25 | 5 | 1 | 3 | easy |
| 87 | redistribuição cargo técnico administrativo | bm25 | 5 | 2 | 4 | easy |
| 88 | progressão funcional carreira magistério | bm25 | 5 | 1 | 2 | easy |
| 89 | adicional insalubridade periculosidade | bm25 | 5 | 1 | 2 | easy |
| 90 | licença capacitação afastamento | bm25 | 5 | 1 | 2 | easy |
| 91 | ata registro preços adesão carona | bm25 | 5 | 1 | 2 | easy |
| 92 | inexigibilidade licitação contratação direta | hybrid | 5 | 4 | 5 | easy |
| 93 | dispensa licitação emergencial | bm25 | 5 | 2 | 3 | easy |
| 94 | termo aditivo contrato prorrogação | semantic | 4 | 5 | 4 | easy |
| 95 | sanção administrativa impedimento licitar | bm25 | 5 | 1 | 2 | easy |
| 96 | residência médica programa vagas | bm25 | 5 | 4 | 4 | easy |
| 97 | medicamento genérico registro ANVISA | bm25 | 3 | 2 | 3 | medium |
| 98 | programa mais médicos interior | bm25 | 4 | 1 | 2 | medium |
| 99 | ENEM resultado vestibular SISU | bm25 | 4 | 2 | 3 | medium |
| 100 | PROUNI bolsa integral parcial | bm25 | 5 | 1 | 2 | easy |

## Worst Performing Queries

**"programa bolsa família reajuste"**
  - bm25: 3/5 — Found 2 results mentioning Bolsa Família program but none specifically about reajuste/adjustment, with mixed relevance overall.
  - semantic: 1/5 — All results are completely irrelevant to Bolsa Família program, showing generic government documents from 2002-2003.
  - hybrid: 2/5 — Hybrid mostly inherited semantic failures with only one BM25 result at top, failing to improve relevance.

**"código florestal alterações"**
  - bm25: 4/5 — First result directly matches query intent about Forest Code amendments, but remaining 4 results only match 'florestal' keyword without addressing Código Florestal changes.
  - semantic: 1/5 — None of the top 5 results relate to Código Florestal; semantic matching captured 'alterações' concept but completely missed the specific legal document context.
  - hybrid: 3/5 — Combines BM25's strength (relevant first result) with semantic's weakness (4 irrelevant results about generic notices), diluting overall quality.

**"estatuto da criança e do adolescente"**
  - bm25: 5/5 — All results directly reference Law 8.069/1990 (ECA) with exact keyword matches and proper amendments.
  - semantic: 1/5 — Results are completely irrelevant, matching generic 'estatuto' rather than the specific Children and Adolescents Statute.
  - hybrid: 2/5 — Only the first result is relevant; hybrid weighting failed to prioritize BM25's superior matches.

**"marco legal das startups"**
  - bm25: 5/5 — Perfect results: the main law (LC 182/2021) is first, followed by related documents about its implementation and application, all directly relevant to the query.
  - semantic: 1/5 — Complete failure: returns generic annex documents from 2002 with no connection to startups or the 2021 law, showing semantic drift to unrelated 'empresa' concepts.
  - hybrid: 2/5 — Only the first result is correct (the main law), but the rest are the same irrelevant 2002 annex documents from semantic search, indicating poor fusion weighting.

**"lei geral de proteção de dados pessoais"**
  - bm25: 5/5 — All results directly mention LGPD implementation across different ministries and include the key ANPD resolution, though the main law itself (Lei 13.709/2018) is not present.
  - semantic: 1/5 — Results are completely irrelevant, focusing on unrelated 2002 decrees about state secrecy and generic notices with no connection to LGPD.
  - hybrid: 3/5 — Mixes one highly relevant LGPD result with completely irrelevant semantic noise (2002 decrees, generic notices), failing to properly rank relevant items.

**"nomeação cargo comissionado"**
  - bm25: 5/5 — All results are highly relevant portarias specifically about nomination procedures for commissioned positions at Anvisa/Ministry of Health, with clear keyword matches and proper ranking by relevance.
  - semantic: 1/5 — Results are completely irrelevant - they are old editais and portarias about public service exams and homologation from 2002, with no connection to 'nomeação cargo comissionado' intent.
  - hybrid: 3/5 — Mixes highly relevant results (positions 1 and 5) with irrelevant old semantic results (positions 2-4), failing to prioritize the most relevant documents at the top.

**"convênio transferência voluntária"**
  - bm25: 4/5 — Strong results with clear keyword matches on both terms, though last two results are generic extratos de convênio lacking 'transferência voluntária' context.
  - semantic: 1/5 — Complete failure - results are entirely unrelated annexes and attachments with no connection to convênios or transferência voluntária.
  - hybrid: 3/5 — Mixes good BM25 results with irrelevant semantic noise; poor ranking places relevant portarias at positions 1 and 4 while irrelevant annexes occupy 2, 3, and 5.

**"medida provisória conversão lei"**
  - bm25: 4/5 — All results are Medidas Provisórias with 'conversão' appearing literally, but only MP 1.146 truly matches the conversion-to-law concept; others just happen to contain 'conversão' in different contexts.
  - semantic: 1/5 — Completely misses the query intent, returning unrelated documents about currency conversion, tax calculations, and abbreviations instead of provisional measures and their legislative conversion.
  - hybrid: 2/5 — Only the first result is relevant (same as BM25's top hit), but then degrades to the same irrelevant semantic results, failing to leverage BM25's strong provisional measure matches.

**"covid vacinação emergencial"**
  - bm25: 4/5 — Strong keyword matches with highly relevant COVID-19 vaccination laws, though last result about drug pricing is off-topic.
  - semantic: 1/5 — No results returned - complete failure for this query.
  - hybrid: 4/5 — Identical to BM25 results with proper scoring, effectively same quality without semantic enhancement.

**"auxílio emergencial pagamento"**
  - bm25: 5/5 — All results are highly relevant documents about emergency aid payment schedules and rules, with good mix of Portarias and Decretos, and excellent ranking with most specific payment calendar documents first.
  - semantic: 1/5 — No results returned, complete failure to retrieve any documents despite the query being straightforward and well-matching available content.
  - hybrid: 5/5 — Identical high-quality results to BM25 with same documents in nearly same order, successfully combining keyword matching with semantic signals.
