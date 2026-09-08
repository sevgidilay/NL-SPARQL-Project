"""
Smoke tests for every manually written SPARQL query in configs/*.yaml.

For each few_shot_examples entry, the query is executed against the
domain's live endpoint (Wikidata / DBpedia) and must return ≥ 1 row.

These are integration tests — they require network access.

Run all:
    pytest tests/test_sparql_examples.py -v

Run a single domain:
    pytest tests/test_sparql_examples.py -v -k "movies"
    pytest tests/test_sparql_examples.py -v -k "scientists"

Run with short tracebacks (cleaner for many failures):
    pytest tests/test_sparql_examples.py -v --tb=short
"""

import time
import yaml
import pytest
from pathlib import Path

from src import sparql_executor

CONFIGS_DIR = Path(__file__).parent.parent / "configs"

# Wikidata throttle — the public endpoint rate-limits aggressive clients.
# A 1.5 s pause between requests keeps us well within the fair-use policy.
_WIKIDATA_HOST = "query.wikidata.org"
_WIKIDATA_DELAY = 1.5  # seconds


def _collect_examples():
    """Return a pytest.param for every few_shot_examples entry in configs/."""
    params = []
    for filepath in sorted(CONFIGS_DIR.glob("*.yaml")):
        with open(filepath) as fh:
            cfg = yaml.safe_load(fh)

        domain = cfg.get("domain_name", filepath.stem)
        endpoint = cfg.get("endpoint", "")

        for ex in cfg.get("few_shot_examples", []):
            sparql = ex.get("sparql", "").strip()
            question = ex.get("question", "?")
            if not sparql:
                continue
            params.append(
                pytest.param(
                    domain, question, sparql, endpoint,
                    id=f"{filepath.stem} | {question[:60]}",
                )
            )
    return params


_NETWORK_ERRORS = (
    "NameResolutionError",
    "Failed to resolve",
    "Max retries exceeded",
    "timed out",
    "ConnectionError",
    "RemoteDisconnected",
)


@pytest.mark.parametrize("domain,question,sparql,endpoint", _collect_examples())
def test_example_returns_results(domain, question, sparql, endpoint):
    """Each config query must succeed and return at least one result row.

    Network/DNS failures (rate-limiting, transient outages) are skipped rather
    than counted as test failures so CI stays green on flaky connectivity.
    """
    if _WIKIDATA_HOST in endpoint:
        time.sleep(_WIKIDATA_DELAY)

    result = sparql_executor.execute(sparql, endpoint)

    # Skip on transient network / rate-limit errors — not a query bug
    if not result["success"] and result["error"]:
        err = str(result["error"])
        if any(marker in err for marker in _NETWORK_ERRORS):
            pytest.skip(f"Network error (rate-limit or DNS): {err[:120]}")

    assert result["success"], (
        f"\n[{domain}] '{question}'\n"
        f"Error : {result['error']}\n"
        f"Query :\n{result['query']}"
    )
    assert len(result["results"]) > 0, (
        f"\n[{domain}] '{question}'\n"
        f"Query executed but returned 0 rows — likely a wrong QID or predicate.\n"
        f"Query :\n{result['query']}"
    )
