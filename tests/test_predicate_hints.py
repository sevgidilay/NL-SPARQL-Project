"""
Tests for the predicate-hints feature across three layers:
  1. nl_to_sparql.build_prompt / translate
  2. chat/tools._generate_sparql
  3. chat/orchestrator.run_turn — KG-only guard + entity trace step
"""
from unittest.mock import MagicMock, patch

import pytest

from src.chat.memory import ChatMemory
from src.chat.orchestrator import run_turn
from src.chat.tools import ToolContext, _generate_sparql
from src.nl_to_sparql import build_prompt, translate


WIKIDATA_CONFIG  = {"endpoint": "https://query.wikidata.org/sparql", "prefixes": "", "ontology_hints": "", "few_shot_examples": []}
FAKE_DOMAIN      = "wikidata_scientists"
FAKE_ENDPOINT    = "https://query.wikidata.org/sparql"
FAKE_RAW_SPARQL  = "SELECT ?x WHERE { ?x wdt:P61 wd:Q68 }"
FAKE_CLEANED     = "SELECT DISTINCT ?x WHERE { ?x wdt:P61 wd:Q68 }"


# ---------------------------------------------------------------------------
# 1. build_prompt — predicate_hints block
# ---------------------------------------------------------------------------

def test_build_prompt_includes_relation_block_when_predicate_hints_given():
    hints = [{"surface": "invented", "pid": "wdt:P61", "label": "discoverer or inventor"}]
    prompt = build_prompt("Who invented the computer?", WIKIDATA_CONFIG, predicate_hints=hints)
    assert "RELATION LOOKUP RESULTS" in prompt
    assert "wdt:P61" in prompt
    assert "discoverer or inventor" in prompt


def test_build_prompt_no_relation_block_when_predicate_hints_empty():
    prompt = build_prompt("Who invented the computer?", WIKIDATA_CONFIG, predicate_hints=[])
    assert "RELATION LOOKUP RESULTS" not in prompt


def test_build_prompt_no_relation_block_when_predicate_hints_none():
    # None means auto-lookup; build_prompt itself does not call lookup — that's translate's job
    prompt = build_prompt("Who invented the computer?", WIKIDATA_CONFIG, predicate_hints=None)
    assert "RELATION LOOKUP RESULTS" not in prompt


def test_build_prompt_relation_block_appears_after_entity_block():
    entity_hints    = [{"surface": "computer", "qid": "Q68", "description": "a device", "label": "computer"}]
    predicate_hints = [{"surface": "invented", "pid": "wdt:P61", "label": "discoverer or inventor"}]
    prompt = build_prompt(
        "Who invented the computer?",
        WIKIDATA_CONFIG,
        entity_hints=entity_hints,
        predicate_hints=predicate_hints,
    )
    entity_pos   = prompt.index("ENTITY LOOKUP RESULTS")
    relation_pos = prompt.index("RELATION LOOKUP RESULTS")
    assert entity_pos < relation_pos


# ---------------------------------------------------------------------------
# 2. translate — auto-lookup and pass-through
# ---------------------------------------------------------------------------

@patch("src.llm_client.chat", return_value=FAKE_RAW_SPARQL)
@patch("src.entity_linker.lookup_relations", return_value=[])
@patch("src.entity_linker.lookup_entities", return_value=[])
def test_translate_calls_lookup_relations_when_none(mock_ents, mock_rels, mock_llm):
    translate("Who invented the computer?", WIKIDATA_CONFIG)
    mock_rels.assert_called_once()


@patch("src.llm_client.chat", return_value=FAKE_RAW_SPARQL)
@patch("src.entity_linker.lookup_relations")
@patch("src.entity_linker.lookup_entities", return_value=[])
def test_translate_skips_lookup_relations_when_empty_list_given(mock_ents, mock_rels, mock_llm):
    translate("Who invented the computer?", WIKIDATA_CONFIG, predicate_hints=[])
    mock_rels.assert_not_called()


@patch("src.llm_client.chat", return_value=FAKE_RAW_SPARQL)
@patch("src.entity_linker.lookup_relations",
       return_value=[{"surface": "invented", "pid": "wdt:P61", "label": "discoverer or inventor"}])
@patch("src.entity_linker.lookup_entities", return_value=[])
def test_translate_passes_predicate_hints_into_prompt(mock_ents, mock_rels, mock_llm):
    translate("Who invented the computer?", WIKIDATA_CONFIG)
    prompt_sent = mock_llm.call_args[0][0]
    assert "wdt:P61" in prompt_sent


# ---------------------------------------------------------------------------
# 3. chat/tools._generate_sparql — predicate hints wired
# ---------------------------------------------------------------------------

def _make_ctx() -> ToolContext:
    memory = ChatMemory()
    memory._domain_stack.append(FAKE_DOMAIN)
    return ToolContext(
        memory=memory,
        configs={FAKE_DOMAIN: {"endpoint": FAKE_ENDPOINT}},
        model="llama3.3:latest",
    )


@patch("src.sparql_executor.clean_sparql", return_value=FAKE_CLEANED)
@patch("src.nl_to_sparql.translate", return_value=FAKE_RAW_SPARQL)
@patch("src.entity_linker.lookup_relations",
       return_value=[{"surface": "invented", "pid": "wdt:P61", "label": "discoverer or inventor"}])
@patch("src.entity_linker.lookup_entities", return_value=[])
def test_generate_sparql_calls_lookup_relations(mock_ents, mock_rels, mock_translate, mock_clean):
    ctx  = _make_ctx()
    args = {"question": "Who invented the computer?", "domain": FAKE_DOMAIN}
    _generate_sparql(args, ctx)
    mock_rels.assert_called_once()


@patch("src.sparql_executor.clean_sparql", return_value=FAKE_CLEANED)
@patch("src.nl_to_sparql.translate", return_value=FAKE_RAW_SPARQL)
@patch("src.entity_linker.lookup_relations",
       return_value=[{"surface": "invented", "pid": "wdt:P61", "label": "discoverer or inventor"}])
@patch("src.entity_linker.lookup_entities", return_value=[])
def test_generate_sparql_passes_predicate_hints_to_translate(mock_ents, mock_rels, mock_translate, mock_clean):
    ctx  = _make_ctx()
    args = {"question": "Who invented the computer?", "domain": FAKE_DOMAIN}
    _generate_sparql(args, ctx)
    _, kwargs = mock_translate.call_args
    assert "predicate_hints" in kwargs
    assert kwargs["predicate_hints"][0]["pid"] == "wdt:P61"


# ---------------------------------------------------------------------------
# 4. orchestrator.run_turn — KG-only guard (fixed pipeline)
# ---------------------------------------------------------------------------

def _make_memory() -> ChatMemory:
    m = ChatMemory()
    m.summary_for_prompt = MagicMock(return_value="")
    return m


_DOMAIN_KEY = "wikidata_scientists"
_FAKE_CONFIG = {"endpoint": "https://query.wikidata.org/sparql"}


def _pipeline_result(**kwargs):
    from src.kg_pipeline import PipelineResult
    defaults = dict(
        found_in_kg=True,
        entity_hints=[],
        predicate_hints=[],
        sparql=FAKE_CLEANED,
        retried=False,
        results=[{"x": "wd:Q937"}],
        summary="Albert Einstein invented it.",
        steps=[
            {"name": "__entity_lookup__", "observation": "no entities resolved"},
            {"name": "generate_sparql",   "observation": "Generated SPARQL (30 chars)"},
            {"name": "execute_sparql",    "observation": "Returned 1 row(s)"},
            {"name": "summarize_results", "observation": "Albert Einstein invented it."},
        ],
    )
    defaults.update(kwargs)
    return PipelineResult(**defaults)


@patch("src.kg_pipeline.run_pipeline")
@patch("src.domain_router.detect_domain")
def test_kg_only_guard_blocks_final_when_no_kg_results(mock_detect, mock_pipeline):
    """When the KG returns no results, the reply must say 'not found', not LLM training data."""
    mock_detect.return_value = _DOMAIN_KEY
    mock_pipeline.return_value = _pipeline_result(
        found_in_kg=False, results=[], summary=None,
        steps=[
            {"name": "__entity_lookup__", "observation": "no entities"},
            {"name": "generate_sparql",   "observation": "Generated SPARQL"},
            {"name": "execute_sparql",    "observation": "Returned 0 row(s)"},
        ],
    )
    msg = run_turn("Who invented the computer?", _make_memory(), {},
                   {_DOMAIN_KEY: _FAKE_CONFIG}, "test-model")

    assert "knowledge graph" in msg.text.lower()
    assert "charles babbage" not in msg.text.lower()  # no LLM fallback


@patch("src.kg_pipeline.run_pipeline")
@patch("src.domain_router.detect_domain")
def test_kg_only_guard_allows_reply_when_kg_has_results(mock_detect, mock_pipeline):
    """When KG returns data, the NL summary is used as the reply."""
    mock_detect.return_value = _DOMAIN_KEY
    mock_pipeline.return_value = _pipeline_result(summary="Results found.")

    msg = run_turn("Who invented the computer?", _make_memory(), {},
                   {_DOMAIN_KEY: _FAKE_CONFIG}, "test-model")
    assert msg.text == "Results found."


@patch("src.kg_pipeline.run_pipeline")
@patch("src.domain_router.detect_domain")
def test_kg_only_guard_uses_summary_not_raw_llm_text(mock_detect, mock_pipeline):
    """The final answer must come from pipeline.summary, not from any direct LLM call."""
    mock_detect.return_value = _DOMAIN_KEY
    mock_pipeline.return_value = _pipeline_result(
        summary="Alan Turing pioneered computer science."
    )
    msg = run_turn("Who invented the computer?", _make_memory(), {},
                   {_DOMAIN_KEY: _FAKE_CONFIG}, "test-model")
    assert "Alan Turing" in msg.text


# ---------------------------------------------------------------------------
# 5. orchestrator.run_turn — entity trace step visibility (fixed pipeline)
# ---------------------------------------------------------------------------

@patch("src.kg_pipeline.run_pipeline")
@patch("src.domain_router.detect_domain")
def test_entity_lookup_trace_step_emitted_when_entity_hints_present(mock_detect, mock_pipeline):
    """When the pipeline resolves entity hints, a __entity_lookup__ trace step must appear."""
    mock_detect.return_value = _DOMAIN_KEY
    mock_pipeline.return_value = _pipeline_result(
        entity_hints=[{"surface": "computer", "qid": "Q68", "description": "a device", "label": "computer"}],
        steps=[
            {"name": "__entity_lookup__", "observation": '"computer" → wd:Q68'},
            {"name": "generate_sparql",   "observation": "Generated SPARQL"},
            {"name": "execute_sparql",    "observation": "Returned 1 row(s)"},
            {"name": "summarize_results", "observation": "Summary."},
        ],
    )

    msg = run_turn("Who invented the computer?", _make_memory(), {},
                   {_DOMAIN_KEY: _FAKE_CONFIG}, "test-model")

    trace_tools = [s["tool"] for s in msg.trace]
    assert "__entity_lookup__" in trace_tools


@patch("src.kg_pipeline.run_pipeline")
@patch("src.domain_router.detect_domain")
def test_entity_lookup_trace_step_appears_before_generate_sparql(mock_detect, mock_pipeline):
    """The __entity_lookup__ trace step must precede the generate_sparql step."""
    mock_detect.return_value = _DOMAIN_KEY
    mock_pipeline.return_value = _pipeline_result(
        entity_hints=[{"surface": "computer", "qid": "Q68", "description": "x", "label": "computer"}],
        steps=[
            {"name": "__entity_lookup__", "observation": '"computer" → wd:Q68'},
            {"name": "generate_sparql",   "observation": "Generated SPARQL"},
            {"name": "execute_sparql",    "observation": "Returned 1 row(s)"},
            {"name": "summarize_results", "observation": "Summary."},
        ],
    )

    msg = run_turn("Who invented the computer?", _make_memory(), {},
                   {_DOMAIN_KEY: _FAKE_CONFIG}, "test-model")

    tools = [s["tool"] for s in msg.trace]
    assert "__entity_lookup__" in tools
    assert "generate_sparql" in tools
    assert tools.index("__entity_lookup__") < tools.index("generate_sparql")
