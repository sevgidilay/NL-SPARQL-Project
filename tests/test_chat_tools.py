"""
Contract tests for src/chat/tools.py.

All tests are fully mocked — no LLM or HTTP calls.
"""
from unittest.mock import MagicMock, patch, call, ANY

import pytest

from src.chat.memory import ChatMemory
from src.chat.tools import (
    ToolContext,
    _generate_sparql, _execute_sparql,
    _detect_domain, _explain_sparql, _summarize_results,
    _visualize_graph, _list_domain_examples, _compare_models,
    _DEFAULT_MODELS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_DOMAIN         = "wikidata_film"
FAKE_ENDPOINT       = "https://query.wikidata.org/sparql"
FAKE_RAW_SPARQL     = "```sparql\nSELECT ?film WHERE { ?film a dbo:Film }\n```"
FAKE_CLEANED_SPARQL = "SELECT DISTINCT ?film WHERE { ?film a dbo:Film }"
FAKE_ROWS           = [{"film": "Inception"}, {"film": "Dune"}]
FAKE_EXPLANATION    = "This query retrieves films where the item is an instance of film."
FAKE_SUMMARY        = "There are 2 films: Inception and Dune."
FAKE_HTML           = (
    "<html><body><script>"
    "nodes.add({id:1});nodes.add({id:2});edges.add({from:1,to:2});"
    "</script></body></html>"
)
FAKE_EXAMPLES       = [
    {"question": "List 10 scientists", "tag": "Simple"},
    {"question": "List Nobel winners", "tag": "Filter"},
]


def _make_ctx(domain_in_stack: bool = False) -> ToolContext:
    memory = ChatMemory()
    if domain_in_stack:
        memory._domain_stack.append(FAKE_DOMAIN)
    configs = {FAKE_DOMAIN: {"endpoint": FAKE_ENDPOINT}}
    return ToolContext(memory=memory, configs=configs, model="llama3.3:latest")


# ---------------------------------------------------------------------------
# generate_sparql contract tests
# ---------------------------------------------------------------------------

@patch("src.sparql_executor.clean_sparql", return_value=FAKE_CLEANED_SPARQL)
@patch("src.nl_to_sparql.translate", return_value=FAKE_RAW_SPARQL)
def test_generate_sparql_calls_clean(mock_translate, mock_clean):
    """clean_sparql must be called exactly once per _generate_sparql call."""
    ctx  = _make_ctx()
    args = {"question": "List films", "domain": FAKE_DOMAIN}
    _generate_sparql(args, ctx)
    mock_clean.assert_called_once_with(FAKE_RAW_SPARQL)


@patch("src.sparql_executor.clean_sparql", return_value=FAKE_CLEANED_SPARQL)
@patch("src.nl_to_sparql.translate", return_value=FAKE_RAW_SPARQL)
def test_generate_sparql_stores_cleaned(mock_translate, mock_clean):
    """The stored artifact payload must be the cleaned string, not the raw LLM output."""
    ctx  = _make_ctx()
    args = {"question": "List films", "domain": FAKE_DOMAIN}
    result = _generate_sparql(args, ctx)

    assert result.error is None
    assert result.artifact_id is not None
    stored = ctx.memory.artifacts[result.artifact_id]
    assert stored == FAKE_CLEANED_SPARQL
    assert stored != FAKE_RAW_SPARQL


# ---------------------------------------------------------------------------
# execute_sparql contract tests
# ---------------------------------------------------------------------------

@patch("src.sparql_executor.execute",
       return_value={"success": True, "results": FAKE_ROWS, "error": None})
def test_execute_sparql_defaults_endpoint_from_memory(mock_execute):
    """When no endpoint arg is given, the endpoint must come from memory.last_domain()."""
    ctx = _make_ctx(domain_in_stack=True)
    # pre-store a sparql artifact so execute_sparql has something to run
    sparql_id = ctx.memory.store_artifact("sparql", FAKE_CLEANED_SPARQL)

    args = {"sparql_artifact_id": sparql_id}  # no endpoint
    result = _execute_sparql(args, ctx)

    assert result.error is None
    mock_execute.assert_called_once_with(FAKE_CLEANED_SPARQL, FAKE_ENDPOINT)


@patch("src.sparql_executor.execute",
       return_value={"success": True, "results": FAKE_ROWS, "error": None})
def test_execute_sparql_explicit_endpoint_wins(mock_execute):
    """An explicit endpoint arg must override the memory-derived default."""
    custom_endpoint = "https://dbpedia.org/sparql"
    ctx = _make_ctx(domain_in_stack=True)
    sparql_id = ctx.memory.store_artifact("sparql", FAKE_CLEANED_SPARQL)

    args = {"sparql_artifact_id": sparql_id, "endpoint": custom_endpoint}
    result = _execute_sparql(args, ctx)

    assert result.error is None
    mock_execute.assert_called_once_with(FAKE_CLEANED_SPARQL, custom_endpoint)


@patch("src.sparql_executor.execute",
       return_value={"success": True, "results": FAKE_ROWS, "error": None})
def test_execute_sparql_resolves_artifact_id(mock_execute):
    """When sparql_artifact_id is given, the stored SPARQL string must be passed to execute."""
    ctx = _make_ctx(domain_in_stack=True)
    sparql_id = ctx.memory.store_artifact("sparql", FAKE_CLEANED_SPARQL)

    args = {"sparql_artifact_id": sparql_id}
    result = _execute_sparql(args, ctx)

    assert result.error is None
    # first positional arg to execute must be the stored SPARQL string
    actual_sparql = mock_execute.call_args[0][0]
    assert actual_sparql == FAKE_CLEANED_SPARQL


# ---------------------------------------------------------------------------
# _detect_domain
# ---------------------------------------------------------------------------

@patch("src.domain_router.detect_domain", return_value=FAKE_DOMAIN)
def test_detect_domain_returns_domain_string(mock_detect):
    ctx  = _make_ctx()
    result = _detect_domain({"question": "List films"}, ctx)
    assert result.error is None
    assert result.payload == FAKE_DOMAIN
    assert isinstance(result.preview, dict) and result.preview["domain_key"] == FAKE_DOMAIN
    assert result.artifact_id is None


@patch("src.domain_router.detect_domain", return_value=FAKE_DOMAIN)
def test_detect_domain_pushes_to_domain_stack(mock_detect):
    ctx = _make_ctx()
    _detect_domain({"question": "List films"}, ctx)
    assert ctx.memory.last_domain() == FAKE_DOMAIN


@patch("src.domain_router.detect_domain", side_effect=RuntimeError("LLM down"))
def test_detect_domain_returns_error_on_exception(mock_detect):
    ctx    = _make_ctx()
    result = _detect_domain({"question": "List films"}, ctx)
    assert result.error == "LLM down"
    assert result.preview is None


def test_detect_domain_missing_question_returns_error():
    ctx    = _make_ctx()
    result = _detect_domain({}, ctx)
    assert result.error is not None
    assert "question" in result.error.lower()


# ---------------------------------------------------------------------------
# _explain_sparql
# ---------------------------------------------------------------------------

@patch("src.sparql_to_nl.translate", return_value=FAKE_EXPLANATION)
def test_explain_sparql_via_artifact_id(mock_translate):
    ctx       = _make_ctx(domain_in_stack=True)
    sparql_id = ctx.memory.store_artifact("sparql", FAKE_CLEANED_SPARQL)
    result    = _explain_sparql({"sparql_artifact_id": sparql_id}, ctx)
    assert result.error is None
    assert result.artifact_id is None
    assert result.preview == FAKE_EXPLANATION[:500]
    mock_translate.assert_called_once_with(FAKE_CLEANED_SPARQL, ANY, model=ctx.model)


@patch("src.sparql_to_nl.translate", return_value=FAKE_EXPLANATION)
def test_explain_sparql_via_raw_sparql(mock_translate):
    ctx    = _make_ctx()
    result = _explain_sparql({"sparql": FAKE_CLEANED_SPARQL}, ctx)
    assert result.error is None
    mock_translate.assert_called_once()


def test_explain_sparql_missing_both_args_returns_error():
    ctx    = _make_ctx()
    result = _explain_sparql({}, ctx)
    assert result.error is not None


def test_explain_sparql_bad_artifact_id_returns_error():
    ctx    = _make_ctx()
    result = _explain_sparql({"sparql_artifact_id": "sparql_999"}, ctx)
    assert "not found" in result.error.lower()


@patch("src.sparql_to_nl.translate", side_effect=Exception("timeout"))
def test_explain_sparql_translate_exception_returns_error(mock_translate):
    ctx    = _make_ctx()
    result = _explain_sparql({"sparql": FAKE_CLEANED_SPARQL}, ctx)
    assert result.error == "timeout"


# ---------------------------------------------------------------------------
# _summarize_results
# ---------------------------------------------------------------------------

@patch("src.answer_summarizer.summarize", return_value=FAKE_SUMMARY)
def test_summarize_results_returns_summary(mock_summarize):
    ctx        = _make_ctx()
    results_id = ctx.memory.store_artifact("results", FAKE_ROWS)
    result     = _summarize_results(
        {"question": "Which films?", "results_artifact_id": results_id}, ctx
    )
    assert result.error is None
    assert result.artifact_id is None
    assert result.preview == FAKE_SUMMARY[:500]


@patch("src.answer_summarizer.summarize", return_value=FAKE_SUMMARY)
def test_summarize_results_passes_correct_rows(mock_summarize):
    ctx        = _make_ctx()
    results_id = ctx.memory.store_artifact("results", FAKE_ROWS)
    _summarize_results({"question": "Which films?", "results_artifact_id": results_id}, ctx)
    mock_summarize.assert_called_once_with("Which films?", FAKE_ROWS, model=ctx.model)


def test_summarize_results_missing_question_returns_error():
    ctx        = _make_ctx()
    results_id = ctx.memory.store_artifact("results", FAKE_ROWS)
    result     = _summarize_results({"results_artifact_id": results_id}, ctx)
    assert result.error is not None


def test_summarize_results_bad_artifact_id_returns_error():
    ctx    = _make_ctx()
    result = _summarize_results({"question": "q", "results_artifact_id": "results_99"}, ctx)
    assert "not found" in result.error.lower()


# ---------------------------------------------------------------------------
# _visualize_graph
# ---------------------------------------------------------------------------

@patch("src.chat.viz.build_pyvis_html", return_value=FAKE_HTML)
def test_visualize_graph_stores_artifact(mock_build):
    ctx        = _make_ctx()
    results_id = ctx.memory.store_artifact("results", FAKE_ROWS)
    result     = _visualize_graph({"results_artifact_id": results_id}, ctx)
    assert result.error is None
    assert result.artifact_id is not None
    assert result.artifact_id.startswith("graph_")
    assert ctx.memory.artifacts[result.artifact_id] == FAKE_HTML


@patch("src.chat.viz.build_pyvis_html", return_value=FAKE_HTML)
def test_visualize_graph_preview_has_node_edge_count(mock_build):
    ctx        = _make_ctx()
    results_id = ctx.memory.store_artifact("results", FAKE_ROWS)
    result     = _visualize_graph({"results_artifact_id": results_id}, ctx)
    assert isinstance(result.preview, dict)
    assert result.preview["node_count"] == 2   # FAKE_HTML has 2 nodes.add(
    assert result.preview["edge_count"] == 1   # FAKE_HTML has 1 edges.add(


def test_visualize_graph_missing_results_id_returns_error():
    ctx    = _make_ctx()
    result = _visualize_graph({}, ctx)
    assert result.error is not None


def test_visualize_graph_bad_results_id_returns_error():
    ctx    = _make_ctx()
    result = _visualize_graph({"results_artifact_id": "results_99"}, ctx)
    assert "not found" in result.error.lower()


# ---------------------------------------------------------------------------
# _list_domain_examples
# ---------------------------------------------------------------------------

def test_list_domain_examples_returns_question_strings():
    ctx = _make_ctx()
    ctx.configs[FAKE_DOMAIN]["example_questions"] = FAKE_EXAMPLES
    result = _list_domain_examples({"domain": FAKE_DOMAIN}, ctx)
    assert result.error is None
    assert result.artifact_id is None
    assert "List 10 scientists" in result.preview


def test_list_domain_examples_respects_limit():
    ctx = _make_ctx()
    ctx.configs[FAKE_DOMAIN]["example_questions"] = FAKE_EXAMPLES + [
        {"question": "Extra Q", "tag": "Simple"}
    ]
    result = _list_domain_examples({"domain": FAKE_DOMAIN, "limit": 1}, ctx)
    assert len(result.preview) == 1


def test_list_domain_examples_default_limit_five():
    ctx = _make_ctx()
    ctx.configs[FAKE_DOMAIN]["example_questions"] = [
        {"question": f"Q{i}"} for i in range(10)
    ]
    result = _list_domain_examples({"domain": FAKE_DOMAIN}, ctx)
    assert len(result.preview) == 5


def test_list_domain_examples_plain_string_items():
    ctx = _make_ctx()
    ctx.configs[FAKE_DOMAIN]["example_questions"] = ["Plain string Q"]
    result = _list_domain_examples({"domain": FAKE_DOMAIN}, ctx)
    assert "Plain string Q" in result.preview


def test_list_domain_examples_unknown_domain_returns_error():
    ctx    = _make_ctx()
    result = _list_domain_examples({"domain": "nonexistent_domain"}, ctx)
    assert result.error is not None


def test_list_domain_examples_missing_domain_arg_returns_error():
    ctx    = _make_ctx()
    result = _list_domain_examples({}, ctx)
    assert result.error is not None


def test_list_domain_examples_empty_config_returns_empty_list():
    ctx    = _make_ctx()   # config has no example_questions key
    result = _list_domain_examples({"domain": FAKE_DOMAIN}, ctx)
    assert result.error is None
    assert result.preview == []


# ---------------------------------------------------------------------------
# _compare_models
# ---------------------------------------------------------------------------

@patch("src.sparql_executor.execute",
       return_value={"success": True, "results": FAKE_ROWS, "error": None})
@patch("src.sparql_executor.clean_sparql", return_value=FAKE_CLEANED_SPARQL)
@patch("src.nl_to_sparql.translate", return_value=FAKE_RAW_SPARQL)
def test_compare_models_stores_comparison_artifact(mock_translate, mock_clean, mock_execute):
    ctx    = _make_ctx(domain_in_stack=True)
    args   = {"question": "List films", "domain": FAKE_DOMAIN, "models": ["llama3.3:latest"]}
    result = _compare_models(args, ctx)
    assert result.error is None
    assert result.artifact_id is not None
    assert result.artifact_id.startswith("comparison_")


@patch("src.sparql_executor.execute",
       return_value={"success": True, "results": FAKE_ROWS, "error": None})
@patch("src.sparql_executor.clean_sparql", return_value=FAKE_CLEANED_SPARQL)
@patch("src.nl_to_sparql.translate", return_value=FAKE_RAW_SPARQL)
def test_compare_models_preview_shape(mock_translate, mock_clean, mock_execute):
    ctx    = _make_ctx(domain_in_stack=True)
    args   = {"question": "List films", "domain": FAKE_DOMAIN, "models": ["llama3.3:latest"]}
    result = _compare_models(args, ctx)
    assert isinstance(result.preview, list)
    assert len(result.preview) == 1
    row = result.preview[0]
    assert "model" in row and "sparql_preview" in row and "status" in row
    assert len(row["sparql_preview"]) <= 100


@patch("src.sparql_executor.execute",
       return_value={"success": True, "results": FAKE_ROWS, "error": None})
@patch("src.sparql_executor.clean_sparql", return_value=FAKE_CLEANED_SPARQL)
@patch("src.nl_to_sparql.translate", return_value=FAKE_RAW_SPARQL)
def test_compare_models_uses_default_models_when_none_given(mock_translate, mock_clean, mock_execute):
    ctx    = _make_ctx(domain_in_stack=True)
    args   = {"question": "List films", "domain": FAKE_DOMAIN}
    _compare_models(args, ctx)
    assert mock_translate.call_count == len(_DEFAULT_MODELS)


@patch("src.nl_to_sparql.translate", side_effect=RuntimeError("model down"))
def test_compare_models_one_model_fails_rest_continue(mock_translate):
    ctx    = _make_ctx(domain_in_stack=True)
    args   = {"question": "List films", "domain": FAKE_DOMAIN,
               "models": ["llama3.3:latest", "qwen3:latest"]}
    result = _compare_models(args, ctx)
    assert result.error is None
    payload = ctx.memory.artifacts[result.artifact_id]
    assert len(payload) == 2
    assert all("generation failed" in e["status"] for e in payload)


def test_compare_models_missing_question_returns_error():
    ctx    = _make_ctx()
    result = _compare_models({"domain": FAKE_DOMAIN}, ctx)
    assert result.error is not None


def test_compare_models_unknown_domain_returns_error():
    ctx    = _make_ctx()
    result = _compare_models({"question": "q", "domain": "unknown"}, ctx)
    assert result.error is not None


def test_default_models_constant_defined():
    assert _DEFAULT_MODELS == ["llama3.3:latest", "qwen3:latest", "mistral:latest"]
