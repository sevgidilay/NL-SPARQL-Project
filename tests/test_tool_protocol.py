"""
Tests for src/chat/tool_protocol.py — parse_llm_output and serialize_observation.

All tests are pure (no mocks, no LLM calls).
"""
import json

import pytest

from src.chat.tool_protocol import (
    ParsedTurn,
    ToolResult,
    parse_llm_output,
    serialize_observation,
)


# ---------------------------------------------------------------------------
# Fixtures — raw LLM output strings
# ---------------------------------------------------------------------------

VALID_TOOL_CALL_RAW = """\
```json
{
  "thought": "I should detect the domain first.",
  "tool": "detect_domain",
  "args": {"question": "Who directed Inception?"}
}
```"""

VALID_FINAL_RAW = """\
```json
{
  "thought": "I have all the information I need.",
  "final_answer": "Christopher Nolan directed Inception.",
  "cite_artifacts": ["sparql_1", "results_1"]
}
```"""

MALFORMED_RAW = "Here is my answer: Christopher Nolan directed Inception."


# ---------------------------------------------------------------------------
# parse_llm_output — 3 tests
# ---------------------------------------------------------------------------

def test_parse_valid_tool_call():
    parsed = parse_llm_output(VALID_TOOL_CALL_RAW)

    assert parsed.kind == "tool_call"
    assert parsed.tool == "detect_domain"
    assert parsed.args == {"question": "Who directed Inception?"}
    assert parsed.thought == "I should detect the domain first."
    assert parsed.raw == VALID_TOOL_CALL_RAW


def test_parse_valid_final():
    parsed = parse_llm_output(VALID_FINAL_RAW)

    assert parsed.kind == "final"
    assert parsed.final_answer == "Christopher Nolan directed Inception."
    assert parsed.cite_artifacts == ["sparql_1", "results_1"]
    assert parsed.thought == "I have all the information I need."
    assert parsed.raw == VALID_FINAL_RAW


def test_parse_malformed():
    parsed = parse_llm_output(MALFORMED_RAW)

    assert parsed.kind == "parse_error"
    assert parsed.raw == MALFORMED_RAW
    assert parsed.tool is None
    assert parsed.final_answer is None


# ---------------------------------------------------------------------------
# parse_llm_output — extra edge cases
# ---------------------------------------------------------------------------

def test_parse_brace_scan_fallback():
    """If there's no fenced block, the balanced-brace fallback should work."""
    raw = 'Some preamble {"thought": "ok", "tool": "detect_domain", "args": {}} trailing text'
    parsed = parse_llm_output(raw)
    assert parsed.kind == "tool_call"
    assert parsed.tool == "detect_domain"


def test_parse_invalid_json_in_fence():
    raw = "```json\n{bad json\n```"
    parsed = parse_llm_output(raw)
    assert parsed.kind == "parse_error"


# ---------------------------------------------------------------------------
# serialize_observation — 2 tests
# ---------------------------------------------------------------------------

def test_serialize_observation_success():
    result = ToolResult(
        tool_name="generate_sparql",
        args={"question": "Who directed Inception?", "domain": "wikidata_film"},
        payload="SELECT DISTINCT ?d WHERE { dbr:Inception dbo:director ?d }",
        preview="SELECT DISTINCT ?d WHERE { dbr:Inception dbo:director ?d }",
        artifact_id="sparql_1",
        error=None,
    )
    obs = serialize_observation(result)

    assert obs.startswith("Observation (tool=generate_sparql):")
    body = json.loads(obs.split(":", 1)[1].strip())
    assert body["preview"] == result.preview
    assert body["artifact_id"] == "sparql_1"
    assert "error" not in body


def test_serialize_observation_error():
    result = ToolResult(
        tool_name="execute_sparql",
        args={"sparql_artifact_id": "sparql_1"},
        payload=None,
        preview=None,
        artifact_id=None,
        error="Endpoint unreachable",
    )
    obs = serialize_observation(result)

    assert obs.startswith("Observation (tool=execute_sparql):")
    body = json.loads(obs.split(":", 1)[1].strip())
    assert body["error"] == "Endpoint unreachable"
    assert "artifact_id" not in body
