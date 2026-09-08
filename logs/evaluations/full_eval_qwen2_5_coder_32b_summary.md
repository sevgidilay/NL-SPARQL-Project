# Full Evaluation Summary — Qwen2.5-Coder-32B

## Command

```bash
python tests/evaluate.py --models "HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct" --save full_eval.json
# Full Evaluation Summary — Qwen2.5-Coder-32B

## Command

```bash
python tests/evaluate.py --models "HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct" --save full_eval.json
```

## Context

Hactar was not responding, so the full evaluation was run using the Hugging Face model only.

## Result File

logs/evaluations/full_eval_qwen2_5_coder_32b.json

## Detailed Full Results

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  MODEL: HuggingFace: Qwen/Qwen2.5-Coder-32B-Instruct
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  [1/16] List 10 diseases
  [PASS] D01   | EA:✓ RA:✓ F1:1.00 BLEU:0.84 | n=  10 t=  6.3s | List 10 diseases

  [2/16] What are the symptoms of diabetes?
  [PASS] D02   | EA:✓ RA:✓ F1:1.00 BLEU:0.82 | n=   3 t=  3.2s | What are the symptoms of diabetes?

  [3/16] Which drugs are used to treat malaria?
  [PASS] D03   | EA:✓ RA:✓ F1:1.00 BLEU:0.82 | n=  15 t=  2.6s | Which drugs are used to treat malaria?

  [4/16] List diseases with their ICD-10 codes
  [PASS] D04   | EA:✓ RA:✓ F1:1.00 BLEU:0.87 | n=  20 t=  7.4s | List diseases with their ICD-10 codes

  [5/16] Which diseases are caused by bacteria?
  [PASS] D05   | EA:✓ RA:✓ F1:1.00 BLEU:0.59 | n=  20 t=  6.2s | Which diseases are caused by bacteria?

  [6/16] List 10 movies
  [PASS] M01   | EA:✓ RA:✓ F1:1.00 BLEU:0.85 | n=  10 t= 34.9s | List 10 movies

  [7/16] List movies directed by Steven Spielberg
  [PASS] M02   | EA:✓ RA:✓ F1:1.00 BLEU:0.86 | n=  20 t= 14.6s | List movies directed by Steven Spielberg

  [8/16] Who directed Inception?
  [PASS] M03   | EA:✓ RA:✓ F1:1.00 BLEU:1.00 | n=   1 t= 19.9s | Who directed Inception?

  [9/16] List all planets in our Solar System
  [PASS] A01   | EA:✓ RA:✓ F1:1.00 BLEU:0.65 | n=  10 t=  4.7s | List all planets in our Solar System

  [10/16] List 10 galaxies
  [FAIL] A02   | EA:✗ RA:✗ F1:1.00 BLEU:0.42 | n=   0 t= 33.6s | List 10 galaxies
         error: Exec:Query timed out (30s limit)

  [11/16] Which moons orbit Jupiter?
  [PASS] A03   | EA:✓ RA:✓ F1:0.67 BLEU:0.77 | n=  97 t=  2.4s | Which moons orbit Jupiter
         missing: ['wd:Q25257']

  [12/16] List 10 philosophers
  [FAIL] P01   | EA:✗ RA:✗ F1:1.00 BLEU:0.84 | n=   0 t= 43.0s | List 10 philosophers
         error: Exec:Query timed out (30s limit)

  [13/16] Who influenced Immanuel Kant?
  [PASS] P02   | EA:✓ RA:✓ F1:1.00 BLEU:1.00 | n=  14 t=  2.8s | Who influenced Immanuel Kant?

  [14/16] List German philosophers born in the 19th century
  [PASS] P03   | EA:✓ RA:✓ F1:1.00 BLEU:0.91 | n=  20 t= 13.6s | List German philosophers born in the 19th century

  [15/16] List 10 novels
  [FAIL] B01   | EA:✗ RA:✗ F1:1.00 BLEU:0.79 | n=   0 t=  6.4s | List 10 novels
         error: Exec:Endpoint returned status 400: Virtuoso 37000 Error SP030: SPARQL compiler, line 10: syntax erro

  [16/16] List books written by George Orwell
  [PASS] B02   | EA:✓ RA:✓ F1:1.00 BLEU:0.86 | n=  12 t=  9.8s | List books written by George Orwell
```

## Results

- Cases: 16
- Execution Accuracy: 81.2%
- Result Accuracy: 81.2%
- Avg Component F1: 0.979
- Avg BLEU: 0.807
- Avg Time: 13.2s

## Notes

This is the full evaluation result for the Hugging Face Qwen2.5-Coder-32B model.
Model comparison with Hactar models can be added later when Hactar is available.
