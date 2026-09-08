"""
Sports (Wikidata) — Comprehensive Query Accuracy Benchmark
===========================================================
Tests every few_shot_examples query from configs/wikidata_sports.yaml
against the live Wikidata SPARQL endpoint, plus additional validation
probes that check specific QID correctness and cross-property consistency.

What is tested:
  1. All few_shot_examples SPARQLs (do they return rows?)
  2. FIFA World Cup: wdt:P3450 vs wdt:P31 comparison
  3. Olympic gold medal: wd:Q15243387 vs wd:Q319921 comparison
  4. Manchester City QID: wd:Q18602070 vs known-correct wd:Q503
  5. Basketball player pattern: wdt:P641 (sport) vs wdt:P106/wd:Q3665646 (occupation)
  6. Olympic Games entity: wd:Q159821 identity check
  7. Label-based player lookup (Messi, Mbappe) — verifies rdfs:label pattern

Usage:
    python logs/Engin/sports_benchmark.py
    python logs/Engin/sports_benchmark.py --out logs/Engin/sports_accuracy.log
"""

import sys
import time
import argparse
import yaml
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src import sparql_executor

CONFIG_PATH  = Path(__file__).parent.parent.parent / "configs" / "wikidata_sports.yaml"
DEFAULT_OUT  = Path(__file__).parent / "sports_accuracy.log"
ENDPOINT     = "https://query.wikidata.org/sparql"
DELAY        = 2.0   # seconds between requests — Wikidata fair-use

# ---------------------------------------------------------------------------
# Validation probes — compare broken vs fixed variants and check entity QIDs
# ---------------------------------------------------------------------------

VALIDATION_PROBES = [
    # ── FIFA World Cup: old property (P3450) vs correct (P31) ────────────────
    {
        "id": "PROBE-01a",
        "label": "FIFA World Cup — wdt:P3450 (current config, possibly incomplete)",
        "note": "wdt:P3450 = 'sports season of', not all editions have this set",
        "sparql": """\
SELECT ?edition ?editionLabel ?winner ?winnerLabel WHERE {
  ?edition wdt:P3450 wd:Q19317 .
  ?edition wdt:P1346 ?winner .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
ORDER BY ?edition
LIMIT 20""",
    },
    {
        "id": "PROBE-01b",
        "label": "FIFA World Cup — wdt:P31 (correct pattern per notes.md)",
        "note": "wdt:P31 = 'instance of', covers all tournament editions",
        "sparql": """\
SELECT ?edition ?editionLabel ?winner ?winnerLabel WHERE {
  ?edition wdt:P31 wd:Q19317 .
  ?edition wdt:P1346 ?winner .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
ORDER BY ?edition
LIMIT 20""",
    },

    # ── Olympic gold medal QID check ─────────────────────────────────────────
    {
        "id": "PROBE-02a",
        "label": "Olympic gold medalists in athletics — wd:Q15243387 (current config)",
        "note": "config lists Q15243387 as 'Olympic gold medal' — may be wrong QID",
        "sparql": """\
SELECT DISTINCT ?athlete ?athleteLabel WHERE {
  ?athlete wdt:P166 wd:Q15243387 .
  ?athlete wdt:P641 wd:Q542 .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
LIMIT 10""",
    },
    {
        "id": "PROBE-02b",
        "label": "Olympic gold medalists in athletics — wd:Q319921 (notes.md suggestion)",
        "note": "Q319921 is 'Olympic gold medal' per notes.md Bug H analysis",
        "sparql": """\
SELECT DISTINCT ?athlete ?athleteLabel WHERE {
  ?athlete wdt:P166 wd:Q319921 .
  ?athlete wdt:P641 wd:Q542 .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
LIMIT 10""",
    },
    {
        "id": "PROBE-02c",
        "label": "Olympic gold medalists in athletics — P166/P279* pattern (broadest)",
        "note": "Traverse the award hierarchy to catch all Olympic gold medal subclasses",
        "sparql": """\
SELECT DISTINCT ?athlete ?athleteLabel WHERE {
  ?medal wdt:P279* wd:Q319921 .
  ?athlete wdt:P166 ?medal .
  ?athlete wdt:P641 wd:Q542 .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
LIMIT 10""",
    },

    # ── Manchester City QID identity check ───────────────────────────────────
    {
        "id": "PROBE-03a",
        "label": "Manchester City QID wd:Q18602070 — what entity is it?",
        "note": "Config says Q18602070 = Manchester City FC; actual Manchester City is Q503",
        "sparql": """\
SELECT ?label WHERE {
  wd:Q18602070 rdfs:label ?label .
  FILTER(LANG(?label) = "en")
}
LIMIT 5""",
    },
    {
        "id": "PROBE-03b",
        "label": "Manchester City QID wd:Q503 — correct QID identity check",
        "note": "Q503 is the known-correct Wikidata QID for Manchester City FC",
        "sparql": """\
SELECT ?label WHERE {
  wd:Q503 rdfs:label ?label .
  FILTER(LANG(?label) = "en")
}
LIMIT 5""",
    },
    {
        "id": "PROBE-03c",
        "label": "Manchester City players using wd:Q18602070 (current config)",
        "note": "Do we get actual Man City players with Q18602070?",
        "sparql": """\
SELECT ?player ?playerLabel WHERE {
  ?player wdt:P31 wd:Q5 .
  ?player wdt:P54 wd:Q18602070 .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
LIMIT 10""",
    },
    {
        "id": "PROBE-03d",
        "label": "Manchester City players using wd:Q503 (correct QID)",
        "note": "Players listed with Q503; compare count vs Q18602070",
        "sparql": """\
SELECT ?player ?playerLabel WHERE {
  ?player wdt:P31 wd:Q5 .
  ?player wdt:P54 wd:Q503 .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
LIMIT 10""",
    },

    # ── Basketball player pattern consistency ─────────────────────────────────
    {
        "id": "PROBE-04a",
        "label": "Basketball players — wdt:P641 wd:Q5372 (current config, sport=basketball)",
        "note": "Current config uses sport property instead of occupation",
        "sparql": """\
SELECT ?player ?playerLabel WHERE {
  ?player wdt:P641 wd:Q5372 .
  ?player wdt:P31 wd:Q5 .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
LIMIT 10""",
    },
    {
        "id": "PROBE-04b",
        "label": "Basketball players — wdt:P106 wd:Q3665646 (occupation=basketball player)",
        "note": "Consistent with football (Q937857) and tennis (Q10833314) approach",
        "sparql": """\
SELECT ?player ?playerLabel WHERE {
  ?player wdt:P106 wd:Q3665646 .
  ?player wdt:P31 wd:Q5 .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
LIMIT 10""",
    },

    # ── Olympic Games entity check ────────────────────────────────────────────
    {
        "id": "PROBE-05",
        "label": "wd:Q159821 identity — config lists as 'Olympic Games'",
        "note": "Q159821 may actually be the International Olympic Committee, not the Games",
        "sparql": """\
SELECT ?label ?desc WHERE {
  wd:Q159821 rdfs:label ?label .
  OPTIONAL { wd:Q159821 schema:description ?desc . FILTER(LANG(?desc) = "en") }
  FILTER(LANG(?label) = "en")
}
LIMIT 3""",
    },
    {
        "id": "PROBE-05b",
        "label": "wd:Q8530 identity — possible correct QID for 'Olympic Games'",
        "note": "Q8530 is a candidate for the broader Olympic Games concept",
        "sparql": """\
SELECT ?label WHERE {
  wd:Q8530 rdfs:label ?label .
  FILTER(LANG(?label) = "en")
}
LIMIT 3""",
    },

    # ── Label-based player lookup sanity checks ───────────────────────────────
    {
        "id": "PROBE-06a",
        "label": "Messi birthplace via rdfs:label (config pattern verification)",
        "note": "Verifies the label-based lookup pattern from few_shot_examples",
        "sparql": """\
SELECT ?birthPlace ?birthPlaceLabel WHERE {
  ?player rdfs:label "Lionel Messi"@en .
  ?player wdt:P31 wd:Q5 .
  ?player wdt:P19 ?birthPlace .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}""",
    },
    {
        "id": "PROBE-06b",
        "label": "Mbappe current club via rdfs:label (config pattern verification)",
        "note": "Verifies label-based club lookup; also tests if Mbappe's club is up to date",
        "sparql": """\
SELECT ?team ?teamLabel WHERE {
  ?player rdfs:label "Kylian Mbappé"@en .
  ?player wdt:P31 wd:Q5 .
  ?player wdt:P54 ?team .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}""",
    },

    # ── Tennis player occupation QID identity ─────────────────────────────────
    {
        "id": "PROBE-07",
        "label": "wd:Q10833314 identity — config lists as 'tennis player'",
        "note": "Verify Q10833314 is correct occupation QID for tennis players",
        "sparql": """\
SELECT ?label WHERE {
  wd:Q10833314 rdfs:label ?label .
  FILTER(LANG(?label) = "en")
}
LIMIT 3""",
    },

    # ── Ice hockey player QID identity ───────────────────────────────────────
    {
        "id": "PROBE-08",
        "label": "wd:Q11774891 identity — config lists as 'ice hockey player'",
        "note": "Verify Q11774891 is correct occupation QID for ice hockey players",
        "sparql": """\
SELECT ?label WHERE {
  wd:Q11774891 rdfs:label ?label .
  FILTER(LANG(?label) = "en")
}
LIMIT 3""",
    },

    # ── Premier League QID identity ───────────────────────────────────────────
    {
        "id": "PROBE-09",
        "label": "wd:Q9448 identity — config lists as 'Premier League'",
        "note": "Verify Q9448 is correct QID for English Premier League",
        "sparql": """\
SELECT ?label WHERE {
  wd:Q9448 rdfs:label ?label .
  FILTER(LANG(?label) = "en")
}
LIMIT 3""",
    },
]


def load_config(path: Path) -> dict:
    with open(path) as fh:
        return yaml.safe_load(fh)


def _status_label(result: dict) -> str:
    if result["success"] and len(result.get("results", [])) > 0:
        return "PASS"
    if result["success"] and len(result.get("results", [])) == 0:
        return "EMPTY"
    return "FAIL"


def _first_rows(results: list, n: int = 3) -> str:
    lines = []
    for row in results[:n]:
        pairs = ", ".join(f"{k}={str(v)[:55]!r}" for k, v in list(row.items())[:4])
        lines.append(f"    {{ {pairs} }}")
    return "\n".join(lines) if lines else "    (no rows)"


def run_benchmark(config: dict, out_path: Path) -> None:
    domain   = config.get("domain_name", "Unknown")
    endpoint = config.get("endpoint", ENDPOINT)
    examples = config.get("few_shot_examples", [])

    run_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    results_main = []
    results_probes = []

    # ── Part 1: few_shot_examples ─────────────────────────────────────────────
    print(f"\n=== Part 1: few_shot_examples ({len(examples)} queries) ===")

    for i, ex in enumerate(examples, 1):
        question = ex.get("question", "?")
        tag      = ex.get("tag", "")
        sparql   = ex.get("sparql", "").strip()

        if not sparql:
            results_main.append({
                "n": i, "question": question, "tag": tag,
                "status": "SKIP", "rows": 0, "elapsed": 0.0,
                "error": "no SPARQL in config", "sample": "", "sparql": "",
            })
            continue

        time.sleep(DELAY)
        t0      = time.perf_counter()
        result  = sparql_executor.execute(sparql, endpoint)
        elapsed = time.perf_counter() - t0

        status = _status_label(result)
        rows   = len(result.get("results", []))
        error  = result.get("error") or ""
        sample = _first_rows(result.get("results", []))

        results_main.append({
            "n": i, "question": question, "tag": tag,
            "status": status, "rows": rows, "elapsed": elapsed,
            "error": error, "sample": sample, "sparql": sparql,
        })

        icon = {"PASS": "OK", "EMPTY": "!!", "FAIL": "XX", "SKIP": "--"}.get(status, "??")
        print(f"  [{icon}] ({i:02d}/{len(examples)}) [{tag:<9}] {question[:55]:<55}  "
              f"{rows:>4} rows  {elapsed:.2f}s")

    # ── Part 2: validation probes ─────────────────────────────────────────────
    print(f"\n=== Part 2: validation probes ({len(VALIDATION_PROBES)} queries) ===")

    for probe in VALIDATION_PROBES:
        time.sleep(DELAY)
        t0      = time.perf_counter()
        result  = sparql_executor.execute(probe["sparql"], ENDPOINT)
        elapsed = time.perf_counter() - t0

        status = _status_label(result)
        rows   = len(result.get("results", []))
        error  = result.get("error") or ""
        sample = _first_rows(result.get("results", []))

        results_probes.append({
            "id":      probe["id"],
            "label":   probe["label"],
            "note":    probe["note"],
            "status":  status,
            "rows":    rows,
            "elapsed": elapsed,
            "error":   error,
            "sample":  sample,
            "sparql":  probe["sparql"],
        })

        icon = {"PASS": "OK", "EMPTY": "!!", "FAIL": "XX"}.get(status, "??")
        print(f"  [{icon}] {probe['id']}  {probe['label'][:60]:<60}  "
              f"{rows:>4} rows  {elapsed:.2f}s")

    # ── Summaries ─────────────────────────────────────────────────────────────
    total_m  = len(results_main)
    passed_m = sum(1 for r in results_main if r["status"] == "PASS")
    empty_m  = sum(1 for r in results_main if r["status"] == "EMPTY")
    failed_m = sum(1 for r in results_main if r["status"] == "FAIL")
    skip_m   = sum(1 for r in results_main if r["status"] == "SKIP")
    acc_m    = (passed_m / total_m * 100) if total_m else 0.0
    avg_m    = sum(r["elapsed"] for r in results_main) / total_m if total_m else 0.0

    total_p  = len(results_probes)
    passed_p = sum(1 for r in results_probes if r["status"] == "PASS")
    empty_p  = sum(1 for r in results_probes if r["status"] == "EMPTY")

    # ── Write log ─────────────────────────────────────────────────────────────
    sep  = "=" * 80
    sep2 = "-" * 80

    lines = [
        sep,
        "  Sports (Wikidata) — Comprehensive Query Accuracy Benchmark",
        f"  Domain  : {domain}",
        f"  Endpoint: {endpoint}",
        f"  Run at  : {run_at}",
        sep,
        "",
        "SUMMARY — few_shot_examples",
        sep2,
        f"  Total queries : {total_m}",
        f"  PASS (>= 1 row): {passed_m}",
        f"  EMPTY (0 rows) : {empty_m}",
        f"  FAIL  (error)  : {failed_m}",
        f"  SKIP  (no SPARQL): {skip_m}",
        f"  Accuracy       : {acc_m:.1f}%  ({passed_m}/{total_m} returned results)",
        f"  Avg response   : {avg_m:.2f}s",
        "",
        "SUMMARY — validation probes",
        sep2,
        f"  Total probes   : {total_p}",
        f"  PASS (>= 1 row): {passed_p}",
        f"  EMPTY (0 rows) : {empty_p}",
        "",
        "DETAIL — few_shot_examples",
        sep2,
    ]

    for r in results_main:
        icon = {"PASS": "[PASS ]", "EMPTY": "[EMPTY]", "FAIL": "[FAIL ]",
                "SKIP": "[SKIP ]"}.get(r["status"], "[?????]")
        lines += [
            "",
            f"{icon}  #{r['n']:02d}  [{r['tag']}]  {r['question']}",
            f"  Rows: {r['rows']}   Time: {r['elapsed']:.2f}s",
        ]
        if r["status"] == "PASS":
            lines += ["  Sample output:", r["sample"]]
        elif r["status"] == "EMPTY":
            lines += ["  Query returned 0 rows — check entity/property QID in config."]
        elif r["status"] == "FAIL":
            lines += [f"  Error: {r['error']}"]
        if r.get("sparql"):
            lines += ["  SPARQL:",
                      *[f"    {ln}" for ln in r["sparql"].splitlines()]]

    lines += [
        "",
        sep2,
        "",
        "DETAIL — validation probes",
        sep2,
    ]

    for r in results_probes:
        icon = {"PASS": "[PASS ]", "EMPTY": "[EMPTY]", "FAIL": "[FAIL ]"}.get(r["status"], "[?????]")
        lines += [
            "",
            f"{icon}  {r['id']}",
            f"  Label   : {r['label']}",
            f"  Note    : {r['note']}",
            f"  Rows    : {r['rows']}   Time: {r['elapsed']:.2f}s",
        ]
        if r["status"] == "PASS":
            lines += ["  Sample output:", r["sample"]]
        elif r["status"] == "EMPTY":
            lines += ["  Returned 0 rows."]
        elif r["status"] == "FAIL":
            lines += [f"  Error: {r['error']}"]
        lines += ["  SPARQL:",
                  *[f"    {ln}" for ln in r["sparql"].splitlines()]]

    # ── Findings section ──────────────────────────────────────────────────────
    lines += ["", sep2, "", "FINDINGS & DIAGNOSIS", sep2, ""]

    def probe_rows(pid: str) -> int:
        for r in results_probes:
            if r["id"] == pid:
                return r["rows"]
        return -1

    def probe_sample(pid: str) -> str:
        for r in results_probes:
            if r["id"] == pid:
                return r["sample"]
        return ""

    # FIFA World Cup
    p1a = probe_rows("PROBE-01a")
    p1b = probe_rows("PROBE-01b")
    lines.append("FIFA World Cup property (PROBE-01a vs PROBE-01b):")
    lines.append(f"  wdt:P3450 (current config) returned {p1a} rows")
    lines.append(f"  wdt:P31   (notes.md fix)   returned {p1b} rows")
    if p1b > p1a:
        lines.append("  FINDING: wdt:P31 returns more results — config few_shot should be updated.")
    elif p1a == 0 and p1b == 0:
        lines.append("  FINDING: both variants return 0 rows — endpoint may be timing out.")
    else:
        lines.append("  FINDING: both return similar counts — either property may work.")
    lines.append("")

    # Olympic gold medal
    p2a = probe_rows("PROBE-02a")
    p2b = probe_rows("PROBE-02b")
    p2c = probe_rows("PROBE-02c")
    lines.append("Olympic gold medal QID (PROBE-02a/b/c):")
    lines.append(f"  wd:Q15243387 (current config) returned {p2a} rows")
    lines.append(f"  wd:Q319921   (notes.md suggestion) returned {p2b} rows")
    lines.append(f"  P279* hierarchy (broadest) returned {p2c} rows")
    if p2a == 0 and p2b > 0:
        lines.append("  FINDING: Q15243387 is wrong — config should use wd:Q319921.")
    elif p2a == 0 and p2b == 0 and p2c > 0:
        lines.append("  FINDING: Q15243387 and Q319921 both fail; P279* subclass pattern needed.")
    elif p2a == 0:
        lines.append("  FINDING: Q15243387 returns 0 rows — the QID in config is incorrect.")
    else:
        lines.append("  FINDING: Q15243387 works; no immediate change required.")
    lines.append("")

    # Manchester City
    p3a = probe_rows("PROBE-03a")
    p3b = probe_rows("PROBE-03b")
    p3c = probe_rows("PROBE-03c")
    p3d = probe_rows("PROBE-03d")
    s3a = probe_sample("PROBE-03a")
    s3b = probe_sample("PROBE-03b")
    lines.append("Manchester City QID (PROBE-03a/b/c/d):")
    lines.append(f"  wd:Q18602070 label: {s3a.strip()}")
    lines.append(f"  wd:Q503       label: {s3b.strip()}")
    lines.append(f"  Players via Q18602070: {p3c} rows")
    lines.append(f"  Players via Q503     : {p3d} rows")
    if p3c == 0 and p3d > 0:
        lines.append("  FINDING: Q18602070 is wrong — config should use wd:Q503 for Manchester City FC.")
    elif "Manchester City" in s3b and "Manchester City" not in s3a:
        lines.append("  FINDING: Q18602070 is not Manchester City FC — config QID is incorrect.")
    else:
        lines.append("  FINDING: review label output above to confirm which QID is correct.")
    lines.append("")

    # Basketball
    p4a = probe_rows("PROBE-04a")
    p4b = probe_rows("PROBE-04b")
    lines.append("Basketball player pattern (PROBE-04a vs PROBE-04b):")
    lines.append(f"  wdt:P641 / sport=basketball (current config): {p4a} rows")
    lines.append(f"  wdt:P106 / occupation=basketball player    : {p4b} rows")
    if p4b > 0 and p4a > 0:
        lines.append("  FINDING: both work, but wdt:P106 is more consistent with football/tennis approach.")
    elif p4b > 0 and p4a == 0:
        lines.append("  FINDING: wdt:P641 fails — switch to wdt:P106 wd:Q3665646.")
    else:
        lines.append("  FINDING: both return results; occupation (P106) preferred for consistency.")
    lines.append("")

    # Olympic Games entity
    p5  = probe_rows("PROBE-05")
    p5b = probe_rows("PROBE-05b")
    s5  = probe_sample("PROBE-05")
    s5b = probe_sample("PROBE-05b")
    lines.append("Olympic Games entity QID (PROBE-05 / PROBE-05b):")
    lines.append(f"  wd:Q159821 label: {s5.strip()}")
    lines.append(f"  wd:Q8530   label: {s5b.strip()}")
    if "International Olympic Committee" in s5 or "IOC" in s5:
        lines.append("  FINDING: Q159821 is the IOC, NOT the Olympic Games — config is incorrect.")
        lines.append("           Use wd:Q8530 (Olympic Games) or wd:Q5389 (Summer Olympics).")
    else:
        lines.append("  FINDING: review label above to confirm entity identity.")
    lines.append("")

    lines += [
        "",
        sep,
        f"  End of log — {run_at}",
        sep,
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nLog written to: {out_path}")
    print(f"few_shot accuracy: {acc_m:.1f}%  "
          f"(pass={passed_m} empty={empty_m} fail={failed_m} skip={skip_m})")
    print(f"probe results   : pass={passed_p} empty={empty_p} "
          f"fail={sum(1 for r in results_probes if r['status']=='FAIL')}")


def main():
    parser = argparse.ArgumentParser(description="Sports Wikidata query benchmark")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output log path")
    args = parser.parse_args()
    config = load_config(CONFIG_PATH)
    run_benchmark(config, args.out)


if __name__ == "__main__":
    main()
