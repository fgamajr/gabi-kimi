# GABI Hybrid Search — Executive Quality Analysis

**Evaluation basis**: 100 queries · kimi-k2.5 LLM judge · 2026-03-13
**Embedding coverage**: ~366K / 16.3M docs (2.2%)
**Embedding model**: Not disclosed in evaluation report — **must be documented before next evaluation** (model name, version, dimensionality, training language distribution)
**Fusion method**: Convex combination (interpolation) — **fusion weight (α), score normalization method, and post-fusion score thresholds were not disclosed**

---

## 1. Architecture Verdict: Uninterpretable Without Fusion Parameters — But Observable Failures Demand Immediate Action

The hybrid system underperforms the BM25 baseline at 2.2% coverage.

| Metric | BM25 | Semantic | Hybrid |
|--------|------|----------|--------|
| Relevance (1–5) | **4.04** | 1.89 | 2.84 |
| Diversity (1–5) | **3.11** | 2.15 | 2.74 |
| Ranking (1–5) | **3.98** | 2.01 | 2.91 |
| Average | **3.71** | 2.02 | 2.83 |
| Zero-result queries | **7** | 10 | **13** |
| Best-mode wins | **80** | 4 | 15 |

### ⚠ This Report Cannot Determine Root Cause

**The observed degradation could be an architecture problem, a coverage problem, or a configuration bug. We cannot distinguish these without the following parameters, which the evaluation did not disclose:**

- **Fusion weight (α)**: If α gives semantic equal or majority weight at 2.2% coverage, the degradation is a configuration error, not an architectural one.
- **Score normalization**: BM25 produces unbounded TF-IDF scores; semantic similarity typically produces values in [0, 1] or [-1, 1]. Combining these without normalization (z-score, min-max, or similar) produces undefined behavior — the "dilution" pattern observed below could be entirely a score-scale artifact.
- **Post-fusion score threshold**: If a minimum score cutoff is applied after fusion, diluted scores from the semantic component could cause BM25-found documents to fall below threshold — this would explain the zero-result anomaly (see below).
- **Score distributions**: The actual BM25 and semantic score ranges for this evaluation are unknown.

**All architectural recommendations in this report are provisional.** The engineering team must disclose (a) the value of α, (b) whether and how scores were normalized before fusion, (c) any post-fusion score thresholds, and (d) the observed score distributions for both retrievers before acting on structural changes. **If normalization was not performed, the highest-priority fix is implementing normalization — not redesigning the fusion architecture.**

### Three Observable Failures Requiring Action Regardless of Configuration

Despite the missing parameters, three patterns indicate problems that must be fixed independent of root cause:

**1. Hybrid returns MORE zero-result queries (13) than BM25 alone (7).**
Under a true convex combination (interpolation), this should be impossible — every BM25-returned document should receive a non-negative fused score. The most likely explanations are:
- **Post-fusion score thresholding**: A minimum score cutoff applied after fusion filters out BM25 results whose scores were diluted by missing semantic scores. If this is the cause, it is a bug — remove or adjust the threshold.
- **Intersection logic**: If the implementation requires documents to appear in *both* retrievers' result sets (AND logic rather than OR logic), zero-result increases are expected but represent a design choice inappropriate for 2.2% coverage.
- **Implementation bug**: Some other code path is discarding results.

The evaluation report does not specify which of these is occurring. **The engineering team must trace the code path for a query where BM25 returns results but hybrid does not, and document the cause.**

**2. Semantic pollution displaces strong BM25 results.** In queries 6–9, 11, 19, and others, BM25 scores 5/5 but hybrid drops to 2–3/5. Semantic retrieval returns old, apparently irrelevant documents (consistently from ~2002) that appear in fused results, displacing BM25's strong hits. (See §2 for caveats on this estimate.)

**3. The embedded document set appears temporally skewed.** Semantic retrieval repeatedly surfaces 2002-era annexes and generic notices across unrelated queries ("marco legal das startups" retrieving 2002 annexes, "LGPD" retrieving 2002 secrecy decrees). The cause is unverified. Possible explanations:
- **Chronological backfill** (oldest documents embedded first) — must be confirmed via `SELECT date_trunc('year', doc_publication_date) as yr, COUNT(*) FROM embedded_documents GROUP BY yr ORDER BY yr`.
- **Template/annex over-representation**: 2002-era generic annexes may be disproportionately numerous in the corpus.
- **Embedding model bias**: The model may produce tighter clusters for older Portuguese legal text, causing those documents to be retrieved more frequently regardless of query.

The backfill and model recommendations in §3 depend on which cause is correct. **Verify before implementing.**

### Missing Baselines

The evaluation tested only three retrieval modes. Two additional baselines would significantly improve decision quality:

- **BM25 with query expansion/synonyms**: If BM25 plus a Portuguese legal synonym dictionary captures the 4 semantic-only wins (queries 18, 40, 85, 94), the entire embedding infrastructure may be redundant for this domain. This is cheaper to test than scaling embeddings to 16.3M documents.
- **Disjunction fusion (RRF)**: At 2.2% coverage, a disjunction strategy (BM25 ∪ Semantic, merged via Reciprocal Rank Fusion) would preserve all BM25 results while allowing semantic to contribute additive hits. This should be tested as a fourth retrieval mode.

### Statistical Context

Win rates (80/15/4) are from n=100 *paired* comparisons (same queries across all modes). McNemar's test confirms BM25's dominance over both hybrid and semantic is statistically significant (p < 0.001). The difference between hybrid (15 wins) and semantic (4 wins) is not statistically significant at α=0.05 given the paired structure and sample size — treat as directional only.

**With only 15 hybrid wins, any subcategory analysis (e.g., "hybrid wins on procurement queries") has insufficient statistical power to distinguish signal from noise. Pattern descriptions in §2 are hypotheses for investigation, not confirmed findings.**

**Bottom line**: The hybrid system is measurably worse than BM25 and should be feature-flagged off for production users. Whether the root cause is configuration, coverage, or architecture cannot be determined without disclosing fusion parameters. Fix the zero-result anomaly and audit fusion configuration before any broader architectural changes.

---

## 2. Pattern Analysis: Where Each Mode Wins and Why

**Statistical power warning**: The subcategory patterns below are derived from small samples (15 hybrid wins, 4 semantic wins) and should be treated as hypotheses for targeted investigation, not confirmed findings.

### BM25 Wins (80/100 queries)

BM25 dominates across three categories:

- **Specific statute/law name queries** (e.g., "lei geral de proteção de dados pessoais", "estatuto da criança e do adolescente", "marco legal das startups"): BM25 achieves 5/5 because exact legal titles appear verbatim in DOU documents. Semantic search fails via **entity confusion** — it matches concept fragments ("estatuto", "empresa") to unrelated documents.

- **Administrative action queries** (e.g., "nomeação cargo comissionado", "aposentadoria", "exoneração", "cessão servidor público"): High-frequency DOU document types with standardized vocabulary. BM25's term frequency signals are strong; semantic adds nothing because the embedded 2.2% slice likely contains very few of these routine documents.

- **Single-term/broad queries** (e.g., "aposentadoria", "nomeação", "portaria", "licitação"): BM25 searches 16.3M documents; semantic searches 366K. Pure recall advantage.

### Hybrid Wins (15/100 queries)

Hybrid appears to outperform BM25 when **both** conditions hold:

1. The query uses procedural/institutional vocabulary that happens to have coverage in the embedded slice.
2. Semantic retrieval surfaces documents that BM25 missed due to vocabulary mismatch or synonym variation.

Notable examples:
- **Query 34** ("energia elétrica tarifa reajuste"): Semantic scored 5/5, BM25 4/5. Semantic may have captured the conceptual relationship between "tarifa" and "reajuste" across variant surface terms.
- **Queries 12, 13, 65, 72, 92**: Procurement/contest queries where the embedded slice happened to include relevant documents.

### Semantic Wins (4/100 queries)

The four semantic-only wins reveal the *potential* of the architecture:
- **Query 18** ("decreto regulamentar execução"): BM25 2/5, semantic 4/5. Broad conceptual query where "decreto" and "execução" appear in millions of unrelated documents — keyword matching is imprecise.
- **Query 40** ("segurança alimentar combate à fome"): Semantic captured the policy concept across varied vocabulary.
- **Query 85** ("imposto seletivo produtos nocivos"): Emerging legal concept not yet well-represented in exact terms.
- **Query 94** ("termo aditivo contrato prorrogação"): Semantic matched contract amendment intent across synonym variation.

**Key observation**: Semantic wins cluster on **broad conceptual queries where keyword specificity is low**. Semantic loses on **specific entity names, statute numbers, and standardized administrative vocabulary** — which likely constitute the majority of DOU search traffic. **This hypothesis should be validated against query log analysis.**

### Failure Taxonomy for Semantic Retrieval

**Note**: Estimated frequencies below are based on manual inspection of score differentials across the 100 queries. These are directional estimates without computed confidence intervals. Automated tagging (via retriever provenance tracking, see R8) is required for precise measurement.

| Failure Mode | Estimated Frequency | Example | Counting Heuristic |
|---|---|---|---|
| **Coverage gap** (document not embedded) | ~55% of semantic failures | Queries 21–25: COVID/auxílio docs not in 366K slice | Semantic returned <3 results AND BM25 returned ≥5 |
| **Temporal mismatch** (old docs for modern concepts) | ~25% of semantic failures | Queries 8, 9, 19: 2002 annexes for modern laws | Semantic top-3 doc dates preceded query topic by >5 years |
| **Entity confusion** (wrong "estatuto", wrong "marco") | ~15% of semantic failures | Queries 7, 8: generic concept match, wrong entity | Semantic returned docs matching ≥1 query term but wrong named entity |
| **Complete miss** (zero results returned) | ~5% of semantic failures | Queries 21, 22: no embedding neighbors found | Zero-result count |

**On semantic pollution rate**: We estimate that a majority of hybrid top-5 result sets contain at least one semantic-contributed document that displaced a stronger BM25 result. This estimate is derived from cases where hybrid relevance drops ≥2 points below BM25 relevance on the same query. A precise measurement requires retriever provenance logging (R8), which does not exist today.

---

## 3. Actionable Recommendations

### Immediate: Audit Before Acting

**R0. Disclose and audit fusion parameters.**
All subsequent recommendations are provisional until the team documents: (a) the α weight, (b) whether BM25 and semantic scores are normalized before combination and by what method, (c) any post-fusion score thresholds, (d) the observed score distributions for both retrievers across this evaluation. **If normalization is absent, implement min-max or z-score normalization before any architectural changes.** This alone may resolve a significant portion of the observed degradation.

**R1. Trace and fix the zero-result anomaly.**
Identify a query where BM25 returns results but hybrid returns zero. Trace the code path. The most likely cause is a post-fusion score threshold filtering out BM25 results diluted by missing semantic scores. Fix the invariant: `|hybrid_results| ≥ min(requested_k, |bm25_results|)`. A hybrid system must never have worse recall than its sparse component.

### Short-term: Coverage-Aware Fusion (this sprint, after R0/R1)

**R2. Implement coverage-aware fusion gating.**
When embedding coverage for a query's candidate set is below a configurable threshold (start at 30%), fall back to pure BM25 (set semantic weight to 0.0). This is the conservative, correct default at low coverage.

**R3. Evaluate RRF as an alternative fusion method.**
Reciprocal Rank Fusion (`RRF_score(d) = Σ 1/(k + rank_retriever(d))` with k=60) is rank-based, eliminating score normalization issues. **Important**: In RRF, documents appearing in only one retriever's results receive a score from that retriever only — they are not discarded. This means RRF preserves all BM25 results (they receive at least their BM25 rank contribution) while allowing semantic results to contribute additively. This is why RRF is preferable to convex combination at low coverage: it cannot degrade BM25 quality. **However**, RRF should be evaluated empirically before replacing the current method — it is not a guaranteed improvement if the semantic retriever's rankings are dominated by noise, since noise documents will still receive nonzero RRF scores and may displace BM25 tail results.

**R4. Add semantic confidence gating.**
Before fusion, compute two signals:
- **Jaccard overlap** between BM25 top-K and semantic top-K document IDs.
- **Score variance** of the semantic top-K results.

If overlap is low (<20%) AND semantic score variance is low (all top-K scores within 0.05 of each other), the semantic retriever is returning noise — set semantic weight to 0.0 for this query and log the event. If overlap is low but variance is high, semantic may have found genuinely different relevant documents — proceed with fusion but prefer RRF over score interpolation.

### Backfill Strategy

**R5. Verify temporal distribution, then test embedding model bias, then prioritize backfill.**

Step 1 (this sprint): Run `SELECT date_trunc('year', doc_publication_date) as yr, COUNT(*) FROM embedded_documents GROUP BY yr ORDER BY yr` to determine actual temporal distribution.

Step 2 (if temporal skew is confirmed): Before reprioritizing backfill, test the embedding model on a held-out balanced set of ~100 documents from 2021+ and ~100 from 2002. Compute mean cosine similarity to a set of 20 representative queries. If 2002 documents consistently produce higher similarities regardless of query relevance, the problem is model bias — reprioritizing backfill will not fix retrieval quality, and a model change or fine-tuning is required.

Step 3 (if skew is confirmed as backfill-order-driven, not model bias): Reprioritize to embed all documents from 2018–present before expanding to historical archives. Target: 95% coverage of 2021–present documents as the first milestone.

Step 4 (if 2002 documents are generic annex templates): Consider excluding or downweighting these document types from the semantic index.

**R6. Prioritize high-frequency document types.**
Analyze BM25 query logs to identify the most-retrieved document types (portarias, editais, extratos de contrato) and prioritize those for embedding.

### Fusion Strategy

**R7. Plan query-type-aware routing (after coverage gates met).**
Static fusion weights cannot distinguish "semantic found a useful paraphrase" from "semantic found a misleading near-miss." After coverage exceeds 30%, evaluate:
- **Heuristic routing**: Presence of quoted strings, statute numbers, or proper nouns → BM25-only; absence of specific entities → balanced fusion.
- **Learned fusion weights** trained on the human calibration set (see §6). This requires the 20-query calibration set plus retriever provenance logs (R8).

**R8. Add temporal coherence as a soft signal.**
When query entities imply a time range (e.g., "LGPD" → post-2018, "marco legal das startups" → post-2021), add a temporal relevance feature that downweights documents where publication date precedes the implied range by >5 years. This should be a score adjustment, not a hard filter, to avoid excluding legitimately relevant older documents.

### Monitoring

**R9. Add retriever provenance tracking.**
For every document in the hybrid result set, log whether it originated from BM25 only, semantic only, or both. This is required to compute semantic pollution rate and diagnose fusion behavior.

**R10. Track hybrid-vs-BM25 parity as a production invariant.**
Alert if any of the following occur on a rolling 7-day window:
- Hybrid zero-result rate exceeds BM25 zero-result rate
- Hybrid average relevance (sampled via periodic LLM grading or click-through proxy) drops below BM25 average relevance by >0.3 points
- Semantic pollution rate (once measurable via R9) exceeds 15%

### Missing Baseline

**R11. Evaluate BM25 with Portuguese legal synonym expansion.**
Before investing further in embedding infrastructure, test whether BM25 plus a domain-specific synonym dictionary (e.g., "tarifa" ↔ "reajuste", "imposto seletivo" ↔ "tributação produtos nocivos") captures the 4 semantic-only wins. If it does, the embedding infrastructure may not be justified for this domain. This test is cheap and should precede the next embedding milestone.

---

## 4. Coverage Threshold for Re-Evaluation

Do not conduct the next formal hybrid evaluation until **both** gates are met:

| Gate | Threshold | Rationale |
|------|-----------|-----------|
| **Overall coverage** | ≥15% (~2.4M docs) | See justification below |
| **Recency coverage** | ≥80% of documents from 2021–present | Eliminates temporal bias (if confirmed per R5) that invalidates current results |

**Justification for 15%**: This threshold is a pragmatic estimate, not a precise calculation. The naive probability model (P = 1 − (1−0.15)^10 ≈ 80% chance that at least one top-10 BM25 result has an embedding) **assumes uniform random distribution of embeddings across the corpus.** This assumption is violated if temporal skew exists (as suspected). The true query-level coverage at 15% overall will depend on which documents are embedded:
- If backfill is reprioritized to modern documents (per R5), 15% overall coverage weighted toward 2018+ documents could yield >80% effective coverage for modern queries.
- If temporal skew persists unremediated, 15% overall coverage could yield <30% effective coverage for modern queries.

**The 15% gate should be interpreted as: 15% overall AND the recency gate, together ensuring that semantic retrieval has meaningful coverage for the queries users actually issue.** If backfill is reprioritized successfully, the recency gate will be the binding constraint.

A **second evaluation gate** at **50% overall coverage with 95% recency coverage** should trigger a full re-evaluation with the same 100-query set plus 50 additional queries weighted toward identified failure modes (conceptual queries, emerging legal concepts, synonym-heavy queries).

**On estimated break-even point**: Based on the pattern that hybrid wins correlate with coverage availability, we tentatively estimate hybrid will match BM25 quality around 30–40% coverage and begin outperforming on conceptual queries around 50–60%. **However, if the LLM grader is biased toward semantic results (see §6), reported hybrid scores are optimistic upper bounds, and the true break-even coverage may be higher.** Do not treat these estimates as commitments.

---

## 5. Fusion Strategy Assessment: Coverage Is Necessary but Not Sufficient

Coverage growth alone will not resolve all observed problems. Even at 100% coverage, a static convex combination will:

1. **Poison specific-entity queries** where BM25 achieves 5/5 by matching exact statute names. Semantic will always return some conceptually-similar-but-wrong documents for queries like "estatuto da criança e do adolescente" (matching other "estatutos"). Static fusion cannot distinguish useful paraphrase matches from misleading near-misses.

2. **Fail to exploit semantic's strength** on broad conceptual queries. When semantic legitimately outperforms BM25 (queries 18, 40, 85, 94), a static weight caps its contribution.

**Required fusion changes regardless of coverage:**

- **Query-type-aware routing** (heuristic first, learned later — see R7)
- **Score variance gating**: If semantic top-K scores are tightly clustered (low variance), the model lacks discriminative signal — downweight toward zero. This is cheap and effective.
- **Overlap-based confidence**: High Jaccard overlap between BM25 and semantic top-K → fusion is safe; low overlap with low semantic variance → default to BM25.

**The value proposition of semantic search in this domain is on the tail**: the 4–15% of queries where keyword matching fails due to synonym variation, conceptual breadth, or emerging terminology. Fusion strategy should capture this tail value without degrading the head. Whether this tail is large enough to justify the infrastructure cost of 16.3M embeddings is an open question (see §7).

---

## 6. Grader Methodology Concerns

### kimi-k2.5 as LLM Judge

**Concern 1: Neural judge bias toward semantic retrieval.** LLM judges process text via neural embeddings sharing distributional properties with the semantic retrieval model. This creates potential systematic bias: the judge may rate semantic results as more relevant than a human would. **Implication: BM25's observed 80-win dominance may be a lower bound. The true quality gap may be larger than reported, and break-even coverage estimates derived from these scores are optimistic.**

**Concern 2: Score compression on failure cases.** Queries 26–30 and 76–77 all score 1/1/1 across modes, collapsing distinct failure modes:
- Query 76 ("xyznonexistentterm12345"): correctly returns nothing — a *true negative*, should not be penalized identically to...
- Query 29 ("extrato contrato prestação serviços"): returns irrelevant results — a *false positive*, qualitatively worse
- Query 26 ("privatização empresa estatal"): marked "easy" with all-1 scores — either the grader or the difficulty classifier is wrong

This compression masks the difference between "system correctly returned nothing" and "system returned garbage," which is critical for diagnosing retrieval vs. ranking failures.

**Concern 3: Domain-specific grading limitations.** For Brazilian legal queries, an LLM judge may:
- Fail to distinguish between a law and its implementing decree (both textually "relevant" but different user intents)
- Not recognize that a 2002 annex is irrelevant to a 2021 law query when overlapping legal vocabulary is present
- Misinterpret domain-specific Portuguese legal terminology

**Concern 4: Difficulty classification is suspect.** Query 26 ("privatização empresa estatal") is marked "easy" but all modes score 1/1/1. Query 77 ("bitcoin criptomoeda regulação") is marked "hard" but should have DOU hits given Brazil's crypto regulation law (14.478/2022). These contradictions undermine both the difficulty labels and the grading accuracy.

### Recommended Grader Improvements

1. **Human calibration set**: Have a Brazilian legal domain expert grade 20 queries (the same 20 across all modes, covering the full difficulty and mode-win spectrum). Compute Cohen's kappa between human and kimi-k2.5. If κ < 0.6, the LLM grader is unreliable and all quantitative conclusions in this report are provisional. This set also serves as seed data for learned fusion weights (R7).

2. **Ternary result classification**: For each result, the grader should output `relevant | irrelevant | empty_correct`. This enables computing precision and recall separately, and correctly handles true-negative cases.

3. **Multi-dimensional grading for DOU search**: Replace the single "relevance" score with:
   - **Topical match** (is this about the right legal subject?)
   - **Temporal match** (is this from the correct legal era?)
   - **Document type match** (did the user want a law, a portaria, an extrato?)
   
   Log separately for diagnostic value; combine into composite for headline metrics.

4. **Empirical difficulty labels**: Define difficulty as `5 - max(BM25_score, semantic_score, hybrid_score)`, computed post-evaluation. The current a priori labels are contradicted by results and should be discarded.

---

## 7. Summary Decision Matrix

| Decision | Recommendation | Urgency |
|----------|---------------|---------|
| Disclose & audit fusion parameters (α, normalization, thresholds)? | **Yes.** All other recommendations are provisional until this is done. | **Immediate (today)** |
| Trace & fix zero-result anomaly? | **Yes.** Correctness bug regardless of cause. | **Immediate (today)** |
| Ship hybrid to production users? | **No.** BM25-only until coverage gates met and fusion validated. | Immediate |
| Implement coverage-aware fusion gating? | **Yes.** Fall back to BM25 below threshold. (R2) | This sprint (after R0) |
| Verify backfill temporal distribution? | **Yes.** Query before changing backfill order. (R5 step 1) | This sprint |
| Test embedding model for temporal bias? | **Yes.** Before reprioritizing backfill. (R5 step 2) | This sprint |
| Test BM25 + synonym expansion? | **Yes.** Cheap test that may challenge the ROI of embeddings. (R11) | This sprint |
| Add retriever provenance tracking? | **Yes.** Required for precise diagnostics. (R9) | This sprint |
| Evaluate RRF as fusion alternative? | **Yes.** Test alongside current method. (R3) | This sprint |
| Evaluate cost-benefit of 16.3M embeddings? | **Yes.** If embedding + storage + inference cost exceeds marginal quality gain on 4–15% of queries, the project may not be justified. | Before next coverage gate |
| Validate LLM grader (20-query human calibration)? | **Yes.** κ < 0.6 invalidates all quantitative findings. | Before next evaluation |
| Re-run formal evaluation? | **Not yet.** Wait for 15% overall + 80% recency coverage. | ~4–8 weeks depending on backfill rate |
| Implement query-type-aware routing? | **After** coverage gates met and calibration set available. (R7) | After 30% coverage |

---

*Appendix: Raw per-query scores and worst-performing query narratives are preserved from the original evaluation report and available in the attached data file.*
