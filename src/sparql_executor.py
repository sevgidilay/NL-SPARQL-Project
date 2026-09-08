"""
SPARQL Executor
================
Executes SPARQL queries against a given endpoint (e.g. Wikidata)
and returns structured results.
"""

import random
import re
import time
import os
import requests

SPARQL_TIMEOUT = int(os.getenv("SPARQL_TIMEOUT", "120"))

_WIKIDATA_URI_RE = re.compile(r'^https?://www\.wikidata\.org/entity/(Q\d+)$')
_QID_RE = re.compile(r'^Q\d+$')
_HTML_TAG_RE = re.compile(r'<[^>]+>')


def _shorten_uri(value: str) -> str:
    m = _WIKIDATA_URI_RE.match(value)
    return m.group(1) if m else value


def _postprocess_wikidata(results: list) -> list:
    """Shorten Wikidata entity URIs and drop rows where any *Label column
    contains only a QID (Wikidata label-service fallback with no real label)."""
    cleaned = []
    for row in results:
        row = {k: _shorten_uri(v) for k, v in row.items()}
        if any(k.endswith("Label") and _QID_RE.match(v) for k, v in row.items()):
            continue
        cleaned.append(row)
    return cleaned


def _clean_endpoint_error(status_code: int, body: str) -> str:
    text = _HTML_TAG_RE.sub(" ", body or "")
    text = re.sub(r"\s+", " ", text).strip()
    if status_code in {502, 503, 504}:
        return f"Endpoint is temporarily unavailable (HTTP {status_code}). Please retry the query in a moment."
    return f"Endpoint returned status {status_code}: {text[:300]}"


def clean_sparql(raw: str) -> str:
    """
    Clean a SPARQL query that may contain markdown fences or extra text.
    Extracts just the SPARQL query from LLM output.

    Args:
        raw: Raw string from LLM that may contain ```sparql blocks

    Returns:
        Clean SPARQL query string
    """
    text = raw.strip()

    # Extract from markdown code blocks if present
    if "```" in text:
        # Try to find ```sparql ... ``` or ``` ... ```
        pattern = r"```(?:sparql)?\s*(.*?)```"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            text = match.group(1).strip()

    # Remove any leading/trailing non-SPARQL text
    # Find the first SELECT, ASK, CONSTRUCT, or DESCRIBE
    found = False
    for keyword in ["SELECT", "ASK", "CONSTRUCT", "DESCRIBE", "PREFIX"]:
        idx = text.upper().find(keyword)
        if idx != -1:
            text = text[idx:]
            found = True
            break

    # If no SPARQL keyword found (e.g. LLM returned an error string), return empty
    if not found:
        return ""

    text = text.strip()
    # Some LLMs emit JavaScript-style comments. SPARQL supports # comments,
    # but // causes Wikidata parse errors.
    text = re.sub(r'(?m)(?<!:)//.*$', '', text).strip()

    upper = text.upper()

    # Inject DISTINCT into SELECT queries that don't already have it and don't
    # use aggregation (COUNT/SUM/etc. or GROUP BY), where DISTINCT would be wrong.
    if (
        upper.lstrip().startswith("SELECT")
        and "DISTINCT" not in upper
        and "COUNT(" not in upper
        and "SUM(" not in upper
        and "AVG(" not in upper
        and "MIN(" not in upper
        and "MAX(" not in upper
        and "GROUP BY" not in upper
    ):
        text = re.sub(r'(?i)\bSELECT\b', 'SELECT DISTINCT', text, count=1)
        upper = text.upper()

    # Inject ORDER BY RAND() before LIMIT so generic list queries return
    # different rows each run. Skip when the query already has ORDER BY or
    # uses aggregation (GROUP BY queries have a meaningful order determined by
    # the aggregation).
    #
    # This heuristic is tuned for Wikidata, whose type-constrained result sets
    # are small and curated. It is deliberately NOT applied to DBpedia queries:
    # the dbo:Film space is huge and noisy, so a random sample surfaces obscure
    # stub entries, truncates specific-entity lookups (e.g. all films by one
    # director), and forces Virtuoso to scan-and-sort the whole class (10-17s
    # latency observed). DBpedia queries are detected by the dbo:/dbr:/dbp:
    # prefixes that every DBpedia config injects.
    _is_dbpedia = bool(re.search(r'\bdb[orp]:', text))
    if (
        "LIMIT" in upper
        and "ORDER BY" not in upper
        and "GROUP BY" not in upper
        and not _is_dbpedia
    ):
        text = re.sub(r'(?i)\bLIMIT\b', 'ORDER BY RAND()\nLIMIT', text, count=1)

    # Remove any stray backticks left over from markdown fences
    text = text.replace("`", "").strip()

    return text


def execute(query: str, endpoint: str) -> dict:
    """
    Execute a SPARQL query against the given endpoint.

    Args:
        query: SPARQL query string
        endpoint: SPARQL endpoint URL

    Returns:
        Dict with keys:
            - success (bool)
            - results (list of dicts) on success
            - error (str) on failure
            - query (str) the cleaned query that was executed
    """
    raw = query.strip()
    cleaned = clean_sparql(query)

    if not cleaned:
        error = raw if raw.startswith("[ERROR]") else "Empty query after cleaning"
        return {
            "success": False,
            "error": error,
            "query": cleaned,
            "results": []
        }

    # Prepend a unique comment so endpoints with result caching treat each
    # request as a distinct query, ensuring ORDER BY RAND() takes effect.
    cache_busted = f"# {random.randint(0, 2**31)}\n{cleaned}"

    try:
        response = None
        for attempt in range(3):
            response = requests.get(
                endpoint,
                params={"query": cache_busted, "format": "json"},
                headers={"User-Agent": "KOS-NL-SPARQL-Project/1.0"},
                timeout=SPARQL_TIMEOUT
            )
            if response.status_code not in {502, 503, 504}:
                break
            if attempt < 2:
                time.sleep(1)

        if response.status_code == 200:
            data = response.json()
            bindings = data.get("results", {}).get("bindings", [])

            # Convert bindings to simpler format
            results = []
            for row in bindings:
                simple_row = {}
                for key, val in row.items():
                    simple_row[key] = val.get("value", "")
                results.append(simple_row)

            if "wikidata.org" in endpoint:
                results = _postprocess_wikidata(results)

            return {
                "success": True,
                "results": results,
                "query": cleaned,
                "error": None
            }
        else:
            return {
                "success": False,
                "error": _clean_endpoint_error(response.status_code, response.text),
                "query": cleaned,
                "results": []
            }

    except requests.exceptions.Timeout:
        return {
            "success": False,
            "error": f"Query timed out ({SPARQL_TIMEOUT}s limit)",
            "query": cleaned,
            "results": []
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "query": cleaned,
            "results": []
        }