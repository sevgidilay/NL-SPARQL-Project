"""
tool_protocol.py — frozen Day-1 interface contracts.

Dataclasses, JSON schema constants, and stub signatures for the chat module.
Business logic lives in orchestrator.py (Saif, Day 2-3).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ToolSpec:
    """Describes a single callable tool exposed to the LLM."""
    name: str
    description: str
    args_schema: dict   # {arg_name: {"type": str, "description": str, "required": bool}}
    return_shape: str   # prose description shown in the system prompt


@dataclass
class ToolResult:
    """Returned by every tool function in tools.py."""
    tool_name: str
    args: dict
    payload: Any                # full data stored in ChatMemory.artifacts
    preview: Any                # <=5-row excerpt serialised into the observation string
    artifact_id: Optional[str]  # e.g. "sparql_3"; None if tool produces no artifact
    error: Optional[str]        # None on success; message string on failure
    # Additional artifacts to register before artifact_id (e.g. entity lookup results)
    extra_artifact_ids: List[str] = field(default_factory=list)


@dataclass
class ChatMessage:
    """One turn in the conversation log (user or assistant)."""
    role: str                           # "user" | "assistant"
    text: str                           # displayed text
    artifact_ids: List[str] = field(default_factory=list)
    # one dict per agentic step: {"tool": str, "args": dict, "observation": str}
    trace: Optional[List[dict]] = None


@dataclass
class ParsedTurn:
    """Result of parse_llm_output(). Discriminated by `kind`."""
    kind: str                    # "tool_call" | "final" | "parse_error"
    raw: str                     # verbatim LLM output — always present
    thought: Optional[str] = None
    # populated when kind == "tool_call"
    tool: Optional[str] = None
    args: Optional[dict] = None
    # populated when kind == "final"
    final_answer: Optional[str] = None
    cite_artifacts: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# JSON schema constants (embedded verbatim in system prompt)
# ---------------------------------------------------------------------------

# Shape 1: call a tool
TOOL_CALL_SCHEMA: dict = {
    "thought": "<reasoning>",
    "tool": "<tool_name>",
    "args": {},
}

# Shape 2: produce a final answer
FINAL_SCHEMA: dict = {
    "thought": "<reasoning>",
    "final_answer": "<answer text shown to user>",
    "cite_artifacts": ["sparql_1", "results_1"],   # optional; default []
}

ARTIFACT_KINDS: tuple = ("sparql", "results", "graph", "comparison")

# ---------------------------------------------------------------------------
# Tool registry (names, required/optional args, artifact stored)
# Used by build_system_prompt to generate the tool listing section.
# ---------------------------------------------------------------------------

TOOL_REGISTRY_TABLE: List[dict] = [
    {
        "name": "detect_domain",
        "required": ["question"],
        "optional": [],
        "artifact": None,
    },
    {
        "name": "generate_sparql",
        "required": ["question", "domain"],
        "optional": [],
        "artifact": "sparql_<n>",
        "contract": "MUST call clean_sparql before storing artifact",
    },
    {
        "name": "execute_sparql",
        "required": ["sparql_artifact_id OR sparql"],
        "optional": ["endpoint"],
        "artifact": "results_<n>",
        "contract": "defaults endpoint from memory.last_domain() if not provided",
    },
    {
        "name": "explain_sparql",
        "required": ["sparql_artifact_id OR sparql"],
        "optional": [],
        "artifact": None,
    },
    {
        "name": "summarize_results",
        "required": ["question", "results_artifact_id"],
        "optional": [],
        "artifact": None,
    },
    {
        "name": "visualize_graph",
        "required": ["results_artifact_id"],
        "optional": ["sparql_artifact_id"],
        "artifact": "graph_<n>",
    },
    {
        "name": "list_domain_examples",
        "required": ["domain"],
        "optional": ["limit"],
        "artifact": None,
    },
    {
        "name": "compare_models",
        "required": ["question", "domain"],
        "optional": ["models"],
        "artifact": "comparison_<n>",
    },
]


# ---------------------------------------------------------------------------
# Full ToolSpec instances — locked Day-1 contract for the system prompt
# ---------------------------------------------------------------------------

TOOL_SPECS: List[ToolSpec] = [
    ToolSpec(
        name="detect_domain",
        description="Identify which knowledge domain the question belongs to.",
        args_schema={
            "question": {"type": "string", "required": True,
                         "description": "The user's natural language question."},
        },
        return_shape="domain: string — the exact domain key to pass verbatim to generate_sparql/compare_models",
    ),
    ToolSpec(
        name="generate_sparql",
        description=(
            "Translate a natural language question to SPARQL for the given domain. "
            "Stores the cleaned query as sparql_<n>."
        ),
        args_schema={
            "question": {"type": "string", "required": True,
                         "description": "Natural language question."},
            "domain":   {"type": "string", "required": True,
                         "description": "Domain name from detect_domain."},
        },
        return_shape="sparql_artifact_id: string; preview: first 500 chars of the SPARQL",
    ),
    ToolSpec(
        name="execute_sparql",
        description=(
            "Run a SPARQL query against the domain endpoint. "
            "Endpoint defaults to the last detected domain if not provided. "
            "Stores results as results_<n>."
        ),
        args_schema={
            "sparql_artifact_id": {"type": "string", "required": False,
                                   "description": "Artifact id of a prior generate_sparql call."},
            "sparql":             {"type": "string", "required": False,
                                   "description": "Raw SPARQL string (use when no artifact id)."},
            "endpoint":           {"type": "string", "required": False,
                                   "description": "SPARQL endpoint URL; defaults from last domain."},
        },
        return_shape=(
            "results_artifact_id: string; "
            "preview: first 5 result rows as list of dicts; "
            "total_rows: int"
        ),
    ),
    ToolSpec(
        name="explain_sparql",
        description="Return a plain-English explanation of a SPARQL query. No artifact stored.",
        args_schema={
            "sparql_artifact_id": {"type": "string", "required": False,
                                   "description": "Artifact id from generate_sparql."},
            "sparql":             {"type": "string", "required": False,
                                   "description": "Raw SPARQL string."},
        },
        return_shape="explanation: string — plain English description of the query",
    ),
    ToolSpec(
        name="summarize_results",
        description="Produce a natural language summary of SPARQL results. No artifact stored.",
        args_schema={
            "question":            {"type": "string", "required": True,
                                    "description": "The original user question."},
            "results_artifact_id": {"type": "string", "required": True,
                                    "description": "Artifact id from execute_sparql."},
        },
        return_shape="summary: string — readable answer synthesised from the result rows",
    ),
    ToolSpec(
        name="visualize_graph",
        description=(
            "Build an interactive PyVis graph from result rows. "
            "Stores the HTML string as graph_<n>."
        ),
        args_schema={
            "results_artifact_id": {"type": "string", "required": True,
                                    "description": "Artifact id from execute_sparql."},
            "sparql_artifact_id":  {"type": "string", "required": False,
                                    "description": "Optional artifact id for label detection."},
        },
        return_shape="graph_artifact_id: string; preview: {node_count: int, edge_count: int}",
    ),
    ToolSpec(
        name="list_domain_examples",
        description="Return example questions for a domain from the config. No artifact stored.",
        args_schema={
            "domain": {"type": "string",  "required": True,
                       "description": "Domain name (key in configs dict)."},
            "limit":  {"type": "integer", "required": False,
                       "description": "Max examples to return (default 5)."},
        },
        return_shape="examples: list[string] — example questions from the domain config",
    ),
    ToolSpec(
        name="compare_models",
        description=(
            "Run the same question through multiple LLM models and compare SPARQL outputs. "
            "Stores comparison as comparison_<n>."
        ),
        args_schema={
            "question": {"type": "string", "required": True,
                         "description": "Natural language question to compare."},
            "domain":   {"type": "string", "required": True,
                         "description": "Domain name from detect_domain."},
            "models":   {"type": "array",  "required": False,
                         "description": "List of model name strings; defaults to all available."},
        },
        return_shape=(
            "comparison_artifact_id: string; "
            "preview: list of {model, sparql_preview, answer_preview} per model"
        ),
    ),
]


# ---------------------------------------------------------------------------
# Stub function signatures (Saif implements on Day 2-3)
# ---------------------------------------------------------------------------

def build_system_prompt(
    tools: List[ToolSpec],
    memory_summary: str,
    domain_keys: Optional[List[str]] = None,
) -> str:
    """Build the full system prompt for one orchestrator turn.

    Includes: tool listing with args/return shapes, JSON schema examples,
    memory summary (last ~6 turns + artifact ids), and output format rules.
    Hard cap: 6000 chars; oldest memory turns dropped first.
    """
    import json

    lines: List[str] = [
        "You are an agentic assistant that answers questions about a knowledge graph.",
        "Each turn you MUST emit exactly one fenced JSON block — nothing else.",
        "",
    ]

    if domain_keys:
        lines += [
            "## Available domains",
            "These are the EXACT strings you must use for the `domain` argument:",
        ]
        for key in domain_keys:
            lines.append(f'- "{key}"')
        lines += [
            "IMPORTANT: Always pass the domain string verbatim — do not reformat, shorten, or translate it.",
            "",
        ]

    lines += [
        "## Available tools",
        "",
    ]

    for spec in tools:
        req_args  = [k for k, v in spec.args_schema.items() if v.get("required")]
        opt_args  = [k for k, v in spec.args_schema.items() if not v.get("required")]
        arg_parts = [f"{a} (required)" for a in req_args] + \
                    [f"{a} (optional)" for a in opt_args]
        lines += [
            f"### {spec.name}",
            spec.description,
            f"Args: {', '.join(arg_parts) if arg_parts else 'none'}",
            f"Returns: {spec.return_shape}",
            "",
        ]

    lines += [
        "## Output format",
        "",
        "Call a tool:",
        "```json",
        json.dumps(TOOL_CALL_SCHEMA, indent=2),
        "```",
        "",
        "Finish (no more tools needed):",
        "```json",
        json.dumps(FINAL_SCHEMA, indent=2),
        "```",
        "",
        "Rules:",
        '- Always include "thought" before "tool" or "final_answer".',
        "- Use artifact ids (e.g. sparql_1) to refer to earlier results.",
        "- Never output plain text outside the fenced block.",
        "- NEVER answer from your training knowledge. ALL factual answers MUST come from tool results only.",
        "- If execute_sparql returns empty results, reply that no information was found in the knowledge graph — do NOT infer or hallucinate an answer.",
        "",
        "## Examples",
        "",
        "**Example A — full pipeline**",
        "",
        'User: Who directed Inception?',
        "Assistant:",
        "```json",
        '{"thought": "I need to detect the domain first.", "tool": "detect_domain", "args": {"question": "Who directed Inception?"}}',
        "```",
        'Observation (tool=detect_domain): {"preview": "dbpedia_films", "artifact_id": null, "error": null}',
        "Assistant:",
        "```json",
        '{"thought": "Domain is dbpedia_films. Now generate SPARQL.", "tool": "generate_sparql", "args": {"question": "Who directed Inception?", "domain": "dbpedia_films"}}',
        "```",
        'Observation (tool=generate_sparql): {"preview": "SELECT ?director WHERE { dbr:Inception dbo:director ?director }", "artifact_id": "sparql_1", "error": null}',
        "Assistant:",
        "```json",
        '{"thought": "Execute the generated query.", "tool": "execute_sparql", "args": {"sparql_artifact_id": "sparql_1"}}',
        "```",
        'Observation (tool=execute_sparql): {"preview": [{"director": "http://dbpedia.org/resource/Christopher_Nolan"}], "artifact_id": "results_1", "error": null}',
        "Assistant:",
        "```json",
        '{"thought": "Summarize results for the user.", "tool": "summarize_results", "args": {"question": "Who directed Inception?", "results_artifact_id": "results_1"}}',
        "```",
        'Observation (tool=summarize_results): {"preview": "Inception was directed by Christopher Nolan.", "artifact_id": null, "error": null}',
        "Assistant:",
        "```json",
        '{"thought": "I have the answer.", "final_answer": "Inception was directed by Christopher Nolan.", "cite_artifacts": ["sparql_1", "results_1"]}',
        "```",
        "",
        "**Example B — empty results**",
        "",
        "User: Who invented the telephone?",
        "Assistant:",
        "```json",
        '{"thought": "Detect domain.", "tool": "detect_domain", "args": {"question": "Who invented the telephone?"}}',
        "```",
        'Observation (tool=detect_domain): {"preview": "dbpedia_films", "artifact_id": null, "error": null}',
        "Assistant:",
        "```json",
        '{"thought": "Generate and execute SPARQL.", "tool": "generate_sparql", "args": {"question": "Who invented the telephone?", "domain": "dbpedia_films"}}',
        "```",
        'Observation (tool=generate_sparql): {"preview": "SELECT ?p WHERE { dbr:Telephone dbo:inventor ?p }", "artifact_id": "sparql_1", "error": null}',
        "Assistant:",
        "```json",
        '{"thought": "Execute the query.", "tool": "execute_sparql", "args": {"sparql_artifact_id": "sparql_1"}}',
        "```",
        'Observation (tool=execute_sparql): {"preview": [], "artifact_id": "results_1", "error": null}',
        "Assistant:",
        "```json",
        '{"thought": "No results returned. I must not guess from my training data.", "final_answer": "The knowledge graph has no data on this topic. Try rephrasing or narrowing your question.", "cite_artifacts": ["sparql_1"]}',
        "```",
        "",
        "**Example C — finish when no tools needed**",
        "",
        "User: Thank you.",
        "Assistant:",
        "```json",
        '{"thought": "No tool needed.", "final_answer": "You\'re welcome! Ask me anything about the knowledge graph.", "cite_artifacts": []}',
        "```",
        "",
        "## Conversation so far",
        "",
        memory_summary or "(no prior turns)",
    ]

    prompt = "\n".join(lines)
    if len(prompt) > 6000:
        budget = 6000 - len(prompt) + len(memory_summary)
        memory_summary = memory_summary[-max(budget, 200):]
        lines[-1] = memory_summary
        prompt = "\n".join(lines)
    return prompt


def parse_llm_output(raw: str) -> ParsedTurn:
    """Extract and validate the JSON tool-call block from LLM output.

    Strategy:
    1. Find first ```json ... ``` fenced block.
    2. Fallback: balanced-brace scan for the first {...}.
    3. Validate shape: tool_call requires "tool" + "args"; final requires "final_answer".
    4. On failure return ParsedTurn(kind="parse_error", raw=raw).
    """
    import re
    import json as _json

    candidate = None

    # 1. Fenced block: ```json ... ``` or ``` ... ```
    m = re.search(r'```(?:json)?\s*(\{.*\})\s*```', raw, re.DOTALL)
    if m:
        candidate = m.group(1)
    else:
        # 2. Balanced-brace scan
        start = raw.find('{')
        if start != -1:
            depth, end = 0, start
            for i, ch in enumerate(raw[start:], start):
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            candidate = raw[start:end + 1]

    if candidate is None:
        return ParsedTurn(kind="parse_error", raw=raw)

    try:
        data = _json.loads(candidate)
    except _json.JSONDecodeError:
        return ParsedTurn(kind="parse_error", raw=raw)

    thought = data.get("thought")

    if "tool" in data and isinstance(data.get("args"), dict):
        return ParsedTurn(
            kind="tool_call",
            raw=raw,
            thought=thought,
            tool=data["tool"],
            args=data["args"],
        )

    if "final_answer" in data:
        return ParsedTurn(
            kind="final",
            raw=raw,
            thought=thought,
            final_answer=data["final_answer"],
            cite_artifacts=data.get("cite_artifacts") or [],
        )

    return ParsedTurn(kind="parse_error", raw=raw)


def serialize_observation(result: ToolResult) -> str:
    """Serialise a ToolResult into an observation string appended to the prompt.

    Format: "Observation (tool=<name>): <json of preview + artifact_id + error>"
    Full payload is never included — only the preview.
    """
    import json as _json

    body: dict = {"preview": result.preview}
    if result.artifact_id is not None:
        body["artifact_id"] = result.artifact_id
    if result.error is not None:
        body["error"] = result.error
    return f"Observation (tool={result.tool_name}): {_json.dumps(body)}"
