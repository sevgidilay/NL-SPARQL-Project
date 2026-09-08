# Chat Demo Scenarios

Eight representative scenarios covering the main chat features. Run these in order during the demo — each builds on the previous where noted.

---

## 1. Single-turn factual (films)

**Input:** `List 10 thriller series`

**Expected trace:** `detect_domain` → `generate_sparql` → `execute_sparql` → `summarize_results`

**Check:** SPARQL block visible in expander, results table renders, summary answer shown.

---

## 2. Follow-up refinement

**After scenario 1 — Input:** `Now show only the British ones`

**Expected:** Model reads `results_N` artifact from memory summary, calls `generate_sparql` with a FILTER on country/language, executes the refined query.

**Check:** New SPARQL contains a FILTER clause; results are a subset of scenario 1.

---

## 3. Knowledge graph visualisation (/graph slash command)

**After scenario 2 — Input:** `/graph`

**Expected:** No agentic loop. PyVis graph renders inline in the chat bubble using last result set.

**Check:** Graph renders at 480px height; nodes and edges visible.

---

## 4. SPARQL explanation (/explain slash command)

**After scenario 1 or 2 — Input:** `/explain`

**Expected:** No agentic loop. Plain-English explanation of the last generated SPARQL.

**Check:** Response describes the WHERE clause, predicates, and FILTER in natural language.

---

## 5. Music domain question (domain switch)

**Input:** `Who are the members of Pink Floyd?`

**Expected trace:** `detect_domain` (returns music domain) → `generate_sparql` → `execute_sparql` → `summarize_results`

**Check:** Domain correctly switches from films; results list band members.

---

## 6. Model comparison (/compare slash command)

**Input:** `/compare List 5 dystopian novels`

**Expected:** Runs the model-arena pipeline directly. Side-by-side columns, one per model.

**Check:** Multiple columns render with model names and their generated SPARQL.

---

## 7. Loop-safety (deliberate stress test)

**Input:** `What is the meaning of life?` (out-of-domain, no DBpedia answer)

**Expected:** Orchestrator exhausts MAX_ITERATIONS or the model calls `detect_domain` and finds no matching domain, then produces a graceful fallback final answer.

**Check:** No infinite loop; fallback message displayed within ~30 s; trace shows attempted steps.

---

## 8. Parse-error recovery (edge case)

Run with a model known to produce unreliable JSON (e.g. `qwen3:8b` if available).

**Input:** `Who directed Interstellar?`

**Expected:** If the model emits malformed JSON, the trace shows a `[JSON parse error]` step and a corrective observation; the model recovers on the second attempt and completes the pipeline.

**Check:** `[JSON parse error]` label visible in "View tool trace"; final answer still produced.
