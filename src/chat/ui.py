"""
ui.py — Streamlit chat rendering layer.

All Streamlit calls must live inside the main script body, never in callbacks.
"""
from __future__ import annotations

import html

import streamlit as st
import streamlit.components.v1 as components

from src import sparql_to_nl, sparql_executor
from .memory import ChatMemory
from .tool_protocol import ChatMessage
from . import viz as _viz

# ── Progress bar helpers ───────────────────────────────────────

_BAR_RUNNING_HTML = """\
<style>
@keyframes _chat_kf_slide {{
    0%   {{ left: -35%; }}
    100% {{ left: 110%; }}
}}
</style>
<div style="margin:6px 0 2px;">
<div style="position:relative;width:100%;height:3px;background:var(--border);border-radius:2px;overflow:hidden;">
  <div style="position:absolute;height:100%;width:35%;background:var(--accent);border-radius:2px;
              animation:_chat_kf_slide 1.4s ease-in-out infinite;"></div>
</div>
</div>
<div style="font-size:0.78rem;color:var(--text-muted);margin-top:4px;">{msg}</div>
"""

_BAR_DONE_HTML = """\
<div style="margin:6px 0 2px;">
<div style="width:100%;height:3px;background:var(--border);border-radius:2px;overflow:hidden;">
  <div style="width:100%;height:100%;background:var(--accent);border-radius:2px;"></div>
</div>
</div>
"""

# Labels for each error_kind in the trace
_TRACE_KIND_LABEL: dict[str, str] = {
    "parse_error": "JSON parse error",
    "tool_error": "tool error",
    "network_error": "network error",
    "duplicate_call": "duplicate call",
}


# ── Private helpers ────────────────────────────────────────────

_WD_ENTITY_RE = __import__("re").compile(r'^https?://www\.wikidata\.org/entity/(Q\d+)$')
_QID_BARE_RE  = __import__("re").compile(r'^(Q\d+)$')


def _cell_html(value: str) -> str:
    """Return an HTML snippet for a single result cell with Wikidata links."""
    v = str(value or "").strip()
    m = _WD_ENTITY_RE.match(v)
    if m:
        qid = m.group(1)
        url = f"https://www.wikidata.org/wiki/{qid}"
        return f'<a href="{url}" target="_blank" rel="noopener">{html.escape(qid)}</a>'
    m = _QID_BARE_RE.match(v)
    if m:
        qid = m.group(1)
        url = f"https://www.wikidata.org/wiki/{qid}"
        return f'<a href="{url}" target="_blank" rel="noopener">{html.escape(qid)}</a>'
    return html.escape(v)


def _render_results_table(rows: list) -> None:
    """Render a list-of-dicts result set as a styled HTML table.

    Extracted from app.py:804. Shared by Tab 1 and the Chat tab.
    """
    if not rows:
        return
    columns = list(rows[0].keys())
    header = "".join(f"<th>{html.escape(c)}</th>" for c in columns)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_cell_html(row.get(c, ''))}</td>" for c in columns)
        body_rows.append(f"<tr>{cells}</tr>")
    body = "\n".join(body_rows)
    table_html = f"""
<div style="overflow-x:auto;">
<table class="wd-result-table">
  <thead><tr>{header}</tr></thead>
  <tbody>{body}</tbody>
</table>
</div>
<style>
.wd-result-table {{
    width: 100%;
    border-collapse: collapse;
    font-family: var(--font-sans);
    font-size: 0.82rem;
    color: var(--text);
}}
.wd-result-table th {{
    background: var(--header-bg);
    color: var(--text-muted);
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    padding: 7px 12px;
    border-bottom: 1.5px solid var(--border-strong);
    text-align: left;
    white-space: nowrap;
}}
.wd-result-table td {{
    padding: 6px 12px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
    word-break: break-word;
}}
.wd-result-table tr:last-child td {{
    border-bottom: none;
}}
.wd-result-table tr:hover td {{
    background: var(--accent-light);
}}
.wd-result-table a {{
    color: var(--accent);
    text-decoration: none;
    font-family: var(--font-mono);
    font-size: 0.78rem;
    background: var(--info-bg);
    border: 1px solid var(--info-border);
    border-radius: 3px;
    padding: 1px 5px;
}}
.wd-result-table a:hover {{
    text-decoration: underline;
    background: var(--accent-light);
}}
</style>
"""
    st.markdown(table_html, unsafe_allow_html=True)


# ── Public API ─────────────────────────────────────────────────

def render_message(msg: ChatMessage, memory: ChatMemory) -> None:
    """Render the artifact payloads for one ChatMessage.

    Call this inside an open st.chat_message(...) context.
    Dispatches by the prefix of each artifact id in msg.artifact_ids.
    """
    for aid in msg.artifact_ids:
        kind = aid.split("_")[0]
        payload = memory.artifacts.get(aid)
        if payload is None:
            continue

        if kind == "entities":
            with st.expander(f"Entity lookup · {len(payload)} resolved", expanded=False):
                for _h in payload:
                    st.markdown(f'**"{_h["surface"]}"** → `wd:{_h["qid"]}` — {_h["description"]}')

        elif kind == "sparql":
            with st.expander("Generated SPARQL", expanded=False):
                st.code(payload, language="sparql")

        elif kind == "results":
            with st.expander(f"Raw results · {len(payload)} rows", expanded=False):
                _render_results_table(payload)

        elif kind == "graph":
            components.html(payload, height=480, scrolling=False)

        elif kind == "comparison":
            # payload is list[{model, sparql, status}]
            if isinstance(payload, list) and payload:
                cols = st.columns(len(payload))
                for col, entry in zip(cols, payload):
                    with col:
                        st.caption(entry.get("model", "?"))
                        st.code(entry.get("sparql", ""), language="sparql")
                        st.caption(entry.get("status", ""))

    if msg.trace:
        with st.expander("View tool trace", expanded=False):
            for i, step in enumerate(msg.trace):
                tool = step.get("tool", "")
                args = step.get("args", {})
                obs = step.get("observation", "")
                error_kind = step.get("error_kind")

                label = f"**Step {i + 1}** — `{tool}`"
                if error_kind:
                    label += f" [{_TRACE_KIND_LABEL.get(error_kind, error_kind)}]"

                st.markdown(label)
                if args:
                    with st.expander("args", expanded=False):
                        st.json(args)
                obs_short = obs[:400] + ("..." if len(obs) > 400 else "")
                st.caption(obs_short)
                st.divider()


def render_chat_tab(memory: ChatMemory, configs: dict, model: str, wikidata_only: bool = False) -> None:
    """Render the full Chat tab.

    1. Re-render conversation history from memory.
    2. Accept new input via st.chat_input.
    3. Dispatch: slash command or agentic orchestrator.
    4. Persist reply and rerun.
    """
    col_spacer, col_btn = st.columns([8, 1])
    with col_btn:
        if st.button("Clear Chat", key="clear_chat_btn", use_container_width=True):
            memory.messages.clear()
            memory.artifacts.clear()
            memory._domain_stack.clear()
            st.rerun()

    # Render full history
    for msg in memory.messages:
        with st.chat_message(msg.role):
            st.markdown(msg.text)
            render_message(msg, memory)

    prompt = st.chat_input("Ask a question or type /explain, /graph, /compare ...")
    if not prompt:
        return

    # Show user message immediately; persist it
    with st.chat_message("user"):
        st.markdown(prompt)
    memory.messages.append(ChatMessage(role="user", text=prompt))

    # Handle response inside assistant bubble
    with st.chat_message("assistant"):
        _progress_bar = st.empty()

        with st.spinner("Thinking..."):
            handled = maybe_handle_slash(prompt, memory, configs, model)

        if not handled:
            from .orchestrator import run_turn
            from .tools import build_registry, ToolContext
            from src.wikidata_generic import WIKIDATA_GENERIC_CONFIG

            def _on_step(msg: str) -> None:
                _progress_bar.markdown(
                    _BAR_RUNNING_HTML.format(msg=html.escape(msg)),
                    unsafe_allow_html=True,
                )

            reply = run_turn(
                prompt,
                memory,
                build_registry(ToolContext(memory, configs, model)),
                configs,
                model,
                progress_callback=_on_step,
                override_config=WIKIDATA_GENERIC_CONFIG if wikidata_only else None,
            )
            _progress_bar.markdown(_BAR_DONE_HTML, unsafe_allow_html=True)
            memory.messages.append(reply)
            st.markdown(reply.text)
            render_message(reply, memory)

    st.rerun()


def maybe_handle_slash(
    text: str,
    memory: ChatMemory,
    configs: dict,
    model: str,
) -> bool:
    """Intercept slash commands before the orchestrator loop.

    Renders the reply in whatever st.chat_message context is active.
    Always appends a ChatMessage to memory so the history loop shows it on rerun.

    Returns True if a slash command was handled; False if text does not start with '/'.
    """
    text = text.strip()
    if not text.startswith("/"):
        return False

    cmd, _, rest = text[1:].partition(" ")
    cmd = cmd.lower()

    if cmd == "explain":
        sparql = rest.strip() or memory.last_sparql()
        if not sparql:
            st.warning("No SPARQL query available. Run a query first or provide one after /explain.")
            reply = ChatMessage(role="assistant", text="No SPARQL query available.")
            memory.messages.append(reply)
            return True
        domain = memory.last_domain() or next(iter(configs))
        cfg = configs[domain]
        explanation = sparql_to_nl.translate(sparql, cfg, model)
        st.markdown(explanation)
        reply = ChatMessage(role="assistant", text=explanation)
        memory.messages.append(reply)
        return True

    if cmd == "graph":
        provided_sparql = rest.strip()
        rows = None

        if provided_sparql:
            domain = memory.last_domain() or next(iter(configs))
            cfg = configs[domain]
            result = sparql_executor.execute(provided_sparql, cfg["endpoint"])
            if not result["success"]:
                st.error(f"Query failed: {result['error']}")
                reply = ChatMessage(role="assistant", text=f"Query failed: {result['error']}")
                memory.messages.append(reply)
                return True
            rows = result["results"]
        else:
            rows = memory.last_results()

        if not rows:
            st.warning("No results to visualize. Run a query first or provide a SPARQL query after /graph.")
            reply = ChatMessage(role="assistant", text="No results to visualize.")
            memory.messages.append(reply)
            return True

        try:
            dark = st.session_state.get("dark_mode", False)
            graph_html = _viz.build_pyvis_html(rows, provided_sparql or "", dark=dark)
            aid = memory.store_artifact("graph", graph_html)
            components.html(graph_html, height=480, scrolling=False)
            reply = ChatMessage(role="assistant", text="Knowledge graph rendered.", artifact_ids=[aid])
            memory.messages.append(reply)
        except ImportError:
            st.error("pyvis is not installed. Run: `pip install pyvis`")
            reply = ChatMessage(role="assistant", text="pyvis is not installed.")
            memory.messages.append(reply)
        except Exception as e:
            st.error(f"Graph rendering failed: {e}")
            reply = ChatMessage(role="assistant", text=f"Graph rendering failed: {e}")
            memory.messages.append(reply)
        return True

    if cmd == "compare":
        question = rest.strip()
        if not question:
            st.warning("Usage: /compare <question>")
            reply = ChatMessage(role="assistant", text="Usage: /compare <question>")
            memory.messages.append(reply)
            return True
        from .tools import build_registry, ToolContext
        ctx = ToolContext(memory, configs, model)
        reg = build_registry(ctx)
        domain = memory.last_domain() or next(iter(configs))
        try:
            result = reg["compare_models"]({"question": question, "domain": domain})
            if result.error:
                st.error(result.error)
                reply = ChatMessage(role="assistant", text=result.error)
            else:
                aid = result.artifact_id
                artifact_ids = [aid] if aid else []
                reply = ChatMessage(role="assistant", text="Model comparison complete.", artifact_ids=artifact_ids)
                st.markdown(reply.text)
                render_message(reply, memory)
        except NotImplementedError:
            msg = "Model comparison tool is not yet implemented."
            st.warning(msg)
            reply = ChatMessage(role="assistant", text=msg)
        memory.messages.append(reply)
        return True

    # Unknown slash command
    st.warning(f"Unknown command: /{cmd}. Supported: /explain, /graph, /compare")
    reply = ChatMessage(role="assistant", text=f"Unknown command: /{cmd}. Supported: /explain, /graph, /compare")
    memory.messages.append(reply)
    return True
