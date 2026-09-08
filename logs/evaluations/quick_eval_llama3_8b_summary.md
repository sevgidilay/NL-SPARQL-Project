# Quick Evaluation Summary — Llama 3 8B

## Command

```bash
python tests/evaluate.py --quick --models "HuggingFace: meta-llama/Meta-Llama-3-8B-Instruct" --save logs/evaluations/quick_eval_llama3_8b.json
```

## Context

Hactar was not responding, so the quick evaluation was run using the Hugging Face Llama 3 8B model only.

## Result File

logs/evaluations/quick_eval_llama3_8b.json

## Detailed Quick Results

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  MODEL: HuggingFace: meta-llama/Meta-Llama-3-8B-Instruct
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  [1/10] List 10 diseases
  [PASS] D01   | EA:✓ RA:✓ F1:1.00 BLEU:0.84 | n=  10 t= 11.4s | List 10 diseases

  [2/10] What are the symptoms of diabetes?
  [PASS] D02   | EA:✓ RA:✓ F1:1.00 BLEU:1.00 | n=   3 t=  3.2s | What are the symptoms of diabetes?

  [3/10] List 10 movies
  [FAIL] M01   | EA:✗ RA:✗ F1:1.00 BLEU:0.85 | n=   0 t= 34.4s | List 10 movies
         error: Exec:Query timed out (30s limit)

  [4/10] List movies directed by Steven Spielberg
  [PASS] M02   | EA:✓ RA:✓ F1:1.00 BLEU:1.00 | n=  38 t= 17.0s | List movies directed by Steven Spielberg

  [5/10] List all planets in our Solar System
  [PASS] A01   | EA:✓ RA:✓ F1:1.00 BLEU:0.44 | n=  10 t=  5.3s | List all planets in our Solar System

  [6/10] List 10 galaxies
  [FAIL] A02   | EA:✗ RA:✗ F1:1.00 BLEU:0.42 | n=   0 t= 31.6s | List 10 galaxies
         error: Exec:Query timed out (30s limit)

  [7/10] List 10 philosophers
  [FAIL] P01   | EA:✗ RA:✗ F1:1.00 BLEU:0.68 | n=   0 t= 32.9s | List 10 philosophers
         error: Exec:Query timed out (30s limit)

  [8/10] Who influenced Immanuel Kant?
  [PASS] P02   | EA:✓ RA:✓ F1:1.00 BLEU:1.00 | n=  14 t=  2.8s | Who influenced Immanuel Kant?

  [9/10] List 10 novels
  [PASS] B01   | EA:✓ RA:✓ F1:1.00 BLEU:0.85 | n=  10 t= 12.9s | List 10 novels

  [10/10] List books written by George Orwell
  [PASS] B02   | EA:✓ RA:✓ F1:1.00 BLEU:1.00 | n=  12 t= 30.5s | List books written by George Orwell
```

## Results

- Execution Accuracy: 70.0%
- Result Accuracy: 70.0%
- Avg Component F1: 1.000
- Avg BLEU: 0.809
- Avg Time: 18.2s

## Notes

This is a quick evaluation snapshot, not the final full evaluation.
The same 10-case quick benchmark was previously run for Qwen2.5-Coder-32B, so this result can be used as an initial comparison point.