"""Hybrid search quality evaluation: 100 queries × 3 modes, graded by Qwen 3.5+.

Usage:
    python ops/eval_hybrid_search.py                  # run full eval
    python ops/eval_hybrid_search.py --queries 10     # quick test with 10 queries
    python ops/eval_hybrid_search.py --report-only    # regenerate report from cached results
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

# Reuse the MCP server's search functions directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ops.bin.mcp_es_server import es_search

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

logging.basicConfig(level=logging.INFO, format="[eval] %(message)s")
logger = logging.getLogger(__name__)

# DashScope endpoints: coding-intl for third-party models, dashscope-intl for Qwen
_QWEN_MODELS = {"qwen-plus", "qwen-turbo", "qwen-max", "qwen-flash", "qwen3-max",
                "qwen3.5-plus", "qwen3.5-flash", "qwen3-coder-plus", "qwen3-coder-flash"}

DASHSCOPE_KEY = (
    os.getenv("DASHSCOPE_API_API_KEY")
    or os.getenv("DASHSCOPE_API_KEY")
    or os.getenv("ALIBABA_API_KEY")
    or ""
)
GRADER_MODEL = os.getenv("EVAL_GRADER_MODEL", "kimi-k2.5")


def _dashscope_url(model: str) -> str:
    if model in _QWEN_MODELS or model.startswith("qwen"):
        return "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
    return "https://coding-intl.dashscope.aliyuncs.com/v1/chat/completions"


def _is_native_dashscope(model: str) -> bool:
    """Native DashScope API uses input/parameters wrapper; OpenAI-compat does not."""
    return model in _QWEN_MODELS or model.startswith("qwen")
RESULTS_PATH = Path(__file__).with_name("eval_hybrid_results.json")
REPORT_PATH = Path(__file__).with_name("eval_hybrid_report.md")

# ---------------------------------------------------------------------------
# 100 diverse DOU queries
# ---------------------------------------------------------------------------

QUERIES: list[dict] = [
    # --- General legal topics ---
    {"q": "reforma tributária regulamentação"},
    {"q": "lei de licitações e contratos administrativos"},
    {"q": "programa bolsa família reajuste"},
    {"q": "salário mínimo 2024"},
    {"q": "política nacional de resíduos sólidos"},
    {"q": "código florestal alterações"},
    {"q": "marco legal das startups"},
    {"q": "lei geral de proteção de dados pessoais"},
    {"q": "reforma da previdência social"},
    {"q": "estatuto da criança e do adolescente"},
    # --- Specific ministries ---
    {"q": "nomeação cargo comissionado", "issuing_organ": "Ministério da Saúde"},
    {"q": "concurso público edital", "issuing_organ": "Ministério da Educação"},
    {"q": "licitação pregão eletrônico", "issuing_organ": "Ministério da Defesa"},
    {"q": "contrato administrativo extrato"},
    {"q": "convênio transferência voluntária"},
    {"q": "portaria normativa instrução"},
    {"q": "resolução conselho nacional"},
    {"q": "decreto regulamentar execução"},
    {"q": "medida provisória conversão lei"},
    {"q": "instrução normativa receita federal"},
    # --- Date-filtered queries ---
    {"q": "covid vacinação emergencial", "date_from": "2021-01-01", "date_to": "2021-12-31"},
    {"q": "auxílio emergencial pagamento", "date_from": "2020-03-01", "date_to": "2020-12-31"},
    {"q": "olimpíadas rio segurança pública", "date_from": "2016-01-01", "date_to": "2016-12-31"},
    {"q": "copa do mundo infraestrutura", "date_from": "2013-01-01", "date_to": "2014-12-31"},
    {"q": "programa minha casa minha vida", "date_from": "2009-01-01", "date_to": "2023-12-31"},
    # --- DOU section filters ---
    {"q": "privatização empresa estatal", "section": "do1"},
    {"q": "nomeação magistrado tribunal", "section": "do1"},
    {"q": "resultado julgamento licitação", "section": "do3"},
    {"q": "extrato contrato prestação serviços", "section": "do3"},
    {"q": "despacho indeferimento recurso", "section": "do1"},
    # --- Art type specific ---
    {"q": "meio ambiente licenciamento ambiental", "art_type": "portaria"},
    {"q": "importação exportação comércio exterior", "art_type": "resolução"},
    {"q": "concessão aposentadoria servidor", "art_type": "portaria"},
    {"q": "energia elétrica tarifa reajuste", "art_type": "resolução"},
    {"q": "transporte rodoviário regulamentação", "art_type": "decreto"},
    # --- Semantic / conceptual queries ---
    {"q": "proteção dos direitos indígenas demarcação terras"},
    {"q": "combate à corrupção transparência pública"},
    {"q": "sustentabilidade ambiental desenvolvimento econômico"},
    {"q": "inclusão digital acesso à internet"},
    {"q": "segurança alimentar combate à fome"},
    {"q": "violência contra a mulher medidas protetivas"},
    {"q": "direitos das pessoas com deficiência acessibilidade"},
    {"q": "liberdade de imprensa sigilo de fonte"},
    {"q": "autonomia universitária ensino superior"},
    {"q": "regulação mercado financeiro banco central"},
    # --- Specific entities / proper nouns ---
    {"q": "Petrobras conselho administração"},
    {"q": "IBAMA multa infração ambiental"},
    {"q": "ANVISA registro medicamento"},
    {"q": "INSS benefício previdenciário"},
    {"q": "Banco do Brasil licitação"},
    {"q": "FUNAI terra indígena"},
    {"q": "CAPES bolsa pesquisa"},
    {"q": "CNPq fomento ciência tecnologia"},
    {"q": "ANATEL telecomunicações frequência"},
    {"q": "ANEEL energia elétrica distribuidora"},
    # --- Complex multi-concept ---
    {"q": "parceria público-privada infraestrutura saneamento"},
    {"q": "zona franca de manaus incentivo fiscal"},
    {"q": "sistema único de saúde financiamento"},
    {"q": "fundo de manutenção educação básica FUNDEB"},
    {"q": "programa nacional alimentação escolar PNAE"},
    {"q": "consórcio intermunicipal resíduos sólidos"},
    {"q": "agência reguladora autonomia financeira"},
    {"q": "contratação temporária excepcional interesse público"},
    {"q": "regime diferenciado contratações RDC"},
    {"q": "pregão eletrônico sistema registro preços"},
    # --- Short / ambiguous queries ---
    {"q": "aposentadoria"},
    {"q": "nomeação"},
    {"q": "exoneração"},
    {"q": "licitação"},
    {"q": "portaria"},
    # --- Long / detailed queries ---
    {"q": "autorização para funcionamento de curso de graduação em medicina universidade federal"},
    {"q": "homologação resultado final concurso público para provimento de cargos efetivos"},
    {"q": "declaração de utilidade pública para fins de desapropriação imóvel rural"},
    {"q": "credenciamento instituição de educação superior recredenciamento"},
    {"q": "concessão pensão civil vitalícia dependente servidor falecido"},
    # --- Negative / edge cases ---
    {"q": "xyznonexistentterm12345"},
    {"q": "bitcoin criptomoeda regulação"},
    {"q": "inteligência artificial regulamentação"},
    {"q": "5G leilão espectro radiofrequência"},
    {"q": "energia solar fotovoltaica geração distribuída"},
    # --- Recent topics ---
    {"q": "marco temporal terras indígenas STF"},
    {"q": "reforma administrativa servidor público"},
    {"q": "teto de gastos emenda constitucional"},
    {"q": "arcabouço fiscal regra despesa"},
    {"q": "imposto seletivo produtos nocivos"},
    # --- Cross-section queries ---
    {"q": "cessão servidor público órgão"},
    {"q": "redistribuição cargo técnico administrativo"},
    {"q": "progressão funcional carreira magistério"},
    {"q": "adicional insalubridade periculosidade"},
    {"q": "licença capacitação afastamento"},
    # --- Procurement / contracts ---
    {"q": "ata registro preços adesão carona"},
    {"q": "inexigibilidade licitação contratação direta"},
    {"q": "dispensa licitação emergencial"},
    {"q": "termo aditivo contrato prorrogação"},
    {"q": "sanção administrativa impedimento licitar"},
    # --- Health / education ---
    {"q": "residência médica programa vagas"},
    {"q": "medicamento genérico registro ANVISA"},
    {"q": "programa mais médicos interior"},
    {"q": "ENEM resultado vestibular SISU"},
    {"q": "PROUNI bolsa integral parcial"},
]

assert len(QUERIES) == 100, f"Expected 100 queries, got {len(QUERIES)}"


# ---------------------------------------------------------------------------
# Search runner
# ---------------------------------------------------------------------------

def run_search(query_spec: dict, mode: str) -> dict:
    """Run a single search and return the result dict."""
    try:
        result = es_search(
            query=query_spec["q"],
            mode=mode,
            page_size=5,
            date_from=query_spec.get("date_from"),
            date_to=query_spec.get("date_to"),
            section=query_spec.get("section"),
            art_type=query_spec.get("art_type"),
            issuing_organ=query_spec.get("issuing_organ"),
        )
        return {
            "mode": result.get("mode"),
            "mode_fallback": result.get("mode_fallback", False),
            "total": result.get("total", 0),
            "results": [
                {
                    "score": r.get("score"),
                    "identifica": (r.get("identifica") or "")[:120],
                    "ementa": (r.get("ementa") or "")[:200],
                    "art_type": r.get("art_type"),
                    "pub_date": r.get("pub_date"),
                    "issuing_organ": (r.get("issuing_organ") or "")[:80],
                    "snippet": (r.get("snippet") or "")[:200],
                }
                for r in result.get("results", [])[:5]
            ],
        }
    except Exception as e:
        return {"mode": mode, "error": str(e), "total": 0, "results": []}


# ---------------------------------------------------------------------------
# LLM grader
# ---------------------------------------------------------------------------

GRADER_PROMPT = """\
You are a search quality evaluator for Brazil's Diário Oficial da União (DOU) legal document search engine.

Given a search query and its top-5 results from three search modes (BM25 keyword, Semantic vector, Hybrid), \
evaluate each mode's result quality.

For each mode, provide:
1. **relevance** (1-5): How relevant are the results to the query intent?
   - 5: All results are highly relevant
   - 4: Most results relevant, minor misses
   - 3: Mixed relevance
   - 2: Mostly irrelevant with some hits
   - 1: Completely irrelevant or no results
2. **diversity** (1-5): Do results cover different aspects/sources?
3. **ranking** (1-5): Are the most relevant results ranked highest?
4. **brief_comment**: One sentence explaining the score (in English).

Also provide:
- **best_mode**: Which mode performed best for this query ("bm25", "semantic", or "hybrid")
- **query_difficulty**: How hard is this query? ("easy", "medium", "hard")

Respond ONLY with valid JSON (no markdown fences, no extra text):
{
  "bm25": {"relevance": N, "diversity": N, "ranking": N, "brief_comment": "..."},
  "semantic": {"relevance": N, "diversity": N, "ranking": N, "brief_comment": "..."},
  "hybrid": {"relevance": N, "diversity": N, "ranking": N, "brief_comment": "..."},
  "best_mode": "...",
  "query_difficulty": "..."
}"""


def grade_results(query_spec: dict, bm25: dict, semantic: dict, hybrid: dict) -> dict | None:
    """Send query + results to Qwen for grading."""
    user_msg = json.dumps({
        "query": query_spec["q"],
        "filters": {k: v for k, v in query_spec.items() if k != "q" and v},
        "bm25_results": bm25.get("results", []),
        "bm25_total": bm25.get("total", 0),
        "bm25_fallback": bm25.get("mode_fallback", False),
        "semantic_results": semantic.get("results", []),
        "semantic_total": semantic.get("total", 0),
        "semantic_fallback": semantic.get("mode_fallback", False),
        "hybrid_results": hybrid.get("results", []),
        "hybrid_total": hybrid.get("total", 0),
        "hybrid_fallback": hybrid.get("mode_fallback", False),
    }, ensure_ascii=False, indent=1)

    url = _dashscope_url(GRADER_MODEL)
    native = _is_native_dashscope(GRADER_MODEL)

    for attempt in range(3):
        try:
            if native:
                # DashScope native API format
                payload: dict = {
                    "model": GRADER_MODEL,
                    "input": {
                        "messages": [
                            {"role": "system", "content": GRADER_PROMPT},
                            {"role": "user", "content": user_msg},
                        ],
                    },
                    "parameters": {
                        "result_format": "message",
                        "max_tokens": 500,
                        "temperature": 0.1,
                    },
                }
            else:
                # OpenAI-compatible format (kimi, minimax, etc.)
                payload = {
                    "model": GRADER_MODEL,
                    "messages": [
                        {"role": "system", "content": GRADER_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    "max_tokens": 500,
                    "temperature": 0.1,
                }

            resp = httpx.post(
                url,
                headers={"Authorization": f"Bearer {DASHSCOPE_KEY}", "Content-Type": "application/json"},
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()

            if native:
                content = data["output"]["choices"][0]["message"]["content"]
            else:
                content = data["choices"][0]["message"]["content"]
            # Strip thinking tags if present
            if "</think>" in content:
                content = content.split("</think>")[-1].strip()
            # Strip markdown fences
            content = content.strip()
            if content.startswith("```"):
                content = "\n".join(content.split("\n")[1:])
            if content.endswith("```"):
                content = content[:-3]
            return json.loads(content.strip())
        except Exception as e:
            logger.warning("Grade attempt %d failed: %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(2)
    return None


# ---------------------------------------------------------------------------
# Report generator
# ---------------------------------------------------------------------------

def generate_report(all_results: list[dict]) -> str:
    """Generate markdown report from graded results."""
    graded = [r for r in all_results if r.get("grade")]
    if not graded:
        return "# No graded results to report\n"

    # Aggregate scores
    modes = ["bm25", "semantic", "hybrid"]
    totals = {m: {"relevance": [], "diversity": [], "ranking": []} for m in modes}
    best_counts = {"bm25": 0, "semantic": 0, "hybrid": 0}
    difficulty_counts = {"easy": 0, "medium": 0, "hard": 0}
    fallback_count = 0
    no_results_count = {m: 0 for m in modes}

    for r in graded:
        g = r["grade"]
        best = g.get("best_mode", "hybrid")
        if best in best_counts:
            best_counts[best] += 1
        diff = g.get("query_difficulty", "medium")
        if diff in difficulty_counts:
            difficulty_counts[diff] += 1
        for m in modes:
            mg = g.get(m, {})
            for metric in ("relevance", "diversity", "ranking"):
                val = mg.get(metric)
                if val is not None:
                    totals[m][metric].append(val)
            # Check no-results
            search_data = r.get(m, {})
            if search_data.get("total", 0) == 0:
                no_results_count[m] += 1
        if r.get("semantic", {}).get("mode_fallback"):
            fallback_count += 1

    def avg(lst):
        return round(sum(lst) / len(lst), 2) if lst else 0

    n = len(graded)
    lines = [
        "# Hybrid Search Quality Evaluation Report",
        "",
        f"**Queries evaluated**: {n} / {len(all_results)}",
        f"**Grader model**: {GRADER_MODEL}",
        f"**Date**: {time.strftime('%Y-%m-%d %H:%M')}",
        f"**Embedding coverage**: ~366K / 16.3M docs (2.2%)",
        "",
        "## Overall Scores (1-5 scale)",
        "",
        "| Mode | Relevance | Diversity | Ranking | Avg |",
        "|------|-----------|-----------|---------|-----|",
    ]
    for m in modes:
        rel = avg(totals[m]["relevance"])
        div = avg(totals[m]["diversity"])
        rank = avg(totals[m]["ranking"])
        overall = round((rel + div + rank) / 3, 2)
        lines.append(f"| {m} | {rel} | {div} | {rank} | {overall} |")

    lines += [
        "",
        "## Best Mode Distribution",
        "",
        f"- **BM25 wins**: {best_counts['bm25']} ({round(best_counts['bm25']/n*100)}%)",
        f"- **Semantic wins**: {best_counts['semantic']} ({round(best_counts['semantic']/n*100)}%)",
        f"- **Hybrid wins**: {best_counts['hybrid']} ({round(best_counts['hybrid']/n*100)}%)",
        "",
        "## Query Difficulty",
        "",
        f"- Easy: {difficulty_counts['easy']}, Medium: {difficulty_counts['medium']}, Hard: {difficulty_counts['hard']}",
        "",
        "## Operational Notes",
        "",
        f"- Semantic fallbacks (embedding server down): {fallback_count}",
        f"- Zero-result queries — BM25: {no_results_count['bm25']}, Semantic: {no_results_count['semantic']}, Hybrid: {no_results_count['hybrid']}",
        "",
        "## Per-Query Details",
        "",
        "| # | Query | Best | BM25 | Sem | Hyb | Difficulty |",
        "|---|-------|------|------|-----|-----|------------|",
    ]
    for i, r in enumerate(graded, 1):
        g = r["grade"]
        q = r["query"][:45]
        best = g.get("best_mode", "?")
        bm25_r = g.get("bm25", {}).get("relevance", "?")
        sem_r = g.get("semantic", {}).get("relevance", "?")
        hyb_r = g.get("hybrid", {}).get("relevance", "?")
        diff = g.get("query_difficulty", "?")
        lines.append(f"| {i} | {q} | {best} | {bm25_r} | {sem_r} | {hyb_r} | {diff} |")

    # Bottom 10 worst queries
    worst = sorted(graded, key=lambda r: min(
        r["grade"].get("bm25", {}).get("relevance", 5),
        r["grade"].get("semantic", {}).get("relevance", 5),
        r["grade"].get("hybrid", {}).get("relevance", 5),
    ))[:10]

    lines += [
        "",
        "## Worst Performing Queries",
        "",
    ]
    for r in worst:
        g = r["grade"]
        q = r["query"]
        comments = []
        for m in modes:
            mg = g.get(m, {})
            comments.append(f"{m}: {mg.get('relevance','?')}/5 — {mg.get('brief_comment','')}")
        lines.append(f"**\"{q}\"**")
        for c in comments:
            lines.append(f"  - {c}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Evaluate hybrid search quality")
    parser.add_argument("--queries", type=int, default=100, help="Number of queries to run")
    parser.add_argument("--report-only", action="store_true", help="Regenerate report from cached results")
    args = parser.parse_args()

    if args.report_only:
        if not RESULTS_PATH.exists():
            logger.error("No cached results at %s", RESULTS_PATH)
            return 1
        all_results = json.loads(RESULTS_PATH.read_text())
        report = generate_report(all_results)
        REPORT_PATH.write_text(report)
        logger.info("Report written to %s", REPORT_PATH)
        print(report)
        return 0

    if not DASHSCOPE_KEY:
        logger.error("No DashScope API key found")
        return 1

    queries = QUERIES[:args.queries]
    total = len(queries)

    # Resume from cached results if available
    cached: list[dict] = []
    if RESULTS_PATH.exists():
        cached = json.loads(RESULTS_PATH.read_text())
        cached_queries = {r["query"] for r in cached if r.get("grade")}
        logger.info("Resuming: %d already graded", len(cached_queries))
    else:
        cached_queries = set()

    all_results: list[dict] = list(cached)

    logger.info("Starting eval: %d queries × 3 modes, grader=%s", total, GRADER_MODEL)

    for i, qspec in enumerate(queries, 1):
        q = qspec["q"]
        if q in cached_queries:
            logger.info("[%d/%d] %s (cached)", i, total, q)
            continue
        logger.info("[%d/%d] %s", i, total, q)

        # Run all 3 modes
        bm25 = run_search(qspec, "bm25")
        semantic = run_search(qspec, "semantic")
        hybrid = run_search(qspec, "hybrid")

        # Grade
        grade = grade_results(qspec, bm25, semantic, hybrid)
        if grade:
            best = grade.get("best_mode", "?")
            rel_h = grade.get("hybrid", {}).get("relevance", "?")
            logger.info("  → graded: best=%s, hybrid_rel=%s", best, rel_h)
        else:
            logger.warning("  → grading failed")

        entry = {
            "query": q,
            "filters": {k: v for k, v in qspec.items() if k != "q"},
            "bm25": bm25,
            "semantic": semantic,
            "hybrid": hybrid,
            "grade": grade,
        }
        all_results.append(entry)

        # Save incrementally
        if i % 10 == 0 or i == total:
            RESULTS_PATH.write_text(json.dumps(all_results, ensure_ascii=False, indent=1))
            logger.info("  checkpoint saved (%d/%d)", i, total)

        # Rate limit: ~2 req/sec for DashScope
        time.sleep(0.5)

    # Final report
    report = generate_report(all_results)
    REPORT_PATH.write_text(report)
    logger.info("Report written to %s", REPORT_PATH)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
