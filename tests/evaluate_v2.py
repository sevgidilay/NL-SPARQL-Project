"""
Advanced Evaluation Framework v2.4 for NL-SPARQL Translation
============================================================
Extends v1 (execution + component + BLEU) with **semantic correctness**.

NEW METRICS in v2:
1. Result Set Match (RSM): Compare result sets of gold vs generated query.
   - rsm_precision, rsm_recall, rsm_f1, rsm_jaccard, rsm_exact_match
2. Ground Truth Coverage (GTC): Did the response contain the URIs/labels
   we know MUST be there? (e.g. "Who wrote 1984?" -> George_Orwell)
3. LLM-as-a-Judge (Judge): A separate model rates relevance/correctness/
   completeness on 0–5 and returns a verdict {CORRECT, PARTIAL, INCORRECT}.
4. Composite Quality Score (CQS): Weighted aggregate of all metrics.

v2.1 revisions:
- chat() called with raw prompt first, messages-list as fallback (was reversed).
- Gold query failures no longer punish RSM: tracked via gold_execution_success
  and rsm_skipped flag; CQS reweights when RSM is unavailable.
- Result-set comparison prefers URI-typed cells over arbitrary first-variable.
- GTC uses word-boundary matching to reduce substring false positives.
- Self-judging is auto-disabled when no distinct judge model is available.

v2.2 revisions:
- Test set expanded from 16 to 32 cases across 4 categories:
    baseline, extended, robustness, cross_domain.
- Aggregate cases (COUNT) carry rsm_applicable=False so RSM is skipped.
- Category auto-derived from ID prefix; summary, comparison, and markdown
  report all break results down per-category.

v2.3 revisions:
- Coverage extended to ALL 10 domain configs (was 6/10):
    + TV Shows (DBpedia)               TV01–TV03
    + Geography (Wikidata)             G01–G03
    + Scientists & Nobel Prizes        S01–S03
    + Music (Wikidata)                 MU01–MU03
- BUG FIX: A01 and F04 used `wdt:P31 wd:Q634` for Solar System planets, which
  the Astronomy YAML explicitly warns returns 0 results. Both now use the
  property path `wdt:P31/wdt:P279* wd:Q634 . ?planet wdt:P397 wd:Q525`.
- Total cases: 44 (28 baseline / 6 robustness / 8 extended / 2 cross_domain).

v2.4 revisions:
- Endpoint robustness: every SPARQL execution now goes through
  execute_with_retry(), which retries on transient errors (timeouts,
  502/503/504, connection resets) with linear backoff. Non-transient
  errors (syntax, bad URIs) are returned immediately without retry.
- New CLI flags: --timeout (default 60s), --retries (default 2),
  --retry-delay (default 3s).
- Best-effort monkey-patch of sparql_executor's hardcoded timeout via
  common attribute names (REQUEST_TIMEOUT, TIMEOUT, etc.). Falls back to
  retry if no settable attribute exists.
- Per-case diagnostics now record gen_retries / gold_retries counts.
- BUG FIX: B01 ("List 10 novels") now uses dbo:WrittenWork + dct:subject
  CONTAINS "novel" pattern (matches the Books YAML's own few-shot example).
  The previous gold relied on dbo:Novel which yields very few rows on
  current DBpedia, causing unfair RSM=0 scoring even for correct queries.

KEPT FROM v1:
- Execution Accuracy (EA), Result Accuracy (RA), Component F1, BLEU.

USAGE
-----
python tests/evaluate_v2.py \
    --models "HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct" \
    --judge  "HuggingFace: meta-llama/Meta-Llama-3-8B-Instruct" \
    --save   results_v2.json --report report_v2.md

Flags:
  --models   Comma-separated list of models under test.
  --judge    Judge model (defaults to first model NOT in --models).
  --domain   Filter by single domain.
  --quick    First 2 cases per domain only.
  --no-judge Skip the LLM-as-a-Judge step (faster).
  --save     Save full JSON results.
  --report   Save Markdown report.
"""

import os, sys, json, time, math, yaml, glob, argparse, re
from datetime import datetime
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src import llm_client, nl_to_sparql, sparql_executor


# ───────────────────────── v1 metrics (kept) ─────────────────────────

def compute_bleu(reference, hypothesis, max_n=4):
    def tokenize(t): return re.findall(r'\w+|[^\s\w]', t.lower())
    ref, hyp = tokenize(reference), tokenize(hypothesis)
    if not hyp: return 0.0
    bp = 1.0 if len(hyp) >= len(ref) else math.exp(1 - len(ref)/max(len(hyp),1))
    precs = []
    for n in range(1, max_n+1):
        rng = Counter(tuple(ref[i:i+n]) for i in range(len(ref)-n+1))
        hng = Counter(tuple(hyp[i:i+n]) for i in range(len(hyp)-n+1))
        clip = sum(min(hng[g], rng[g]) for g in hng)
        total = sum(hng.values())
        precs.append(clip/total if total else 0)
    log_avg = 0
    for p in precs:
        if p == 0: return 0.0
        log_avg += math.log(p)/max_n
    return bp * math.exp(log_avg)


def compute_component_f1(expected, sparql):
    if not expected: return {"precision":1,"recall":1,"f1":1,"found":[],"missing":[]}
    low = sparql.lower()
    found = [c for c in expected if c.lower() in low]
    missing = [c for c in expected if c.lower() not in low]
    rec = len(found)/len(expected)
    return {"precision":round(rec,4),"recall":round(rec,4),"f1":round(rec,4),
            "found":found,"missing":missing}


# ───────── transient-error retry wrapper for SPARQL endpoints ─────────
# Public Wikidata/DBpedia endpoints regularly return:
#   - "Query timed out (30s limit)"  when the query is heavy
#   - HTTP 502/503/504              when the endpoint is overloaded
#   - connection resets             during deploys / brief outages
# These are not model errors; they should not count as model failures.
# We retry with linear backoff and report the final outcome.

# Error substrings (case-insensitive) we treat as transient & retryable.
_TRANSIENT_PATTERNS = (
    "timed out","timeout","time-out",
    "502","503","504","temporarily","unavailable",
    "connection","reset","refused","gateway","overloaded",
)

def _is_transient(err_text):
    if not err_text: return False
    e = str(err_text).lower()
    return any(p in e for p in _TRANSIENT_PATTERNS)


def _try_raise_executor_timeout(seconds):
    """Best-effort monkey-patch of the SPARQL executor's hardcoded timeout.
    Returns the attribute name that was set, or None if nothing matched.
    The user's src/sparql_executor.py uses timeout=30 as a literal; if the
    module exposes a settable constant, we lift it. Otherwise our retry
    wrapper still catches the eventual transient failures."""
    for attr in ("REQUEST_TIMEOUT","TIMEOUT","DEFAULT_TIMEOUT",
                 "HTTP_TIMEOUT","SPARQL_TIMEOUT","QUERY_TIMEOUT"):
        if hasattr(sparql_executor, attr):
            try:
                setattr(sparql_executor, attr, seconds)
                return attr
            except Exception:
                continue
    return None


def execute_with_retry(query, endpoint, max_attempts=2, base_delay=3):
    """Wrapper around sparql_executor.execute() with retry on transient errors.

    Keeps the original return shape: {"success": bool, "results": list, "error": str}.
    Only the final attempt's error survives; intermediate retry attempts are
    recorded in res["retry_log"] for diagnostics."""
    attempts = []
    last = None
    for i in range(1, max_attempts + 1):
        try:
            res = sparql_executor.execute(query, endpoint)
            if res.get("success"):
                if attempts: res["retry_log"] = attempts
                return res
            err = res.get("error","") or ""
            attempts.append(f"attempt {i}: {err[:120]}")
            if not _is_transient(err):
                # Non-transient (syntax error, bad URI, etc.) — don't retry.
                if attempts: res["retry_log"] = attempts
                return res
            last = res
        except Exception as e:
            err = str(e)
            attempts.append(f"attempt {i} raised: {err[:120]}")
            last = {"success": False, "error": err, "results": []}
            if not _is_transient(err):
                last["retry_log"] = attempts
                return last
        if i < max_attempts:
            time.sleep(base_delay * i)  # 3s, 6s, ...
    if last is None:
        last = {"success": False, "error": "no attempts made", "results": []}
    last["retry_log"] = attempts
    return last


# ───────────────────────── new: result-set metrics ─────────────────────────

def _is_uri_like(s):
    if not isinstance(s, str): return False
    s = s.strip()
    return s.startswith("http://") or s.startswith("https://") or s.startswith("urn:")


def _row_cells(row):
    """Yield raw scalar values from a result row, regardless of binding format."""
    if not isinstance(row, dict): return
    for v in row.values():
        if isinstance(v, dict) and "value" in v: yield v["value"]
        else: yield v


def _extract_values_smart(rows):
    """Build a comparable set of values from a result list.
    Strategy: prefer URI cells (most discriminative). If a row has no URI,
    fall back to its non-empty scalar cells. All values lower-cased.
    This is robust to variable-order changes between gold and generated."""
    if not rows: return set()
    out = set()
    for row in rows:
        cells = [str(c).strip() for c in _row_cells(row) if c is not None and str(c).strip()]
        if not cells: continue
        uris = [c for c in cells if _is_uri_like(c)]
        chosen = uris if uris else cells
        for c in chosen: out.add(c.lower())
    return out


def _extract_primary_uris(rows):
    """Kept for backward compatibility; delegates to the smarter extractor."""
    return _extract_values_smart(rows)


def compute_result_set_metrics(gold_rows, gen_rows, gold_success=True):
    """If gold_success=False, RSM is marked skipped so it does not unfairly
    penalize the model under test for endpoint flakiness."""
    if not gold_success:
        return {"rsm_precision":0,"rsm_recall":0,"rsm_f1":0,"rsm_jaccard":0,
                "rsm_exact_match":False,"gold_size":0,"gen_size":len(gen_rows or []),
                "overlap":0,"rsm_skipped":True}
    G = _extract_values_smart(gold_rows)
    A = _extract_values_smart(gen_rows)
    if not G and not A:
        return {"rsm_precision":1,"rsm_recall":1,"rsm_f1":1,"rsm_jaccard":1,
                "rsm_exact_match":True,"gold_size":0,"gen_size":0,"overlap":0,
                "rsm_skipped":False}
    inter = G & A
    union = G | A
    p = len(inter)/len(A) if A else 0.0
    r = len(inter)/len(G) if G else 0.0
    f1 = 2*p*r/(p+r) if (p+r) else 0.0
    jac = len(inter)/len(union) if union else 0.0
    return {"rsm_precision":round(p,4),"rsm_recall":round(r,4),"rsm_f1":round(f1,4),
            "rsm_jaccard":round(jac,4),"rsm_exact_match":(G==A and len(G)>0),
            "gold_size":len(G),"gen_size":len(A),"overlap":len(inter),
            "rsm_skipped":False}


# ───────────────────────── new: ground-truth coverage ─────────────────────────

def compute_ground_truth_coverage(expected_answers, rows):
    """expected_answers is a list of substrings (URI fragments or labels).
    A token is considered present if it appears as a whole word/identifier
    inside any cell of the result set. Word-boundary matching reduces
    false positives compared to plain substring containment."""
    if not expected_answers:
        return {"gtc_score":1.0,"gtc_found":[],"gtc_missing":[],"gtc_skipped":True}
    haystack = json.dumps(rows, default=str).lower()
    found, missing = [], []
    for tok in expected_answers:
        t = tok.lower()
        # \b treats letters/digits/underscore as word chars, which matches
        # how DBpedia URI fragments (Christopher_Nolan) and Wikidata IDs
        # (Q9312) behave naturally.
        pattern = r'(?<!\w)' + re.escape(t) + r'(?!\w)'
        if re.search(pattern, haystack): found.append(tok)
        else: missing.append(tok)
    score = len(found)/len(expected_answers)
    return {"gtc_score":round(score,4),"gtc_found":found,"gtc_missing":missing,
            "gtc_skipped":False}


# ───────────────────────── new: LLM-as-a-judge ─────────────────────────

JUDGE_PROMPT = """You are an expert evaluator of SPARQL query results against natural language questions. Your job is to decide whether the returned data actually answers the user's question correctly.

Question:
{question}

Generated SPARQL query:
```sparql
{sparql}
```

Sample of returned results (up to 10 rows, JSON):
{sample}

Reference (gold) SPARQL for context:
```sparql
{gold}
```

Rate the answer on three independent 0–5 axes:
- relevance      : do the returned items belong to the type the user asked for?
- correctness    : are the specific values factually right (no wrong entities, no nonsense)?
- completeness   : does the result cover the scope implied by the question?

Then give a single verdict in {{CORRECT, PARTIAL, INCORRECT}}.

Return ONLY a single valid JSON object on one line, no prose, no code fences:
{{"relevance": <int 0-5>, "correctness": <int 0-5>, "completeness": <int 0-5>, "verdict": "<CORRECT|PARTIAL|INCORRECT>", "reasoning": "<one short sentence>"}}"""


ROW_JUDGE_PROMPT = """You are an expert evaluator checking whether individual rows returned by a SPARQL query correctly answer a natural language question.

Question:
{question}

Reference (gold) result rows (up to 10, JSON):
{gold_sample}

Generated result rows to evaluate (numbered):
{numbered_rows}

For EACH numbered row, decide:
- CORRECT  : the row is a valid, factually accurate answer to the question
- INCORRECT: the row is wrong, irrelevant, or does not answer the question

Return ONLY a single valid JSON array, one object per row, no prose, no code fences:
[{{"row": 1, "verdict": "CORRECT", "reason": "<one short phrase>"}},
 {{"row": 2, "verdict": "INCORRECT", "reason": "<one short phrase>"}},
 ...]"""


def _call_llm_raw(prompt, model):
    """Best-effort raw LLM call. Tries common interfaces on llm_client.
    For chat()-style helpers, tries plain-string first, then messages-list,
    because llm_client.chat() in this project takes a raw prompt string."""
    for fn_name in ("generate","complete","ask","query","completion"):
        fn = getattr(llm_client, fn_name, None)
        if callable(fn):
            try: return fn(prompt, model=model)
            except TypeError:
                try: return fn(prompt, model)
                except Exception: continue
            except Exception: continue
    chat = getattr(llm_client, "chat", None)
    if callable(chat):
        # Try string-prompt signatures first (matches llm_client.chat in this repo).
        try: return chat(prompt, model=model)
        except TypeError:
            try: return chat(prompt, model)
            except Exception: pass
        except Exception: pass
        # Fall back to messages-list signatures (OpenAI-style clients).
        msgs = [{"role":"user","content":prompt}]
        try: return chat(msgs, model=model)
        except TypeError:
            try: return chat(msgs, model)
            except Exception: pass
        except Exception: pass
    raise RuntimeError(
        "No usable LLM call found on llm_client. "
        "Expose a generate(prompt, model=...) or chat(prompt, model=...) helper.")


def _parse_judge_json(text):
    if not text: return None
    # Strip code fences and grab the first {...} block.
    m = re.search(r'\{[^{}]*"verdict"[^{}]*\}', text, re.DOTALL)
    if not m:
        m = re.search(r'\{.*\}', text, re.DOTALL)
    if not m: return None
    blob = m.group(0)
    blob = re.sub(r',\s*}', '}', blob)  # tolerate trailing commas
    try: return json.loads(blob)
    except Exception: return None


def _parse_row_judge_json(text):
    """Parse a JSON array of per-row verdicts from LLM response.
    Strips code fences; returns list of dicts or None on failure."""
    if not text: return None
    # Strip markdown code fences if present
    text = re.sub(r'```[^\n]*\n?', '', text).strip()
    m = re.search(r'\[.*\]', text, re.DOTALL)
    if not m: return None
    blob = m.group(0)
    blob = re.sub(r',\s*]', ']', blob)   # tolerate trailing commas
    blob = re.sub(r',\s*}', '}', blob)
    try:
        parsed = json.loads(blob)
        if isinstance(parsed, list): return parsed
    except Exception:
        pass
    return None


def llm_judge(question, sparql, results, gold_sparql, judge_model):
    """Returns dict with relevance/correctness/completeness/verdict/reasoning,
    plus a normalized judge_score in [0,1]. On failure, judge_skipped=True."""
    sample = results[:10] if isinstance(results, list) else results
    try: sample_str = json.dumps(sample, default=str, indent=2)[:3000]
    except Exception: sample_str = str(sample)[:3000]
    prompt = JUDGE_PROMPT.format(question=question, sparql=sparql,
                                 sample=sample_str, gold=gold_sparql)
    try:
        raw = _call_llm_raw(prompt, judge_model)
    except Exception as e:
        return {"judge_skipped":True,"judge_error":str(e)[:200],"judge_score":0,
                "verdict":"UNKNOWN","reasoning":""}
    parsed = _parse_judge_json(raw or "")
    if not parsed:
        return {"judge_skipped":True,"judge_error":"parse_failed",
                "judge_raw":(raw or "")[:300],"judge_score":0,
                "verdict":"UNKNOWN","reasoning":""}
    try:
        rel = max(0,min(5,int(parsed.get("relevance",0))))
        cor = max(0,min(5,int(parsed.get("correctness",0))))
        com = max(0,min(5,int(parsed.get("completeness",0))))
    except Exception:
        rel = cor = com = 0
    avg = (rel+cor+com)/3.0
    norm = round(avg/5.0, 4)
    verdict = str(parsed.get("verdict","UNKNOWN")).upper().strip()
    if verdict not in ("CORRECT","PARTIAL","INCORRECT"): verdict = "UNKNOWN"
    return {"judge_skipped":False,"relevance":rel,"correctness":cor,
            "completeness":com,"judge_score":norm,"verdict":verdict,
            "reasoning":str(parsed.get("reasoning",""))[:300]}


def llm_judge_rows(question, gen_rows, gold_rows, judge_model, max_rows=10):
    """Row-level LLM judge: evaluates each generated row individually.

    Returns a dict suitable for r.update():
      row_verdicts      list of {"row":int, "verdict":"CORRECT"|"INCORRECT", "reason":str}
      row_precision     float  correct_count / total_judged
      row_judge_correct int
      row_judge_total   int
      row_judge_skipped bool   True on any error
      row_judge_error   str    set when skipped
    """
    _skip = {"row_verdicts": [], "row_precision": 0.0,
             "row_judge_correct": 0, "row_judge_total": 0,
             "row_judge_skipped": True}

    rows_to_judge = (gen_rows or [])[:max_rows]
    if not rows_to_judge:
        return {**_skip, "row_judge_error": "no_rows"}

    try:
        gold_str = json.dumps((gold_rows or [])[:10], default=str, indent=2)[:2000]
    except Exception:
        gold_str = str((gold_rows or [])[:10])[:2000]

    numbered = []
    for i, row in enumerate(rows_to_judge, 1):
        try:
            numbered.append(f"{i}. {json.dumps(row, default=str)}")
        except Exception:
            numbered.append(f"{i}. {str(row)}")
    numbered_str = "\n".join(numbered)

    prompt = ROW_JUDGE_PROMPT.format(
        question=question,
        gold_sample=gold_str,
        numbered_rows=numbered_str,
    )
    try:
        raw = _call_llm_raw(prompt, judge_model)
    except Exception as e:
        return {**_skip, "row_judge_error": str(e)[:200]}

    parsed = _parse_row_judge_json(raw or "")
    if not parsed:
        return {**_skip, "row_judge_error": "parse_failed",
                "row_judge_raw": (raw or "")[:300]}

    verdicts = []
    correct = 0
    for entry in parsed:
        if not isinstance(entry, dict): continue
        v = str(entry.get("verdict", "")).upper().strip()
        if v not in ("CORRECT", "INCORRECT"): v = "INCORRECT"
        row_num = int(entry.get("row", 0))
        reason = str(entry.get("reason", ""))[:200]
        verdicts.append({"row": row_num, "verdict": v, "reason": reason})
        if v == "CORRECT": correct += 1

    total = len(verdicts)
    precision = round(correct / total, 4) if total else 0.0
    return {"row_verdicts": verdicts, "row_precision": precision,
            "row_judge_correct": correct, "row_judge_total": total,
            "row_judge_skipped": False}


# ───────────────────────── composite quality score ─────────────────────────

# Weights chosen so semantic signals outweigh syntactic ones.
# If a metric is skipped, its weight is redistributed proportionally
# across the remaining metrics so the score stays in [0, 1].
W_FULL = {"ea":0.10,"ra":0.10,"comp_f1":0.10,"rsm_f1":0.30,"gtc":0.15,"judge":0.25}
W_NO_JUDGE = {"ea":0.10,"ra":0.10,"comp_f1":0.15,"rsm_f1":0.45,"gtc":0.20,"judge":0.0}

def composite_score(r):
    base = W_NO_JUDGE if r.get("judge_skipped",True) else dict(W_FULL)
    weights = dict(base)
    contribs = {
        "ea":      1.0 if r["execution_accuracy"] else 0.0,
        "ra":      1.0 if r["result_accuracy"] else 0.0,
        "comp_f1": float(r.get("component_f1",0)),
        "rsm_f1":  float(r.get("rsm_f1",0)),
        "gtc":     float(r.get("gtc_score",0)),
        "judge":   float(r.get("judge_score",0)),
    }
    # Drop weights of metrics that were skipped (gold failed, no GT, no judge).
    if r.get("rsm_skipped",False): weights["rsm_f1"] = 0.0
    if r.get("gtc_skipped",True):  weights["gtc"]    = 0.0
    if r.get("judge_skipped",True):weights["judge"]  = 0.0
    total_w = sum(weights.values())
    if total_w <= 0: return 0.0
    s = sum(weights[k]*contribs[k] for k in weights)
    return round(s/total_w, 4)


# ───────────────────────── gold standard (extended) ─────────────────────────
# Each case may now carry `expected_answers` (URI fragments or labels that
# MUST appear in the answer set). Empty list => GTC is skipped for that case.

GOLD_STANDARD = [
    {"id":"D01","domain":"Diseases","complexity":"simple","question":"List 10 diseases",
     "gold_sparql":"SELECT DISTINCT ?disease ?diseaseLabel WHERE { ?disease wdt:P31 wd:Q12136 . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } } LIMIT 10",
     "expected_components":["wdt:P31","wd:Q12136","LIMIT"],"min_results":5,
     "expected_answers":[]},
    {"id":"D02","domain":"Diseases","complexity":"simple","question":"What are the symptoms of diabetes?",
     "gold_sparql":"SELECT DISTINCT ?symptom ?symptomLabel WHERE { wd:Q12206 wdt:P780 ?symptom . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } }",
     "expected_components":["wdt:P780","wd:Q12206"],"min_results":1,
     "expected_answers":[]},
    {"id":"D03","domain":"Diseases","complexity":"simple","question":"Which drugs are used to treat malaria?",
     "gold_sparql":"SELECT DISTINCT ?drug ?drugLabel WHERE { wd:Q12156 wdt:P2176 ?drug . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } }",
     "expected_components":["wdt:P2176","wd:Q12156"],"min_results":1,
     "expected_answers":[]},
    {"id":"D04","domain":"Diseases","complexity":"medium","question":"List diseases with their ICD-10 codes",
     "gold_sparql":"SELECT DISTINCT ?disease ?diseaseLabel ?icd WHERE { ?disease wdt:P31 wd:Q12136 . ?disease wdt:P494 ?icd . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } } LIMIT 20",
     "expected_components":["wdt:P31","wd:Q12136","wdt:P494"],"min_results":3,
     "expected_answers":[]},
    {"id":"D05","domain":"Diseases","complexity":"complex","question":"Which diseases are caused by bacteria?",
     "gold_sparql":"SELECT DISTINCT ?disease ?diseaseLabel WHERE { ?disease wdt:P31 wd:Q12136 . ?disease wdt:P828 ?agent . ?agent wdt:P31 wd:Q10876 . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } } LIMIT 20",
     "expected_components":["wdt:P828","wd:Q10876","wdt:P31","wd:Q12136"],"min_results":1,
     "expected_answers":[]},
    {"id":"M01","domain":"Movies (DBpedia)","complexity":"simple","question":"List 10 movies",
     "gold_sparql":"SELECT DISTINCT ?film ?name WHERE { ?film a dbo:Film . ?film rdfs:label ?name . FILTER(LANG(?name) = \"en\") } LIMIT 10",
     "expected_components":["dbo:Film","rdfs:label","FILTER","LIMIT"],"min_results":5,
     "expected_answers":[]},
    {"id":"M02","domain":"Movies (DBpedia)","complexity":"simple","question":"List movies directed by Steven Spielberg",
     "gold_sparql":"SELECT DISTINCT ?film ?name WHERE { ?film a dbo:Film . ?film dbo:director dbr:Steven_Spielberg . ?film rdfs:label ?name . FILTER(LANG(?name) = \"en\") }",
     "expected_components":["dbo:Film","dbo:director","Steven_Spielberg"],"min_results":1,
     "expected_answers":["Jurassic_Park","Schindler"]},
    {"id":"M03","domain":"Movies (DBpedia)","complexity":"medium","question":"Who directed Inception?",
     "gold_sparql":"SELECT DISTINCT ?director ?name WHERE { dbr:Inception dbo:director ?director . ?director rdfs:label ?name . FILTER(LANG(?name) = \"en\") }",
     "expected_components":["dbo:director","Inception"],"min_results":1,
     "expected_answers":["Christopher_Nolan","Nolan"]},
    {"id":"A01","domain":"Astronomy (Wikidata)","complexity":"simple","question":"List all planets in our Solar System",
     "gold_sparql":"SELECT DISTINCT ?planet ?planetLabel WHERE { ?planet wdt:P31/wdt:P279* wd:Q634 . ?planet wdt:P397 wd:Q525 . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } }",
     "expected_components":["wd:Q634","wd:Q525","wdt:P397"],"min_results":5,
     "expected_answers":["Q308","Q313","Q319"]},  # Mercury, Venus, Jupiter
    {"id":"A02","domain":"Astronomy (Wikidata)","complexity":"simple","question":"List 10 galaxies",
     "gold_sparql":"SELECT DISTINCT ?galaxy ?galaxyLabel WHERE { ?galaxy wdt:P31 wd:Q318 . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } } LIMIT 10",
     "expected_components":["wdt:P31","wd:Q318","LIMIT"],"min_results":5,
     "expected_answers":[]},
    {"id":"A03","domain":"Astronomy (Wikidata)","complexity":"medium","question":"Which moons orbit Jupiter?",
     "gold_sparql":"SELECT DISTINCT ?moon ?moonLabel WHERE { ?moon wdt:P31 wd:Q25257 . ?moon wdt:P397 wd:Q319 . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } }",
     "expected_components":["wd:Q25257","wd:Q319","wdt:P397"],"min_results":1,
     "expected_answers":["Q3169","Q3134"]},  # Io, Europa
    {"id":"P01","domain":"Philosophy (Wikidata)","complexity":"simple","question":"List 10 philosophers",
     "gold_sparql":"SELECT DISTINCT ?philosopher ?philosopherLabel WHERE { ?philosopher wdt:P106 wd:Q4964182 . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } } LIMIT 10",
     "expected_components":["wdt:P106","wd:Q4964182","LIMIT"],"min_results":5,
     "expected_answers":[]},
    {"id":"P02","domain":"Philosophy (Wikidata)","complexity":"simple","question":"Who influenced Immanuel Kant?",
     "gold_sparql":"SELECT DISTINCT ?influence ?influenceLabel WHERE { wd:Q9312 wdt:P737 ?influence . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } }",
     "expected_components":["wdt:P737","wd:Q9312"],"min_results":1,
     "expected_answers":["Hume","Rousseau"]},
    {"id":"P03","domain":"Philosophy (Wikidata)","complexity":"complex","question":"List German philosophers born in the 19th century",
     "gold_sparql":"SELECT DISTINCT ?philosopher ?philosopherLabel ?birth WHERE { ?philosopher wdt:P106 wd:Q4964182 . ?philosopher wdt:P27 wd:Q183 . ?philosopher wdt:P569 ?birth . FILTER(YEAR(?birth) >= 1800 && YEAR(?birth) < 1900) SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } }",
     "expected_components":["wdt:P106","wd:Q4964182","wd:Q183","wdt:P569","FILTER"],"min_results":1,
     "expected_answers":["Nietzsche"]},
    {"id":"B01","domain":"Books (DBpedia)","complexity":"simple","question":"List 10 novels",
     "gold_sparql":"SELECT DISTINCT ?book ?name WHERE { ?book a dbo:WrittenWork . ?book dct:subject ?category . ?book rdfs:label ?name . FILTER(LANG(?name) = \"en\") FILTER(CONTAINS(LCASE(STR(?category)), \"novel\")) } LIMIT 10",
     "expected_components":["dbo:WrittenWork","dct:subject","rdfs:label","FILTER","LIMIT"],"min_results":5,
     "expected_answers":[]},
    {"id":"B02","domain":"Books (DBpedia)","complexity":"simple","question":"List books written by George Orwell",
     "gold_sparql":"SELECT DISTINCT ?book ?name WHERE { ?book a dbo:Book . ?book dbo:author dbr:George_Orwell . ?book rdfs:label ?name . FILTER(LANG(?name) = \"en\") }",
     "expected_components":["dbo:author","George_Orwell"],"min_results":1,
     "expected_answers":["Animal_Farm","Nineteen_Eighty"]},

    # ──────── ROBUSTNESS: typo / noisy user input ────────
    # Test entity normalization and the domain router under realistic
    # misspellings. Each typo case mirrors a baseline case so we can
    # directly read the cost of the typo.
    {"id":"T01","domain":"Movies (DBpedia)","complexity":"typo","question":"List movies directed by Steven Spielbrg",
     "gold_sparql":"SELECT DISTINCT ?film ?name WHERE { ?film a dbo:Film . ?film dbo:director dbr:Steven_Spielberg . ?film rdfs:label ?name . FILTER(LANG(?name) = \"en\") } LIMIT 20",
     "expected_components":["dbo:Film","dbo:director","Steven_Spielberg"],"min_results":1,
     "expected_answers":["Jurassic_Park","Schindler"]},
    {"id":"T02","domain":"Philosophy (Wikidata)","complexity":"typo","question":"Who influenced Immanuel Knt?",
     "gold_sparql":"SELECT DISTINCT ?influence ?influenceLabel WHERE { wd:Q9312 wdt:P737 ?influence . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } }",
     "expected_components":["wdt:P737","wd:Q9312"],"min_results":1,
     "expected_answers":["Hume","Rousseau"]},
    {"id":"T03","domain":"Astronomy (Wikidata)","complexity":"typo","question":"List 10 galxies",
     "gold_sparql":"SELECT DISTINCT ?galaxy ?galaxyLabel WHERE { ?galaxy wdt:P31 wd:Q318 . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } } LIMIT 10",
     "expected_components":["wdt:P31","wd:Q318","LIMIT"],"min_results":5,
     "expected_answers":[]},
    {"id":"T04","domain":"Diseases","complexity":"typo","question":"What are the symtoms of diabetes?",
     "gold_sparql":"SELECT DISTINCT ?symptom ?symptomLabel WHERE { wd:Q12206 wdt:P780 ?symptom . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } }",
     "expected_components":["wdt:P780","wd:Q12206"],"min_results":1,
     "expected_answers":[]},

    # ──────── EXTENDED: harder filters (F01/F02 omitted: xsd: cast issues) ────────
    {"id":"F03","domain":"Philosophy (Wikidata)","complexity":"filter","question":"List French philosophers",
     "gold_sparql":"SELECT DISTINCT ?philosopher ?philosopherLabel WHERE { ?philosopher wdt:P106 wd:Q4964182 . ?philosopher wdt:P27 wd:Q142 . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } } LIMIT 20",
     "expected_components":["wdt:P106","wd:Q4964182","wd:Q142"],"min_results":3,
     "expected_answers":[]},
    {"id":"F04","domain":"Astronomy (Wikidata)","complexity":"filter","question":"List planets with their mass",
     "gold_sparql":"SELECT DISTINCT ?planet ?planetLabel ?mass WHERE { ?planet wdt:P31/wdt:P279* wd:Q634 . ?planet wdt:P397 wd:Q525 . ?planet wdt:P2067 ?mass . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } } LIMIT 20",
     "expected_components":["wd:Q634","wd:Q525","wdt:P2067"],"min_results":3,
     "expected_answers":[]},

    # ──────── EXTENDED: aggregates (COUNT) ────────
    # rsm_applicable=False — count values drift between executions and
    # would unfairly penalize correct queries. EA / Components / Judge still apply.
    {"id":"AG01","domain":"Diseases","complexity":"aggregate","question":"Count diseases in Wikidata",
     "gold_sparql":"SELECT (COUNT(DISTINCT ?disease) AS ?count) WHERE { ?disease wdt:P31 wd:Q12136 . }",
     "expected_components":["COUNT","DISTINCT","wdt:P31","wd:Q12136"],"min_results":1,
     "expected_answers":[],"rsm_applicable":False},
    {"id":"AG02","domain":"Movies (DBpedia)","complexity":"aggregate","question":"Count films directed by Steven Spielberg",
     "gold_sparql":"SELECT (COUNT(DISTINCT ?film) AS ?count) WHERE { ?film a dbo:Film . ?film dbo:director dbr:Steven_Spielberg . }",
     "expected_components":["COUNT","dbo:Film","dbo:director","Steven_Spielberg"],"min_results":1,
     "expected_answers":[],"rsm_applicable":False},
    {"id":"AG03","domain":"Books (DBpedia)","complexity":"aggregate","question":"Count books written by George Orwell",
     "gold_sparql":"SELECT (COUNT(DISTINCT ?book) AS ?count) WHERE { ?book dbo:author dbr:George_Orwell . }",
     "expected_components":["COUNT","dbo:author","George_Orwell"],"min_results":1,
     "expected_answers":[],"rsm_applicable":False},

    # ──────── EXTENDED: joins / multi-variable ────────
    {"id":"J01","domain":"Books (DBpedia)","complexity":"join","question":"List books and their authors",
     "gold_sparql":"SELECT DISTINCT ?book ?bookName ?author ?authorName WHERE { ?book dbo:author ?author . ?book rdfs:label ?bookName . ?author rdfs:label ?authorName . FILTER(LANG(?bookName) = \"en\") FILTER(LANG(?authorName) = \"en\") } LIMIT 20",
     "expected_components":["dbo:author","rdfs:label","FILTER"],"min_results":5,
     "expected_answers":[]},
    {"id":"J02","domain":"Movies (DBpedia)","complexity":"join","question":"List films with their directors",
     "gold_sparql":"SELECT DISTINCT ?film ?filmName ?director ?directorName WHERE { ?film a dbo:Film . ?film dbo:director ?director . ?film rdfs:label ?filmName . ?director rdfs:label ?directorName . FILTER(LANG(?filmName) = \"en\") FILTER(LANG(?directorName) = \"en\") } LIMIT 20",
     "expected_components":["dbo:Film","dbo:director","rdfs:label"],"min_results":5,
     "expected_answers":[]},
    {"id":"J03","domain":"Philosophy (Wikidata)","complexity":"join","question":"List philosophers with their countries of citizenship",
     "gold_sparql":"SELECT DISTINCT ?philosopher ?philosopherLabel ?country ?countryLabel WHERE { ?philosopher wdt:P106 wd:Q4964182 . ?philosopher wdt:P27 ?country . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } } LIMIT 20",
     "expected_components":["wdt:P106","wd:Q4964182","wdt:P27"],"min_results":5,
     "expected_answers":[]},

    # ──────── CROSS-DOMAIN STRESS ────────
    # Both executable on a single endpoint via dbo:basedOn, but conceptually
    # span Movies + Books knowledge.
    {"id":"X01","domain":"Movies (DBpedia)","complexity":"cross-domain","question":"List films based on books",
     "gold_sparql":"SELECT DISTINCT ?film ?name ?bookName WHERE { ?film a dbo:Film . ?film dbo:basedOn ?book . ?film rdfs:label ?name . ?book rdfs:label ?bookName . FILTER(LANG(?name) = \"en\") FILTER(LANG(?bookName) = \"en\") } LIMIT 20",
     "expected_components":["dbo:Film","dbo:basedOn","rdfs:label"],"min_results":3,
     "expected_answers":[]},
    {"id":"X02","domain":"Books (DBpedia)","complexity":"cross-domain","question":"List books that were adapted into films",
     "gold_sparql":"SELECT DISTINCT ?book ?bookName ?film ?filmName WHERE { ?film a dbo:Film . ?film dbo:basedOn ?book . ?book rdfs:label ?bookName . ?film rdfs:label ?filmName . FILTER(LANG(?bookName) = \"en\") FILTER(LANG(?filmName) = \"en\") } LIMIT 20",
     "expected_components":["dbo:Film","dbo:basedOn","rdfs:label"],"min_results":3,
     "expected_answers":[]},

    # ──────── ROBUSTNESS: ambiguous wording ────────
    # "football" is ambiguous (soccer / American football / many roles).
    # The gold query commits to association football; the model must resolve it.
    {"id":"AM01","domain":"Sports (Wikidata)","complexity":"ambiguous","question":"List 10 football players",
     "gold_sparql":"SELECT DISTINCT ?player ?playerLabel WHERE { ?player wdt:P106 wd:Q937857 . ?player wdt:P31 wd:Q5 . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } } LIMIT 10",
     "expected_components":["wdt:P106","wd:Q937857","wdt:P31","wd:Q5"],"min_results":5,
     "expected_answers":[]},
    {"id":"AM02","domain":"Sports (Wikidata)","complexity":"ambiguous","question":"List 10 football clubs",
     "gold_sparql":"SELECT DISTINCT ?club ?clubLabel WHERE { ?club wdt:P31 wd:Q476028 . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } } LIMIT 10",
     "expected_components":["wdt:P31","wd:Q476028"],"min_results":5,
     "expected_answers":[]},

    # ──────── BASELINE: TV Shows (DBpedia) ────────
    # Patterns mirror the TV Shows YAML's own few-shot examples to give the
    # model a fair chance: dbo:TelevisionShow, dbo:network, dbo:creator.
    {"id":"TV01","domain":"TV Shows (DBpedia)","complexity":"simple","question":"List 10 TV shows",
     "gold_sparql":"SELECT DISTINCT ?show ?name WHERE { ?show a dbo:TelevisionShow . ?show rdfs:label ?name . FILTER(LANG(?name) = \"en\") } LIMIT 10",
     "expected_components":["dbo:TelevisionShow","rdfs:label","FILTER","LIMIT"],"min_results":5,
     "expected_answers":[]},
    {"id":"TV02","domain":"TV Shows (DBpedia)","complexity":"simple","question":"Who created Breaking Bad?",
     "gold_sparql":"SELECT ?creator ?creatorName WHERE { dbr:Breaking_Bad dbo:creator ?creator . ?creator rdfs:label ?creatorName . FILTER(LANG(?creatorName) = \"en\") }",
     "expected_components":["dbo:creator","Breaking_Bad"],"min_results":1,
     "expected_answers":["Vince_Gilligan","Gilligan"]},
    {"id":"TV03","domain":"TV Shows (DBpedia)","complexity":"medium","question":"List TV shows on HBO",
     "gold_sparql":"SELECT DISTINCT ?show ?name WHERE { ?show a dbo:TelevisionShow . ?show dbo:network dbr:HBO . ?show rdfs:label ?name . FILTER(LANG(?name) = \"en\") } LIMIT 20",
     "expected_components":["dbo:TelevisionShow","dbo:network","HBO"],"min_results":3,
     "expected_answers":["Game_of_Thrones"]},

    # ──────── BASELINE: Geography (Wikidata) ────────
    # Simple lookup, exact lookup against a known entity, and ORDER BY+LIMIT.
    {"id":"G01","domain":"Geography (Wikidata)","complexity":"simple","question":"List all continents",
     "gold_sparql":"SELECT ?continent ?continentLabel WHERE { ?continent wdt:P31 wd:Q5107 . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } }",
     "expected_components":["wdt:P31","wd:Q5107"],"min_results":5,
     "expected_answers":["Q46","Q48"]},  # Europe, Asia
    {"id":"G02","domain":"Geography (Wikidata)","complexity":"simple","question":"What is the capital of France?",
     "gold_sparql":"SELECT ?capital ?capitalLabel WHERE { wd:Q142 wdt:P36 ?capital . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } }",
     "expected_components":["wdt:P36","wd:Q142"],"min_results":1,
     "expected_answers":["Q90"]},  # Paris
    {"id":"G03","domain":"Geography (Wikidata)","complexity":"medium","question":"List the 10 most populous cities in the world",
     "gold_sparql":"SELECT ?city ?cityLabel ?population WHERE { ?city wdt:P31 wd:Q515 . ?city wdt:P1082 ?population . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } } ORDER BY DESC(?population) LIMIT 10",
     "expected_components":["wdt:P31","wd:Q515","wdt:P1082","ORDER BY","DESC","LIMIT"],"min_results":5,
     "expected_answers":[]},

    # ──────── BASELINE: Scientists & Nobel Prizes (Wikidata) ────────
    {"id":"S01","domain":"Scientists & Nobel Prizes (Wikidata)","complexity":"simple","question":"List 10 scientists",
     "gold_sparql":"SELECT ?scientist ?scientistLabel WHERE { ?scientist wdt:P106 wd:Q901 . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } } LIMIT 10",
     "expected_components":["wdt:P106","wd:Q901","LIMIT"],"min_results":5,
     "expected_answers":[]},
    {"id":"S02","domain":"Scientists & Nobel Prizes (Wikidata)","complexity":"medium","question":"List Nobel Prize winners in Physics",
     "gold_sparql":"SELECT ?laureate ?laureateLabel WHERE { ?laureate wdt:P166 wd:Q38104 . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } } LIMIT 20",
     "expected_components":["wdt:P166","wd:Q38104"],"min_results":5,
     "expected_answers":["Q937"]},  # Albert Einstein
    {"id":"S03","domain":"Scientists & Nobel Prizes (Wikidata)","complexity":"medium","question":"List scientists who worked at CERN",
     "gold_sparql":"SELECT ?scientist ?scientistLabel WHERE { ?scientist wdt:P108 wd:Q42944 . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } } LIMIT 20",
     "expected_components":["wdt:P108","wd:Q42944"],"min_results":3,
     "expected_answers":[]},

    # ──────── BASELINE: Music (Wikidata) ────────
    # Prefix is "MU" because "M" is taken by Movies. The Music YAML uses the
    # rdfs:label + LANG filter idiom (not SERVICE wikibase:label) for queries
    # over musicians/albums to avoid silently dropping unlabelled rows.
    {"id":"MU01","domain":"Music (Wikidata)","complexity":"simple","question":"List 10 musicians",
     "gold_sparql":"SELECT ?musician ?musicianLabel WHERE { ?musician wdt:P106 wd:Q639669 . ?musician rdfs:label ?musicianLabel . FILTER(LANG(?musicianLabel) = \"en\") } LIMIT 10",
     "expected_components":["wdt:P106","wd:Q639669","FILTER","LIMIT"],"min_results":5,
     "expected_answers":[]},
    {"id":"MU02","domain":"Music (Wikidata)","complexity":"medium","question":"List albums released by The Beatles",
     "gold_sparql":"SELECT ?album ?albumLabel WHERE { ?album wdt:P31 wd:Q482994 . ?album wdt:P175 wd:Q1299 . ?album rdfs:label ?albumLabel . FILTER(LANG(?albumLabel) = \"en\") }",
     "expected_components":["wdt:P31","wd:Q482994","wdt:P175","wd:Q1299"],"min_results":3,
     "expected_answers":["Abbey","Revolver"]},  # iconic Beatles album labels
    {"id":"MU03","domain":"Music (Wikidata)","complexity":"simple","question":"List 10 rock bands",
     "gold_sparql":"SELECT ?band ?bandLabel WHERE { ?band wdt:P31 wd:Q5741069 . ?band rdfs:label ?bandLabel . FILTER(LANG(?bandLabel) = \"en\") } LIMIT 10",
     "expected_components":["wdt:P31","wd:Q5741069","FILTER","LIMIT"],"min_results":5,
     "expected_answers":[]},
]


# ───────────────────────── case category routing ─────────────────────────
# Auto-derived from the ID prefix so the GOLD_STANDARD entries stay short.
# Note: regex is greedy on [A-Z]+, so "TV01" -> "TV", not "T". This is what
# we want, since "T" alone is reserved for typo (robustness) cases.
_CATEGORY_BY_PREFIX = {
    # original baseline domains (5)
    "D":"baseline","M":"baseline","A":"baseline","P":"baseline","B":"baseline",
    # added baseline domains (4)
    "TV":"baseline","G":"baseline","S":"baseline","MU":"baseline",
    # robustness probes
    "T":"robustness","AM":"robustness",
    # extended difficulty
    "F":"extended","AG":"extended","J":"extended",
    # cross-domain stress
    "X":"cross_domain",
}

def _category_for_id(case_id):
    m = re.match(r'^([A-Z]+)\d', case_id or "")
    if not m: return "other"
    return _CATEGORY_BY_PREFIX.get(m.group(1), "other")


# ───────────────────────── per-case runner ─────────────────────────

def run_test(case, config, model, judge_model=None, skip_judge=False,
             max_attempts=2, retry_delay=3):
    r = {"id":case["id"],"question":case["question"],"domain":case["domain"],
         "complexity":case["complexity"],"category":_category_for_id(case["id"]),
         "model":model,"judge_model":judge_model,
         "generated_sparql":"","gold_sparql":case["gold_sparql"],
         # v1
         "execution_accuracy":False,"result_accuracy":False,"result_count":0,
         "component_precision":0,"component_recall":0,"component_f1":0,
         "components_found":[],"components_missing":[],"bleu":0,
         # v2
         "rsm_applicable":case.get("rsm_applicable", True),
         "rsm_precision":0,"rsm_recall":0,"rsm_f1":0,"rsm_jaccard":0,
         "rsm_exact_match":False,"gold_size":0,"gen_size":0,"overlap":0,
         "rsm_skipped":True,
         "gold_execution_success":False,"gold_error":None,
         "gtc_score":0,"gtc_found":[],"gtc_missing":[],"gtc_skipped":True,
         "judge_skipped":True,"judge_score":0,"verdict":"UNKNOWN",
         "relevance":0,"correctness":0,"completeness":0,"reasoning":"",
         "composite_score":0,
         # row-level judge
         "row_verdicts":[],"row_precision":0.0,
         "row_judge_correct":0,"row_judge_total":0,"row_judge_skipped":True,
         # diagnostics
         "gen_retries":0,"gold_retries":0,
         # timing
         "generation_time_s":0,"execution_time_s":0,"total_time_s":0,"error":None}

    # ── 1. Generate ──
    t0 = time.time()
    try:
        raw = nl_to_sparql.translate(case["question"], config, model=model)
        cleaned = sparql_executor.clean_sparql(raw)
        r["generated_sparql"] = cleaned
        r["generation_time_s"] = round(time.time()-t0, 2)
    except Exception as e:
        r["error"] = f"Gen:{str(e)[:200]}"
        r["generation_time_s"] = round(time.time()-t0, 2)
        return r
    if not cleaned or cleaned.startswith("[ERROR]"):
        r["error"] = f"Empty:{cleaned[:200]}"; return r

    # ── 2. Syntactic similarity (v1) ──
    r["bleu"] = round(compute_bleu(case["gold_sparql"], cleaned), 4)
    comp = compute_component_f1(case["expected_components"], cleaned)
    r["component_precision"] = comp["precision"]
    r["component_recall"]    = comp["recall"]
    r["component_f1"]        = comp["f1"]
    r["components_found"]    = comp["found"]
    r["components_missing"]  = comp["missing"]

    # ── 3. Execute generated query (with retry on transient endpoint errors) ──
    t1 = time.time()
    gen_results = []
    try:
        ex = execute_with_retry(cleaned, config["endpoint"],
                                max_attempts=max_attempts, base_delay=retry_delay)
        r["execution_time_s"] = round(time.time()-t1, 2)
        r["gen_retries"] = max(0, len(ex.get("retry_log",[])) - 1)
        if ex.get("success"):
            r["execution_accuracy"] = True
            gen_results = ex.get("results", [])
            r["result_count"] = len(gen_results)
            r["result_accuracy"] = r["result_count"] >= case.get("min_results", 0)
        else:
            tag = "Exec" if not _is_transient(ex.get("error","")) else "Exec[transient]"
            r["error"] = f"{tag}:{ex.get('error','')[:200]}"
    except Exception as e:
        r["error"] = f"ExecErr:{str(e)[:200]}"
        r["execution_time_s"] = round(time.time()-t1, 2)

    # ── 4. Execute gold query for set comparison (skip if not applicable) ──
    gold_results = []
    if r["execution_accuracy"] and r["rsm_applicable"]:
        try:
            gx = execute_with_retry(case["gold_sparql"], config["endpoint"],
                                    max_attempts=max_attempts, base_delay=retry_delay)
            r["gold_retries"] = max(0, len(gx.get("retry_log",[])) - 1)
            if gx.get("success"):
                gold_results = gx.get("results", [])
                r["gold_execution_success"] = True
            else:
                r["gold_error"] = (gx.get("error","") or "")[:200]
        except Exception as e:
            r["gold_error"] = str(e)[:200]
    elif not r["rsm_applicable"]:
        r["gold_error"] = "rsm_not_applicable"

    # ── 5. Result-set metrics (only meaningful if gold also ran) ──
    rsm = compute_result_set_metrics(gold_results, gen_results,
                                     gold_success=r["gold_execution_success"])
    r.update(rsm)

    # ── 6. Ground-truth coverage ──
    gtc = compute_ground_truth_coverage(case.get("expected_answers", []), gen_results)
    r.update(gtc)

    # ── 7. LLM-as-a-Judge ──
    if not skip_judge and judge_model and r["execution_accuracy"]:
        j = llm_judge(case["question"], cleaned, gen_results,
                      case["gold_sparql"], judge_model)
        r.update(j)

    # ── 7b. Row-level judge ──
    if not skip_judge and judge_model and r["execution_accuracy"] and gen_results:
        rj = llm_judge_rows(case["question"], gen_results, gold_results,
                            judge_model, max_rows=10)
        r.update(rj)

    # ── 8. Composite ──
    r["composite_score"] = composite_score(r)
    r["total_time_s"] = round(r["generation_time_s"]+r["execution_time_s"], 2)
    return r


# ───────────────────────── presentation ─────────────────────────

def print_result(r):
    pass_strict = (r["execution_accuracy"] and r["result_accuracy"]
                   and r["component_f1"] >= 0.5 and r["composite_score"] >= 0.5)
    tag = "PASS" if pass_strict else "FAIL"
    judge = r["verdict"][:4] if not r.get("judge_skipped",True) else "skip"
    rsm_str = "skip" if r.get("rsm_skipped",False) else f"{r['rsm_f1']:.2f}"
    rprec_str = "skip" if r.get("row_judge_skipped", True) else f"{r['row_precision']:.2f}"
    print(f"  [{tag}] {r['id']:5s} | EA:{'✓' if r['execution_accuracy'] else '✗'}"
          f" RA:{'✓' if r['result_accuracy'] else '✗'}"
          f" cF1:{r['component_f1']:.2f} rF1:{rsm_str}"
          f" GTC:{r['gtc_score']:.2f} Jdg:{r['judge_score']:.2f}({judge})"
          f" rPrec:{rprec_str}"
          f" CQS:{r['composite_score']:.2f}"
          f" | n={r['result_count']:4d} t={r['total_time_s']:5.1f}s"
          f" | {r['question'][:38]}")
    if r.get("rsm_skipped") and r.get("gold_error"):
        print(f"         rsm-skip: gold query failed -> {r['gold_error'][:80]}")
    if r.get("gen_retries") or r.get("gold_retries"):
        print(f"         retries: gen={r.get('gen_retries',0)} gold={r.get('gold_retries',0)}")
    if r.get("gtc_missing"): print(f"         gtc-miss: {r['gtc_missing']}")
    if r.get("reasoning"):    print(f"         judge: {r['reasoning'][:90]}")
    wrong_rows = [v["row"] for v in r.get("row_verdicts",[]) if v.get("verdict")=="INCORRECT"]
    if wrong_rows: print(f"         row-fail: rows {wrong_rows} incorrect")
    if r["error"]:            print(f"         error: {r['error'][:90]}")


def _avg(rs, key): return (sum(r[key] for r in rs)/len(rs)) if rs else 0.0
def _frac(rs, key): return (sum(1 for r in rs if r[key])/len(rs)) if rs else 0.0

def print_summary(model, results):
    if not results: return
    n = len(results)
    print(f"\n  Model: {model}")
    print(f"  {'─'*60}")
    print(f"  Execution Accuracy:    {_frac(results,'execution_accuracy'):.1%}")
    print(f"  Result Accuracy:       {_frac(results,'result_accuracy'):.1%}")
    print(f"  Avg Component F1:      {_avg(results,'component_f1'):.3f}")
    rsm_active = [r for r in results if not r.get("rsm_skipped",False)]
    if rsm_active:
        print(f"  Avg Result-Set F1:     {_avg(rsm_active,'rsm_f1'):.3f}"
              f"  ({len(rsm_active)}/{n} cases, gold ran)")
        print(f"  Avg Result-Set Jacc:   {_avg(rsm_active,'rsm_jaccard'):.3f}")
        print(f"  Result-Set Exact:      {_frac(rsm_active,'rsm_exact_match'):.1%}")
    else:
        print(f"  Result-Set metrics:    skipped (gold queries did not run)")
    judged = [r for r in results if not r.get("judge_skipped",True)]
    if judged:
        c = sum(1 for r in judged if r["verdict"]=="CORRECT")/len(judged)
        p = sum(1 for r in judged if r["verdict"]=="PARTIAL")/len(judged)
        i = sum(1 for r in judged if r["verdict"]=="INCORRECT")/len(judged)
        print(f"  Judge Avg Score:       {_avg(judged,'judge_score'):.3f}  "
              f"(CORRECT {c:.0%} / PARTIAL {p:.0%} / INCORRECT {i:.0%})")
    gtc_active = [r for r in results if not r.get("gtc_skipped",True)]
    if gtc_active:
        print(f"  Ground-Truth Coverage: {_avg(gtc_active,'gtc_score'):.3f}"
              f"  ({len(gtc_active)} cases with GT)")
    row_judged = [r for r in results if not r.get("row_judge_skipped",True)]
    if row_judged:
        print(f"  Avg Row Precision:     {_avg(row_judged,'row_precision'):.3f}"
              f"  ({len(row_judged)} cases, row-level judge)")
    print(f"  Avg BLEU:              {_avg(results,'bleu'):.3f}")
    print(f"  COMPOSITE QUALITY:     {_avg(results,'composite_score'):.3f}")
    print(f"  Avg Time:              {_avg(results,'total_time_s'):.1f}s")

    # Per-category breakdown so headline numbers are not diluted by hard cases.
    cats = sorted({r["category"] for r in results})
    if len(cats) > 1:
        print(f"  {'─'*60}")
        print(f"  By category:")
        for c in cats:
            sub = [r for r in results if r["category"] == c]
            sub_rsm = [r for r in sub if not r.get("rsm_skipped",False)]
            rsm_str = f"{_avg(sub_rsm,'rsm_f1'):.2f}" if sub_rsm else " n/a"
            print(f"    {c:<14s} n={len(sub):2d}  "
                  f"EA:{_frac(sub,'execution_accuracy'):>4.0%}  "
                  f"RSM-F1:{rsm_str}  "
                  f"CQS:{_avg(sub,'composite_score'):.2f}")


def print_comparison(all_results):
    models = list(all_results.keys())
    if len(models) < 2: return
    print(f"\n{'='*92}\nMODEL COMPARISON\n{'='*92}")
    h = f"{'Metric':<28s}"
    for m in models: h += f" | {m[:22]:>22s}"
    print(h); print("─"*len(h))
    def rsm_active(rs): return [r for r in rs if not r.get("rsm_skipped",False)]
    def judged(rs):     return [r for r in rs if not r.get("judge_skipped",True)]
    rows = [
        ("Execution Accuracy",  lambda rs: f"{_frac(rs,'execution_accuracy'):.0%}"),
        ("Result Accuracy",     lambda rs: f"{_frac(rs,'result_accuracy'):.0%}"),
        ("Avg Component F1",    lambda rs: f"{_avg(rs,'component_f1'):.3f}"),
        ("Avg Result-Set F1",   lambda rs: f"{_avg(rsm_active(rs),'rsm_f1'):.3f} (n={len(rsm_active(rs))})"),
        ("Result-Set Exact",    lambda rs: f"{_frac(rsm_active(rs),'rsm_exact_match'):.0%}" if rsm_active(rs) else "n/a"),
        ("Avg Judge Score",     lambda rs: f"{_avg(judged(rs),'judge_score'):.3f}" if judged(rs) else "n/a"),
        ("Composite Quality",   lambda rs: f"{_avg(rs,'composite_score'):.3f}"),
        ("Avg Time (s)",        lambda rs: f"{_avg(rs,'total_time_s'):.1f}s"),
    ]
    for label, fn in rows:
        line = f"{label:<28s}"
        for m in models: line += f" | {fn(all_results[m]):>22s}"
        print(line)

    # Per-category cross-model breakdown
    cats = sorted({r["category"] for rs in all_results.values() for r in rs})
    if len(cats) > 1:
        print(f"\n{'─'*92}\nBY CATEGORY\n{'─'*92}")
        h = f"{'Category':<28s}"
        for m in models: h += f" | {m[:22]:>22s}"
        print(h); print("─"*len(h))
        for c in cats:
            line = f"  {c:<26s}"
            for m in models:
                sub = [r for r in all_results[m] if r["category"] == c]
                if sub:
                    cell = f"EA:{_frac(sub,'execution_accuracy'):.0%} CQS:{_avg(sub,'composite_score'):.2f}"
                else:
                    cell = "n/a"
                line += f" | {cell:>22s}"
            print(line)


# ───────────────────────── markdown report ─────────────────────────

def write_markdown_report(path, all_results, judge_model, models):
    lines = []
    lines.append(f"# NL→SPARQL Advanced Evaluation Report")
    lines.append(f"_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n")
    lines.append(f"- **Models under test:** {', '.join(models)}")
    lines.append(f"- **Judge model:** {judge_model or '(none)'}")
    lines.append(f"- **Total cases per model:** {len(next(iter(all_results.values()), []))}\n")

    lines.append("## Aggregate Metrics\n")
    lines.append("| Model | EA | RA | Comp-F1 | RSM-F1 (n) | RSM-Exact | Judge | CQS |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for m, rs in all_results.items():
        if not rs: continue
        rsm_active = [r for r in rs if not r.get("rsm_skipped",False)]
        judged = [r for r in rs if not r.get("judge_skipped",True)]
        lines.append(
            f"| `{m}` "
            f"| {_frac(rs,'execution_accuracy'):.0%} "
            f"| {_frac(rs,'result_accuracy'):.0%} "
            f"| {_avg(rs,'component_f1'):.3f} "
            f"| {(_avg(rsm_active,'rsm_f1') if rsm_active else 0):.3f} ({len(rsm_active)}/{len(rs)}) "
            f"| {(_frac(rsm_active,'rsm_exact_match') if rsm_active else 0):.0%} "
            f"| {(_avg(judged,'judge_score') if judged else 0):.3f} "
            f"| **{_avg(rs,'composite_score'):.3f}** |")

    lines.append("\n## By Category\n")
    lines.append("Categories separate ordinary baseline questions from harder probes "
                 "(typos, ambiguous wording, cross-domain) so the headline accuracy "
                 "is not diluted.\n")
    cats = sorted({r["category"] for rs in all_results.values() for r in rs})
    lines.append("| Model | Category | n | EA | RSM-F1 | GTC | Judge | CQS |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for m, rs in all_results.items():
        for c in cats:
            sub = [r for r in rs if r["category"] == c]
            if not sub: continue
            sub_rsm = [r for r in sub if not r.get("rsm_skipped",False)]
            sub_gtc = [r for r in sub if not r.get("gtc_skipped",True)]
            sub_jdg = [r for r in sub if not r.get("judge_skipped",True)]
            lines.append(
                f"| `{m}` | {c} | {len(sub)} "
                f"| {_frac(sub,'execution_accuracy'):.0%} "
                f"| {(_avg(sub_rsm,'rsm_f1') if sub_rsm else 0):.3f} "
                f"| {(_avg(sub_gtc,'gtc_score') if sub_gtc else 0):.3f} "
                f"| {(_avg(sub_jdg,'judge_score') if sub_jdg else 0):.3f} "
                f"| **{_avg(sub,'composite_score'):.3f}** |")

    lines.append("\n## By Domain\n")
    domains = sorted({r["domain"] for rs in all_results.values() for r in rs})
    lines.append("| Model | Domain | n | EA | RSM-F1 | CQS |")
    lines.append("|---|---|---|---|---|---|")
    for m, rs in all_results.items():
        for d in domains:
            sub = [r for r in rs if r["domain"]==d]
            if not sub: continue
            sub_rsm = [r for r in sub if not r.get("rsm_skipped",False)]
            lines.append(f"| `{m}` | {d} | {len(sub)} "
                         f"| {_frac(sub,'execution_accuracy'):.0%} "
                         f"| {(_avg(sub_rsm,'rsm_f1') if sub_rsm else 0):.3f} "
                         f"| {_avg(sub,'composite_score'):.3f} |")

    lines.append("\n## Verdict Breakdown (LLM-as-a-Judge)\n")
    lines.append("| Model | Cases judged | CORRECT | PARTIAL | INCORRECT | UNKNOWN |")
    lines.append("|---|---|---|---|---|---|")
    for m, rs in all_results.items():
        judged = [r for r in rs if not r.get("judge_skipped",True)]
        if not judged: lines.append(f"| `{m}` | 0 | – | – | – | – |"); continue
        c = sum(1 for r in judged if r["verdict"]=="CORRECT")
        p = sum(1 for r in judged if r["verdict"]=="PARTIAL")
        i = sum(1 for r in judged if r["verdict"]=="INCORRECT")
        u = sum(1 for r in judged if r["verdict"]=="UNKNOWN")
        lines.append(f"| `{m}` | {len(judged)} | {c} | {p} | {i} | {u} |")

    lines.append("\n## Per-case Detail\n")
    for m, rs in all_results.items():
        lines.append(f"\n### `{m}`\n")
        lines.append("| ID | Question | EA | RSM-F1 | GTC | Judge | Row-Prec | Verdict | CQS |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for r in rs:
            q = r["question"].replace("|","\\|")[:60]
            rprec = "–" if r.get("row_judge_skipped",True) else f"{r['row_precision']:.2f}"
            lines.append(f"| {r['id']} | {q} "
                         f"| {'✓' if r['execution_accuracy'] else '✗'} "
                         f"| {r['rsm_f1']:.2f} "
                         f"| {r['gtc_score']:.2f} "
                         f"| {r['judge_score']:.2f} "
                         f"| {rprec} "
                         f"| {r['verdict']} "
                         f"| {r['composite_score']:.2f} |")
    with open(path, "w") as f: f.write("\n".join(lines))


# ───────────────────────── main ─────────────────────────

def _parse_models_arg(s):
    return [p.strip() for p in re.split(r',(?![^\[]*\])', s) if p.strip()]

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--models", default=None,
                   help='Comma-separated. Default: HF Qwen + HF Llama-3.')
    p.add_argument("--judge", default=None,
                   help='Judge model. Defaults to first model not in --models.')
    p.add_argument("--domain", default=None)
    p.add_argument("--complexity", default=None)
    p.add_argument("--save", default=None)
    p.add_argument("--report", default=None, help="Markdown report path.")
    p.add_argument("--quick", action="store_true")
    p.add_argument("--no-judge", action="store_true")
    p.add_argument("--timeout", type=int, default=60,
                   help="Best-effort SPARQL request timeout in seconds. "
                        "Only applied if the executor module exposes a settable "
                        "timeout attribute; otherwise retry handles it. Default 60.")
    p.add_argument("--retries", type=int, default=2,
                   help="Number of attempts per SPARQL query on transient errors "
                        "(timeouts, 502/503/504). Default 2 (1 retry).")
    p.add_argument("--retry-delay", type=int, default=3,
                   help="Base seconds between retries; multiplied by attempt#. Default 3.")
    a = p.parse_args()

    # Best-effort: lift the SPARQL executor's hardcoded timeout for this run.
    patched_attr = _try_raise_executor_timeout(a.timeout)
    if patched_attr:
        print(f"INFO: raised sparql_executor.{patched_attr} -> {a.timeout}s for this run")
    else:
        print(f"INFO: sparql_executor exposes no settable timeout attribute. "
              f"Hardcoded module-level timeout (typically 30s) is in effect; "
              f"retry will handle transient timeouts. To raise it permanently, "
              f"edit src/sparql_executor.py and change timeout=30 to "
              f"timeout={a.timeout}.")

    default_models = [
        "HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct",
        "HuggingFace: meta-llama/Meta-Llama-3-8B-Instruct",
    ]
    models = _parse_models_arg(a.models) if a.models else default_models

    avail = []
    try: avail = llm_client.list_models() or []
    except Exception: pass
    if avail:
        models = [m for m in models if m in avail or print(f"WARN: {m} not in list_models() — trying anyway") or True]

    judge_model = a.judge
    auto_no_judge = False
    if not judge_model and not a.no_judge:
        # Pick a judge that is NOT among the tested models.
        candidates = [m for m in (avail or default_models) if m not in models]
        if candidates:
            judge_model = candidates[0]
        else:
            # No distinct judge available -> disable judging instead of self-judging.
            print("WARN: no distinct model available as judge "
                  "(all candidates overlap with --models). "
                  "Auto-disabling judge to avoid self-judging bias. "
                  "Pass --judge MODEL explicitly to override.")
            auto_no_judge = True
            judge_model = None
    elif a.judge and a.judge in models:
        print(f"WARN: judge model == one of tested models ({a.judge}). "
              f"Self-judging bias is likely; results may be inflated.")
    skip_judge = a.no_judge or auto_no_judge

    configs = {}
    for fp in glob.glob("configs/*.yaml"):
        with open(fp) as f:
            c = yaml.safe_load(f)
            configs[c.get("domain_name", os.path.basename(fp))] = c

    cases = GOLD_STANDARD[:]
    if a.domain:     cases = [c for c in cases if c["domain"] == a.domain]
    if a.complexity: cases = [c for c in cases if c["complexity"] == a.complexity]
    if a.quick:
        seen, q = {}, []
        for c in cases:
            seen[c["domain"]] = seen.get(c["domain"], 0)
            if seen[c["domain"]] < 2:
                q.append(c); seen[c["domain"]] += 1
        cases = q
    cases = [c for c in cases if c["domain"] in configs]
    if not cases:
        print("No cases. Available domains:", list(configs.keys())); return

    print(f"{'='*92}\nNL-SPARQL ADVANCED EVALUATION (v2)\n{'='*92}")
    print(f"Date:       {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Models:     {', '.join(models)}")
    print(f"Judge:      {judge_model or '(disabled)'}")
    print(f"Cases:      {len(cases)}")
    print(f"Timeout:    {a.timeout}s (executor-attribute monkey-patch "
          f"{'applied' if patched_attr else 'not available; retries cover transients'})")
    print(f"Retries:    up to {a.retries} attempts per query, "
          f"backoff {a.retry_delay}s × attempt#")
    print(f"Metrics:    EA, RA, Comp-F1, BLEU, RSM-{{P,R,F1,Jacc,Exact}}, "
          f"GTC, Judge, Composite\n")

    all_results = {}
    for model in models:
        print(f"\n{'━'*92}\n  MODEL: {model}\n{'━'*92}")
        mr = []
        for i, case in enumerate(cases, 1):
            cfg = configs.get(case["domain"])
            if not cfg: continue
            print(f"\n  [{i}/{len(cases)}] {case['question']}")
            r = run_test(case, cfg, model,
                         judge_model=None if skip_judge else judge_model,
                         skip_judge=skip_judge,
                         max_attempts=max(1, a.retries),
                         retry_delay=max(0, a.retry_delay))
            print_result(r); mr.append(r); time.sleep(1)
        all_results[model] = mr
        print_summary(model, mr)

    if len(models) > 1: print_comparison(all_results)

    if a.save:
        out = {
            "timestamp": datetime.now().isoformat(),
            "models": models, "judge_model": judge_model,
            "no_judge": skip_judge, "case_count": len(cases),
            "metrics": ["execution_accuracy","result_accuracy","component_f1",
                        "bleu","rsm_f1","rsm_jaccard","rsm_exact_match",
                        "gtc_score","judge_score","verdict","composite_score"],
            "summaries": {}, "detailed_results": {},
        }
        for m, rs in all_results.items():
            if not rs: continue
            judged = [r for r in rs if not r.get("judge_skipped",True)]
            row_judged = [r for r in rs if not r.get("row_judge_skipped",True)]
            out["summaries"][m] = {
                "execution_accuracy": round(_frac(rs,'execution_accuracy'),4),
                "result_accuracy":    round(_frac(rs,'result_accuracy'),4),
                "avg_component_f1":   round(_avg(rs,'component_f1'),4),
                "avg_bleu":           round(_avg(rs,'bleu'),4),
                "avg_rsm_f1":         round(_avg(rs,'rsm_f1'),4),
                "avg_rsm_jaccard":    round(_avg(rs,'rsm_jaccard'),4),
                "rsm_exact_match":    round(_frac(rs,'rsm_exact_match'),4),
                "avg_judge_score":    round(_avg(judged,'judge_score'),4) if judged else 0,
                "verdict_correct":    sum(1 for r in judged if r["verdict"]=="CORRECT"),
                "verdict_partial":    sum(1 for r in judged if r["verdict"]=="PARTIAL"),
                "verdict_incorrect":  sum(1 for r in judged if r["verdict"]=="INCORRECT"),
                "avg_row_precision":  round(_avg(row_judged,'row_precision'),4) if row_judged else 0,
                "row_judge_cases":    len(row_judged),
                "avg_composite":      round(_avg(rs,'composite_score'),4),
                "avg_time_s":         round(_avg(rs,'total_time_s'),2),
            }
            out["detailed_results"][m] = rs
        with open(a.save, "w") as f: json.dump(out, f, indent=2, default=str)
        print(f"\nSaved JSON: {a.save}")

    if a.report:
        write_markdown_report(a.report, all_results, judge_model, models)
        print(f"Saved Markdown report: {a.report}")

    print(f"\nDone: {datetime.now().strftime('%H:%M:%S')}")


if __name__ == "__main__":
    main()
