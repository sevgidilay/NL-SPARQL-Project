# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A research prototype that converts natural language ↔ SPARQL queries bidirectionally, using prompt engineering with the Hactar LLM (hactar.unige.ch — UNIGE's local LLM). Dataset: DBpedia (film/music domain). See `PLAN.md` for full implementation plan.

## Common Commands

```bash
# Install dependencies
pip install -r requirements.txt
python -m spacy download en_core_web_sm

# Run the Streamlit demo
streamlit run app/streamlit_app.py

# Run the CLI
python app/cli.py nl2sparql --input "Who directed Inception?" --strategy few_shot
python app/cli.py sparql2nl --input "SELECT ?d WHERE { dbr:Inception dbo:director ?d }" --strategy chain_of_thought

# Run all tests
pytest tests/

# Run a single test file
pytest tests/test_nl2sparql_pipeline.py -v

# Run the full benchmark (all 24 cells)
python -m src.evaluation.benchmark

# Run benchmark on Tier 1 only (fast smoke test)
python -m src.evaluation.benchmark --tier 1
```

## Architecture

The system has two mirrored pipelines sharing the same LLM and prompt infrastructure:

```
NL input  →  prompt_builder  →  hactar_client  →  postprocessor  →  validator  →  SPARQL output
                                                                           ↓
                                                                       executor  →  results

SPARQL input  →  query_parser  →  prompt_builder  →  hactar_client  →  NL output
```

### Key modules

**`src/llm/`** — shared LLM layer used by both pipelines
- `hactar_client.py`: HTTP client for the Hactar API. All LLM calls go through here.
- `prompt_builder.py`: constructs prompts for all 4 strategies (`zero_shot`, `chain_of_thought`, `schema_hint`, `few_shot`). Takes `(input_text, strategy, direction, examples=None)` and returns a formatted prompt string.

**`src/nl2sparql/`**
- `pipeline.py`: orchestrates NL→SPARQL — calls prompt_builder → hactar_client → postprocessor → validator
- `postprocessor.py`: extracts the SPARQL block from raw LLM output. First tries fenced code block (` ```sparql `), falls back to detecting lines starting with SELECT/PREFIX/ASK/CONSTRUCT.

**`src/sparql2nl/`**
- `pipeline.py`: orchestrates SPARQL→NL — calls query_parser → prompt_builder → hactar_client
- `query_parser.py`: parses SPARQL structure before prompting. Detects query type, projected variables, and complexity flags (OPTIONAL, UNION, subquery present). These flags drive which prompt strategy is applied and inform the feasibility analysis.

**`src/sparql_engine/`**
- `executor.py`: loads `data/raw/dbpedia_sample.ttl` into an rdflib Graph and executes SPARQL queries against it. Returns result rows or an error code.
- `validator.py`: syntax-checks generated SPARQL using rdflib's `prepareQuery` before execution. A query failing validation is logged as a hard failure in benchmarking.

**`src/evaluation/`**
- `benchmark.py`: runs the 4 strategies × 3 tiers × 2 directions = 24-cell evaluation matrix. Writes raw outputs to `data/results/`.
- `metrics.py`: computes Execution Success Rate (ESR) for NL→SPARQL and BLEU-4 + human intelligibility for SPARQL→NL.

### Data format

Query pair files in `data/queries/tier*.json` use this schema:
```json
[
  {
    "nl": "Who directed Inception?",
    "sparql": "SELECT ?d WHERE { dbr:Inception dbo:director ?d . }",
    "tier": 1,
    "notes": "simple single-triple pattern"
  }
]
```

### Prompt strategies

Defined in `src/llm/prompt_builder.py`. The strategy name is always passed as a string parameter — never hardcode strategy logic in the pipelines:
- `zero_shot` — plain instruction only
- `chain_of_thought` — step-by-step reasoning instruction
- `schema_hint` — DBpedia prefixes and key predicates injected into the prompt
- `few_shot` — 3 curated NL/SPARQL example pairs prepended
- `decomposition` — used for Tier 3 queries only; breaks the problem into sub-questions

### Query tiers

- **Tier 1:** Single triple pattern, one named entity, one variable. No FILTER, no joins.
- **Tier 2:** 2-3 triples, at least one join variable, FILTER/ORDER BY/LIMIT allowed.
- **Tier 3:** OPTIONAL, UNION, GROUP BY, COUNT, or subqueries present. `query_parser.py` detects these automatically.

## DBpedia Prefixes

Always use these standard prefixes in generated and reference SPARQL:
```sparql
PREFIX dbo: <http://dbpedia.org/ontology/>
PREFIX dbr: <http://dbpedia.org/resource/>
PREFIX dbp: <http://dbpedia.org/property/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
```

## Style Rules

- Never use emojis anywhere — not in the UI, tab labels, buttons, messages, or code comments.

## Git Identity

```bash
git config --local user.name "Your Name"
git config --local user.email "your.email@etu.unige.ch"
```
