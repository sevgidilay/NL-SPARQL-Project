"""
Tests for src/chat/orchestrator.py — fixed deterministic pipeline.

All tests mock domain_router.detect_domain and kg_pipeline.run_pipeline
so no real LLM or network calls are made.
"""
from unittest.mock import MagicMock, patch

import pytest

from src.chat.memory import ChatMemory
from src.chat.orchestrator import run_turn
from src.kg_pipeline import PipelineResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_memory() -> ChatMemory:
    m = ChatMemory()
    m.summary_for_prompt = MagicMock(return_value="")
    return m


def _make_config(endpoint: str = "https://query.wikidata.org/sparql") -> dict:
    return {"endpoint": endpoint, "domain_name": "Test Domain"}


def _full_pipeline_result(**kwargs) -> PipelineResult:
    defaults = dict(
        found_in_kg=True,
        entity_hints=[{"surface": "Inception", "qid": "Q25188", "label": "Inception", "description": "2010 film"}],
        predicate_hints=[{"surface": "directed", "pid": "wdt:P57", "label": "director"}],
        sparql="SELECT ?d WHERE { wd:Q25188 wdt:P57 ?d . }",
        retried=False,
        results=[{"director": "Christopher Nolan"}],
        summary="Inception was directed by Christopher Nolan.",
        steps=[
            {"name": "__entity_lookup__", "observation": '"Inception" → wd:Q25188'},
            {"name": "generate_sparql", "observation": "Generated SPARQL (42 chars)"},
            {"name": "execute_sparql", "observation": "Returned 1 row(s)"},
            {"name": "summarize_results", "observation": "Inception was directed by Christopher Nolan."},
        ],
    )
    defaults.update(kwargs)
    return PipelineResult(**defaults)


DOMAIN_KEY = "wikidata_scientists"


# ---------------------------------------------------------------------------
# Test 1: full successful pipeline produces correct ChatMessage
# ---------------------------------------------------------------------------

@patch("src.kg_pipeline.run_pipeline")
@patch("src.domain_router.detect_domain")
def test_successful_pipeline(mock_detect, mock_run_pipeline):
    mock_detect.return_value = DOMAIN_KEY
    mock_run_pipeline.return_value = _full_pipeline_result()

    memory = _make_memory()
    configs = {DOMAIN_KEY: _make_config()}

    msg = run_turn("Who directed Inception?", memory, {}, configs, "llama3.3:latest")

    assert msg.role == "assistant"
    assert "Christopher Nolan" in msg.text
    # Artifacts stored: entities, sparql, results
    assert any(a.startswith("entities") for a in msg.artifact_ids)
    assert any(a.startswith("sparql") for a in msg.artifact_ids)
    assert any(a.startswith("results") for a in msg.artifact_ids)
    # Trace has domain detection + pipeline steps
    assert any(s["tool"] == "detect_domain" for s in msg.trace)
    assert any(s["tool"] == "__entity_lookup__" for s in msg.trace)


# ---------------------------------------------------------------------------
# Test 2: zero KG results → "not found" message, no LLM fallback
# ---------------------------------------------------------------------------

@patch("src.kg_pipeline.run_pipeline")
@patch("src.domain_router.detect_domain")
def test_not_found_in_kg(mock_detect, mock_run_pipeline):
    mock_detect.return_value = DOMAIN_KEY
    mock_run_pipeline.return_value = _full_pipeline_result(
        found_in_kg=False, results=[], summary=None,
        steps=[
            {"name": "__entity_lookup__", "observation": "no entities resolved"},
            {"name": "generate_sparql", "observation": "Generated SPARQL (50 chars)"},
            {"name": "execute_sparql", "observation": "Returned 0 row(s)"},
        ],
    )

    memory = _make_memory()
    configs = {DOMAIN_KEY: _make_config()}

    msg = run_turn("Who invented the cheese grater?", memory, {}, configs, "llama3.3:latest")

    assert msg.role == "assistant"
    assert "knowledge graph" in msg.text.lower()
    assert "christopher nolan" not in msg.text.lower()
    assert not any(a.startswith("results") for a in msg.artifact_ids)


# ---------------------------------------------------------------------------
# Test 3: domain detection failure → fallback to first config
# ---------------------------------------------------------------------------

@patch("src.kg_pipeline.run_pipeline")
@patch("src.domain_router.detect_domain")
def test_domain_detection_fallback(mock_detect, mock_run_pipeline):
    mock_detect.side_effect = RuntimeError("LLM unreachable")
    mock_run_pipeline.return_value = _full_pipeline_result()

    memory = _make_memory()
    configs = {DOMAIN_KEY: _make_config()}

    msg = run_turn("Anything", memory, {}, configs, "llama3.3:latest")

    # Pipeline still ran using fallback domain
    assert msg.role == "assistant"
    mock_run_pipeline.assert_called_once()


# ---------------------------------------------------------------------------
# Test 4: pipeline raises exception → error ChatMessage returned
# ---------------------------------------------------------------------------

@patch("src.kg_pipeline.run_pipeline")
@patch("src.domain_router.detect_domain")
def test_pipeline_exception(mock_detect, mock_run_pipeline):
    mock_detect.return_value = DOMAIN_KEY
    mock_run_pipeline.side_effect = RuntimeError("Unexpected failure")

    memory = _make_memory()
    configs = {DOMAIN_KEY: _make_config()}

    msg = run_turn("What is the speed of light?", memory, {}, configs, "llama3.3:latest")

    assert msg.role == "assistant"
    assert "pipeline error" in msg.text.lower() or "error" in msg.text.lower()


# ---------------------------------------------------------------------------
# Test 5: no entity hints → no entities artifact stored
# ---------------------------------------------------------------------------

@patch("src.kg_pipeline.run_pipeline")
@patch("src.domain_router.detect_domain")
def test_no_entity_hints_no_artifact(mock_detect, mock_run_pipeline):
    mock_detect.return_value = DOMAIN_KEY
    mock_run_pipeline.return_value = _full_pipeline_result(
        entity_hints=[],
        steps=[
            {"name": "__entity_lookup__", "observation": "no entities resolved"},
            {"name": "generate_sparql", "observation": "Generated SPARQL (30 chars)"},
            {"name": "execute_sparql", "observation": "Returned 1 row(s)"},
            {"name": "summarize_results", "observation": "Inception was directed by Christopher Nolan."},
        ],
    )

    memory = _make_memory()
    configs = {DOMAIN_KEY: _make_config()}

    msg = run_turn("Who directed Inception?", memory, {}, configs, "llama3.3:latest")

    assert not any(a.startswith("entities") for a in msg.artifact_ids)
    assert any(a.startswith("sparql") for a in msg.artifact_ids)


# ---------------------------------------------------------------------------
# Test 6: progress_callback called at key steps
# ---------------------------------------------------------------------------

@patch("src.kg_pipeline.run_pipeline")
@patch("src.domain_router.detect_domain")
def test_progress_callback_called(mock_detect, mock_run_pipeline):
    mock_detect.return_value = DOMAIN_KEY
    mock_run_pipeline.return_value = _full_pipeline_result()

    memory = _make_memory()
    configs = {DOMAIN_KEY: _make_config()}
    calls = []

    run_turn("Who directed Inception?", memory, {}, configs, "llama3.3:latest",
             progress_callback=calls.append)

    assert len(calls) > 0
    assert any("detect" in c.lower() or "entity" in c.lower() for c in calls)
