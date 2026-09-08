"""
tools.py — tool registry wrapping existing src/* modules.

Jumainah implements the function bodies on Day 2-3.
No business logic is duplicated — every tool delegates to an existing module.

Day-1 contracts (locked):
  - generate_sparql MUST call sparql_executor.clean_sparql before storing artifact.
  - execute_sparql MUST default endpoint from memory.last_domain() when not supplied.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .memory import ChatMemory
from .tool_protocol import ToolResult, ToolSpec


_DEFAULT_MODELS: list = ["llama3.3:latest", "qwen3:latest", "mistral:latest"]


@dataclass
class ToolContext:
    """Shared context passed to every tool call."""
    memory: ChatMemory
    configs: dict   # {domain_name: config_dict} loaded from YAML
    model: str      # active LLM model name


# ---------------------------------------------------------------------------
# Registry builder
# ---------------------------------------------------------------------------

def build_registry(ctx: ToolContext) -> dict:
    """Return a dict mapping tool name -> callable(args: dict) -> ToolResult.

    Each callable closes over ctx so tools can access memory and configs
    without additional arguments.
    """
    return {
        "detect_domain":        lambda args: _detect_domain(args, ctx),
        "generate_sparql":      lambda args: _generate_sparql(args, ctx),
        "execute_sparql":       lambda args: _execute_sparql(args, ctx),
        "explain_sparql":       lambda args: _explain_sparql(args, ctx),
        "summarize_results":    lambda args: _summarize_results(args, ctx),
        "visualize_graph":      lambda args: _visualize_graph(args, ctx),
        "list_domain_examples": lambda args: _list_domain_examples(args, ctx),
        "compare_models":       lambda args: _compare_models(args, ctx),
    }


# ---------------------------------------------------------------------------
# Tool stubs — one per entry in TOOL_REGISTRY_TABLE
# ---------------------------------------------------------------------------

def _detect_domain(args: dict, ctx: ToolContext) -> ToolResult:
    """Wrap domain_router.detect_domain.

    Required args: question (str)
    Returns: domain name string; no artifact stored.
    """
    import src.domain_router as domain_router

    question = args.get("question")
    if not question:
        return ToolResult("detect_domain", args, None, None, None,
                          "Missing required arg: question")
    try:
        domain = domain_router.detect_domain(question, ctx.configs, model=ctx.model)
    except Exception as exc:
        return ToolResult("detect_domain", args, None, None, None, str(exc))

    ctx.memory._domain_stack.append(domain)
    return ToolResult(
        tool_name="detect_domain", args=args,
        payload=domain,
        preview={
            "domain_key": domain,
            "instruction": f'Call generate_sparql with domain="{domain}" — copy this string exactly.',
        },
        artifact_id=None,
        error=None,
    )


def _generate_sparql(args: dict, ctx: ToolContext) -> ToolResult:
    """Wrap nl_to_sparql.translate + sparql_executor.clean_sparql.

    Required args: question (str), domain (str)
    Contract: MUST call clean_sparql; stores cleaned string as sparql_<n>.
    Preview: first 500 chars of the cleaned SPARQL string.
    """
    import src.nl_to_sparql as nl_to_sparql
    import src.sparql_executor as sparql_executor
    import src.entity_linker as entity_linker

    question = args.get("question")
    domain   = args.get("domain")

    config = ctx.configs.get(domain)
    if config is None:
        return ToolResult("generate_sparql", args, None, None, None,
                          f"Unknown domain: {domain!r}")

    entity_hints    = entity_linker.lookup_entities(question, config)
    predicate_hints = entity_linker.lookup_relations(question, config)

    try:
        raw     = nl_to_sparql.translate(question, config, model=ctx.model, entity_hints=entity_hints, predicate_hints=predicate_hints)
        cleaned = sparql_executor.clean_sparql(raw)  # CONTRACT
    except Exception as exc:
        return ToolResult("generate_sparql", args, None, None, None, str(exc))

    ctx.memory._domain_stack.append(domain)

    extra_ids = []
    if entity_hints:
        extra_ids.append(ctx.memory.store_artifact("entities", entity_hints))

    artifact_id = ctx.memory.store_artifact("sparql", cleaned)

    return ToolResult(
        tool_name          = "generate_sparql",
        args               = args,
        payload            = cleaned,
        preview            = cleaned[:500],
        artifact_id        = artifact_id,
        error              = None,
        extra_artifact_ids = extra_ids,
    )


def _execute_sparql(args: dict, ctx: ToolContext) -> ToolResult:
    """Wrap sparql_executor.execute.

    Required args: sparql_artifact_id (str) OR sparql (str)
    Optional args: endpoint (str) — defaults from memory.last_domain()
    Contract: endpoint resolved via configs[memory.last_domain()]["endpoint"].
    Stores full results list as results_<n>; preview is first 5 rows.
    """
    import src.sparql_executor as sparql_executor

    # resolve SPARQL string
    sparql_id  = args.get("sparql_artifact_id")
    if sparql_id:
        sparql_str = ctx.memory.artifacts.get(sparql_id)
        if sparql_str is None:
            return ToolResult("execute_sparql", args, None, None, None,
                              f"Artifact not found: {sparql_id!r}")
    else:
        sparql_str = args.get("sparql")
    if not sparql_str:
        return ToolResult("execute_sparql", args, None, None, None,
                          "Provide sparql_artifact_id or sparql.")

    # resolve endpoint — CONTRACT: default from memory.last_domain()
    endpoint = args.get("endpoint")
    # If the LLM passed a domain name instead of a URL, resolve it
    if endpoint and endpoint in ctx.configs:
        endpoint = ctx.configs[endpoint].get("endpoint")
    if not endpoint:
        domain = ctx.memory.last_domain()
        if domain and domain in ctx.configs:
            endpoint = ctx.configs[domain].get("endpoint")
    if not endpoint:
        return ToolResult("execute_sparql", args, None, None, None,
                          "Cannot determine endpoint — no prior domain detected.")

    try:
        result = sparql_executor.execute(sparql_str, endpoint)
    except Exception as exc:
        return ToolResult("execute_sparql", args, None, None, None, str(exc))

    rows  = result.get("results", [])
    error = None if result.get("success") else result.get("error")
    artifact_id = ctx.memory.store_artifact("results", rows)

    return ToolResult(
        tool_name   = "execute_sparql",
        args        = args,
        payload     = rows,
        preview     = rows[:5],
        artifact_id = artifact_id,
        error       = error,
    )


def _explain_sparql(args: dict, ctx: ToolContext) -> ToolResult:
    """Wrap sparql_to_nl.translate.

    Required args: sparql_artifact_id (str) OR sparql (str)
    Returns: NL explanation string; no artifact stored.
    """
    import src.sparql_to_nl as sparql_to_nl

    sparql_id = args.get("sparql_artifact_id")
    if sparql_id:
        sparql_str = ctx.memory.artifacts.get(sparql_id)
        if sparql_str is None:
            return ToolResult("explain_sparql", args, None, None, None,
                              f"Artifact not found: {sparql_id!r}")
    else:
        sparql_str = args.get("sparql")
    if not sparql_str:
        return ToolResult("explain_sparql", args, None, None, None,
                          "Provide sparql_artifact_id or sparql.")

    domain = ctx.memory.last_domain()
    config = ctx.configs.get(domain, {}) if domain else {}

    try:
        explanation = sparql_to_nl.translate(sparql_str, config, model=ctx.model)
    except Exception as exc:
        return ToolResult("explain_sparql", args, None, None, None, str(exc))

    return ToolResult(
        tool_name="explain_sparql", args=args,
        payload=explanation, preview=explanation[:500], artifact_id=None, error=None,
    )


def _summarize_results(args: dict, ctx: ToolContext) -> ToolResult:
    """Wrap answer_summarizer.summarize.

    Required args: question (str), results_artifact_id (str)
    Returns: NL summary string; no artifact stored.
    """
    import src.answer_summarizer as answer_summarizer

    question   = args.get("question")
    results_id = args.get("results_artifact_id")
    if not question:
        return ToolResult("summarize_results", args, None, None, None,
                          "Missing required arg: question")
    if not results_id:
        return ToolResult("summarize_results", args, None, None, None,
                          "Missing required arg: results_artifact_id")

    rows = ctx.memory.artifacts.get(results_id)
    if rows is None:
        return ToolResult("summarize_results", args, None, None, None,
                          f"Artifact not found: {results_id!r}")

    try:
        summary = answer_summarizer.summarize(question, rows, model=ctx.model)
    except Exception as exc:
        return ToolResult("summarize_results", args, None, None, None, str(exc))

    return ToolResult(
        tool_name="summarize_results", args=args,
        payload=summary, preview=summary[:500], artifact_id=None, error=None,
    )


def _visualize_graph(args: dict, ctx: ToolContext) -> ToolResult:
    """Wrap viz.build_pyvis_html.

    Required args: results_artifact_id (str)
    Optional args: sparql_artifact_id (str)
    Stores PyVis HTML string as graph_<n>; preview is node/edge count.
    """
    import re
    from src.chat import viz

    results_id = args.get("results_artifact_id")
    if not results_id:
        return ToolResult("visualize_graph", args, None, None, None,
                          "Missing required arg: results_artifact_id")

    rows = ctx.memory.artifacts.get(results_id)
    if rows is None:
        return ToolResult("visualize_graph", args, None, None, None,
                          f"Artifact not found: {results_id!r}")

    sparql_id = args.get("sparql_artifact_id")
    if sparql_id:
        sparql_str = ctx.memory.artifacts.get(sparql_id) or ""
    else:
        sparql_str = ctx.memory.last_sparql() or ""

    try:
        html = viz.build_pyvis_html(rows, sparql_str, dark=False, height_px=480)
    except Exception as exc:
        return ToolResult("visualize_graph", args, None, None, None, str(exc))

    node_count = len(re.findall(r"nodes\.add\(", html))
    edge_count = len(re.findall(r"edges\.add\(", html))
    artifact_id = ctx.memory.store_artifact("graph", html)

    return ToolResult(
        tool_name="visualize_graph", args=args,
        payload=html,
        preview={"node_count": node_count, "edge_count": edge_count},
        artifact_id=artifact_id,
        error=None,
    )


def _list_domain_examples(args: dict, ctx: ToolContext) -> ToolResult:
    """Read example questions from configs[domain]["example_questions"].

    Required args: domain (str)
    Optional args: limit (int, default 5)
    Returns: list of example question strings; no artifact stored.
    """
    domain = args.get("domain")
    if not domain:
        return ToolResult("list_domain_examples", args, None, None, None,
                          "Missing required arg: domain")
    config = ctx.configs.get(domain)
    if config is None:
        return ToolResult("list_domain_examples", args, None, None, None,
                          f"Unknown domain: {domain!r}")

    try:
        limit = int(args.get("limit", 5))
    except (TypeError, ValueError):
        limit = 5

    raw = config.get("example_questions", [])
    questions = []
    for ex in raw[:limit]:
        if isinstance(ex, dict):
            questions.append(ex.get("question", ""))
        else:
            questions.append(str(ex))
    questions = [q for q in questions if q]

    return ToolResult(
        tool_name="list_domain_examples", args=args,
        payload=questions, preview=questions, artifact_id=None, error=None,
    )


def _compare_models(args: dict, ctx: ToolContext) -> ToolResult:
    """Run the model-arena pipeline (Tab 4 logic).

    Required args: question (str), domain (str)
    Optional args: models (list[str])
    Stores comparison result as comparison_<n>.
    Preview: one row per model with a 100-char answer excerpt.
    """
    import src.nl_to_sparql as nl_to_sparql
    import src.sparql_executor as sparql_executor

    question = args.get("question")
    domain   = args.get("domain")
    models   = args.get("models") or _DEFAULT_MODELS

    if not question:
        return ToolResult("compare_models", args, None, None, None,
                          "Missing required arg: question")
    if not domain:
        return ToolResult("compare_models", args, None, None, None,
                          "Missing required arg: domain")
    config = ctx.configs.get(domain)
    if config is None:
        return ToolResult("compare_models", args, None, None, None,
                          f"Unknown domain: {domain!r}")

    endpoint = config.get("endpoint")
    results  = []
    for model in models:
        entry = {"model": model, "sparql": "", "status": ""}
        try:
            raw     = nl_to_sparql.translate(question, config, model=model)
            cleaned = sparql_executor.clean_sparql(raw)
            entry["sparql"] = cleaned
            if endpoint:
                try:
                    res = sparql_executor.execute(cleaned, endpoint)
                    if res.get("success"):
                        n = len(res.get("results", []))
                        entry["status"] = f"ok ({n} rows)"
                    else:
                        entry["status"] = f"error: {res.get('error', '')[:80]}"
                except Exception as exc:
                    entry["status"] = f"execution failed: {str(exc)[:80]}"
            else:
                entry["status"] = "generated (no endpoint)"
        except Exception as exc:
            entry["status"] = f"generation failed: {str(exc)[:80]}"
        results.append(entry)

    artifact_id = ctx.memory.store_artifact("comparison", results)
    preview = [
        {"model": r["model"], "sparql_preview": r["sparql"][:100], "status": r["status"]}
        for r in results
    ]
    return ToolResult(
        tool_name="compare_models", args=args,
        payload=results, preview=preview, artifact_id=artifact_id, error=None,
    )
