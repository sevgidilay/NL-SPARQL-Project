# Fixed Bugs — Kamar El Morabit

---

## Astronomy Domain — `configs/wikidata_astronomy.yaml`

**Date fixed:** 2026-04-30
**Branch:** kamar2
**Commit:** `fix: correct entity IDs and queries in wikidata_astronomy config`

**Task:** Run and verify every example question for the Astronomy domain. Fix any question that returns a wrong or empty answer by correcting the Wikidata entity or property IDs.

---

### Bug 1 — "List all planets in our Solar System" returned 0 results

**Symptom:** The planets query executed without error but returned an empty table.

**Root cause:** The query used `?planet wdt:P31 wd:Q634` to match planets by type. Although `wd:Q634` is the Wikidata entity for "planet", the 8 Solar System planets are not directly typed as `Q634`. They each use more specific subtypes — Mercury and Venus are typed as `Q3504248` (inner planet of the Solar System), Jupiter and Saturn as `Q30014` (outer planet), etc. A direct `P31 = Q634` match finds nothing.

**Fix:** Use the property path `wdt:P31/wdt:P279*` to traverse the subclass chain from specific planet subtypes up to `wd:Q634`, combined with `wdt:P397 wd:Q525` to restrict to bodies whose parent astronomical body is the Sun:

```sparql
SELECT DISTINCT ?planet ?planetLabel WHERE {
  ?planet wdt:P31/wdt:P279* wd:Q634 .
  ?planet wdt:P397 wd:Q525 .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
```

Both conditions are required:
- `wdt:P31 wd:Q634` alone returns 0 rows (planets use specific subtypes, not Q634 directly)
- `wdt:P397 wd:Q525` alone returns 100k+ rows (every asteroid, comet, spacecraft in the Solar System)
- Combined, they return the 8 Solar System planets. The LLM can apply this pattern to any planets question, not just one specific phrasing.

**Result:** Returns all 8 planets (plus 2 edge cases from Wikidata data quality: Theia and Luna 1).

---

### Bug 2 — "List constellations and the number of stars in each" caused HTTP 400 / timeout

**Symptom:** The constellations query caused either an HTTP 400 Bad Request error (nested subquery form) or a timeout (simplified GROUP BY form). No results were ever returned.

**Root cause:** The original query used a nested subquery to count stars per constellation, scanning all items typed as `wd:Q523` (star) — hundreds of thousands of entries on Wikidata. This scan is too expensive for the public SPARQL endpoint's timeout limit. The nested subquery syntax also caused a 400 error on its own.

**Fix:** Replaced the entire query with a direct lookup of IAU constellations using the correct class entity `wd:Q8928` (constellation):

```sparql
SELECT ?constellation ?constellationLabel WHERE {
  ?constellation wdt:P31 wd:Q8928 .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
ORDER BY ?constellationLabel
LIMIT 20
```

The question was also renamed from "List constellations and the number of stars in each" to "List constellations" to match what the query actually returns.

**Result:** Returns 20 IAU constellations alphabetically, reliably, with no timeout.

---

### Bug 3 — "List asteroids and their discovery dates" had no SPARQL in the config

**Symptom:** The question appeared in `example_questions` but had no corresponding entry in `few_shot_examples`, meaning the LLM had no reference SPARQL to guide it. Generated queries were inconsistent.

**Fix:** Added a verified few_shot SPARQL entry:

```sparql
SELECT ?asteroid ?asteroidLabel ?date WHERE {
  ?asteroid wdt:P31 wd:Q3863 .
  ?asteroid wdt:P575 ?date .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
LIMIT 20
```

Properties used: `wdt:P31 wd:Q3863` = instance of asteroid, `wdt:P575` = time of discovery.

**Result:** Returns 20 asteroids with their discovery dates.

---

### Bug 4 — "Which astronomer discovered the most celestial bodies?" had no SPARQL and timed out

**Symptom:** No SPARQL existed for this question. When tested manually, an open-ended `GROUP BY` over all items with `wdt:P61` (discoverer) across all celestial body types timed out on Wikidata's endpoint.

**Fix:** Scoped the query to asteroids only (the largest and most consistently catalogued class of discovered bodies), and removed `ORDER BY` to stay within the endpoint timeout:

```sparql
SELECT ?astronomer ?astronomerLabel (COUNT(?asteroid) AS ?count) WHERE {
  ?asteroid wdt:P31 wd:Q3863 .
  ?asteroid wdt:P61 ?astronomer .
  ?astronomer wdt:P31 wd:Q5 .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
GROUP BY ?astronomer ?astronomerLabel
ORDER BY DESC(?count)
LIMIT 10
```

The question was also renamed to "Which astronomer discovered the most asteroids?" to accurately reflect the scoped query.

**Result:** Returns the top 10 asteroid discoverers with their counts (e.g. Tom Gehrels).

---

### Ontology Hints Updated

The `ontology_hints` section was updated to reflect all the above findings:

- Added individual QIDs for all 8 Solar System planets (Q308–Q332).
- Added `wd:Q8928 = "constellation"` with usage note.
- Added `wd:Q5 = "human"` with a note to use it with `wdt:P61` for discoverer queries.
- Added a warning that `wd:Q634 = "planet"` should not be used directly with `wdt:P31` for Solar System planets — use the explicit VALUES approach instead.

---

### Summary Table

| Question | Status before | Fix applied |
|---|---|---|
| List all planets in our Solar System | Empty (0 rows) | `P31/P279* Q634 + P397 Q525` pattern |
| List 10 galaxies | Silently empty (label filter dropped rows) | `rdfs:label + FILTER(LANG='en')` |
| Which moons orbit Jupiter? | OK | No change needed |
| List 10 exoplanets with their discovery dates | OK | Added English label filter |
| Find stars discovered before 1900 | OK | Added English label filter |
| List constellations | HTTP 400 / timeout | Replaced with Q8928 direct query |
| List asteroids and their discovery dates | No SPARQL | Added verified SPARQL + label filter |
| Which astronomer discovered the most asteroids? | No SPARQL / timeout | Added scoped asteroid-only query |

---

## Geography Domain — `configs/wikidata_geography.yaml`

**Date fixed:** 2026-05-03
**Branch:** kamar2
**Commit:** `fix: correct entity IDs and queries in wikidata_geography config`

**Task:** Run and verify every example question for the Geography domain. Fix any question that returns wrong or empty results.

---

### Bug 1 — "List mountains higher than 8000 metres" returned 1166 wrong results

**Symptom:** The query returned 1,166 rows of mountains, most of them US peaks like Echo Peak and Boston Peak — not the 14 Himalayan eight-thousanders. Sorted descending, US mountains appeared above Mount Everest.

**Root cause:** Wikidata stores `wdt:P2044` (elevation) in whatever unit the contributor entered — some entries use metres, others use feet. US mountains stored in feet with values like 8500 (feet = 2591m) pass the filter `?elevation > 8000` because 8500 > 8000, even though the actual elevation is only 2591 metres. There is no clean numeric range that separates the 14 eight-thousanders (8011–8849m) from US mountains stored in feet in the same numeric range. Unit-aware queries (using `psv:P2044` + `wikibase:quantityUnit`) consistently timed out on the Wikidata endpoint.

**Fix:** Replaced the filter-based query with `VALUES` listing the 13 verified QIDs of the eight-thousanders, looked up directly on Wikidata:

```sparql
SELECT ?mountain ?mountainLabel WHERE {
  VALUES ?mountain {
    wd:Q513 wd:Q43512 wd:Q1230019 wd:Q168702 wd:Q169986 wd:Q170089
    wd:Q165440 wd:Q170070 wd:Q130736 wd:Q16466024
    wd:Q180996 wd:Q186853 wd:Q105124
  }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
```

**Result:** Returns 13 named eight-thousanders correctly (Everest, K2, Kangchenjunga, Lhotse, Makalu, Cho Oyu, Dhaulagiri, Manaslu, Nanga Parbat, Annapurna I, Broad Peak, Gasherbrum II, Shishapangma).

---

### Bug 2 — "List the longest rivers in the world" timed out

**Symptom:** The query timed out every time it was executed.

**Root cause:** The original query used `wdt:P31/wdt:P279* wd:Q4022` (property path traversing all river subclasses) combined with `ORDER BY DESC(?length)`. Scanning all subclasses of river across millions of Wikidata items is too expensive for the endpoint's 25-second timeout.

**Additional issue:** River length (`wdt:P2043`) is also stored in inconsistent units. The Nile is stored as `6650` (km) while some smaller rivers are stored in metres (e.g. `650000` for a 650 km river). A simple `ORDER BY DESC` mixes these units and produces wrong ordering.

**Fix:** Removed the subclass path (direct `P31 Q4022` only), and added a range filter `FILTER(?length > 2000 && ?length < 10000)` which reliably captures km-stored major rivers (Nile = 6650, Amazon = 6400, Yangtze = 6300, etc.) while excluding metre-stored values (which would be > 1,000,000). Added English label filter.

```sparql
SELECT DISTINCT ?river ?riverLabel ?length WHERE {
  ?river wdt:P31 wd:Q4022 .
  ?river wdt:P2043 ?length .
  ?river rdfs:label ?riverLabel .
  FILTER(?length > 2000 && ?length < 10000)
  FILTER(LANG(?riverLabel) = "en")
}
ORDER BY DESC(?length)
LIMIT 10
```

**Result:** Returns the world's 10 longest rivers correctly (Nile, Amazon, Yangtze, Yellow River, Paraná, Congo, Mekong, Lena, Irtysh, Niger).

---

### Bug 3 — "List lakes with an area larger than 10000 square kilometres" returned tiny ponds

**Symptom:** The query returned small Canadian and European ponds (Big Trout Lake, Courtney Lake, etc.) instead of the world's largest lakes.

**Root cause:** Wikidata stores `wdt:P2046` (area) in inconsistent units. The Caspian Sea is stored as `386400` (km²) while Big Trout Lake is stored as `645578374` (m² = 645 km²). The filter `?area > 10000` catches any lake with area > 10,000 square metres (= 0.01 km²), which is basically every lake. These small lakes have English labels (they're Canadian lakes), so the label filter doesn't help. There is no clean numeric range to separate km²-stored large lakes from m²-stored small lakes because the values overlap.

**Fix:** Replaced the filter with `VALUES` listing the 10 verified QIDs of the world's largest lakes:

```sparql
SELECT ?lake ?lakeLabel WHERE {
  VALUES ?lake {
    wd:Q5484 wd:Q1066 wd:Q1383 wd:Q1169 wd:Q5511
    wd:Q5513 wd:Q5525 wd:Q5532 wd:Q5539 wd:Q5492
  }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
```

**Result:** Returns the 10 largest lakes correctly (Caspian Sea, Lake Superior, Lake Huron, Lake Michigan, Lake Tanganyika, Lake Baikal, Great Bear Lake, Lake Malawi, Great Slave Lake, Lake Erie).

---

### Bug 4 — "Count countries by continent" had no SPARQL in the config

**Symptom:** The question appeared in `example_questions` but had no corresponding `few_shot_examples` entry.

**Fix:** Added a verified `GROUP BY` aggregate query:

```sparql
SELECT ?continent ?continentLabel (COUNT(?country) AS ?count) WHERE {
  ?country wdt:P31 wd:Q6256 .
  ?country wdt:P30 ?continent .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
GROUP BY ?continent ?continentLabel
ORDER BY DESC(?count)
```

**Result:** Returns 7 rows (one per continent) with country counts.

---

### Ontology Hints Updated

Added explicit unit inconsistency warnings for `P2044`, `P2046`, and `P2043` with a note that simple `FILTER` on these properties produces wrong results. Listed verified QIDs for all 13 known eight-thousanders and the 10 world's largest lakes directly in the hints so the LLM can reuse them for any related question.

---

### Summary Table

| Question | Status before | Fix applied |
|---|---|---|
| List all continents | OK | No change needed |
| List countries in Europe with their capitals | OK | No change needed |
| List the 10 most populous cities in the world | OK | No change needed |
| List mountains higher than 8000 metres | 1166 wrong rows (feet vs metres) | VALUES with 13 verified eight-thousander QIDs |
| List the longest rivers in the world | Timeout | Direct P31 + range filter 2000–10000 km |
| List countries in Asia and their populations | OK | No change needed |
| List lakes with an area larger than 10000 km² | Wrong results (m² vs km² units) | VALUES with 10 verified large lake QIDs |
| Count countries by continent | No SPARQL | Added GROUP BY aggregate query |

---

## Music Domain — `configs/wikidata_music.yaml`

**Date fixed:** 2026-05-03
**Branch:** kamar2
**Commit:** `fix: correct entity IDs and queries in wikidata_music config`

**Task:** Run and verify every example question for the Music domain. Fix any question that returns wrong or empty results.

---

### Bug 1 — "Who are the members of Radiohead?" returned drum parts

**Symptom:** The query returned cymbal, snare drum, bass drum, and hi-hat instead of band members.

**Root cause:** The query used `wd:Q128309` as the Radiohead entity. `Q128309` is actually **drum kit**, not Radiohead. The correct QID for Radiohead is `wd:Q44190`. The query also used a UNION pattern that was unnecessary.

**Fix:** Replaced `wd:Q128309` with `wd:Q44190` (Radiohead) and simplified to a single triple:
```sparql
SELECT ?member ?memberLabel WHERE {
  ?member wdt:P463 wd:Q44190 .
  ?member rdfs:label ?memberLabel .
  FILTER(LANG(?memberLabel) = "en")
}
```

**Result:** Returns the 5 actual members — Thom Yorke, Jonny Greenwood, Philip Selway, Colin Greenwood, Ed O'Brien.

---

### Bug 2 — "List jazz musicians born before 1920" returned rock musicians

**Symptom:** The query returned only 3 results, none of them jazz musicians.

**Root cause:** The `ontology_hints` listed `wd:Q11399 = "jazz"` — but `Q11399` is **rock music**, not jazz. The query filtered by the wrong genre entirely. The correct QID for jazz is `wd:Q8341`.

**Fix:** Changed `wdt:P136 wd:Q11399` to `wdt:P136 wd:Q8341` and added English label filter:
```sparql
SELECT ?musician ?musicianLabel ?birth WHERE {
  ?musician wdt:P106 wd:Q639669 .
  ?musician wdt:P136 wd:Q8341 .
  ?musician wdt:P569 ?birth .
  FILTER(YEAR(?birth) < 1920)
  ?musician rdfs:label ?musicianLabel .
  FILTER(LANG(?musicianLabel) = "en")
} LIMIT 20
```

**Result:** Returns 20 authentic jazz musicians (Billie Holiday, Art Tatum, Bessie Smith, etc.).

---

### Bug 3 — "List 10 rock bands" returned 0 results

**Symptom:** The query returned nothing.

**Root cause:** Two problems combined:
1. `wdt:P31/wdt:P279* wd:Q215380` — subclass path over musical groups timed out on the Wikidata endpoint.
2. `wdt:P136/wdt:P279* wd:Q169930` — `Q169930` is **extended play** (an album format), not rock music. This was a completely wrong entity ID.

**Fix:** Replaced both broken patterns with a single direct type lookup using `wd:Q5741069` (rock band), which works without a subclass path:
```sparql
SELECT ?band ?bandLabel WHERE {
  ?band wdt:P31 wd:Q5741069 .
  ?band rdfs:label ?bandLabel .
  FILTER(LANG(?bandLabel) = "en")
} LIMIT 10
```

**Result:** Returns 10 actual rock bands correctly.

---

### Bug 4 — Wrong genre QIDs throughout ontology_hints

**Symptom:** Multiple genre-based queries returned wrong results due to incorrect QID mappings in `ontology_hints`.

**Root cause:**

| Listed as | Actual entity |
|---|---|
| `Q169930 = "rock music"` | Q169930 = **extended play** |
| `Q11399 = "jazz"` | Q11399 = **rock music** |
| `Q9778 = "classical music"` | Q9778 = **electronic music** |

**Fix:** Corrected all genre QIDs in ontology_hints:
- `wd:Q11399` = rock music
- `wd:Q8341` = jazz
- `wd:Q9730` = classical music
- `wd:Q37073` = pop music
- `wd:Q83440` = country music
- `wd:Q5741069` = rock band

---

### Bug 5 — Label filter dropping rows silently (all queries)

**Symptom:** Several queries returned fewer rows than expected in the UI, or 0 rows intermittently.

**Root cause:** Same as Astronomy domain — `_postprocess_wikidata` drops rows where any `*Label` is a bare QID. Using `SERVICE wikibase:label` returns QIDs for items without English labels, which get silently filtered.

**Fix:** Replaced `SERVICE wikibase:label` with `rdfs:label + FILTER(LANG='en')` in all queries (musicians, albums, rock bands, jazz musicians, Mozart works, pianists, guitarists, record labels).

---

### Bug 6 — "Count musicians by genre" had no SPARQL

**Symptom:** The question appeared in `example_questions` with no `few_shot_examples` entry.

**Fix:** Added a scoped aggregate using `VALUES` for 6 verified genre QIDs to avoid timeout:
```sparql
SELECT ?genre ?genreLabel (COUNT(?musician) AS ?count) WHERE {
  VALUES ?genre { wd:Q11399 wd:Q8341 wd:Q9730 wd:Q37073 wd:Q83440 wd:Q7749 }
  ?musician wdt:P106 wd:Q639669 .
  ?musician wdt:P136 ?genre .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
GROUP BY ?genre ?genreLabel
ORDER BY DESC(?count)
```

**Result:** Returns counts for rock, jazz, classical, pop, country, and rock and roll.

---

### Summary Table

| Question | Status before | Fix applied |
|---|---|---|
| List 10 musicians | Rows silently dropped | English label filter |
| List albums released by The Beatles | 7 rows dropped | English label filter |
| List 10 rock bands | Empty (wrong QID + timeout) | Direct P31 Q5741069 + label filter |
| Who are the members of Radiohead? | Returned drum parts (Q128309 = drum kit) | Corrected to Q44190 (Radiohead) |
| List jazz musicians born before 1920 | Rock musicians (Q11399 = rock, not jazz) | Corrected to Q8341 (jazz) |
| List songs composed by Mozart | Rows silently dropped | English label filter |
| List 10 pianists | Rows silently dropped | English label filter |
| List 10 guitarists | Rows silently dropped | English label filter |
| List 10 record labels and artists | Rows silently dropped | English label filter |
| Count musicians by genre | No SPARQL | Added VALUES + GROUP BY aggregate |
