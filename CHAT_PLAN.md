# Unified Agentic Chat Module

## Context

`app.py` currently exposes four segmented tabs (NL→SPARQL, SPARQL→NL, Knowledge Graph, Model Arena). Tab 1 already runs an end-to-end pipeline (detect_domain → generate → execute → summarize), but the experience is form-driven and feature-fragmented. The team wants one conversational surface where the LLM acts agentically — choosing tools per turn, carrying multi-turn memory, and rendering SPARQL/results/graphs inline.

The course is about prompt engineering, so the chat must showcase explicit, inspectable tool-calling — not a hidden pipeline. The work is split across three people (Saif, Jumainah, Kamar) by layer so they can develop in parallel against frozen interfaces.

---

## User decisions (confirmed)

- Chat is added as a new **first** tab. The four existing tabs remain as fallback for the demo.
- LLM is **agentic with explicit tool-calling**. Plain `chat()` API stays — tool calls are emitted as JSON inside a fenced block and parsed by the orchestrator.
- v1 capabilities: multi-turn memory + follow-ups, inline SPARQL block + on-demand PyVis graph, slash commands (`/explain`, `/graph`, `/compare`). Streaming is **out** of scope.
- Split by layer (orchestrator / tools / UI), not by feature.

---

## Architecture

```
app.py  (new "Chat" tab)
   └─> src/chat/ui.render_chat_tab(memory, configs, model)
          ├─> ui.maybe_handle_slash(...)        # /explain /graph /compare bypass
          └─> orchestrator.run_turn(user_msg, memory, registry, configs, model)
                 └─ loops up to MAX_ITERATIONS:
                     llm_client.chat(prompt)
                     tool_protocol.parse_llm_output(raw)
                     tools.dispatch(name, args, ctx)   # → ToolResult
                     append observation to prompt
```

New package: `src/chat/` (one subpackage; the existing `src/` stays flat).

```
src/chat/
  __init__.py            re-exports run_turn, build_registry, ChatMemory
  tool_protocol.py       Saif:    prompt build + parse + dataclasses
  orchestrator.py        Saif:    agentic loop
  tools.py               Jumainah: registry wrapping existing src/* modules
  memory.py              Jumainah: ChatMemory + artifact store
  ui.py                  Kamar:   Streamlit chat rendering
  viz.py                 Kamar:   extracted PyVis builder
```

---

## Tool-calling protocol

`src/llm_client.py` does plain chat completion (no native tool-calls). The model emits **one tool call per turn** in a fenced JSON block. Two valid shapes:

```
{ "thought": "...", "tool": "<name>", "args": {...} }              # call a tool
{ "thought": "...", "final_answer": "...", "cite_artifacts": [...] } # finish
```

System prompt (built once per turn) lists every tool with its args schema and return shape, plus a condensed memory summary (last 6 turns + artifact ids). `parse_llm_output` extracts the first fenced block, falls back to balanced-brace scan, validates shape.

Orchestrator loop (`MAX_ITERATIONS = 6`):

1. Build prompt → call LLM → parse.
2. On `tool_call`: dispatch via registry, serialize result as `Observation (tool=<name>): <json>`, append to prompt, repeat.
3. On `final`: return immediately.
4. On `parse_error`: inject corrective observation, cap retries at 2.
5. Detect identical consecutive tool calls (same name + args) and force the model to change strategy.
6. If iterations exhausted: synthesize a fallback final from collected artifacts.

---

## Tool registry

Each tool is a thin wrapper. **No business logic is duplicated** — they all delegate to existing `src/*` functions.

| Tool                   | Wraps                                                     | Key args                                      | Artifact stored  |
| ---------------------- | --------------------------------------------------------- | --------------------------------------------- | ---------------- |
| `detect_domain`        | `domain_router.detect_domain`                             | `question`                                    | —                |
| `generate_sparql`      | `nl_to_sparql.translate` + `sparql_executor.clean_sparql` | `question`, `domain`                          | `sparql_<n>`     |
| `execute_sparql`       | `sparql_executor.execute`                                 | `sparql_artifact_id` or `sparql`, `endpoint?` | `results_<n>`    |
| `explain_sparql`       | `sparql_to_nl.translate`                                  | `sparql_artifact_id` or `sparql`              | —                |
| `summarize_results`    | `answer_summarizer.summarize`                             | `question`, `results_artifact_id`             | —                |
| `visualize_graph`      | `viz.build_pyvis_html`                                    | `results_artifact_id`, `sparql_artifact_id`   | `graph_<n>`      |
| `list_domain_examples` | reads `configs[domain]["example_questions"]`              | `domain`, `limit?`                            | —                |
| `compare_models`       | extracted Tab 4 logic                                     | `question`, `domain`, `models?`               | `comparison_<n>` |

Two contracts to lock in on day 1:

- **`generate_sparql` MUST call `clean_sparql`** before storing the artifact, so the cleaned (DISTINCT-injected, cache-busted) string is what `/explain` and downstream `execute_sparql` see.
- **`execute_sparql` defaults endpoint from `memory.last_domain()`** rather than re-implementing endpoint detection — avoid divergence from `detect_endpoint` in `app.py:738`.

Tools that consume large data (results, sparql) take **artifact ids**, not raw payloads. Tools that produce data return only a 5-row preview to the LLM and stash the full payload in `ChatMemory.artifacts`. This keeps prompts small and lets follow-ups reference earlier results without re-querying.

---

## Memory model

`ChatMemory` lives in `st.session_state.chat_memory`. It holds:

- `messages: list[ChatMessage]` — full chronological log; source of truth for re-rendering on every Streamlit rerun. Each message has `text`, `artifact_ids`, optional `trace`.
- `artifacts: dict[str, dict]` — opaque store keyed by `<kind>_<n>` (`sparql_3`, `results_3`, `graph_3`). Stores full SPARQL strings, full result lists, generated PyVis HTML strings.
- `summary_for_prompt()` — what the LLM sees as prior context. Renders the last ~6 turns as `User: ... / Assistant: <text> [artifacts: sparql_3, results_3]`. Hard cap at 6000 chars; oldest turns dropped first.

**Follow-up flow** (e.g. "show me only the European ones"): the model sees `results_3` in the summary, calls `generate_sparql` again with a refined question, then `execute_sparql`. We do not filter cached results in Python — the LLM regenerates the SPARQL with an added FILTER, consistent with the existing pipeline.

PyVis HTML is stored as a plain string (output of `net.generate_html()`), not a `Network` object — Streamlit can serialize it across reruns without issue.

---

## Slash commands

Parsed in the **UI layer** (`ui.maybe_handle_slash`) before the orchestrator runs. They bypass the agentic loop entirely so they're predictable and fast.

- `/explain` → calls `sparql_to_nl.translate(memory.last_sparql(), ...)`.
- `/explain <SPARQL>` → same with provided query.
- `/graph` → calls `viz.build_pyvis_html(memory.last_results(), memory.last_sparql())`.
- `/graph <SPARQL>` → executes first, then graphs.
- `/compare <question>` → runs the model-arena pipeline directly.

Messages without a leading `/` fall through to `orchestrator.run_turn`.

---

## Streamlit chat UI

```python
chat_tab, tab1, tab3, tab2, tab4 = st.tabs(["Chat", "NL → SPARQL", "SPARQL → NL", "Knowledge Graph", "Model Arena"])
with chat_tab:
    render_chat_tab(memory, configs, model)
```

`render_chat_tab`:

1. Initialize `st.session_state.chat_memory` on first run.
2. Loop `memory.messages`; for each, open `st.chat_message(role)` and call `render_message(msg, memory)`.
3. Render `st.chat_input("Ask a question or type /explain, /graph, /compare ...")`.
4. On submit: try `maybe_handle_slash` first; otherwise call `orchestrator.run_turn`. `st.rerun()`.

`render_message` dispatches by artifact `kind`:

- `sparql` → `st.expander("Generated SPARQL")` + `st.code(..., language="sparql")`.
- `results` → `st.expander(f"Raw results · {n} rows")` wrapping the existing `_render_results_table` helper from `app.py:785` (extracted to `src/chat/ui.py`).
- `graph_html` → `components.html(payload, height=480, scrolling=False)` — narrower than Tab 2's 570 because the chat bubble is narrower.
- `comparison` → side-by-side columns mirroring Tab 4.
- `trace` → collapsed expander "View tool trace" listing each step.

Non-text artifacts must only be rendered inside the main script body, never inside Streamlit callbacks (Streamlit raises in callback context).

---

## Files to modify and reuse

**New:**

- `src/chat/tool_protocol.py`, `orchestrator.py`, `tools.py`, `memory.py`, `ui.py`, `viz.py`, `__init__.py`
- `tests/test_tool_protocol.py`, `test_orchestrator.py`, `test_chat_tools.py`, `test_chat_memory.py`, `test_viz.py`, `test_chat_e2e.py`

**Modified:**

- `app.py` — add Chat tab as first tab; refactor Tab 2's PyVis block to call `viz.build_pyvis_html` (delete duplicated logic).

**Reused (do not modify, just wrap):**

- `src/domain_router.py:detect_domain`
- `src/nl_to_sparql.py:translate`
- `src/sparql_executor.py:execute`, `clean_sparql`
- `src/sparql_to_nl.py:translate`
- `src/answer_summarizer.py:summarize`
- `src/llm_client.py:chat`
- `_render_results_table` from `app.py:785` — extracted to `src/chat/ui.py`, called from both Tab 1 and Chat.
- PyVis block from `app.py:1437–1525` — extracted into `viz.build_pyvis_html`; Tab 2 rewritten to call it.

---

## Parallel work split

### Day 1 — alignment (all three together, ~2h) ✅ COMPLETED (2026-05-06)

Lock these as committed stub files before anyone implements:

1. `ToolSpec`, `ToolResult`, `ChatMessage`, `ParsedTurn` dataclasses (exact field names + types).
2. The tool-call JSON schema (the two shapes above, verbatim).
3. The artifact-id naming convention (`<kind>_<n>`).
4. The full registry table (names, args, return shapes) — this goes into the system prompt verbatim.
5. The two contracts: `generate_sparql` must call `clean_sparql`; `execute_sparql` defaults endpoint from memory.

### Day 2–3 — parallel implementation

**Saif — orchestrator + protocol** ✅ COMPLETED (2026-05-06)

- `tool_protocol.py`: `build_system_prompt`, `parse_llm_output`, `serialize_observation`. ✓
- `orchestrator.py`: `run_turn` loop with mocked registry, max-iterations, parse-error retry, identical-call detection, fallback final synthesis. ✓
- Tests: 3 fixtures for parser (valid call / valid final / malformed). 5 cases for loop (single tool, three tools, parse error, max iterations, tool error). ✓

**Jumainah — tools + memory** ✅ COMPLETED (2026-05-06)

- `memory.py`: `ChatMemory` with artifact store, `summary_for_prompt` (char-budgeted), `last_results/last_sparql/last_domain` accessors. ✓
- `tools.py`: all 8 tools wired to existing `src/*` modules; `_DEFAULT_MODELS` constant aligned with Tab 4. ✓
- `tests/test_chat_memory.py`: 17 tests covering store_artifact, accessors, summary_for_prompt (char cap, turn window). ✓
- `tests/test_chat_tools.py`: extended with 27 new tests for all 6 newly implemented tools. ✓
- Coordinated with Saif: `serialize_observation` shape confirmed; `preview` is always JSON-serializable. ✓

**Saif — UI + viz** ✅ COMPLETED (2026-05-06)

- `viz.py`: extract `build_pyvis_html` and `detect_label_uri_columns`. Pure functions; Streamlit-free. ✓
- `ui.py`: `render_message` dispatch, `render_chat_tab` shell, `maybe_handle_slash`. ✓
- Wires the new `chat_tab` into `app.py` and refactors Tab 2 to call `build_pyvis_html`. ✓

Each layer's only external dependency is the day-1 dataclasses, so all three can develop simultaneously without blocking.

### Day 4 — integration ✅ COMPLETED (2026-05-06)

- Kamar + Jumainah: end-to-end run on real Hactar (`llama3.3:latest`). Tune system prompt for JSON reliability (likely 2–3 iterations + add 2–3 in-prompt few-shot examples). ✓
- Kamar: implement slash commands; finish Tab 2 refactor. ✓

### Day 5 — polish + demo ✅ COMPLETED (2026-05-06)

- Step-by-step progress indicator during agentic loop (adapt `_bar_running` from `app.py:1235`). ✓
- Tune error messages (parse_error vs tool_error vs network_error). ✓
- Pre-record 6–8 representative chat scenarios for the demo. ✓ (see `DEMO_SCENARIOS.md`)

---

## Verification

1. **Unit tests** — `pytest tests/test_tool_protocol.py tests/test_orchestrator.py tests/test_chat_tools.py tests/test_chat_memory.py tests/test_viz.py` — all green with mocked LLM/HTTP.
2. **End-to-end smoke** — `pytest tests/test_chat_e2e.py` (skipped without `HACTAR_API_KEY`): one real turn for "Who directed Inception?" asserts the trace contains `generate_sparql` and `execute_sparql`, and the final answer mentions Christopher Nolan.
3. **Manual UI** — `streamlit run app.py`, then in the Chat tab:
   - Single-turn factual: "List 10 thriller series" — expect SPARQL block + results table + summary.
   - Follow-up: "now show only the British ones" — expect new SPARQL referencing prior context.
   - Slash: `/explain` after a query — expect English explanation of last SPARQL with no agentic loop.
   - Slash: `/graph` after results — expect inline PyVis network in the chat bubble.
   - Slash: `/compare List 5 dystopian novels` — expect side-by-side model outputs.
   - Tab 1, Tab 2, Tab 3, Tab 4 still function unchanged (regression check).
4. **Loop safety** — feed a deliberately ambiguous question and confirm `MAX_ITERATIONS` halts cleanly with a fallback final answer rather than spinning.

---

## Risks and mitigations

- **Unreliable JSON from the LLM.** Strict system prompt + 2–3 in-prompt few-shot examples + parse-retry cap of 2 + fallback final answer. Test specifically with `llama3.3:latest` and `qwen3:8b` since they're the worst-case in the fallback chain.
- **Loops on identical tool calls.** Detect same name + same args back-to-back; force a strategy change.
- **Hactar latency in agentic loops.** A 4-step plan = up to 6 LLM calls, ~20–30s. Show step-by-step progress in the UI; allow `MAX_ITERATIONS` to be tuned in the sidebar.
- **PyVis embedding in narrow chat bubble.** `Network(width="100%")` (already set) + `height_px=480` for chat (vs 570 in Tab 2).
- **Pipeline drift between Tab 1 and Chat.** Mitigated by extracting Tab 2's PyVis builder and the Tab 1 `_render_results_table` into shared helpers; Tab 1's pipeline is wrapped 1:1 by the tools, not duplicated.
- **`clean_sparql` skipped.** Locked as a day-1 contract; covered by `test_chat_tools.py::test_generate_sparql_calls_clean`.
