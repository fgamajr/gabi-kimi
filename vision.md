1. Cross-Encoder Reranking (highest impact, easiest to add)
This is the single biggest quality gap in the current spec. Right now, GABI retrieves candidates via BM25 and vector search, fuses them with RRF, and returns the result. But the initial retrieval models are bi-encoders — they encode query and document independently, which is fast but loses fine-grained interaction between them.
A cross-encoder reranker takes the top-K candidates (say 50) and rescores each one by processing the query-document pair together through a transformer. The quality improvement is dramatic — typically 15-30% better relevance for legal text.
The implementation would be a "Phase 9.5" in the pipeline — between RRF fusion and final response. Models like cross-encoder/ms-marco-MiniLM-L-12-v2 or the multilingual variant run locally on CPU in under 100ms for 50 candidates. It fits perfectly into the existing architecture — just another TEI container serving a different model.
This is genuinely the lowest-effort, highest-impact change possible.
2. Vision-Language Models for Document Understanding (replaces pdfplumber + OCR)
The current PDF pipeline is fragile: pdfplumber extracts text, and if that fails, pytesseract does OCR. This breaks on scanned documents with complex layouts, tables, stamps, signatures, and mixed formatting — which is exactly what TCU documents look like.
ColPali and similar vision-language models skip text extraction entirely. They embed page images directly into the same vector space as text queries. You search against page images, not extracted text. This eliminates the entire pdfplumber → OCR → text cleanup pipeline and handles tables, diagrams, and scanned documents natively.
The more practical near-term option is using a multimodal LLM (like Claude's vision capabilities, which you're already familiar with from the CAF audit work) for structured extraction: send the page image to the API and get clean, structured text back. It's more expensive per document but dramatically more accurate than regex-based parsing for complex layouts.
The tradeoff is cost vs. accuracy, and for a corpus of ~470k documents processed once (with incremental daily updates), the cost is manageable.
3. GraphRAG (biggest long-term payoff)
Legal documents don't exist in isolation. Acórdãos cite other acórdãos. Súmulas reference normativos. Normativos revoke or amend previous ones. The current spec treats each document as an independent unit, which throws away the most valuable signal in legal text: the citation graph.
GraphRAG would involve building a knowledge graph where nodes are documents (and entities like ministros, órgãos, processos) and edges are relationships (cita, revoga, fundamenta, referencia). At query time, you don't just retrieve the best-matching documents — you traverse the graph to find related precedents, the normative chain, and conflicting jurisprudence.
Practically, this means adding a graph layer (Neo4j, or even PostgreSQL with recursive CTEs for simpler cases) and an entity/relation extraction step in the pipeline. The extraction could use an LLM to identify citations and relationships from the document text — something like:

"Acórdão 123/2024 cita Súmula 247"
"Acórdão 456/2024 diverge do Acórdão 123/2024"
"IN 75/2022 revoga IN 43/2017"

This is the technology that would differentiate GABI from a generic search engine. An auditor searching for "licitação de TI" wouldn't just get matching documents — they'd get the normative chain, conflicting precedents, and the evolution of TCU's understanding on the topic.
The downside is complexity. It adds a new data store, a new extraction step, and query-time graph traversal. I'd put this in a second phase, after the core pipeline is proven.
4. Learned Sparse Embeddings (SPLADE)
This is more subtle but worth mentioning. The current hybrid search combines dense embeddings (semantic meaning) with BM25 (lexical matching). SPLADE is a model that produces sparse embeddings — essentially learned term weights that capture semantic information in a format compatible with inverted indices.
The practical benefit: you could replace the two-system approach (Elasticsearch + pgvector) with a single system that does both lexical and semantic matching natively. Elasticsearch 8.x already supports sparse vectors. This simplifies the architecture and eliminates the RRF fusion step entirely.
For Portuguese legal text specifically, SPLADE-style models handle the synonym problem better than the manually curated synonym list in the current Elasticsearch analyzer. The model learns that "licitação" and "certame" are related, rather than requiring you to enumerate every synonym.
The catch: there aren't great pre-trained SPLADE models for Portuguese yet. You'd need to fine-tune one, which requires a relevance dataset.