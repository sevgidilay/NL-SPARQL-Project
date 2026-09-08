"""
kg_pipeline.py — shared deterministic KG pipeline.

Fixed sequence: entity_lookup → template_sparql → generate_sparql → execute → (retry) → summarize.
Used by both the chat tab (orchestrator.py) and the NL→SPARQL tab (app.py).
"""
from __future__ import annotations

import re as _re
from dataclasses import dataclass, field
from typing import Optional

_WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"

_SUPERLATIVE_RE = _re.compile(
    r"\b(tallest|highest|largest|biggest|greatest|smallest|shortest|"
    r"oldest|youngest|richest|poorest|fastest|slowest|heaviest|lightest|"
    r"most\s+\w+|least\s+\w+)\b",
    _re.IGNORECASE,
)

# oldest/shortest → ASC (smallest value = most extreme in that direction for dates/sizes)
# youngest/tallest → DESC (largest value = most extreme)
_SUPERLATIVE_DIRECTION: dict[str, str] = {
    "tallest": "DESC", "highest": "DESC", "largest": "DESC", "biggest": "DESC",
    "greatest": "DESC", "richest": "DESC", "fastest": "DESC", "heaviest": "DESC",
    "most": "DESC", "youngest": "DESC",
    "smallest": "ASC", "shortest": "ASC", "oldest": "ASC",
    "poorest": "ASC", "slowest": "ASC", "lightest": "ASC", "least": "ASC",
}


def _detect_superlative(question: str) -> str | None:
    """Return 'ASC' or 'DESC' if a superlative is detected in the question, else None."""
    m = _SUPERLATIVE_RE.search(question)
    if not m:
        return None
    word = m.group(1).lower().split()[0]
    return _SUPERLATIVE_DIRECTION.get(word)


def _try_template_sparql(
    entity_hints: list,
    predicate_hints: list,
    question: str = "",
) -> tuple[str | None, list]:
    """Try a deterministic template SPARQL for each (entity, predicate) pair.

    Tries forward direction (wd:Qxxx wdt:Pyyy ?o) first; if 0 rows, tries
    reverse (?s wdt:Pyyy wd:Qxxx).  Returns (sparql_string, rows) for the
    first pair that produces results, else (None, []).

    Always targets the Wikidata endpoint regardless of domain config, because
    entity QIDs are always Wikidata identifiers.
    """
    import src.sparql_executor as sparql_executor

    order_dir = _detect_superlative(question)

    for eh in entity_hints:
        qid = eh.get("qid", "")
        for ph in predicate_hints:
            pid = ph.get("pid", "").replace("wdt:", "")
            if not qid or not pid:
                continue

            if order_dir:
                fwd = (
                    f"SELECT DISTINCT ?o ?oLabel WHERE {{\n"
                    f"  wd:{qid} wdt:{pid} ?o .\n"
                    f'  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}\n'
                    f"  FILTER(isLiteral(?o))\n"
                    f"}}\nORDER BY {order_dir}(?o)\nLIMIT 1"
                )
            else:
                fwd = (
                    f"SELECT DISTINCT ?o ?oLabel WHERE {{\n"
                    f"  wd:{qid} wdt:{pid} ?o .\n"
                    f'  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}\n'
                    f"}}\nLIMIT 10"
                )

            fwd_res = sparql_executor.execute(fwd, _WIKIDATA_SPARQL)
            fwd_rows = fwd_res.get("results", []) if fwd_res.get("success") else []

            # reverse direction is not meaningful for superlatives
            if order_dir:
                if fwd_rows:
                    return fwd, fwd_rows
                continue

            rev = (
                f"SELECT DISTINCT ?s ?sLabel WHERE {{\n"
                f"  ?s wdt:{pid} wd:{qid} .\n"
                f'  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}\n'
                f"}}\nLIMIT 10"
            )
            rev_res = sparql_executor.execute(rev, _WIKIDATA_SPARQL)
            rev_rows = rev_res.get("results", []) if rev_res.get("success") else []

            # Prefer the direction with more results — a single-row forward hit
            # is often the wrong direction (e.g. Jupiter→Sun instead of moons→Jupiter)
            if rev_rows and len(rev_rows) > len(fwd_rows):
                return rev, rev_rows
            if fwd_rows:
                return fwd, fwd_rows

    return None, []


@dataclass
class PipelineResult:
    found_in_kg: bool
    entity_hints: list
    predicate_hints: list
    sparql: Optional[str]
    retried: bool
    results: Optional[list]
    summary: Optional[str]
    steps: list = field(default_factory=list)
    llm_terms: dict = field(default_factory=dict)


def run_pipeline(question: str, config: dict, model: str) -> PipelineResult:
    """Run the fixed KG pipeline and return a PipelineResult.

    Steps:
      1. Entity + predicate lookup
      2. NL → SPARQL (with entity hints)
      3. Execute; retry once with temperature=0.7 if 0 rows
      4. Summarize results (or mark not found)
    """
    import src.entity_linker as entity_linker
    import src.nl_to_sparql as nl_to_sparql
    import src.sparql_executor as sparql_executor
    import src.answer_summarizer as answer_summarizer

    steps: list[dict] = []

    # ── Step 0: LLM extraction (Wikidata + model only) ────────────────────
    llm_terms: dict = {}
    if "wikidata.org" in config.get("endpoint", "") and model:
        llm_ents, llm_rels = entity_linker.llm_extract(question, model)
        llm_terms = {"entities": llm_ents, "relations": llm_rels}
        steps.append({
            "name": "__llm_extraction__",
            "observation": f"LLM identified: entities={llm_ents}, relations={llm_rels}",
        })

    # ── Step 1: Entity lookup ──────────────────────────────────────────────
    entity_hints = entity_linker.lookup_entities(question, config, model=model)
    predicate_hints = entity_linker.lookup_relations(
        question, config, model=model, entity_hints=entity_hints
    )

    # Fetch the actual properties present on each resolved entity from Wikidata
    # so the LLM prompt contains real PIDs rather than keyword-guessed ones.
    # Skip class/type entities — their properties are metadata about the class itself,
    # not predicates useful for generating instance-listing queries.
    entity_properties: dict[str, list[dict]] = {}
    if "wikidata.org" in config.get("endpoint", ""):
        for eh in entity_hints:
            qid = eh.get("qid", "")
            if qid and not eh.get("is_class"):
                props = entity_linker.fetch_entity_properties(qid)
                if props:
                    entity_properties[qid] = props

    if entity_hints:
        entity_obs = "Entity lookup · " + "; ".join(
            f'"{h["surface"]}" → wd:{h["qid"]}' for h in entity_hints
        )
    else:
        entity_obs = "Entity lookup · no entities resolved"
    steps.append({"name": "__entity_lookup__", "observation": entity_obs})

    # ── Step 1b: Template SPARQL (direct answer when entity+predicate are known) ──
    if entity_hints and predicate_hints:
        tmpl_sparql, tmpl_rows = _try_template_sparql(entity_hints, predicate_hints, question)
        if tmpl_sparql and tmpl_rows:
            steps.append({
                "name": "generate_sparql",
                "observation": f"Template SPARQL ({len(tmpl_sparql)} chars) — skipped LLM",
            })
            steps.append({
                "name": "execute_sparql",
                "observation": f"Template returned {len(tmpl_rows)} row(s)",
            })
            try:
                summary = answer_summarizer.summarize(question, tmpl_rows, model=model)
                steps.append({"name": "summarize_results", "observation": summary[:300]})
            except Exception as exc:
                summary = None
                steps.append({"name": "summarize_results", "observation": f"Summarization failed: {exc}", "error": str(exc)})
            return PipelineResult(
                found_in_kg=True, entity_hints=entity_hints, predicate_hints=predicate_hints,
                sparql=tmpl_sparql, retried=False, results=tmpl_rows, summary=summary, steps=steps,
                llm_terms=llm_terms,
            )

    # ── Step 2: SPARQL generation ──────────────────────────────────────────
    try:
        raw = nl_to_sparql.translate(
            question, config, model=model,
            entity_hints=entity_hints,
            predicate_hints=predicate_hints,
            entity_properties=entity_properties or None,
        )
        sparql = sparql_executor.clean_sparql(raw)
    except Exception as exc:
        steps.append({"name": "generate_sparql", "observation": f"SPARQL generation failed: {exc}", "error": str(exc)})
        return PipelineResult(
            found_in_kg=False, entity_hints=entity_hints, predicate_hints=predicate_hints,
            sparql=None, retried=False, results=None, summary=None, steps=steps,
            llm_terms=llm_terms,
        )

    steps.append({"name": "generate_sparql", "observation": f"Generated SPARQL ({len(sparql)} chars)"})

    # ── Step 3: Execute ────────────────────────────────────────────────────
    endpoint = config.get("endpoint", "")
    if not endpoint:
        steps.append({"name": "execute_sparql", "observation": "No endpoint configured for this domain", "error": "no_endpoint"})
        return PipelineResult(
            found_in_kg=False, entity_hints=entity_hints, predicate_hints=predicate_hints,
            sparql=sparql, retried=False, results=None, summary=None, steps=steps,
            llm_terms=llm_terms,
        )

    result = sparql_executor.execute(sparql, endpoint)
    retried = False

    if result.get("success") and not result.get("results"):
        # Retry once with higher temperature for variety
        retried = True
        try:
            retry_raw = nl_to_sparql.translate(
                question, config, model=model, temperature=0.7,
                entity_hints=entity_hints, predicate_hints=predicate_hints,
                entity_properties=entity_properties or None,
            )
            retry_sparql = sparql_executor.clean_sparql(retry_raw)
            retry_result = sparql_executor.execute(retry_sparql, endpoint)
            if retry_result.get("success") and retry_result.get("results"):
                sparql = retry_sparql
                result = retry_result
                steps.append({"name": "execute_sparql", "observation": f"Retry succeeded · {len(result['results'])} row(s)"})
            else:
                steps.append({"name": "execute_sparql", "observation": "Retry also returned 0 rows"})
        except Exception as exc:
            steps.append({"name": "execute_sparql", "observation": f"Retry failed: {exc}", "error": str(exc)})
    elif result.get("success"):
        n = len(result.get("results", []))
        steps.append({"name": "execute_sparql", "observation": f"Returned {n} row(s)"})
    else:
        err = result.get("error", "unknown error")
        steps.append({"name": "execute_sparql", "observation": f"Query failed: {err}", "error": err})

    rows = result.get("results", []) if result.get("success") else []

    if not rows:
        return PipelineResult(
            found_in_kg=False, entity_hints=entity_hints, predicate_hints=predicate_hints,
            sparql=sparql, retried=retried, results=[], summary=None, steps=steps,
            llm_terms=llm_terms,
        )

    # ── Step 4: Summarize ──────────────────────────────────────────────────
    try:
        summary = answer_summarizer.summarize(question, rows, model=model, entity_hints=entity_hints)
        steps.append({"name": "summarize_results", "observation": summary[:300]})
    except Exception as exc:
        summary = None
        steps.append({"name": "summarize_results", "observation": f"Summarization failed: {exc}", "error": str(exc)})

    return PipelineResult(
        found_in_kg=True, entity_hints=entity_hints, predicate_hints=predicate_hints,
        sparql=sparql, retried=retried, results=rows, summary=summary, steps=steps,
        llm_terms=llm_terms,
    )
