"""
Knowledge Graph — Correctness Benchmark
========================================
Tests every curated SPARQL query against the live endpoints and validates:

  - Query execution (returns rows / empty / error)
  - Column structure detection (uri_cols, label_cols)
  - KG mode detection (star vs relational)
  - TTL export validity (rdflib can parse the output)
  - Label quality (rdfs:label values must not be raw URIs)
  - Edge deduplication (unique edges == TTL relation triples)
  - Center node label format (star mode: readable text, not ALL-CAPS)

Usage:
    python logs/Engin/kg_benchmark.py
    python logs/Engin/kg_benchmark.py --out logs/Engin/kg_accuracy.log
"""

import re
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src import sparql_executor

# ── URI / namespace constants (mirrors app.py) ────────────────────────────────
WD_URI           = "http://www.wikidata.org/entity/"
WDT_URI          = "http://www.wikidata.org/prop/direct/"
RDFS_URI         = "http://www.w3.org/2000/01/rdf-schema#"
LAMIA_URI        = "https://group-b-lamia.unige.ch/kg/"
LAMIA_ONTOLOGY_URI = "https://group-b-lamia.unige.ch/kg/ontology"

DEFAULT_OUT = Path(__file__).parent / "kg_accuracy.log"
ENDPOINT_DELAY = 1.2  # seconds between requests

# ── Helpers inlined from app.py (no Streamlit import) ─────────────────────────

def _slug_uri_part(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value).strip()).strip("_")
    return slug or "item"


def _humanize_var_name(value: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value or ""))
    text = re.sub(r"[_-]+", " ", text).strip()
    return text.title() or "Entity"


def _result_value_to_uri(value: str):
    from rdflib import URIRef
    value = str(value or "").strip()
    if value.startswith(("http://", "https://")):
        return URIRef(value)
    if re.fullmatch(r"Q\d+", value):
        return URIRef(f"{WD_URI}{value}")
    return URIRef(f"{LAMIA_URI}entity/{_slug_uri_part(value)}")


def _class_uri_for_var(value: str):
    from rdflib import URIRef
    return URIRef(f"{LAMIA_URI}class/{_slug_uri_part(value)}")


def _expand_prefixed_name(token: str, prefixes: dict):
    token = token.strip().strip("<>")
    if token.startswith(("http://", "https://")):
        return token
    if ":" not in token:
        return None
    prefix, local = token.split(":", 1)
    base = prefixes.get(prefix)
    return f"{base}{local}" if base else None


def _infer_predicate_uri(query: str, src_k: str, tgt_k: str):
    from rdflib import URIRef
    prefixes = {"wdt": WDT_URI, "rdfs": RDFS_URI, "lamia": LAMIA_URI}
    for prefix, uri in re.findall(r"(?im)^\s*PREFIX\s+([A-Za-z][\w-]*):\s*<([^>]+)>", query):
        prefixes[prefix] = uri
    pattern = rf"\?{re.escape(src_k)}\s+([A-Za-z][\w-]*:[^\s;.]+|<[^>]+>)\s+\?{re.escape(tgt_k)}"
    match = re.search(pattern, query)
    if match:
        expanded = _expand_prefixed_name(match.group(1), prefixes)
        if expanded:
            return URIRef(expanded)
    return URIRef(f"{LAMIA_URI}relation/{_slug_uri_part(src_k)}_to_{_slug_uri_part(tgt_k)}")


def build_turtle_export(rows: list, query: str, uri_cols: list, label_map: dict) -> str:
    from rdflib import Graph, Literal, Namespace, URIRef
    from rdflib.namespace import OWL, RDF, RDFS

    WD    = Namespace(WD_URI)
    WDT   = Namespace(WDT_URI)
    LAMIA = Namespace(LAMIA_URI)
    g = Graph()
    g.bind("wd", WD); g.bind("wdt", WDT); g.bind("rdfs", RDFS)
    g.bind("lamia", LAMIA); g.bind("owl", OWL); g.bind("rdf", RDF)
    g.add((URIRef(LAMIA_ONTOLOGY_URI), RDF.type, OWL.Ontology))

    if len(uri_cols) >= 2:
        src_k, tgt_k = uri_cols[0], uri_cols[1]
        src_lk   = label_map.get(src_k)
        tgt_lk   = label_map.get(tgt_k)
        src_cls  = _class_uri_for_var(src_k)
        tgt_cls  = _class_uri_for_var(tgt_k)
        pred     = _infer_predicate_uri(query, src_k, tgt_k)

        g.add((src_cls, RDF.type, OWL.Class))
        g.add((src_cls, RDFS.subClassOf, OWL.Thing))
        g.add((src_cls, RDFS.label, Literal(_humanize_var_name(src_k), lang="en")))
        g.add((tgt_cls, RDF.type, OWL.Class))
        g.add((tgt_cls, RDFS.subClassOf, OWL.Thing))
        g.add((tgt_cls, RDFS.label, Literal(_humanize_var_name(tgt_k), lang="en")))
        g.add((pred, RDF.type, OWL.ObjectProperty))
        g.add((pred, RDFS.domain, src_cls))
        g.add((pred, RDFS.range, tgt_cls))
        g.add((pred, RDFS.label, Literal(
            f"{_humanize_var_name(src_k)} to {_humanize_var_name(tgt_k)}", lang="en")))

        seen: set = set()
        for row in rows:
            if not row.get(src_k) or not row.get(tgt_k):
                continue
            src_uri = _result_value_to_uri(row[src_k])
            tgt_uri = _result_value_to_uri(row[tgt_k])
            g.add((src_uri, RDF.type, OWL.NamedIndividual))
            g.add((src_uri, RDF.type, src_cls))
            g.add((tgt_uri, RDF.type, OWL.NamedIndividual))
            g.add((tgt_uri, RDF.type, tgt_cls))
            key = (str(src_uri), str(tgt_uri))
            if key not in seen:
                g.add((src_uri, pred, tgt_uri))
                seen.add(key)
            if src_lk and row.get(src_lk):
                g.add((src_uri, RDFS.label, Literal(row[src_lk], lang="en")))
            if tgt_lk and row.get(tgt_lk):
                g.add((tgt_uri, RDFS.label, Literal(row[tgt_lk], lang="en")))
    else:
        ek   = uri_cols[0] if uri_cols else next(iter(rows[0].keys()))
        elk  = label_map.get(ek)
        cname = _humanize_var_name(ek) + "s" if not ek.lower().endswith("s") else _humanize_var_name(ek)
        center   = URIRef(f"{LAMIA_URI}concept/{_slug_uri_part(ek)}")
        pred     = URIRef(f"{LAMIA_URI}relation/has_member")
        c_cls    = URIRef(f"{LAMIA_URI}class/concept")
        e_cls    = _class_uri_for_var(ek)

        g.add((c_cls, RDF.type, OWL.Class))
        g.add((c_cls, RDFS.subClassOf, OWL.Thing))
        g.add((c_cls, RDFS.label, Literal("Concept", lang="en")))
        g.add((e_cls, RDF.type, OWL.Class))
        g.add((e_cls, RDFS.subClassOf, OWL.Thing))
        g.add((e_cls, RDFS.label, Literal(_humanize_var_name(ek), lang="en")))
        g.add((center, RDF.type, OWL.NamedIndividual))
        g.add((center, RDF.type, c_cls))
        g.add((pred, RDF.type, OWL.ObjectProperty))
        g.add((pred, RDFS.domain, c_cls))
        g.add((pred, RDFS.range, e_cls))
        g.add((pred, RDFS.label, Literal("Has Member", lang="en")))
        g.add((center, RDFS.label, Literal(cname, lang="en")))

        for row in rows:
            if not row.get(ek):
                continue
            e_uri = _result_value_to_uri(row[ek])
            g.add((e_uri, RDF.type, OWL.NamedIndividual))
            g.add((e_uri, RDF.type, e_cls))
            g.add((center, pred, e_uri))
            if elk and row.get(elk):
                g.add((e_uri, RDFS.label, Literal(row[elk], lang="en")))

    return g.serialize(format="turtle")


# ── Column structure detection (mirrors app.py logic) ─────────────────────────

def detect_columns(rows: list) -> tuple[list, list, dict]:
    """
    Returns (uri_cols, label_cols, label_map).

    Two-pass detection:
      1. Wikidata-style ?xLabel suffix pairs.
      2. Value-based fallback: columns whose sampled values contain no URIs
         are treated as label columns (handles DBpedia ?name / ?title etc.).
    """
    if not rows:
        return [], [], {}
    keys = list(rows[0].keys())
    label_map: dict = {}
    label_cols: set = set()

    for k in keys:
        if k.endswith("Label"):
            base = k[:-5]
            if base in keys:
                label_map[base] = k
                label_cols.add(k)

    _ENTITY_RE = re.compile(r'^(?:https?://|Q\d+$)')
    sample = rows[:10]
    for k in keys:
        if k in label_cols:
            continue
        vals = [str(r.get(k, "")) for r in sample if r.get(k)]
        if vals and not any(_ENTITY_RE.match(v) for v in vals):
            paired = next(
                (u for u in keys
                 if u not in label_cols and u != k and u not in label_map),
                None,
            )
            if paired:
                label_map[paired] = k
            label_cols.add(k)

    uri_cols = [k for k in keys if k not in label_cols]
    return uri_cols, sorted(label_cols), label_map


# ── TTL quality checks ─────────────────────────────────────────────────────────

def _labels_are_text(ttl: str) -> tuple[bool, list]:
    """Returns (ok, offending_labels). Fails if any rdfs:label value looks like a URI."""
    from rdflib import Graph
    from rdflib.namespace import RDFS
    g = Graph()
    g.parse(data=ttl, format="turtle")
    bad = []
    for _, _, obj in g.triples((None, RDFS.label, None)):
        val = str(obj)
        if val.startswith(("http://", "https://")):
            bad.append(val[:80])
    return len(bad) == 0, bad


def _count_individuals_and_edges(ttl: str, uri_cols: list) -> tuple[int, int]:
    """Returns (named_individual_count, relation_triple_count)."""
    from rdflib import Graph, URIRef
    from rdflib.namespace import OWL, RDF
    g = Graph()
    g.parse(data=ttl, format="turtle")
    individuals = set(s for s, _, _ in g.triples((None, RDF.type, OWL.NamedIndividual)))
    # Relation triples = all triples whose predicate is NOT rdf:type / rdfs:* / owl:*
    skip_ns = ("http://www.w3.org/1999/02/22-rdf-syntax-ns#",
               "http://www.w3.org/2000/01/rdf-schema#",
               "http://www.w3.org/2002/07/owl#")
    rel_triples = [
        (s, p, o) for s, p, o in g
        if not any(str(p).startswith(ns) for ns in skip_ns)
        and isinstance(o, URIRef)
    ]
    return len(individuals), len(rel_triples)


def _center_label_ok(ttl: str, entity_k: str) -> tuple[bool, str]:
    """
    For star graphs: checks that the center node's rdfs:label is properly
    capitalised text (e.g. "Scientists") and not ALL-CAPS (e.g. "SCIENTISTS").
    """
    from rdflib import Graph, URIRef
    from rdflib.namespace import RDFS
    center_uri = URIRef(f"{LAMIA_URI}concept/{_slug_uri_part(entity_k)}")
    g = Graph()
    g.parse(data=ttl, format="turtle")
    labels = [str(o) for _, _, o in g.triples((center_uri, RDFS.label, None))]
    if not labels:
        return False, "(no label found)"
    label = labels[0]
    ok = label == label.title() or (label[0].isupper() and not label.isupper())
    return ok, label


# ── Test case definitions ─────────────────────────────────────────────────────

WIKIDATA  = "https://query.wikidata.org/sparql"
DBPEDIA   = "https://dbpedia.org/sparql"

TEST_CASES = [
    # ── Star graph tests (1 URI column + label column) ──────────────────────
    {
        "id": "KG-01", "domain": "Scientists (Wikidata)", "mode": "star",
        "endpoint": WIKIDATA,
        "question": "List 10 scientists",
        "sparql": """\
SELECT DISTINCT ?scientist ?scientistLabel WHERE {
  ?scientist wdt:P31 wd:Q5 ;
             wdt:P106 wd:Q901 .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
LIMIT 10""",
    },
    {
        "id": "KG-02", "domain": "Astronomy (Wikidata)", "mode": "star",
        "endpoint": WIKIDATA,
        "question": "List planets in our Solar System",
        "sparql": """\
SELECT DISTINCT ?planet ?planetLabel WHERE {
  ?planet wdt:P31/wdt:P279* wd:Q634 .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
LIMIT 15""",
    },
    {
        "id": "KG-03", "domain": "Philosophy (Wikidata)", "mode": "star",
        "endpoint": WIKIDATA,
        "question": "List 10 philosophers",
        "sparql": """\
SELECT DISTINCT ?philosopher ?philosopherLabel WHERE {
  ?philosopher wdt:P31 wd:Q5 ;
               wdt:P106 wd:Q4964182 .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
LIMIT 10""",
    },
    {
        "id": "KG-04", "domain": "Diseases (Wikidata)", "mode": "star",
        "endpoint": WIKIDATA,
        "question": "List 10 diseases",
        "sparql": """\
SELECT DISTINCT ?disease ?diseaseLabel WHERE {
  ?disease wdt:P31/wdt:P279* wd:Q12136 .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
LIMIT 10""",
    },
    {
        "id": "KG-05", "domain": "Sports (Wikidata)", "mode": "star",
        "endpoint": WIKIDATA,
        "question": "List 10 football players",
        "sparql": """\
SELECT DISTINCT ?player ?playerLabel WHERE {
  ?player wdt:P31 wd:Q5 ;
          wdt:P106 wd:Q937857 .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
LIMIT 10""",
    },
    {
        "id": "KG-06", "domain": "Books (Wikidata)", "mode": "star",
        "endpoint": WIKIDATA,
        "question": "List 10 novels",
        "sparql": """\
SELECT DISTINCT ?novel ?novelLabel WHERE {
  ?novel wdt:P31 wd:Q7725634 .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
LIMIT 10""",
    },
    {
        "id": "KG-07", "domain": "Movies (DBpedia)", "mode": "star",
        "endpoint": DBPEDIA,
        "question": "List 10 movies",
        "sparql": """\
SELECT DISTINCT ?film ?name WHERE {
  ?film a dbo:Film ;
        rdfs:label ?name .
  FILTER (lang(?name) = "en")
}
LIMIT 10""",
    },
    # ── Relational graph tests (2+ URI columns) ──────────────────────────────
    {
        "id": "KG-08", "domain": "Geography (Wikidata)", "mode": "relational",
        "endpoint": WIKIDATA,
        "question": "Countries and their capitals",
        "sparql": """\
SELECT DISTINCT ?country ?countryLabel ?capital ?capitalLabel WHERE {
  ?country wdt:P31 wd:Q6256 ;
           wdt:P36 ?capital .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
LIMIT 20""",
    },
    {
        "id": "KG-09", "domain": "Scientists (Wikidata)", "mode": "relational",
        "endpoint": WIKIDATA,
        "question": "Female Nobel Prize laureates and their awards",
        "sparql": """\
SELECT DISTINCT ?laureate ?laureateLabel ?award ?awardLabel WHERE {
  ?laureate wdt:P21 wd:Q6581072 ;
            wdt:P166 ?award .
  ?award wdt:P31/wdt:P279* wd:Q7191 .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
LIMIT 20""",
    },
    {
        "id": "KG-10", "domain": "Philosophy (Wikidata)", "mode": "relational",
        "endpoint": WIKIDATA,
        "question": "Philosophers and who influenced them",
        "sparql": """\
SELECT DISTINCT ?philosopher ?philosopherLabel ?influence ?influenceLabel WHERE {
  ?philosopher wdt:P31 wd:Q5 ;
               wdt:P106 wd:Q4964182 ;
               wdt:P737 ?influence .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
LIMIT 20""",
    },
    {
        "id": "KG-11", "domain": "Diseases (Wikidata)", "mode": "relational",
        "endpoint": WIKIDATA,
        "question": "Diseases and their treatments",
        "sparql": """\
SELECT DISTINCT ?disease ?diseaseLabel ?drug ?drugLabel WHERE {
  ?disease wdt:P31/wdt:P279* wd:Q12136 ;
           wdt:P2176 ?drug .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
LIMIT 20""",
    },
    {
        "id": "KG-12", "domain": "Movies (DBpedia)", "mode": "star",
        "endpoint": DBPEDIA,
        "question": "Movies directed by Steven Spielberg",
        "sparql": """\
SELECT DISTINCT ?film ?name WHERE {
  ?film a dbo:Film ;
        dbo:director dbr:Steven_Spielberg ;
        rdfs:label ?name .
  FILTER (lang(?name) = "en")
}
LIMIT 15""",
    },
]


# ── Per-test validation ────────────────────────────────────────────────────────

def _detect_pyvis_duplicates(rows: list, uri_cols: list) -> tuple[int, int]:
    """Returns (total_pairs, unique_pairs) for relational mode."""
    if len(uri_cols) < 2:
        return 0, 0
    src_k, tgt_k = uri_cols[0], uri_cols[1]
    pairs = [(r.get(src_k, ""), r.get(tgt_k, "")) for r in rows
             if r.get(src_k) and r.get(tgt_k)]
    return len(pairs), len(set(pairs))


def validate_case(tc: dict, rows: list, elapsed: float) -> dict:
    uri_cols, label_cols, label_map = detect_columns(rows)
    detected_mode = "relational" if len(uri_cols) >= 2 else "star"
    mode_match = detected_mode == tc["mode"]

    # TTL export
    ttl_valid = False
    ttl_error = ""
    ttl_triples = 0
    ttl_individuals = 0
    ttl_edges = 0
    labels_ok = True
    bad_labels: list = []
    center_label = ""
    center_label_ok = True

    try:
        ttl = build_turtle_export(rows, tc["sparql"], uri_cols, label_map)
        ttl_valid = True
        ttl_triples = ttl.count("\n")  # approximate line count
        ttl_individuals, ttl_edges = _count_individuals_and_edges(ttl, uri_cols)
        labels_ok, bad_labels = _labels_are_text(ttl)
        if detected_mode == "star":
            ek = uri_cols[0] if uri_cols else list(rows[0].keys())[0]
            center_label_ok, center_label = _center_label_ok(ttl, ek)
    except Exception as e:
        ttl_error = str(e)

    # Duplicate edge check (relational only)
    total_pairs, unique_pairs = _detect_pyvis_duplicates(rows, uri_cols)
    has_duplicates = total_pairs != unique_pairs and total_pairs > 0

    # Overall status
    if not rows:
        status = "EMPTY"
    elif not ttl_valid:
        status = "TTL_FAIL"
    elif not labels_ok:
        status = "LABEL_BUG"
    elif not mode_match:
        status = "MODE_MISMATCH"
    else:
        status = "PASS"

    return {
        "id": tc["id"],
        "domain": tc["domain"],
        "question": tc["question"],
        "expected_mode": tc["mode"],
        "detected_mode": detected_mode,
        "mode_match": mode_match,
        "rows": len(rows),
        "elapsed": elapsed,
        "uri_cols": uri_cols,
        "label_cols": label_cols,
        "has_labels": bool(label_cols),
        "ttl_valid": ttl_valid,
        "ttl_error": ttl_error,
        "ttl_triples": ttl_triples,
        "ttl_individuals": ttl_individuals,
        "ttl_edges": ttl_edges,
        "labels_ok": labels_ok,
        "bad_labels": bad_labels,
        "center_label": center_label,
        "center_label_ok": center_label_ok,
        "total_pairs": total_pairs,
        "unique_pairs": unique_pairs,
        "has_duplicates": has_duplicates,
        "status": status,
    }


# ── Main runner ────────────────────────────────────────────────────────────────

def run_benchmark(out_path: Path) -> None:
    run_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    results = []

    print(f"Knowledge Graph Benchmark — {len(TEST_CASES)} test cases")
    print(f"Run at: {run_at}\n")

    for tc in TEST_CASES:
        time.sleep(ENDPOINT_DELAY)
        t0 = time.perf_counter()
        result = sparql_executor.execute(tc["sparql"], tc["endpoint"])
        elapsed = time.perf_counter() - t0

        if not result["success"]:
            r = {
                "id": tc["id"], "domain": tc["domain"], "question": tc["question"],
                "expected_mode": tc["mode"], "detected_mode": "-", "mode_match": False,
                "rows": 0, "elapsed": elapsed,
                "uri_cols": [], "label_cols": [], "has_labels": False,
                "ttl_valid": False, "ttl_error": result.get("error", ""),
                "ttl_triples": 0, "ttl_individuals": 0, "ttl_edges": 0,
                "labels_ok": False, "bad_labels": [],
                "center_label": "", "center_label_ok": False,
                "total_pairs": 0, "unique_pairs": 0, "has_duplicates": False,
                "status": "FAIL",
            }
        elif not result["results"]:
            r = {
                "id": tc["id"], "domain": tc["domain"], "question": tc["question"],
                "expected_mode": tc["mode"], "detected_mode": "-", "mode_match": False,
                "rows": 0, "elapsed": elapsed,
                "uri_cols": [], "label_cols": [], "has_labels": False,
                "ttl_valid": False, "ttl_error": "no rows",
                "ttl_triples": 0, "ttl_individuals": 0, "ttl_edges": 0,
                "labels_ok": False, "bad_labels": [],
                "center_label": "", "center_label_ok": False,
                "total_pairs": 0, "unique_pairs": 0, "has_duplicates": False,
                "status": "EMPTY",
            }
        else:
            r = validate_case(tc, result["results"], elapsed)

        results.append(r)

        icons = {"PASS": "OK", "EMPTY": "!!", "FAIL": "XX",
                 "TTL_FAIL": "TF", "LABEL_BUG": "LB", "MODE_MISMATCH": "MM"}
        icon = icons.get(r["status"], "??")
        dup_note = f"  [DUP:{r['total_pairs']}->{r['unique_pairs']}]" if r["has_duplicates"] else ""
        print(f"  [{icon}] {r['id']}  {r['domain'][:28]:<28}  "
              f"{r['rows']:>4} rows  {r['elapsed']:.2f}s  "
              f"ttl:{r['ttl_individuals']}ind/{r['ttl_edges']}rel"
              f"{dup_note}")

    # Summary
    total   = len(results)
    passed  = sum(1 for r in results if r["status"] == "PASS")
    empty   = sum(1 for r in results if r["status"] == "EMPTY")
    failed  = sum(1 for r in results if r["status"] == "FAIL")
    ttl_fail = sum(1 for r in results if r["status"] == "TTL_FAIL")
    label_bug = sum(1 for r in results if r["status"] == "LABEL_BUG")
    mode_mm  = sum(1 for r in results if r["status"] == "MODE_MISMATCH")
    accuracy = (passed / total * 100) if total else 0.0
    avg_time = sum(r["elapsed"] for r in results) / total if total else 0.0

    # Write log
    sep  = "=" * 82
    sep2 = "-" * 82

    lines = [
        sep,
        "  Knowledge Graph Correctness Benchmark",
        f"  Run at    : {run_at}",
        sep,
        "",
        "SUMMARY",
        sep2,
        f"  Total test cases     : {total}",
        f"  PASS  (all checks ok): {passed}",
        f"  EMPTY (0 rows)       : {empty}",
        f"  FAIL  (exec error)   : {failed}",
        f"  TTL_FAIL (bad export): {ttl_fail}",
        f"  LABEL_BUG (URI label): {label_bug}",
        f"  MODE_MISMATCH        : {mode_mm}",
        f"  Accuracy             : {accuracy:.1f}%  ({passed}/{total} fully passing)",
        f"  Avg response         : {avg_time:.2f}s",
        "",
        "CHECKS EXPLAINED",
        sep2,
        "  PASS        — query returned rows, TTL export valid, labels are readable",
        "                text, KG mode correctly detected, no URI-as-label bugs.",
        "  EMPTY       — SPARQL executed but returned 0 rows.",
        "  FAIL        — SPARQL endpoint returned an error.",
        "  TTL_FAIL    — Query returned rows but rdflib could not parse the exported",
        "                Turtle, or build_turtle_export raised an exception.",
        "  LABEL_BUG   — At least one rdfs:label in the TTL contains a raw URI",
        "                (e.g. http://www.wikidata.org/entity/Q...) instead of text.",
        "  MODE_MISMATCH — Detected KG mode (star/relational) differs from expected.",
        "",
        "DETAIL",
        sep2,
    ]

    for r in results:
        icon = {
            "PASS": "[PASS        ]",
            "EMPTY": "[EMPTY       ]",
            "FAIL": "[FAIL        ]",
            "TTL_FAIL": "[TTL_FAIL    ]",
            "LABEL_BUG": "[LABEL_BUG   ]",
            "MODE_MISMATCH": "[MODE_MISMATCH]",
        }.get(r["status"], "[???         ]")

        lines += [
            "",
            f"{icon}  {r['id']}  [{r['expected_mode']}]  {r['domain']}",
            f"  Question    : {r['question']}",
            f"  Rows        : {r['rows']}   Time: {r['elapsed']:.2f}s",
            f"  URI cols    : {r['uri_cols']}",
            f"  Label cols  : {r['label_cols']}  (has_labels={r['has_labels']})",
            f"  KG mode     : expected={r['expected_mode']}  detected={r['detected_mode']}"
            + ("  OK" if r["mode_match"] else "  MISMATCH"),
            f"  TTL valid   : {r['ttl_valid']}"
            + (f"  (error: {r['ttl_error']})" if r["ttl_error"] else ""),
            f"  TTL stats   : ~{r['ttl_triples']} lines  "
            f"{r['ttl_individuals']} individuals  {r['ttl_edges']} relation triples",
            f"  Labels ok   : {r['labels_ok']}"
            + (f"  OFFENDING: {r['bad_labels'][:3]}" if r["bad_labels"] else ""),
        ]

        if r["expected_mode"] == "star" and r["rows"] > 0:
            lines.append(
                f"  Center label: {r['center_label']!r}  "
                + ("OK" if r["center_label_ok"] else "BAD (ALL-CAPS or missing)")
            )

        if r["expected_mode"] == "relational" and r["total_pairs"] > 0:
            dup_note = (f"  DUPLICATE EDGES: {r['total_pairs']} raw pairs -> "
                        f"{r['unique_pairs']} unique"
                        if r["has_duplicates"] else "  No duplicate edges")
            lines.append(f"  Edge dedup  :{dup_note}")

        if r["status"] == "FAIL":
            lines.append(f"  Error       : {r['ttl_error']}")

    lines += [
        "",
        sep,
        f"  End of log — {run_at}",
        sep,
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nLog written to: {out_path}")
    print(f"Accuracy: {accuracy:.1f}%  "
          f"(pass={passed} empty={empty} fail={failed} "
          f"ttl_fail={ttl_fail} label_bug={label_bug} mode_mismatch={mode_mm})")


def main():
    parser = argparse.ArgumentParser(description="Knowledge Graph correctness benchmark")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help="Output log path (default: logs/Engin/kg_accuracy.log)")
    args = parser.parse_args()
    run_benchmark(args.out)


if __name__ == "__main__":
    main()
