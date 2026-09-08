# NL→SPARQL Advanced Evaluation Report
_Generated: 2026-05-17 15:28_

- **Models under test:** HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct
- **Judge model:** HuggingFace: meta-llama/Meta-Llama-3-8B-Instruct
- **Total cases per model:** 20

## Aggregate Metrics

| Model | EA | RA | Comp-F1 | RSM-F1 (n) | RSM-Exact | Judge | CQS |
|---|---|---|---|---|---|---|---|
| `HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct` | 20% | 15% | 0.200 | 0.500 (4/20) | 50% | 0.617 | **0.138** |

## By Category

Categories separate ordinary baseline questions from harder probes (typos, ambiguous wording, cross-domain) so the headline accuracy is not diluted.

| Model | Category | n | EA | RSM-F1 | GTC | Judge | CQS |
|---|---|---|---|---|---|---|---|
| `HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct` | baseline | 18 | 22% | 0.500 | 1.000 | 0.617 | **0.154** |
| `HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct` | robustness | 2 | 0% | 0.000 | 0.000 | 0.000 | **0.000** |

## By Domain

| Model | Domain | n | EA | RSM-F1 | CQS |
|---|---|---|---|---|---|
| `HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct` | Astronomy (Wikidata) | 2 | 0% | 0.000 | 0.000 |
| `HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct` | Books (DBpedia) | 2 | 0% | 0.000 | 0.000 |
| `HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct` | Diseases | 2 | 100% | 0.500 | 0.784 |
| `HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct` | Geography (Wikidata) | 2 | 0% | 0.000 | 0.000 |
| `HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct` | Movies (DBpedia) | 2 | 100% | 0.500 | 0.601 |
| `HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct` | Music (Wikidata) | 2 | 0% | 0.000 | 0.000 |
| `HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct` | Philosophy (Wikidata) | 2 | 0% | 0.000 | 0.000 |
| `HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct` | Scientists & Nobel Prizes (Wikidata) | 2 | 0% | 0.000 | 0.000 |
| `HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct` | Sports (Wikidata) | 2 | 0% | 0.000 | 0.000 |
| `HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct` | TV Shows (DBpedia) | 2 | 0% | 0.000 | 0.000 |

## Verdict Breakdown (LLM-as-a-Judge)

| Model | Cases judged | CORRECT | PARTIAL | INCORRECT | UNKNOWN |
|---|---|---|---|---|---|
| `HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct` | 4 | 1 | 2 | 0 | 1 |

## Per-case Detail


### `HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct`

| ID | Question | EA | RSM-F1 | GTC | Judge | Row-Prec | Verdict | CQS |
|---|---|---|---|---|---|---|---|---|
| D01 | List 10 diseases | ✓ | 0.00 | 1.00 | 0.93 | 0.80 | CORRECT | 0.63 |
| D02 | What are the symptoms of diabetes? | ✓ | 1.00 | 1.00 | 0.80 | 0.67 | PARTIAL | 0.94 |
| M01 | List 10 movies | ✓ | 0.00 | 1.00 | 0.73 | – | PARTIAL | 0.45 |
| M02 | List movies directed by Steven Spielberg | ✓ | 1.00 | 1.00 | 0.00 | – | UNKNOWN | 0.75 |
| A01 | List all planets in our Solar System | ✗ | 0.00 | 0.00 | 0.00 | – | UNKNOWN | 0.00 |
| A02 | List 10 galaxies | ✗ | 0.00 | 0.00 | 0.00 | – | UNKNOWN | 0.00 |
| P01 | List 10 philosophers | ✗ | 0.00 | 0.00 | 0.00 | – | UNKNOWN | 0.00 |
| P02 | Who influenced Immanuel Kant? | ✗ | 0.00 | 0.00 | 0.00 | – | UNKNOWN | 0.00 |
| B01 | List 10 novels | ✗ | 0.00 | 0.00 | 0.00 | – | UNKNOWN | 0.00 |
| B02 | List books written by George Orwell | ✗ | 0.00 | 0.00 | 0.00 | – | UNKNOWN | 0.00 |
| AM01 | List 10 football players | ✗ | 0.00 | 0.00 | 0.00 | – | UNKNOWN | 0.00 |
| AM02 | List 10 football clubs | ✗ | 0.00 | 0.00 | 0.00 | – | UNKNOWN | 0.00 |
| TV01 | List 10 TV shows | ✗ | 0.00 | 0.00 | 0.00 | – | UNKNOWN | 0.00 |
| TV02 | Who created Breaking Bad? | ✗ | 0.00 | 0.00 | 0.00 | – | UNKNOWN | 0.00 |
| G01 | List all continents | ✗ | 0.00 | 0.00 | 0.00 | – | UNKNOWN | 0.00 |
| G02 | What is the capital of France? | ✗ | 0.00 | 0.00 | 0.00 | – | UNKNOWN | 0.00 |
| S01 | List 10 scientists | ✗ | 0.00 | 0.00 | 0.00 | – | UNKNOWN | 0.00 |
| S02 | List Nobel Prize winners in Physics | ✗ | 0.00 | 0.00 | 0.00 | – | UNKNOWN | 0.00 |
| MU01 | List 10 musicians | ✗ | 0.00 | 0.00 | 0.00 | – | UNKNOWN | 0.00 |
| MU02 | List albums released by The Beatles | ✗ | 0.00 | 0.00 | 0.00 | – | UNKNOWN | 0.00 |