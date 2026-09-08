"""Contract tests for src/chat/memory.py — ChatMemory."""
import pytest

from src.chat.memory import ChatMemory
from src.chat.tool_protocol import ChatMessage


# ---------------------------------------------------------------------------
# store_artifact
# ---------------------------------------------------------------------------

def test_store_artifact_sequential_ids():
    mem = ChatMemory()
    id1 = mem.store_artifact("sparql", "SELECT ?x WHERE { }")
    id2 = mem.store_artifact("sparql", "SELECT ?y WHERE { }")
    assert id1 == "sparql_1"
    assert id2 == "sparql_2"


def test_store_artifact_independent_counters():
    mem = ChatMemory()
    sid = mem.store_artifact("sparql", "SELECT ?x WHERE { }")
    rid = mem.store_artifact("results", [{"x": "foo"}])
    assert sid == "sparql_1"
    assert rid == "results_1"


def test_store_artifact_unknown_kind_raises_value_error():
    mem = ChatMemory()
    with pytest.raises(ValueError, match="Unknown artifact kind"):
        mem.store_artifact("bogus", "payload")


def test_store_artifact_payload_retrievable():
    mem = ChatMemory()
    payload = [{"film": "Inception"}, {"film": "Dune"}]
    artifact_id = mem.store_artifact("results", payload)
    assert mem.artifacts[artifact_id] == payload


# ---------------------------------------------------------------------------
# last_domain / last_sparql / last_results
# ---------------------------------------------------------------------------

def test_last_domain_empty():
    mem = ChatMemory()
    assert mem.last_domain() is None


def test_last_domain_returns_newest():
    mem = ChatMemory()
    mem._domain_stack.append("wikidata_film")
    mem._domain_stack.append("wikidata_music")
    assert mem.last_domain() == "wikidata_music"


def test_last_sparql_empty():
    mem = ChatMemory()
    assert mem.last_sparql() is None


def test_last_sparql_returns_newest():
    mem = ChatMemory()
    mem.store_artifact("sparql", "SELECT ?x WHERE { }")
    mem.store_artifact("sparql", "SELECT ?y WHERE { }")
    assert mem.last_sparql() == "SELECT ?y WHERE { }"


def test_last_results_returns_newest():
    mem = ChatMemory()
    mem.store_artifact("results", [{"a": 1}])
    mem.store_artifact("results", [{"b": 2}])
    assert mem.last_results() == [{"b": 2}]


# ---------------------------------------------------------------------------
# summary_for_prompt
# ---------------------------------------------------------------------------

def test_summary_empty_history():
    mem = ChatMemory()
    assert mem.summary_for_prompt() == ""


def test_summary_user_message_only():
    mem = ChatMemory()
    mem.messages.append(ChatMessage(role="user", text="Who directed Inception?"))
    result = mem.summary_for_prompt()
    assert result.startswith("User: ")
    assert "Who directed Inception?" in result


def test_summary_user_and_assistant():
    mem = ChatMemory()
    mem.messages.append(ChatMessage(role="user", text="Who directed Inception?"))
    mem.messages.append(ChatMessage(role="assistant", text="Christopher Nolan."))
    result = mem.summary_for_prompt()
    assert "User: Who directed Inception?" in result
    assert "Assistant: Christopher Nolan." in result
    assert result.index("User:") < result.index("Assistant:")


def test_summary_assistant_with_artifacts():
    mem = ChatMemory()
    mem.messages.append(ChatMessage(
        role="assistant",
        text="Done.",
        artifact_ids=["sparql_1", "results_1"],
    ))
    result = mem.summary_for_prompt()
    assert "[artifacts: sparql_1, results_1]" in result


def test_summary_assistant_no_artifacts():
    mem = ChatMemory()
    mem.messages.append(ChatMessage(role="assistant", text="Done."))
    result = mem.summary_for_prompt()
    assert "[artifacts:" not in result


def test_summary_max_six_turns():
    """7 turns stored; only last 6 (Q1-Q6) should appear — Q0 absent."""
    mem = ChatMemory()
    for i in range(7):
        mem.messages.append(ChatMessage(role="user", text=f"Q{i}"))
        mem.messages.append(ChatMessage(role="assistant", text=f"A{i}"))
    result = mem.summary_for_prompt()
    assert "Q0" not in result
    assert "Q6" in result


def test_summary_char_cap_drops_oldest():
    """20 turns with long text; result must stay under 6000 chars."""
    mem = ChatMemory()
    for i in range(20):
        mem.messages.append(ChatMessage(role="user", text=f"Q{i}: " + "x" * 400))
        mem.messages.append(ChatMessage(role="assistant", text=f"A{i}: " + "y" * 400))
    result = mem.summary_for_prompt()
    assert len(result) <= 6000
    assert "Q19" in result
    assert "Q0:" not in result


def test_summary_exactly_six_turns_fits():
    """12 short messages (6 turns) all fit under the cap."""
    mem = ChatMemory()
    for i in range(6):
        mem.messages.append(ChatMessage(role="user", text=f"Q{i}"))
        mem.messages.append(ChatMessage(role="assistant", text=f"A{i}"))
    result = mem.summary_for_prompt()
    assert len(result) <= 6000
    for i in range(6):
        assert f"Q{i}" in result
        assert f"A{i}" in result
