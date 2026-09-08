# Full Evaluation Summary — Llama 3 8B

## Command

```bash
python tests/evaluate.py --models "HuggingFace: meta-llama/Meta-Llama-3-8B-Instruct" --save logs/evaluations/full_eval_llama3_8b.json
```

## Context

Hactar was not responding, so the full evaluation was run using the Hugging Face Llama 3 8B model only.

## Result File

logs/evaluations/full_eval_llama3_8b.json

## Detailed Full Results

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  MODEL: HuggingFace: meta-llama/Meta-Llama-3-8B-Instruct
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  [1/16] List 10 diseases
  [PASS] D01   | EA:✓ RA:✓ F1:1.00 BLEU:0.84 | n=  10 t=  3.4s | List 10 diseases

  [2/16] What are the symptoms of diabetes?
  [PASS] D02   | EA:✓ RA:✓ F1:1.00 BLEU:1.00 | n=   3 t=  3.1s | What are the symptoms of diabetes?

  [3/16] Which drugs are used to treat malaria?
  [PASS] D03   | EA:✓ RA:✓ F1:1.00 BLEU:1.00 | n=  15 t=  4.6s | Which drugs are used to treat malaria?

  [4/16] List diseases with their ICD-10 codes
  [PASS] D04   | EA:✓ RA:✓ F1:1.00 BLEU:0.87 | n=  20 t=  7.1s | List diseases with their ICD-10 codes

  [5/16] Which diseases are caused by bacteria?
  [PASS] D05   | EA:✓ RA:✓ F1:1.00 BLEU:0.59 | n=  20 t=  4.6s | Which diseases are caused by bacteria?

  [6/16] List 10 movies
  [PASS] M01   | EA:✓ RA:✓ F1:1.00 BLEU:0.85 | n=  10 t= 16.0s | List 10 movies

  [7/16] List movies directed by Steven Spielberg
  [PASS] M02   | EA:✓ RA:✓ F1:1.00 BLEU:1.00 | n=  38 t= 27.5s | List movies directed by Steven Spielberg

  [8/16] Who directed Inception?
  [FAIL] M03   | EA:✓ RA:✗ F1:1.00 BLEU:0.75 | n=   0 t= 18.6s | Who directed Inception?

  [9/16] List all planets in our Solar System
  [PASS] A01   | EA:✓ RA:✓ F1:1.00 BLEU:0.65 | n=  10 t=  4.8s | List all planets in our Solar System

  [10/16] List 10 galaxies
  [FAIL] A02   | EA:✗ RA:✗ F1:1.00 BLEU:0.42 | n=   0 t= 33.8s | List 10 galaxies
         error: Exec:Query timed out (30s limit)

  [11/16] Which moons orbit Jupiter?
  [PASS] A03   | EA:✓ RA:✓ F1:0.67 BLEU:0.62 | n=  97 t=  3.1s | Which moons orbit Jupiter?
         missing: ['wd:Q25257']

  [12/16] List 10 philosophers
  [FAIL] P01   | EA:✗ RA:✗ F1:1.00 BLEU:0.68 | n=   0 t= 32.4s | List 10 philosophers
         error: Exec:Query timed out (30s limit)

  [13/16] Who influenced Immanuel Kant?
  [PASS] P02   | EA:✓ RA:✓ F1:1.00 BLEU:1.00 | n=  14 t=  1.5s | Who influenced Immanuel Kant?

  [14/16] List German philosophers born in the 19th century
  [PASS] P03   | EA:✓ RA:✓ F1:1.00 BLEU:0.66 | n=  20 t=  9.4s | List German philosophers born in the 19th century

  [15/16] List 10 novels
  [PASS] B01   | EA:✓ RA:✓ F1:1.00 BLEU:0.85 | n=  10 t= 26.9s | List 10 novels

  [16/16] List books written by George Orwell
  [FAIL] B02   | EA:✗ RA:✗ F1:1.00 BLEU:1.00 | n=   0 t= 32.6s | List books written by George Orwell
         error: Exec:Query timed out (30s limit)
```

## Results

- Cases: 16
- Execution Accuracy: 81.2%
- Result Accuracy: 75.0%
- Avg Component F1: 0.979
- Avg BLEU: 0.800
- Avg Time: 14.3s

## Failed Cases

- M03 — Who directed Inception?: query executed but returned 0 results.
- A02 — List 10 galaxies: query timed out.
- P01 — List 10 philosophers: query timed out.
- B02 — List books written by George Orwell: query timed out.

## Notes

This is the full evaluation result for the Hugging Face Llama 3 8B model.
It uses the same 16-case baseline benchmark as the Qwen2.5-Coder-32B full evaluation, so the results can be compared directly.