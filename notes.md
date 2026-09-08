# Ideas

- Chat-based UI with a side panel showing query graphs
- Add streaming support for LLM responses

---

# Fix notes — sparql_to_nl.py (branch: kmr)

All changes are in `src/sparql_to_nl.py`.

## 1. WHERE body extraction was broken

The original regex `WHERE\s*\{(.*?)\}` used a non-greedy `.*?` which stopped
at the **first** `}` found. Any query with a `SERVICE` block has a `}` inside
WHERE, so the regex captured only the text up to that inner brace and missed
everything after it.

**Fix:** Strip `SERVICE { ... }` blocks first, then use greedy `(.*)` to
capture the full WHERE body up to the outermost `}`.

## 2. Arrow notation in rule-based output

The rule-based function built descriptions like:
`disease → instance of → wd:Q12136`
using `→` arrows and raw SPARQL identifiers.

**Fix:** Rewrote the sentence builder with three templates depending on which
end of a triple is fixed:
- Fixed subject entity → "This query retrieves the director of Inception."
- Fixed object entity  → "This query searches for films where the director is Steven Spielberg."
- Both variables (join) → "This query searches for writers along with their notable work."

## 3. Internal identifiers exposed in output

Wikidata QIDs (`wd:Q12136`) and prefixed URIs (`dbo:director`) appeared raw.

**Fix:**
- `_extract_entity_labels()` reads `wd:Q... = "label"` lines from
  `ontology_hints` and maps QIDs to human labels.
- Any QID not in the config lookup triggers immediate LLM fallback.
- Any `wdt:P...` property not in the config also triggers LLM fallback
  (otherwise it renders as meaningless "p106").
- DBpedia entity names (`dbr:Steven_Spielberg`) are decoded by stripping the
  prefix and replacing underscores → "Steven Spielberg".

## 4. Type detection was missing

`?var a dbo:Film` (the `a` shorthand for `rdf:type`) was not recognised by the
triple regex (`\w+` does not match the bare keyword `a`). Wikidata type
declarations (`?disease wdt:P31 wd:Q12136`) were also undetected.

**Fix:**
- Added a dedicated `type_re` pattern that matches both `a` and `rdf:type`.
- Added a `p31_re` pass that reads `wdt:P31 wd:Q...` as "instance of `<type>`"
  and populates `var_types`.
- Redundant constraints are removed: if the subject is already "diseases",
  "instance of disease" is not added as a separate clause.

## 5. Display-label variables polluted content selection

Variables like `?filmLabel`, `?directorName`, `?name` are display aliases, not
semantic results. Including them caused the wrong variable to be the subject,
producing "show names along with their network" instead of "television shows".

**Fix:** Variables ending in `label` or `name` are filtered out. When all
SELECT variables are display aliases, the semantic variable is recovered from
`var_types` populated during WHERE body analysis.

## 6. Pluralisation of class names

`dbo:Country` produced "countrys", `dbo:City` produced "citys".

**Fix:** Added `_pluralize()` with an irregular-plural table.

## 7. Config label formats

`_extract_property_labels()` only matched `= "quoted"` format. Several domain
configs (TV Shows, Books) use an em-dash format:
`dbo:starring — cast member / actor`.

**Fix:** Added a second regex for the em-dash format. `_clean_label()` then
takes the first slash alternative and strips parenthetical notes
(`"capital (of a country)"` → `"capital"`).

## 8. LLM prompt had no rules

The old prompt gave no constraints, so the LLM sometimes produced arrow
notation, exposed raw URIs, or described triple structure instead of intent.

**Fix:** Added 5 explicit rules to the prompt:
1. Never expose prefixed URIs — translate to human meaning.
2. Never use arrow notation.
3. Describe what is searched, not how triples are structured.
4. Mention filters/limits only when they add meaningful context.
5. Keep to 2–4 sentences, no bullet points.

## 9. Debug prefixes leaked into the UI

`translate()` returned `"[Rule-based] This query lists films."` — an
implementation detail visible to users.

**Fix:** Removed the `[Rule-based]` and `[LLM-generated]` prefixes.
`translate()` now returns the explanation text directly.

---

## Open Bugs

---

###  Bug I - Exclusion / Negation Only Works with Exact Entity ID

**Symptom:** Natural language queries like "List scientists who are not physicists" or "Diseases excluding cancer" either return wrong results (cancer still appears) or fail silently, unless the user happens to provide the exact Wikidata ID in the question (e.g. "excluding wd:Q12078").

**Root cause:** The generated SPARQL uses `FILTER(?x != "cancer")` or similar string comparison instead of `FILTER(?x != wd:Q12078)`. String matching against URIs always fails, so the filter has no effect.

**Fix needed:** Inject an entity-linking step before SPARQL generation — resolve entity names in FILTER/negation clauses to their canonical URIs before passing to the LLM, or add a schema_hint example that demonstrates the correct `FILTER(?x != wd:Q...)` pattern.



---

## Testing Log — 

### Bug A — Autodetect Maps Scientists to Wrong Domain (Main Branch)

**Symptom:** On the main branch, Dilay's autodetect maps "List 10 scientists" to the astronomy domain. Results include Pokémon scientists, LGBT people in science, and power engineering scientists — no real scientist names returned.

**Status:** Open — found 2026-04-22

---


**Root cause:** Incorrect entity IDs mapped in `configs/*.yaml` files for the Wikidata sports domain.

**Fix needed:** Audit and correct sport entity IDs in the Wikidata config YAML files.

**Status:** Open — found 2026-04-22

---

### Bug C — "Use This" Button Does Nothing When Search Bar Has Existing Text

**Symptom:** When the search bar already contains text, clicking the "Use this" button on an example card has no effect. Expected behaviour: the button should replace whatever is in the search bar with the example query.

**Status:** Open — found 2026-04-22

---

### Bug D — Piano Musician Queries Return Actors/Directors (Music Domain)

**Symptom:** "List 10 piano musicians" returns no meaningful results even after the `?person wdt:P31 wd:Q5` human type constraint was added. "List 10 pianists" returns a list of actors and directors instead of pianists.

**Root cause (suspected):** The instrument/occupation property path used in the generated SPARQL doesn't correctly target pianists. The `wdt:P31 wd:Q5` constraint filters to humans but doesn't narrow to the correct occupation or instrument property.

**Fix needed:** Add a schema hint or few-shot example that demonstrates the correct Wikidata property path for musicians by instrument (e.g. `wdt:P1303 wd:Q5994` for piano as instrument played, combined with `wdt:P31 wd:Q5`).

**Status:** Open — found 2026-04-22

---

### Bug E — Domain Resets to Scientists After Selecting Example Question

**Symptom:** When a domain is manually selected from the dropdown and the user clicks one of the example questions, the question is correctly copied into the search box, but the UI then switches back to the scientists/default domain. The domain selection should remain on whichever domain the user chose.

**Root cause:** `_replace_widget_text` set `session_state["nl_input"]` directly inside a button `on_click` callback. In Streamlit 1.x, writing any widget key from inside `on_click` can cause other widget-owned keys (including `selected_domain`) to reset to their default value on the rerun.

**Fix:** Replaced the direct write with a pending pattern (same as `_pending_model`). The `_use_example` callback stores the question and current domain in `_pending_nl_input` / `_pending_domain`. At the top of the script — before any widget is instantiated — these are applied to `nl_input` and `selected_domain`. The selectbox then renders with the correct domain.

**Status:** Fixed — 2026-04-30

---

### Bug F — SPARQL-to-NL Explanation Is Unclear

**Symptom:** The natural language explanation generated in the SPARQL→NL tab does not clearly summarise what the SPARQL query does. The output is difficult to understand and does not read as a plain-English description of the query intent.

**Fix needed:** Review and improve the summarisation prompt in the SPARQL→NL pipeline so the output is a concise, plain-English explanation of what the query retrieves.

**Status:** Open — found 2026-04-29

---

### Bug G — Example Questions Do Not Return Results for All Domains

**Symptom:** The example question cards shown for some domains do not return any results when executed. It has not been verified that every domain's example questions produce valid, non-empty answers.

**Fix needed:** Run each example question across all domains and confirm they return expected results. Replace or fix any example that returns zero results.

**Status:** Open — found 2026-04-29

---

## Bug H - Zero-Result Queries (retested, fixed)

1) "List Olympic gold medalists in athletics"
- Returned 0 results.
- Earlier hypothesis: Wikidata medal data uses `wdt:P166` (award received) + `wd:Q319921` (Olympic gold medal), so the generated query probably used the wrong dataset/property pattern.
- 2026-05-15 retest: this hypothesis was wrong. Live Wikidata labels show `wd:Q15243387` is "Olympic gold medal" and `wd:Q319921` is "Bückeburg station". The current sports YAML uses `wdt:P166 wd:Q15243387` and returns rows.
- Status: Fixed/no config change needed for the medal QID.

---


---

## What Still Needs Testing

- **Model switching** — confirm the selected model actually changes LLM responses (not just UI state). Try a query on `llama3.3:latest` vs another model and compare outputs.
- **Retry logic** — Bug #2 (intermittent no-result) has no retry yet; needs at least 1–2 auto-retries before surfacing failure to the user. Also, this retry query needs to be cross checked to see if it is valid.
- **Fictional entity filter** — `wdt:P31 wd:Q5` type constraint added to prompt and needs to be tested more with different type of questions relating to persons that could have fictional answers.
- **SPARQL → NL rule-based path** — only tested via LLM fallback; the rule-based branch needs queries that actually match its regex patterns.
- **Dark mode** — visual check across all card/tag/alert states.
- **Domain switching** — verify that changing domain updates example cards and endpoint correctly without stale cache.

---

## Fixes Applied

### Bugs #4/#5 — Hallucination in Summaries (strict grounding prompt)

**Fix:** Rewrote the summarizer prompt in `src/answer_summarizer.py` to strictly ground the LLM to the returned rows. Key additions:
- Framed the data block as "the ONLY facts you may use"
- Explicit rule: do not invent, infer, or recall names/IDs/dates from training data
- Explicit rule: if the table lacks enough info, say so rather than guessing
- URI columns were already filtered out before sending to the LLM (label-only), removing a vector for ID hallucination (Bug #5)

**Why this works:** The previous prompt said "synthesize the results" with no prohibition on adding outside knowledge. The LLM filled gaps from training memory. The new prompt closes that door explicitly.

---

### Bug #7 — Domain Selector Grouped and Moved to NL→SPARQL Tab

**Fix:** Moved the domain selector out of the sidebar and into the NL→SPARQL tab (tab1), right next to the translate button. Domains are now grouped under Wikidata and DBpedia section headers. Selecting a separator snaps to the first domain in that group via an `on_change` callback. "Auto" option removed — a keyword mapping approach would never cover enough cases reliably; defaults to the first Wikidata domain on load.

The sidebar retains the endpoint display (reads from session state), model selector, options, and dark mode toggle.

---

### Bug #8 — Domain Tag Removed from SPARQL→NL Cards

**Fix:** Removed the `<span class="qx-tag qx-tag-domain">` pill from the SPARQL→NL example cards in `app.py`. The NL→SPARQL cards keep their domain pill (it's useful context there). The SPARQL→NL cards don't need it — the query already describes the domain, and the global sidebar selection makes the tag redundant.

---

### Bug #9 — Duplicate Rows (DISTINCT injection)

**Fix:** Added automatic `DISTINCT` injection inside `clean_sparql()` in `src/sparql_executor.py`. After extracting the SPARQL from LLM output, if the query starts with `SELECT` and does not already contain `DISTINCT`, and does not use any aggregation function (`COUNT`, `SUM`, `AVG`, `MIN`, `MAX`) or `GROUP BY`, the function rewrites `SELECT` → `SELECT DISTINCT` via regex.

**Why this works:** Multi-valued properties in Wikidata/DBpedia cause Cartesian-product-style row duplication when the LLM omits `DISTINCT`. Applying it centrally in post-processing means every query benefits without touching any prompt.

**Edge cases handled:** Aggregation queries are excluded because `SELECT DISTINCT COUNT(...)` is semantically wrong and would change query intent.

### Bug #10 — Sports Domain Returns Wrong Athletes (Entity ID Mismatch in Config)

**Symptom:** Queries for tennis players consistently return basketball players or irrelevant results:
- "List 10 tennis players" → Ivan Nestaval (not a tennis player), Andre Roberts (basketball), Pari Naghipoor (basketball), Joan Riera (basketball)
- "List 10 tennis athletes" → basketball players
- "List 10 tennis persons" → basketball players (all unknown)
- "List 10 soccer players" → no results
- "List 10 footballers" → returns tennis players

Tennis players and tennis as a sport do exist on Wikidata.

This case has been solved and the required queries written below has been tested. 

**Fix:** Corrected the Wikidata entity IDs and sports-specific examples in `configs/wikidata_sports.yaml`. The previous configuration caused the LLM to map sports terms such as tennis, basketball, football, and athletes to incorrect Wikidata entities, which led to wrong SPARQL queries and irrelevant results. The sports domain config was updated with the correct Wikidata IDs, especially `wd:Q847` for tennis, `wd:Q5372` for basketball, `wd:Q2736` for association football/soccer, and `wd:Q937857` for association football player. The few-shot examples were also rewritten to use the correct Wikidata properties such as `wdt:P641` for sport and `wdt:P106` for occupation.

**Why this works:** The LLM relies heavily on the domain configuration and few-shot examples when generating SPARQL queries. If the entity IDs in the config are wrong or misleading, the generated queries may still be syntactically valid but semantically incorrect. By replacing the incorrect IDs with the correct Wikidata entities and adding tested examples for tennis, basketball, and football players, the model now generates queries that target the intended sport instead of returning athletes from unrelated domains.

**Edge cases handled:** Football/soccer players are handled using `wdt:P106 wd:Q937857` because “football player” is best represented as an occupation in Wikidata. Tennis and basketball players are handled using `wdt:P641` with the correct sport entity, because many athletes are categorized by the sport they play rather than a sport-specific occupation. The examples also include filters such as country of citizenship and birth date to ensure that more complex sports queries still use the corrected entity mappings.

## Zero-Result Queries (confirmed, FIXED) 

### "List 10 football players"
- Returned 0 results.
- Likely cause: model generates a query using `dbo:sportsNumber` or `dbo:position` without a broad enough type constraint; football players may not match the label/property path used.
**Fixed:** 




### 7. Knowledge Graph is Problematic

**Symptom:** Raw results are valid but the graph creation is not working properly.
 When the graph was not loaded, a proper raw data was visible, but it's graph is not accurate.

**Root cause:** The current query returns a flat list—just “scientist + name.” There are no relationships (edges). The Knowledge Graph tab expects relational data in the format “X → relationship → Y”. However, since the query only returns a single-column list like “James Watson, George E. Smith, Max Noether...”, PyVIS draws each row as a separate node and creates meaningless connections between them. Additionally, the URI and label appear as separate nodes (which is why the names appear twice).

**Fix:**
 Mode 1 — Relational graph (2+ URI columns): A source → target network. Works for queries like “Diseases & treatments.”
Mode 2 — Star graph (1 URI column): This is what you want. It places a large orange concept node in the center (derived from the variable name: ?novel → “Novels”), then connects each result to it. Works for simple lists like “List 10 novels.”

**Status:** Partially fixed — further bugs identified and fixed 2026-05-01 (see “Knowledge Graph / TTL Consistency Fixes” below).

---

### Knowledge Graph Export for Protege

**Fix:** Added `rdflib` as a project dependency and introduced a Turtle export option in the Knowledge Graph tab. After a graph query is visualized, the app now provides a `Download Turtle (.ttl)` button so the generated graph can be opened in Protege.

**How it works:** The app converts the same rows used by the PyVis visualization into RDF triples. Wikidata IDs such as `Q12136` are expanded back into full Wikidata entity URIs, existing DBpedia/full HTTP URIs are preserved, and available label columns are exported as `rdfs:label` values. For relational graph queries with two entity columns, the exported RDF uses the detected source and target columns as subject and object.

**Predicate handling:** When possible, the export infers the predicate URI from the original SPARQL triple pattern, for example `?disease wdt:P2176 ?drug`. If no clear predicate can be inferred, it falls back to a local project namespace under `https://group-b-lamia.unige.ch/kg/`. For single-column/star graphs, the export creates a central concept node and connects the returned entities with a local `lamia:has_member` relation.

**Protege workflow:** Run a graph query, click `Download Turtle (.ttl)`, then open the downloaded file in Protege using `File > Open`. The individuals, labels, and object-property relationships should be visible from the exported Turtle file.

---

### RDF Dependency and Local Installation Issue

**Problem encountered:** Protege export required RDF serialization, so `rdflib` had to be added to the project dependencies. During local setup, running `pip3 install -r requirements.txt` on macOS produced an `externally-managed-environment` error because the active Python installation was managed by Homebrew/PEP 668.

**Update:** Added `rdflib>=7.0.0` to `requirements.txt` so the project explicitly declares the RDF/Turtle export dependency. The recommended local installation approach is to install the missing dependency through the active Conda environment, for example `conda install -c conda-forge rdflib`, or to run package installation through the correct active Python interpreter with `python -m pip`.

**Why this matters:** Without declaring `rdflib`, the Turtle export feature would work only on machines where the package happened to be installed already. Adding it to `requirements.txt` makes the feature reproducible for other group members and graders.

---

### Graph Rendering Must Stay Independent from Turtle Export

**Problem encountered:** After adding Turtle export, there was a risk that an export failure could interrupt the existing PyVis graph visualization. This was not acceptable because the original Knowledge Graph tab still needed to show the interactive shape even if RDF serialization failed.

**Update:** The PyVis graph rendering and the Turtle export were separated. The visual graph is generated first, and the `.ttl` export is now wrapped in its own error handling block. If RDF export fails, the app shows a warning such as `Graph rendered, but Turtle export failed`, while the visual graph remains visible.

**Related endpoint issue:** A temporary SPARQL endpoint failure returned a raw `502 Bad Gateway` HTML page to the user. The executor was updated to retry temporary gateway errors and to replace raw HTML with a readable message, for example `Endpoint is temporarily unavailable (HTTP 502). Please retry the query in a moment.`

**Why this matters:** The Knowledge Graph tab now has two independent outputs: the interactive PyVis visualization for immediate inspection and the Turtle file for Protege. A failure in one output should not break the other.

---

### Protege OWLViz DOT Dependency

**Problem encountered:** The generated Turtle file opened in Protege, but switching to OWLViz produced repeated errors saying that Protege could not run `/usr/local/bin/dot`. The stack trace came from OWLViz and Graphviz, not from the ontology loader itself.

**Root cause:** OWLViz uses the Graphviz `dot` command to lay out graphs. On macOS, Graphviz may not be installed, or the executable may be located at `/opt/homebrew/bin/dot` instead of `/usr/local/bin/dot`, especially on Apple Silicon machines.

**Update:** This was documented as an environment/setup issue rather than an ontology-generation bug. The ontology had already been processed by HermiT, which confirmed that Protege could load it. The local fix is to install Graphviz with `brew install graphviz` and configure OWLViz to point to the actual `dot` path returned by `which dot`.

**Why this matters:** It separates real ontology export problems from Protege visualization tooling problems. The Turtle file can be valid even when OWLViz cannot draw it because DOT is missing.

---

### Protege Class Graph Only Showed `owl:Thing`

**Problem encountered:** After the Turtle file was loaded in Protege, the individual names were present as instances, but OntoGraf and the class hierarchy view only showed `owl:Thing`. This made the graph look empty or incorrect even though RDF triples existed in the file.

**Root cause:** The first Protege-friendly export declared returned entities as `owl:NamedIndividual`, but it did not create domain-specific OWL classes such as `Philosopher`, `Influence`, `Disease`, or `Drug`. Protege's class-oriented graph views mainly visualize class structure, so a file with only individuals and object-property assertions still appears almost empty in the class graph.

**Update:** The Turtle exporter now creates a lightweight class layer from the SPARQL variable names. For example, a query with `?philosopher` and `?influence` creates local classes under the project namespace, assigns each returned entity to the appropriate class, and declares the relationship as an `owl:ObjectProperty` with `rdfs:domain` and `rdfs:range`.

**Why this matters:** The export now works better with Protege's ontology views. Classes appear in the class hierarchy, individuals appear under their classes in `Individuals by class`, and object-property assertions remain available for inspecting the actual knowledge graph relationships.

---

### Results Table Shown Immediately, Summary After

**Fix:** The results table now appears as soon as the query returns, before the LLM summarizes. Previously the table was only shown after the summary finished generating. Now the user gets raw results instantly and the summary loads below it.

---

### Tab Order + Knowledge Graph Marked Experimental

**Fix:** Moved Knowledge Graph to the 3rd tab (after SPARQL→NL) and labelled it "Knowledge Graph (Experimental)" since it's still rough.

---

### SPARQL→NL Quick Examples Now Cross-Domain

**Fix:** The example cards in the SPARQL→NL tab used to only show examples from whichever domain was currently selected. They now pull one card from each domain config so you get a variety across Wikidata and DBpedia. Domain tag is shown on each card so you know which knowledge base it targets.

---

### Both Endpoints Shown in Sidebar

**Fix:** The sidebar was only showing the endpoint for the currently selected domain. It now lists both Wikidata and DBpedia endpoints, with the active one bold and the inactive one dimmed.

---

### Loading Bar and Witty Messages

**Fix:** Replaced the plain spinner with a proper loading flow. While the LLM is working, an animated bar slides left to right continuously (CSS-based so it keeps moving even when Python is blocked). Between steps it fills to 33% / 66% / 100%. Each step shows a random dry message while running — things like "Bothering Wikidata..." or "Writing SPARQL so you don't have to..." — and ends with "Done. That took Xs."

---

### More Readable Output for No Results (implemented) (Jumainah on 22/04/2026)

**Before:**

```
Generated SPARQL

SELECT DISTINCT ?inventor ?inventorLabel ?invention ?inventionLabel WHERE {
  ?invention rdfs:label "flying car"@en .
  ?inventor wdt:P800 ?invention .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
LIMIT 20

Returned 0 results.
Query executed but returned no rows.
```

**After:** Replace the raw technical message with a friendly explanation, e.g.:

> "No results found for your query. This may mean the information isn't available in the knowledge base, or the query needs to be rephrased." 

Optionally show a "View generated SPARQL" expander for power users.

---

### 1. Fictional Entity in Results (Spider-Man)(Jumainah on 22/04/2026)

**Symptom:** The model returned Spider-Man as a scientist in a list of real scientists.

> "Here's a list of 10 scientists for you. The list includes notable figures like James Watson and George E. Smith... It's worth noting that the list does include a fictional character, Spider-Man, who isn't actually a real scientist."

**Wikidata entity:** http://www.wikidata.org/entity/Q79037

**Root cause (suspected):** The SPARQL query doesn't filter by `rdf:type dbo:Scientist` or equivalent — fictional characters with scientist-adjacent properties slip through.

**Fix needed:** Add type constraints to the generated query (e.g. `?person wdt:P31 wd:Q5` to restrict to humans, or filter against known fictional entity classes).

---

### 2. Intermittent No-Result on Valid Queries (Jumainah on 22/04/2026)

**Symptom:** "Who came up with unified field theory?" returned no results on the first run but succeeded on a rerun with the same query.

**Suspected cause:** Non-deterministic LLM output generating a slightly different (broken) SPARQL on the first attempt, or a transient Wikidata endpoint timeout.

**Fix needed:** Add retry logic (1–2 retries) when the query returns 0 results; optionally surface the raw SPARQL so the user can inspect it.

---

### 3. Model Switching Bug (Jumainah on 22/04/2026)

**Symptom:** TBD — behaviour after switching models needs to be documented.

- Sidebar not letting to change the model. It defaults to the first model in the list and doesn't update when a different model is selected.

---

### Knowledge Graph / TTL Consistency Fixes — 2026-05-01

**Problems observed:** The PyVis graph and the downloaded Turtle (.ttl) file were inconsistent in multiple ways, and the graph rendering itself had several correctness bugs.

**Bug 1 — Duplicate edges in relational graph (PyVis)**
In the relational (2+ URI column) mode, `net.add_edge` was called for every SPARQL result row without checking whether that `(source, target)` pair had already been drawn. Multi-valued properties in Wikidata produce one row per value, so the same pair could appear many times, producing a visually cluttered graph with stacked edges. The Turtle export had no duplicates because rdflib deduplicates triples automatically — this was the most visible PyVis ≠ TTL mismatch.

**Fix:** Added `_edge_set` to track added `(sid, tid)` pairs; `net.add_edge` is now called at most once per unique pair. The displayed edge count now reflects actual deduplicated edges.

**Bug 2 — URI value written as `rdfs:label` in TTL**
`label_map.get(src_k, src_k)` was used as the label-column lookup key. When no `?srcLabel` column existed the fallback was `src_k` itself, so `row[src_k]` (a full Wikidata URI) was written as the `rdfs:label` of the entity. This produced labels like `http://www.wikidata.org/entity/Q12345` in Protege.

**Fix:** Changed to `label_map.get(src_k)` (returns `None` when no label column exists). Labels are now only added to the TTL when a true label column is present; the guard became `if src_lk and row.get(src_lk)`.

**Bug 3 — Star graph center node name mismatch between PyVis and TTL**
PyVis used `entity_k.upper() + "S"` (e.g. `"NOVELS"`) while TTL used the same uppercase logic. Both were changed to `_humanize_var_name(entity_k) + "s"` so the label is properly capitalised (e.g. `"Novels"` instead of `"NOVELS"`) and the two representations are now identical.

**Bug 4 — Star graph edge count reported incorrectly**
The "N nodes · M edges" summary below the star graph reported `len(rows)` as edge count, which counted duplicate entries and did not subtract the central concept node. Fixed to `len(_added) - 1` (actual unique entity nodes added).

**Bug 5 — `None` string rendered as node label**
`_row.get(src_lk, sid)` fell through to `sid` correctly, but when the label column existed and held an empty/None value the result was the string `"None"`. Fixed with `(_row.get(src_lk, "") or sid)` so the fallback is always the URI, never the word "None".

**Files changed:** `app.py` — `build_turtle_export`, relational graph block, star graph block.

---

### Hugging Face Serverless Inference Router Fix

**Problem encountered:** When integrating Hugging Face models using the user's `HF_API_KEY`, attempting to use `aksw/text2sparql-S`, `mistralai/Mistral-7B-Instruct-v0.2`, and `HuggingFaceH4/zephyr-7b-beta` resulted in Hugging Face API errors:
1. `403 {"error":"This authentication method does not have sufficient permissions to call Inference Providers..."}`
2. `{"error":{"message":"The requested model '...' is not supported by any provider you have enabled.","code":"model_not_supported"}}`

**Root cause:** 
1. The user's token lacked permissions. By default, Hugging Face tokens are read-only.
2. The Hugging Face OpenAI-compatible Serverless Router (`https://router.huggingface.co/v1/chat/completions`) only supports a curated list of actively maintained models (like Llama-3, Qwen-2.5, DeepSeek-R1, etc). Older models like Zephyr and Mistral v0.2 have been deprecated from the free router pool to make room for newer models.

**Update:**
- Guided the user to create a new "Fine-grained" token with "Make calls to the Serverless Inference API" enabled.
- Updated the Hugging Face endpoint in `src/llm_client.py` to the official router URL `https://router.huggingface.co/v1/chat/completions`.
- Replaced the unsupported models with high-performing, currently-supported models (`Qwen/Qwen2.5-Coder-32B-Instruct` and `meta-llama/Meta-Llama-3-8B-Instruct`).

**Why this matters:** This ensures the prototype can successfully route SPARQL generation tasks to state-of-the-art Hugging Face models without throwing `model_not_supported` errors, allowing direct performance comparisons against the local Hactar models.

---

### DBpedia Resources with Parentheses Cause SPARQL Syntax Error

**Symptom:** Queries involving genres or shows whose DBpedia resource name contains parentheses — e.g. "List 15 thriller series" — fail with a Virtuoso error:

```
Virtuoso 37000 Error SP030: SPARQL compiler, line 4: syntax error at '(' before 'genre'
```

The generated query used `dbr:Thriller_(genre)`, which is syntactically invalid SPARQL because prefixed names cannot contain parentheses.

**Root cause:** SPARQL prefixed-name syntax (defined in the W3C grammar) forbids parentheses inside a `prefix:local` token. The LLM was following the config's known-genre table verbatim (`Thriller -> dbr:Thriller_(genre)`), which looked correct but produced invalid SPARQL. The same problem affects any DBpedia resource whose name includes parentheses (show disambiguators like `_(TV_series)`, `_(American_TV_series)`, etc.).

**Fix (`configs/dbpedia_tv_shows.yaml`):**
1. Added Rule 8 to `ontology_hints` — explicitly instructs the LLM that any resource name containing parentheses must use full URI syntax in angle brackets (`<http://dbpedia.org/resource/Thriller_(genre)>`) instead of the `dbr:` prefix shorthand.
2. Updated all affected entries in the "Known Show Resources" and "Known Genre Resources" tables to show the correct full URI form (affects: The Office, Lost, Dexter, 24, House of Cards, Sherlock, Westworld, The Crown, and Thriller).
3. Added a "List 15 thriller series" few-shot example using the correct full URI, so the LLM has a concrete in-context example to follow for this exact pattern.

**Why this works:** The LLM generates what the config tells it. Showing the wrong short form (`dbr:Thriller_(genre)`) in the known-resources table is enough to make the LLM reproduce it. Replacing those entries with the full URI form and adding an explicit rule + a matching example closes all three reinforcement paths (rule, reference table, few-shot) simultaneously.

---

---

## Arena Tab — Full Overhaul (branch: arenak)

All changes are in `app.py` and `src/nl_to_sparql.py`.

### 1. New helper functions in `src/nl_to_sparql.py`

**`build_retry_prompt(question, config, failed_sparql)`**
When the first generated SPARQL returns zero results or has a syntax/execution error, a second attempt is made with a different prompt. The retry prompt shows the broken query and explicitly instructs the model to stop guessing hardcoded entity IDs (e.g. `wd:Q12345`, `dbr:Inception`) and instead use label-based matching (`rdfs:label` with `FILTER` or `VALUES`). This catches the most common cause of empty results: the LLM hallucinating an entity ID that does not exist in the knowledge base.

**`explain_query(sparql, question, model)`**
Calls the LLM with a short prompt asking it to summarise what the SPARQL query retrieves in exactly one sentence. This is always called after the final SPARQL is produced (whether from the first attempt or the retry) and shown under "What it does:" in each model's column.

**`results_to_nl(question, results, model)`**
Takes the first five result rows and calls the LLM to answer the original question in one natural language sentence using only those rows. This gives each model column a human-readable answer instead of just a count. If the query returned no results, the answer is hardcoded to "No answer found" without an extra LLM call.

---

### 2. Arena — model selector

Added a `st.multiselect` above the question input showing all `MONITORED_MODELS`. All models are pre-selected by default. The user can deselect any model whose server is unavailable before running. The Compare button is disabled if no models are selected. All internal references to `MONITORED_MODELS` inside the button block were replaced with `selected_models` so column counts, thread pool size, and future submission all respect the user's choice.

---

### 3. Arena — extended retry logic

Previously the retry only fired when `success=True` and `row_count=0`. It now also fires when `success=False` (i.e. SPARQL syntax or execution error). In both cases the same `build_retry_prompt` is used. The retry result replaces the original only if it both succeeds and returns at least one row — otherwise the original result is kept. A `[Retried]` badge is displayed next to the status line when the retry was adopted.

---

### 4. Arena — NL answer always shown

Previously `nl_answer` was only populated when the query succeeded and returned rows. Now every model column always shows an answer:
- Query succeeded with rows → `results_to_nl()` produces a natural language sentence.
- Query failed or returned zero rows after retry → `"No answer found"` is shown directly without an extra LLM call.

---

### 5. Arena — response consistency check

Each model runs the same translation a second time inside its thread. The first answer value (preferring `*Label` columns) from both runs is compared. If they match, the model is marked **Consistent: yes**; if they differ, **Consistent: no**; if one or both runs returned no results, **Consistent: N/A**. This column appears in the comparison summary table. Note: this doubles the number of LLM calls per model, which adds latency, but since all models run concurrently the wall time is bounded by the slowest model rather than multiplied.

---

### 6. Arena — result rows table

When a model returns results, the actual rows (capped at 10) are rendered as a `st.dataframe` directly in that model's column, below the NL answer. Previously only the row count was shown.

---

### 7. Arena — richer comparison summary table

The summary table after all models finish now has 9 columns:

| Column | Description |
|---|---|
| Model | Model name |
| Status | "OK" or "FAIL" |
| Rows | Number of result rows returned |
| Time (s) | Total wall time including retries, explanation, consistency check |
| Complexity | Approximate count of triple patterns in the WHERE clause (regex heuristic) |
| Consistent | "yes" / "no" / "N/A" from the consistency check |
| Retried | "yes" if the retry attempt was adopted |
| Winner | "Best" on the fastest model that returned results |
| Agreement | "Agree" if all successful models returned the same first answer; "Differ" if they diverged; "N/A" if no model got results |

Rows are sorted: successful models first, then by row count descending, then by time ascending.

---

### 8. Arena — user voting with persistent leaderboard

After the comparison runs, a voting section appears below the summary table. It persists across reruns using `st.session_state["arena_results"]` so clicking "Submit Vote" does not clear the results.

**Storage:** `logs/arena_votes.json` — a JSON array of objects with `question`, `model`, and `ts` (ISO timestamp). The file is created on first vote.

**Vote helpers (defined inside `with tab4:`):**
- `_load_votes()` — reads the JSON file; returns `[]` on missing or corrupt file.
- `_save_vote(question, model)` — appends one record and rewrites the file atomically.
- `_leaderboard()` — aggregates vote counts per model and returns a sorted list for display.

**UI:** A horizontal radio group with one option per model that ran, plus "None are correct". One "Submit Vote" button. After submission a success message is shown. Below the voting UI, an **All-time leaderboard** table shows total vote counts for all models across all sessions.

---

### 9. Minor: sparql_to_nl.py prompt length

Reduced the LLM explanation length instruction from "2–4 sentences" to "2–3 sentences" to keep SPARQL→NL tab outputs more concise.

---

### List Queries Always Return the Same Rows

**Symptom:** Repeating the same natural language query (e.g. "list 10 thriller series") always returns identical rows in the same order, even across separate button clicks.

**Root cause (two compounding factors):**
1. The LLM is called at low/default temperature and deterministically generates the same SPARQL string every time.
2. DBpedia's public Virtuoso endpoint caches query results by exact query string. Because the same string arrives on every request, the endpoint serves the cached result set without re-executing the query — so even adding `ORDER BY RAND()` to the query text had no effect.

**Fix (`src/sparql_executor.py`):**
1. `ORDER BY RAND()` injection — `clean_sparql()` now automatically inserts `ORDER BY RAND()` before any `LIMIT` clause when the query has no existing `ORDER BY` and no `GROUP BY`. This ensures Virtuoso randomises the result set when a fresh execution does occur.
2. Cache-busting comment — `execute()` prepends a unique random integer comment (e.g. `# 1482736591`) to the cleaned query before sending it to the endpoint. The SPARQL semantics are completely unchanged, but the query string is different on every request, so the endpoint's cache is bypassed and `ORDER BY RAND()` takes effect every time.

**Why this works:** SPARQL endpoints key their result cache on the exact query string. A unique comment makes each request look like a new query, forcing a fresh execution. Combining this with `ORDER BY RAND()` guarantees both that the endpoint re-runs the query and that it returns a different random sample of rows each time.

---

### Auto-detect Maps Neighbour / Türkiye Queries to TV Shows (Fixed — 2026-05-13)

**Symptom:** Queries like "Count the number of neighbours of Türkiye" were auto-detected as "TV Shows (DBpedia)" instead of "Geography (Wikidata)". The keyword matcher had no score for geography and was falling through to LLM classification, which then picked the wrong domain.

**Root cause (two compounding factors):**
1. "neighbour/neighbors/Türkiye" were not in the geography keyword list, so the keyword pre-filter scored 0 for geography.
2. The keyword matcher used plain substring matching (`kw in question`). The 3-letter keyword `HBO` matched as a substring inside "neig**HBO**urs", giving TV Shows a spurious score of 1. The LLM fallback then broke the tie incorrectly.

**Fix:**
1. `configs/wikidata_geography.yaml` — Added `neighbour`, `neighbours`, `neighbor`, `neighbors`, `neighbouring`, `neighboring`, `adjacent`, `turkey`, `türkiye` to the keywords list.
2. `src/domain_router.py` — Changed keyword matching from plain substring (`kw in question_lower`) to regex word-boundary matching (`re.search(r'\b' + re.escape(kw) + r'\b', question_lower)`). This prevents short keywords like `HBO` from matching inside longer words.

**Why this works:** The geography domain now scores positively for any neighbour/border/Türkiye question before the LLM fallback is reached. The word-boundary fix eliminates false positives from short keywords being substrings of unrelated words.

---

### Geography Domain Hallucinating Wrong Neighbours (Fixed — 2026-05-13)

**Symptom:** "Count neighbours of Georgia and say their names" returned Andorra as the only neighbour of Georgia with count=1 — completely wrong. Georgia (country) shares borders with Russia, Turkey, Armenia, and Azerbaijan.

**Root cause:** The geography config had no few-shot example for border/neighbour queries. Without a concrete pattern to follow, the LLM hallucinated a wrong SPARQL structure using incorrect properties and entity IDs. The Wikidata property for "shares border with" (`wdt:P47`) was also not documented in the ontology hints.

**Fix (`configs/wikidata_geography.yaml`):**
1. Added `wdt:P47 = "shares border with"` to `ontology_hints`, along with an explicit note on the correct query pattern (match country by `rdfs:label`, traverse `wdt:P47`, filter neighbours to `wdt:P31 wd:Q6256`).
2. Added three few-shot examples:
   - "List the neighbouring countries of France" — basic list pattern
   - "Count the number of neighbours of Germany" — aggregate COUNT pattern
   - "Count neighbours of Turkey and say their names" — list with SERVICE label

**Why this works:** The LLM relies on few-shot examples for unfamiliar property patterns. Without `wdt:P47` shown explicitly, it invents a wrong path. The examples give it a verified template to follow for any neighbour query.

---

### Sports Domain Config Audit and Hallucination Fixes (Fixed — 2026-05-13)

**Problems found during config audit:**

**1 — "Count athletes by sport" had no SPARQL example**
Listed in `example_questions` but missing from `few_shot_examples`. The LLM had no guidance for aggregate-by-sport queries and would hallucinate.
**Fix:** Added the missing SPARQL using `wdt:P641 ?sport` + `GROUP BY ?sport ?sportLabel` + `ORDER BY DESC(?count)`.

**2 — FC Barcelona / Real Madrid queries missing human filter**
`wdt:P54` (member of sports team) can link to non-human entities (e.g. mascots, sponsor brands). Without `wdt:P31 wd:Q5`, non-player results could appear.
**Fix:** Added `?player wdt:P31 wd:Q5 .` to both club membership queries.

**3 — FIFA World Cup query used `wdt:P3450` (incomplete)**
`wdt:P3450` ("sports season of") is not set on all World Cup editions, especially older ones, causing missing winners. `wdt:P31 wd:Q19317` (instance of FIFA World Cup) is the standard pattern and covers all editions.
**Fix:** Changed `?edition wdt:P3450 wd:Q19317` → `?edition wdt:P31 wd:Q19317`.

**4 — No verified QIDs for common entities; no label-based fallback pattern**
When a question names a player or team not in the examples (e.g. "Where was Ronaldo born?"), the LLM guesses QIDs from training data — which are often wrong or stale.
**Fix:**
- Extended `ontology_hints` with a verified QIDs section covering common clubs (Barcelona, Real Madrid, Manchester United/City, Arsenal, Chelsea), competition entities (Premier League, Olympics, FIFA World Cup), and country citizenship IDs.
- Added an explicit "ENTITY ID RULES" block: do not guess QIDs not in the verified list; use `rdfs:label "Name"@en` matching instead.
- Added three label-based few-shot examples: athlete birthplace lookup, club membership lookup, and country-filtered player list — all using `rdfs:label` matching rather than hard-coded QIDs.

---

### Sports Domain Follow-up Audit — 2026-05-15

**Context:** Rechecked `configs/wikidata_sports.yaml` against Engin's `logs/Engin/sports_accuracy.log`, then verified the risky cases against live Wikidata.

**Fixes:**
1. Corrected stale/wrong verified club QIDs:
   - `wd:Q18656` = Manchester United F.C.
   - `wd:Q50602` = Manchester City F.C.
   - `wd:Q9617` = Arsenal F.C.
   - `wd:Q9616` = Chelsea F.C.
   Removed misleading IDs that live Wikidata labels as unrelated entities: `wd:Q18602070` (ferrous hexacyanomanganate), `wd:Q4803` (Surakarta), `wd:Q9599` (Susanne Albers), and the benchmark's suggested `wd:Q503` (banana).

2. Reduced timeout risk in broad player list examples. `List 10 football players`, `List 10 tennis players`, and `List 10 basketball players` now use bounded `SERVICE bd:sample` blocks plus an explicit final `ORDER BY`/`LIMIT`. This avoids the executor's automatic `ORDER BY RAND()` from turning huge Wikidata player classes into slow queries.

3. Replaced several `SERVICE wikibase:label` lookups with direct English `rdfs:label` filters and deterministic `ORDER BY` clauses in filtered examples. This keeps the returned labels equivalent while making the examples faster and less sensitive to endpoint load.

4. Fixed the English Premier League example. The previous query could return `CSM Târgu Jiu`; adding `?club wdt:P17 wd:Q145` restricts results to UK clubs and the live query returns the expected 20 clubs.

5. Bounded `Count athletes by sport` to the known sports listed in the sports config (`association football`, `ice hockey`, `tennis`, `basketball`, `athletics`). The unbounded aggregate over all humans with `wdt:P641` was too expensive for the public Wikidata endpoint.

6. Added a concrete Turkey hockey example after the UI returned no results for `list 10 hockey players from Turkey`. Live Wikidata confirms `wd:Q43` = Turkey and the stable pattern is `?player wdt:P106 wd:Q11774891 ; wdt:P27 wd:Q43`. This also adds Turkey to the verified country list so the LLM does not need to guess the country QID.

7. Added a fallback entity extractor for environments where the optional `en_core_web_sm` spaCy model is missing. The UI previously showed `Entity lookup · no entities found` for `Turkey` because entity enrichment was disabled entirely. The fallback extracts title-cased entity candidates such as `Turkey` and still resolves them through the existing Wikidata lookup path.

8. Fixed `find me 10 archers from Turkey`. The question was auto-detected as Geography because `Turkey` was a geography keyword while `archers` was not a sports keyword. Added `archer` / `archers` / `archery` to sports keywords, added verified Wikidata IDs `wd:Q108429` (archery) and `wd:Q13382355` (archer), and added a tested few-shot query using `wdt:P106 wd:Q13382355` plus `wdt:P27 wd:Q43`. The domain router now treats country-name keywords like `Turkey` / `Türkiye` as weak signals, so a concrete sports term wins while neighbour/capital questions still route to Geography.

**Intentionally not changed:**
- FIFA World Cup remains on `wdt:P3450 wd:Q19317`; Engin's log and the live probes show this returns rows, while the older `wdt:P31 wd:Q19317` hypothesis returned 0 rows.
- Olympic gold medal remains `wd:Q15243387`; live Wikidata confirms `wd:Q319921` is not an Olympic medal.

**Validation:**
- `pytest tests/test_domain_router.py tests/test_wikidata_sports_config.py -q` -> 12 passed.
- `pytest tests/test_entity_linker.py tests/test_wikidata_sports_config.py -q` -> 15 passed, 7 skipped.
- `pytest tests/test_sparql_examples.py -q -k wikidata_sports --tb=short` -> 17 passed, 86 deselected against live Wikidata.
- Short live probes: FIFA `wdt:P3450` returned 22 editions with winners, FIFA `wdt:P31` returned 0; Olympic `wd:Q15243387` returned 5 athletics medalists, `wd:Q319921` returned 0.
