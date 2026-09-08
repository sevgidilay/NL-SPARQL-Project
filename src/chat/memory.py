"""
memory.py — ChatMemory: conversation log + artifact store.

Jumainah implements the method bodies on Day 2-3.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from .tool_protocol import ChatMessage


def _latest(artifacts: dict, kind: str) -> Optional[Any]:
    keys = [k for k in artifacts if k.startswith(kind + "_")]
    if not keys:
        return None
    keys.sort(key=lambda k: int(k.split("_", 1)[1]))
    return artifacts[keys[-1]]


@dataclass
class ChatMemory:
    """Persisted in st.session_state.chat_memory across Streamlit reruns."""

    messages: List[ChatMessage] = field(default_factory=list)
    # keyed by artifact_id e.g. "sparql_1", "results_1", "graph_2"
    artifacts: dict = field(default_factory=dict)
    # domain names pushed by detect_domain / generate_sparql calls
    _domain_stack: List[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Prompt context
    # ------------------------------------------------------------------

    def summary_for_prompt(self) -> str:
        """Return a condensed string of the last ~6 turns for the system prompt.

        Format per turn:
            User: <text>
            Assistant: <text> [artifacts: sparql_1, results_1]

        Hard cap at 6000 chars; oldest turns are dropped first.
        """
        CHAR_CAP = 6000
        window = self.messages[-12:]   # last 6 turns

        def _fmt(msgs):
            lines = []
            for msg in msgs:
                if msg.role == "user":
                    lines.append(f"User: {msg.text}")
                else:
                    if msg.artifact_ids:
                        ids = ", ".join(msg.artifact_ids)
                        lines.append(f"Assistant: {msg.text} [artifacts: {ids}]")
                    else:
                        lines.append(f"Assistant: {msg.text}")
            return "\n".join(lines)

        result = _fmt(window)
        while len(result) > CHAR_CAP and len(window) > 1:
            window = window[1:]
            result = _fmt(window)
        return result

    # ------------------------------------------------------------------
    # Artifact store
    # ------------------------------------------------------------------

    def store_artifact(self, kind: str, payload: Any) -> str:
        """Persist payload under a new artifact_id and return that id.

        kind must be one of: "sparql", "results", "graph", "comparison".
        id format: "<kind>_<n>" where n is the 1-based count for that kind.
        """
        if kind not in ("sparql", "results", "graph", "comparison", "entities"):
            raise ValueError(f"Unknown artifact kind: {kind!r}")
        n = sum(1 for k in self.artifacts if k.startswith(kind + "_")) + 1
        artifact_id = f"{kind}_{n}"
        self.artifacts[artifact_id] = payload
        return artifact_id

    # ------------------------------------------------------------------
    # Convenience accessors (used by execute_sparql default-endpoint logic)
    # ------------------------------------------------------------------

    def last_domain(self) -> Optional[str]:
        """Return the most recently detected/used domain name, or None."""
        return self._domain_stack[-1] if self._domain_stack else None

    def last_sparql(self) -> Optional[str]:
        """Return the most recently stored SPARQL string (payload), or None."""
        return _latest(self.artifacts, "sparql")

    def last_results(self) -> Optional[list]:
        """Return the most recently stored results list (payload), or None."""
        return _latest(self.artifacts, "results")

    def last_entities(self) -> Optional[list]:
        """Return the most recently stored entity hints list, or None."""
        return _latest(self.artifacts, "entities")
