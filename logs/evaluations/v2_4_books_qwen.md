# NL→SPARQL Advanced Evaluation Report
_Generated: 2026-05-08 18:02_

- **Models under test:** HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct
- **Judge model:** (none)
- **Total cases per model:** 5

## Aggregate Metrics

| Model | EA | RA | Comp-F1 | RSM-F1 (n) | RSM-Exact | Judge | CQS |
|---|---|---|---|---|---|---|---|
| `HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct` | 100% | 80% | 0.827 | 0.250 (4/5) | 25% | 0.000 | **0.605** |

## By Category

Categories separate ordinary baseline questions from harder probes (typos, ambiguous wording, cross-domain) so the headline accuracy is not diluted.

| Model | Category | n | EA | RSM-F1 | GTC | Judge | CQS |
|---|---|---|---|---|---|---|---|
| `HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct` | baseline | 2 | 100% | 0.500 | 1.000 | 0.000 | **0.700** |
| `HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct` | cross_domain | 1 | 100% | 0.000 | 0.000 | 0.000 | **0.188** |
| `HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct` | extended | 2 | 100% | 0.000 | 0.000 | 0.000 | **0.719** |

## By Domain

| Model | Domain | n | EA | RSM-F1 | CQS |
|---|---|---|---|---|---|
| `HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct` | Books (DBpedia) | 5 | 100% | 0.250 | 0.605 |

## Verdict Breakdown (LLM-as-a-Judge)

| Model | Cases judged | CORRECT | PARTIAL | INCORRECT | UNKNOWN |
|---|---|---|---|---|---|
| `HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct` | 0 | – | – | – | – |

## Per-case Detail


### `HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct`

| ID | Question | EA | RSM-F1 | GTC | Judge | Verdict | CQS |
|---|---|---|---|---|---|---|---|
| B01 | List 10 novels | ✓ | 0.00 | 1.00 | 0.00 | UNKNOWN | 0.40 |
| B02 | List books written by George Orwell | ✓ | 1.00 | 1.00 | 0.00 | UNKNOWN | 1.00 |
| AG03 | Count books written by George Orwell | ✓ | 0.00 | 1.00 | 0.00 | UNKNOWN | 1.00 |
| J01 | List books and their authors | ✓ | 0.00 | 1.00 | 0.00 | UNKNOWN | 0.44 |
| X02 | List books that were adapted into films | ✓ | 0.00 | 1.00 | 0.00 | UNKNOWN | 0.19 |