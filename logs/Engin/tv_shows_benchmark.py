"""
TV Shows (DBpedia) — Query Accuracy Benchmark
==============================================
Runs every few_shot_examples query from configs/dbpedia_tv_shows.yaml
against the live DBpedia SPARQL endpoint and writes a structured log.

Usage:
    python logs/tv_shows_benchmark.py
    python logs/tv_shows_benchmark.py --out logs/tv_shows_accuracy.log
"""

import sys
import time
import argparse
import yaml
from pathlib import Path
from datetime import datetime, timezone

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src import sparql_executor

CONFIG_PATH = Path(__file__).parent.parent.parent / "configs" / "dbpedia_tv_shows.yaml"
DEFAULT_OUT  = Path(__file__).parent / "tv_shows_accuracy.log"

DBPEDIA_DELAY = 1.0  # seconds between requests — respect DBpedia fair-use


def load_config(path: Path) -> dict:
    with open(path) as fh:
        return yaml.safe_load(fh)


def _status_label(result: dict) -> str:
    if result["success"] and len(result["results"]) > 0:
        return "PASS"
    if result["success"] and len(result["results"]) == 0:
        return "EMPTY"
    return "FAIL"


def _first_rows(results: list, n: int = 3) -> str:
    lines = []
    for row in results[:n]:
        pairs = ", ".join(f"{k}={v[:60]!r}" for k, v in list(row.items())[:3])
        lines.append(f"    {{ {pairs} }}")
    return "\n".join(lines) if lines else "    (no rows)"


def run_benchmark(config: dict, out_path: Path) -> None:
    domain   = config.get("domain_name", "Unknown")
    endpoint = config.get("endpoint", "")
    examples = config.get("few_shot_examples", [])

    run_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    results_data = []

    print(f"Running {len(examples)} queries against {endpoint} ...")

    for i, ex in enumerate(examples, 1):
        question = ex.get("question", "?")
        tag      = ex.get("tag", "")
        sparql   = ex.get("sparql", "").strip()

        if not sparql:
            results_data.append({
                "n": i, "question": question, "tag": tag,
                "status": "SKIP", "rows": 0, "elapsed": 0.0,
                "error": "no SPARQL in config", "sample": "",
            })
            continue

        time.sleep(DBPEDIA_DELAY)
        t0     = time.perf_counter()
        result = sparql_executor.execute(sparql, endpoint)
        elapsed = time.perf_counter() - t0

        status = _status_label(result)
        rows   = len(result.get("results", []))
        error  = result.get("error") or ""
        sample = _first_rows(result.get("results", []))

        results_data.append({
            "n": i, "question": question, "tag": tag,
            "status": status, "rows": rows, "elapsed": elapsed,
            "error": error, "sample": sample, "sparql": sparql,
        })

        icon = {"PASS": "OK", "EMPTY": "!!", "FAIL": "XX", "SKIP": "--"}.get(status, "??")
        print(f"  [{icon}] ({i:02d}/{len(examples)}) {tag:<12} {question[:55]:<55}  "
              f"{rows:>4} rows  {elapsed:.2f}s")

    # Compute summary
    total = len(results_data)
    passed = sum(1 for r in results_data if r["status"] == "PASS")
    empty  = sum(1 for r in results_data if r["status"] == "EMPTY")
    failed = sum(1 for r in results_data if r["status"] == "FAIL")
    skipped = sum(1 for r in results_data if r["status"] == "SKIP")
    accuracy = (passed / total * 100) if total else 0.0
    avg_time = sum(r["elapsed"] for r in results_data) / total if total else 0.0

    # Write log
    sep  = "=" * 78
    sep2 = "-" * 78

    lines = [
        sep,
        f"  TV Shows (DBpedia) — Query Accuracy Log",
        f"  Domain  : {domain}",
        f"  Endpoint: {endpoint}",
        f"  Run at  : {run_at}",
        sep,
        "",
        "SUMMARY",
        sep2,
        f"  Total queries  : {total}",
        f"  PASS  (>= 1 row): {passed}",
        f"  EMPTY (0 rows)  : {empty}",
        f"  FAIL  (error)   : {failed}",
        f"  SKIP  (no SPARQL): {skipped}",
        f"  Accuracy        : {accuracy:.1f}%  ({passed}/{total} queries returned results)",
        f"  Avg response    : {avg_time:.2f}s",
        "",
        "DETAIL",
        sep2,
    ]

    for r in results_data:
        icon  = {"PASS": "[PASS ]", "EMPTY": "[EMPTY]", "FAIL": "[FAIL ]", "SKIP": "[SKIP ]"}.get(r["status"], "[?????]")
        lines += [
            f"",
            f"{icon}  #{r['n']:02d}  [{r['tag']}]  {r['question']}",
            f"  Rows: {r['rows']}   Time: {r['elapsed']:.2f}s",
        ]
        if r["status"] == "PASS":
            lines += [f"  Sample output:", r["sample"]]
        elif r["status"] == "EMPTY":
            lines += [f"  Query executed but returned 0 rows — check class/predicate URI."]
        elif r["status"] == "FAIL":
            lines += [f"  Error: {r['error']}"]
        if r.get("sparql"):
            lines += [
                f"  SPARQL:",
                *[f"    {ln}" for ln in r["sparql"].splitlines()],
            ]

    lines += [
        "",
        sep,
        f"  End of log — {run_at}",
        sep,
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nLog written to: {out_path}")
    print(f"Accuracy: {accuracy:.1f}%  ({passed} pass / {empty} empty / {failed} fail / {skipped} skip)")


def main():
    parser = argparse.ArgumentParser(description="TV Shows DBpedia query benchmark")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output log path")
    args = parser.parse_args()

    config = load_config(CONFIG_PATH)
    run_benchmark(config, args.out)


if __name__ == "__main__":
    main()
