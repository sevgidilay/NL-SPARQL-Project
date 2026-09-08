"""
orchestrator.py — fixed deterministic KG pipeline turn.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

from .memory import ChatMemory
from .tool_protocol import ChatMessage
import src.domain_router as domain_router
import src.kg_pipeline as kg_pipeline


_STEP_LABELS: dict[str, str] = {
    "__llm_extraction__": "Asking LLM what to look up...",
    "__entity_lookup__": "Looking up entities...",
    "resolve_pronouns":  "Resolving context...",
    "generate_sparql":   "Generating SPARQL...",
    "execute_sparql":    "Executing query...",
    "summarize_results": "Summarizing results...",
}

_THIRD_PERSON_PRONOUNS = re.compile(
    r"\b(he|she|it|they|him|her|his|hers|their|theirs|its)\b",
    re.IGNORECASE,
)


def _resolve_pronouns(user_msg: str, memory: ChatMemory) -> tuple[str, str | None]:
    """Replace third-person pronouns with the primary entity from the last turn.

    Only rewrites when the current message has pronouns but no extractable
    named entities of its own.  Returns (resolved_question, note) where note
    is None when no rewrite occurred.
    """
    if not _THIRD_PERSON_PRONOUNS.search(user_msg):
        return user_msg, None
    last_ents = memory.last_entities()
    if not last_ents:
        return user_msg, None
    from src.entity_linker import _extract_entities
    if _extract_entities(user_msg):
        return user_msg, None
    primary = last_ents[0]["surface"]
    resolved = _THIRD_PERSON_PRONOUNS.sub(primary, user_msg, count=1)
    return resolved, f"'{user_msg}' → '{resolved}'"


def run_turn(
    user_msg: str,
    memory: ChatMemory,
    registry: dict,
    configs: dict,
    model: str,
    progress_callback: Optional[Callable[[str], None]] = None,
    override_config: Optional[dict] = None,
) -> ChatMessage:
    """Run one fixed-pipeline turn and return the assistant ChatMessage.

    Deterministic sequence (no LLM routing):
      1. detect_domain  — keyword/LLM classifier picks a config
      2. entity_lookup  — NER + Wikidata API resolves entity QIDs
      3. generate_sparql — NL → SPARQL with entity hints injected
      4. execute_sparql  — live SPARQL endpoint; retry once on 0 rows
      5. summarize       — results → one-sentence NL answer
      6. "not found"     — if KG has no data, say so; no LLM fallback

    The returned ChatMessage has:
      - role="assistant"
      - text=NL answer (or "not found" message)
      - artifact_ids=[entities_n, sparql_n, results_n] as produced
      - trace=list of step dicts for the "View tool trace" expander
    """
    def _progress(msg: str) -> None:
        if progress_callback is not None:
            progress_callback(msg)

    trace: list[dict] = []
    artifact_ids: list[str] = []

    # ── 1. Detect domain ──────────────────────────────────────────────────
    if override_config is not None:
        config = override_config
        detected = override_config.get("domain_name", "Wikidata (Generic)")
        trace.append({"tool": "detect_domain", "args": {},
                      "observation": f"Domain override: {detected}"})
    else:
        _progress("Detecting topic...")
        try:
            detected = domain_router.detect_domain(user_msg, configs, model=model)
            config = configs[detected]
            memory._domain_stack.append(detected)
            trace.append({"tool": "detect_domain", "args": {"question": user_msg},
                          "observation": f"Domain: {detected}"})
        except Exception as exc:
            # Fall back to first available config
            detected = next(iter(configs))
            config = configs[detected]
            trace.append({"tool": "detect_domain", "args": {},
                          "observation": f"Domain detection failed ({exc}); using {detected}"})

    # ── 1.5. Resolve pronouns from prior context ──────────────────────────
    resolved_msg, note = _resolve_pronouns(user_msg, memory)
    if note:
        trace.append({"tool": "resolve_pronouns", "args": {"original": user_msg},
                      "observation": f"Pronoun resolved: {note}"})

    # ── 2-5. Run shared fixed pipeline ───────────────────────────────────
    _progress("Looking up entities...")
    try:
        result = kg_pipeline.run_pipeline(resolved_msg, config, model)
    except Exception as exc:
        return ChatMessage(
            role="assistant",
            text=f"Pipeline error: {exc}. Please try again.",
            artifact_ids=artifact_ids,
            trace=trace,
        )

    # Translate pipeline steps into trace entries
    for step in result.steps:
        trace.append({
            "tool":        step["name"],
            "args":        {},
            "observation": step["observation"],
            **({"error_kind": "tool_error"} if step.get("error") else {}),
        })

    # ── 3. Store artifacts in memory ──────────────────────────────────────
    if result.entity_hints:
        aid = memory.store_artifact("entities", result.entity_hints)
        artifact_ids.append(aid)
    if result.sparql:
        _progress("Generating SPARQL...")
        aid = memory.store_artifact("sparql", result.sparql)
        artifact_ids.append(aid)
    if result.results:
        _progress("Executing query...")
        aid = memory.store_artifact("results", result.results)
        artifact_ids.append(aid)

    # ── 4. Compose reply ──────────────────────────────────────────────────
    if result.found_in_kg and result.summary:
        text = result.summary
    elif result.found_in_kg and result.results:
        text = f"Found {len(result.results)} result(s) in the knowledge graph."
    else:
        text = (
            "The knowledge graph does not contain information matching this question. "
            "Try rephrasing, or check that the selected domain covers this topic."
        )

    return ChatMessage(role="assistant", text=text, artifact_ids=artifact_ids, trace=trace)
