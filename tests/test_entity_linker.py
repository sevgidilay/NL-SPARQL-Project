"""
Tests for src/entity_linker.py — entity and relation extraction.

All Wikidata HTTP calls are mocked; spaCy is loaded for _extract_relations
tests (requires en_core_web_sm). Tests that need spaCy are marked so they
can be skipped if the model is not installed.
"""
import pytest
from unittest.mock import patch, MagicMock

import src.entity_linker as el


WIKIDATA_CONFIG  = {"endpoint": "https://query.wikidata.org/sparql"}
DBPEDIA_CONFIG   = {"endpoint": "https://dbpedia.org/sparql"}
EMPTY_CONFIG     = {}


# ---------------------------------------------------------------------------
# lookup_relations — gating
# ---------------------------------------------------------------------------

def test_lookup_relations_returns_empty_for_non_wikidata_endpoint():
    result = el.lookup_relations("Who invented the computer?", DBPEDIA_CONFIG)
    assert result == []


def test_lookup_relations_returns_empty_for_missing_endpoint():
    result = el.lookup_relations("Who invented the computer?", EMPTY_CONFIG)
    assert result == []


# ---------------------------------------------------------------------------
# _extract_relations — verb matching (requires spaCy)
# ---------------------------------------------------------------------------

def _spacy_available() -> bool:
    try:
        import spacy
        spacy.load("en_core_web_sm")
        return True
    except Exception:
        return False


spacy_required = pytest.mark.skipif(
    not _spacy_available(),
    reason="en_core_web_sm not installed"
)


@spacy_required
def test_extract_relations_invent_maps_to_P61():
    results = el._extract_relations("Who invented the computer?")
    pids = [r["pid"] for r in results]
    assert "wdt:P61" in pids


@spacy_required
def test_extract_relations_discover_maps_to_P61():
    results = el._extract_relations("Who discovered penicillin?")
    pids = [r["pid"] for r in results]
    assert "wdt:P61" in pids


@spacy_required
def test_extract_relations_direct_maps_to_P57():
    results = el._extract_relations("Who directed Inception?")
    pids = [r["pid"] for r in results]
    assert "wdt:P57" in pids


@spacy_required
def test_extract_relations_returns_surface_text():
    results = el._extract_relations("Who invented the computer?")
    assert len(results) > 0
    assert all("surface" in r for r in results)
    assert all("pid" in r for r in results)
    assert all("label" in r for r in results)


@spacy_required
def test_extract_relations_returns_empty_for_no_known_verbs():
    # "is" / "was" are aux — should be filtered; no content verb matches _VERB_TO_PROPERTY
    results = el._extract_relations("What is the capital of France?")
    assert results == []


@spacy_required
def test_extract_relations_no_duplicates_for_repeated_verb():
    results = el._extract_relations("Who invented and invented again?")
    pids = [r["pid"] for r in results]
    assert len(pids) == len(set(pids))


# ---------------------------------------------------------------------------
# lookup_relations — silent-fail
# ---------------------------------------------------------------------------

def test_lookup_relations_silent_fail_on_exception():
    with patch("src.entity_linker._extract_relations", side_effect=RuntimeError("boom")):
        result = el.lookup_relations("Who invented the computer?", WIKIDATA_CONFIG)
    assert result == []


# ---------------------------------------------------------------------------
# lookup_entities — existing behaviour preserved
# ---------------------------------------------------------------------------

@spacy_required
@patch("src.entity_linker._search_wikidata", return_value=[
    {"id": "Q68", "label": "computer", "description": "general-purpose device"}
])
def test_lookup_entities_returns_qid_for_noun_chunk(mock_search):
    results = el.lookup_entities("Who invented the computer?", WIKIDATA_CONFIG)
    assert len(results) == 1
    assert results[0]["qid"] == "Q68"
    assert results[0]["surface"] == "computer"


def test_lookup_entities_returns_empty_for_non_wikidata():
    results = el.lookup_entities("Who invented the computer?", DBPEDIA_CONFIG)
    assert results == []


def test_extract_entities_falls_back_to_titlecase_when_spacy_missing():
    with patch("src.entity_linker._get_nlp", return_value=None):
        results = el._extract_entities("list 10 hockey players from Turkey")

    assert results == ["Turkey"]


@patch("src.entity_linker._get_nlp", return_value=None)
@patch("src.entity_linker._search_wikidata", return_value=[
    {"id": "Q43", "label": "Turkey", "description": "country in West Asia and Southeast Europe"}
])
def test_lookup_entities_uses_titlecase_fallback_without_spacy(mock_search, mock_nlp):
    results = el.lookup_entities("list 10 hockey players from Turkey", WIKIDATA_CONFIG)

    assert len(results) == 1
    assert results[0]["surface"] == "Turkey"
    assert results[0]["qid"] == "Q43"
