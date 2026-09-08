# Quick Evaluation Summary — Qwen2.5-Coder-32B

## Command

```bash
python tests/evaluate.py --quick --models "HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct" --save quick_eval.json
## Context

Hactar was not responding, so the quick evaluation was run using the Hugging Face model only.

## Result File

logs/evaluations/quick_eval_qwen2_5_coder_32b.json

## Detailed Quick Results

```text

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  MODEL: HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  [1/10] List 10 diseases
  [PASS] D01   | EA:✓ RA:✓ F1:1.00 BLEU:0.84 | n=  10 t=  4.5s | List 10 diseases

  [2/10] What are the symptoms of diabetes?
  [PASS] D02   | EA:✓ RA:✓ F1:1.00 BLEU:1.00 | n=   3 t=  2.0s | What are the symptoms of diabetes?

  [3/10] List 10 movies
  [FAIL] M01   | EA:✗ RA:✗ F1:1.00 BLEU:0.79 | n=   0 t= 14.2s | List 10 movies
         error: Exec:Endpoint returned status 400: Virtuoso 37000 Error SP030: SPARQL compiler, line 10: syntax erro

  [4/10] List movies directed by Steven Spielberg
  [PASS] M02   | EA:✓ RA:✓ F1:1.00 BLEU:0.86 | n=  20 t= 11.6s | List movies directed by Steven Spielberg

  [5/10] List all planets in our Solar System
  [PASS] A01   | EA:✓ RA:✓ F1:1.00 BLEU:0.65 | n=  10 t=  3.0s | List all planets in our Solar System

  [6/10] List 10 galaxies
  [FAIL] A02   | EA:✗ RA:✗ F1:1.00 BLEU:0.42 | n=   0 t= 31.9s | List 10 galaxies
         error: Exec:Query timed out (30s limit)

  [7/10] List 10 philosophers
  [PASS] P01   | EA:✓ RA:✓ F1:1.00 BLEU:0.84 | n=  10 t= 18.2s | List 10 philosophers

  [8/10] Who influenced Immanuel Kant?
  [PASS] P02   | EA:✓ RA:✓ F1:1.00 BLEU:0.82 | n=  14 t=  2.1s | Who influenced Immanuel Kant?

  [9/10] List 10 novels
  [FAIL] B01   | EA:✗ RA:✗ F1:1.00 BLEU:0.79 | n=   0 t= 15.2s | List 10 novels
         error: Exec:Endpoint returned status 400: Virtuoso 37000 Error SP030: SPARQL compiler, line 10: syntax erro

  [10/10] List books written by George Orwell
  [PASS] B02   | EA:✓ RA:✓ F1:1.00 BLEU:0.86 | n=  12 t= 10.1s | List books written by George Orwell

  ```


## Results

- Execution Accuracy: 70.0%
- Result Accuracy: 70.0%
- Avg Component F1: 1.000
- Avg BLEU: 0.788
- Avg Time: 11.3s

## Notes

This is a quick evaluation snapshot, not the final full evaluation.
The full evaluation and model comparison can be added later when all models are available.

