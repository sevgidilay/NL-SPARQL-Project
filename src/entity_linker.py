"""
entity_linker.py
================
Pre-LLM enrichment: extract named entities from a natural language question
and resolve them to verified Wikidata QIDs via the Wikidata Search API.

Only runs for Wikidata-endpoint configs. All network failures are silently
swallowed so the calling pipeline degrades gracefully.
"""

import json
import logging
import re

import requests

WIKIDATA_SEARCH_URL = "https://www.wikidata.org/w/api.php"
_WIKIDATA_HOST = "wikidata.org"
_REQUEST_TIMEOUT = 3  # seconds; fast-fail — LLM latency dominates overall

logger = logging.getLogger(__name__)

_nlp = None  # lazy-loaded singleton; False = tried and failed

# Last-query LLM extraction cache: keyed by (question, model) → (entities, relations)
_llm_cache: dict[tuple[str, str], tuple[list[str], list[str]]] = {}

_KEEP_TYPES = {"PERSON", "ORG", "GPE", "LOC", "EVENT", "WORK_OF_ART", "PRODUCT", "FAC", "NORP"}

_NATIONALITY_TO_COUNTRY: dict[str, str] = {
    "indian": "India", "chinese": "China", "american": "United States",
    "british": "United Kingdom", "french": "France", "german": "Germany",
    "japanese": "Japan", "australian": "Australia", "spanish": "Spain",
    "italian": "Italy", "russian": "Russia", "brazilian": "Brazil",
    "canadian": "Canada", "mexican": "Mexico", "korean": "South Korea",
    "dutch": "Netherlands", "swedish": "Sweden", "swiss": "Switzerland",
    "portuguese": "Portugal", "greek": "Greece", "turkish": "Turkey",
    "pakistani": "Pakistan", "bangladeshi": "Bangladesh",
    "sri lankan": "Sri Lanka", "argentinian": "Argentina",
    "egyptian": "Egypt", "south african": "South Africa",
    "nigerian": "Nigeria", "kenyan": "Kenya", "iranian": "Iran",
    "saudi": "Saudi Arabia", "emirati": "United Arab Emirates",
    "thai": "Thailand", "vietnamese": "Vietnam", "indonesian": "Indonesia",
    "malaysian": "Malaysia", "philippine": "Philippines", "filipino": "Philippines",
    "ukrainian": "Ukraine", "polish": "Poland", "romanian": "Romania",
    "czech": "Czech Republic", "hungarian": "Hungary",
}


def _get_nlp():
    """Return cached spaCy model, loading it on first call. Returns None if not installed."""
    global _nlp
    if _nlp is not None:
        return _nlp if _nlp is not False else None
    try:
        import spacy
        _nlp = spacy.load("en_core_web_sm")
    except (ImportError, OSError):
        logger.warning(
            "spaCy model en_core_web_sm not found — entity enrichment disabled. "
            "Fix: python -m spacy download en_core_web_sm"
        )
        _nlp = False
    return _nlp if _nlp is not False else None


_CHUNK_STOPWORDS = {
    "who", "what", "where", "when", "which", "how", "list", "show",
    "find", "give", "tell", "name", "get", "describe",
}

_TITLECASE_ENTITY_RE = re.compile(
    r"\b(?:[A-Z][\w''.-]*)(?:\s+(?:[A-Z][\w''.-]*))*\b",
    re.UNICODE,
)

_VERB_TO_PROPERTY: dict[str, dict] = {
    # discovery / creation
    "invent":     {"pid": "wdt:P61",   "label": "discoverer or inventor"},
    "discover":   {"pid": "wdt:P61",   "label": "discoverer or inventor"},
    "create":     {"pid": "wdt:P170",  "label": "creator"},
    "found":      {"pid": "wdt:P112",  "label": "founded by"},
    "establish":  {"pid": "wdt:P112",  "label": "founded by"},
    "build":      {"pid": "wdt:P287",  "label": "designed by"},
    "design":     {"pid": "wdt:P287",  "label": "designed by"},
    "develop":    {"pid": "wdt:P178",  "label": "developer"},
    "engineer":   {"pid": "wdt:P178",  "label": "developer"},
    # arts / media
    "direct":     {"pid": "wdt:P57",   "label": "director"},
    "write":      {"pid": "wdt:P50",   "label": "author"},
    "author":     {"pid": "wdt:P50",   "label": "author"},
    "compose":    {"pid": "wdt:P86",   "label": "composer"},
    "produce":    {"pid": "wdt:P162",  "label": "producer"},
    "publish":    {"pid": "wdt:P123",  "label": "publisher"},
    "star":       {"pid": "wdt:P161",  "label": "cast member"},
    "act":        {"pid": "wdt:P161",  "label": "cast member"},
    "perform":    {"pid": "wdt:P161",  "label": "cast member"},
    "illustrate": {"pid": "wdt:P110",  "label": "illustrator"},
    "paint":      {"pid": "wdt:P170",  "label": "creator"},
    "release":    {"pid": "wdt:P577",  "label": "publication date"},
    "record":     {"pid": "wdt:P264",  "label": "record label"},
    "sing":       {"pid": "wdt:P175",  "label": "performer"},
    "play":       {"pid": "wdt:P175",  "label": "performer"},
    "narrate":    {"pid": "wdt:P1811", "label": "narrator"},
    "score":      {"pid": "wdt:P86",   "label": "composer"},
    # biography
    "born":       {"pid": "wdt:P19",   "label": "place of birth"},
    "bear":       {"pid": "wdt:P19",   "label": "place of birth"},  # spaCy lemma of "born"
    "die":        {"pid": "wdt:P20",   "label": "place of death"},
    "marry":      {"pid": "wdt:P26",   "label": "spouse"},
    "wed":        {"pid": "wdt:P26",   "label": "spouse"},
    "study":      {"pid": "wdt:P69",   "label": "educated at"},
    "attend":     {"pid": "wdt:P69",   "label": "educated at"},
    "graduate":   {"pid": "wdt:P69",   "label": "educated at"},
    "work":       {"pid": "wdt:P108",  "label": "employer"},
    "employ":     {"pid": "wdt:P108",  "label": "employer"},
    "lead":       {"pid": "wdt:P488",  "label": "chairperson"},
    "head":       {"pid": "wdt:P488",  "label": "chairperson"},
    "rule":       {"pid": "wdt:P35",   "label": "head of state"},
    "govern":     {"pid": "wdt:P6",    "label": "head of government"},
    "represent":  {"pid": "wdt:P39",   "label": "position held"},
    "serve":      {"pid": "wdt:P39",   "label": "position held"},
    "hold":       {"pid": "wdt:P39",   "label": "position held"},
    # sport
    "coach":      {"pid": "wdt:P286",  "label": "head coach"},
    "train":      {"pid": "wdt:P286",  "label": "head coach"},
    # awards / recognition
    "win":        {"pid": "wdt:P166",  "label": "award received"},
    "receive":    {"pid": "wdt:P166",  "label": "award received"},
    "award":      {"pid": "wdt:P166",  "label": "award received"},
    "nominate":   {"pid": "wdt:P1411", "label": "nominated for"},
    # membership / belonging
    "belong":     {"pid": "wdt:P463",  "label": "member of"},
    "join":       {"pid": "wdt:P463",  "label": "member of"},
    "include":    {"pid": "wdt:P463",  "label": "member of"},
    "locate":     {"pid": "wdt:P131",  "label": "located in"},
    "situate":    {"pid": "wdt:P131",  "label": "located in"},
    # other factual
    "speak":      {"pid": "wdt:P37",   "label": "official language"},
    "use":        {"pid": "wdt:P37",   "label": "official language"},
    "border":     {"pid": "wdt:P47",   "label": "shares border with"},
    "share":      {"pid": "wdt:P47",   "label": "shares border with"},
    "own":        {"pid": "wdt:P127",  "label": "owned by"},
    "sponsor":    {"pid": "wdt:P859",  "label": "sponsor"},
}

_NOUN_PHRASE_TO_PROPERTY: dict[str, dict] = {
    # geography / administration
    "capital":         {"pid": "wdt:P36",   "label": "capital"},
    "currency":        {"pid": "wdt:P38",   "label": "currency"},
    "language":        {"pid": "wdt:P37",   "label": "official language"},
    "continent":       {"pid": "wdt:P30",   "label": "continent"},
    "country":         {"pid": "wdt:P17",   "label": "country"},
    "state":           {"pid": "wdt:P131",  "label": "located in administrative entity"},
    "region":          {"pid": "wdt:P131",  "label": "located in administrative entity"},
    "location":        {"pid": "wdt:P131",  "label": "located in administrative entity"},
    "flag":            {"pid": "wdt:P41",   "label": "flag image"},
    "anthem":          {"pid": "wdt:P85",   "label": "anthem"},
    "timezone":        {"pid": "wdt:P421",  "label": "located in time zone"},
    "border":          {"pid": "wdt:P47",   "label": "shares border with"},
    "neighbor":        {"pid": "wdt:P47",   "label": "shares border with"},
    # demographics / statistics
    "population":      {"pid": "wdt:P1082", "label": "population"},
    "area":            {"pid": "wdt:P2046", "label": "area"},
    "elevation":       {"pid": "wdt:P2044", "label": "elevation above sea level"},
    "height":          {"pid": "wdt:P2048", "label": "height"},
    "depth":           {"pid": "wdt:P4511", "label": "vertical depth"},
    "length":          {"pid": "wdt:P2043", "label": "length"},
    "width":           {"pid": "wdt:P2049", "label": "width"},
    "age":             {"pid": "wdt:P569",  "label": "date of birth"},
    # government / leadership
    "president":       {"pid": "wdt:P35",   "label": "head of state"},
    "prime minister":  {"pid": "wdt:P6",    "label": "head of government"},
    "leader":          {"pid": "wdt:P6",    "label": "head of government"},
    "ruler":           {"pid": "wdt:P35",   "label": "head of state"},
    "king":            {"pid": "wdt:P35",   "label": "head of state"},
    "queen":           {"pid": "wdt:P35",   "label": "head of state"},
    "minister":        {"pid": "wdt:P6",    "label": "head of government"},
    "ceo":             {"pid": "wdt:P169",  "label": "chief executive officer"},
    "director":        {"pid": "wdt:P1037", "label": "director / manager"},
    "chairman":        {"pid": "wdt:P488",  "label": "chairperson"},
    "founder":         {"pid": "wdt:P112",  "label": "founded by"},
    # biography
    "birthplace":      {"pid": "wdt:P19",   "label": "place of birth"},
    "nationality":     {"pid": "wdt:P27",   "label": "country of citizenship"},
    "citizenship":     {"pid": "wdt:P27",   "label": "country of citizenship"},
    "occupation":      {"pid": "wdt:P106",  "label": "occupation"},
    "profession":      {"pid": "wdt:P106",  "label": "occupation"},
    "spouse":          {"pid": "wdt:P26",   "label": "spouse"},
    "partner":         {"pid": "wdt:P26",   "label": "spouse"},
    "father":          {"pid": "wdt:P22",   "label": "father"},
    "mother":          {"pid": "wdt:P25",   "label": "mother"},
    "child":           {"pid": "wdt:P40",   "label": "child"},
    "sibling":         {"pid": "wdt:P3373", "label": "sibling"},
    "award":           {"pid": "wdt:P166",  "label": "award received"},
    # arts / media
    "author":          {"pid": "wdt:P50",   "label": "author"},
    "writer":          {"pid": "wdt:P50",   "label": "author"},
    "composer":        {"pid": "wdt:P86",   "label": "composer"},
    "publisher":       {"pid": "wdt:P123",  "label": "publisher"},
    "producer":        {"pid": "wdt:P162",  "label": "producer"},
    "genre":           {"pid": "wdt:P136",  "label": "genre"},
    "cast":            {"pid": "wdt:P161",  "label": "cast member"},
    "subject":         {"pid": "wdt:P921",  "label": "main subject"},
    # science / invention
    "discoverer":      {"pid": "wdt:P61",   "label": "discoverer or inventor"},
    "inventor":        {"pid": "wdt:P61",   "label": "discoverer or inventor"},
    "developer":       {"pid": "wdt:P178",  "label": "developer"},
}

_NP_PREP_RE = re.compile(r"\b(of|for)\b", re.IGNORECASE)


def _extract_relations(question: str) -> list[dict]:
    """Extract predicate/relation candidates from question verbs.

    Uses spaCy dependency parsing to find main verbs and maps their lemmas
    to known Wikidata property IDs via _VERB_TO_PROPERTY.
    Returns: [{"surface": "invented", "pid": "wdt:P61", "label": "discoverer or inventor"}]
    """
    nlp = _get_nlp()
    if nlp is None:
        return []
    doc = nlp(question)
    seen: dict[str, None] = {}
    results = []
    for token in doc:
        if token.pos_ != "VERB" or token.dep_ in ("aux", "auxpass"):
            continue
        lemma = token.lemma_.lower()
        if lemma in seen:
            continue
        if lemma in _VERB_TO_PROPERTY:
            seen[lemma] = None
            prop = _VERB_TO_PROPERTY[lemma]
            results.append({
                "surface": token.text,
                "pid": prop["pid"],
                "label": prop["label"],
            })
        else:
            # Verb found by spaCy but not in static dict — try live Wikidata property search.
            # This is more reliable than _dynamic_property_search's first-word approach because
            # spaCy has already identified this token as the relational verb in the sentence.
            hits = _search_wikidata_property(lemma)
            if hits:
                seen[lemma] = None
                top = hits[0]
                results.append({
                    "surface": token.text,
                    "pid": top["pid"],
                    "label": top["label"],
                })
    return results


def _extract_np_properties_spacy(nlp, question: str) -> list[dict]:
    doc = nlp(question)
    seen: dict[str, None] = {}
    results = []

    for token in doc:
        if token.lower_ not in ("of", "for") or token.dep_ != "prep":
            continue
        head = token.head
        if head.pos_ not in ("NOUN", "PROPN", "ADJ"):
            continue
        lemma = head.lemma_.lower()
        if lemma in _NOUN_PHRASE_TO_PROPERTY and lemma not in seen:
            seen[lemma] = None
            prop = _NOUN_PHRASE_TO_PROPERTY[lemma]
            results.append({"surface": head.text, "pid": prop["pid"], "label": prop["label"]})

    # check two-word keys (e.g. "prime minister")
    tokens = list(doc)
    for i in range(len(tokens) - 1):
        bigram = f"{tokens[i].lemma_.lower()} {tokens[i + 1].lemma_.lower()}"
        if bigram not in _NOUN_PHRASE_TO_PROPERTY or bigram in seen:
            continue
        look_ahead = tokens[i + 2: i + 4] if i + 2 < len(tokens) else []
        if any(t.lower_ in ("of", "for") for t in look_ahead):
            seen[bigram] = None
            prop = _NOUN_PHRASE_TO_PROPERTY[bigram]
            results.append({
                "surface": f"{tokens[i].text} {tokens[i + 1].text}",
                "pid": prop["pid"],
                "label": prop["label"],
            })

    return results


def _extract_np_properties_regex(question: str) -> list[dict]:
    seen: dict[str, None] = {}
    results = []
    parts = _NP_PREP_RE.split(question.lower())
    if len(parts) < 2:
        return []
    left = parts[0].strip().split()
    if not left:
        return []
    for n in (2, 1):
        if len(left) >= n:
            key = " ".join(left[-n:])
            if key in _NOUN_PHRASE_TO_PROPERTY and key not in seen:
                seen[key] = None
                prop = _NOUN_PHRASE_TO_PROPERTY[key]
                results.append({"surface": key, "pid": prop["pid"], "label": prop["label"]})
    return results


def _extract_noun_phrase_properties(question: str) -> list[dict]:
    """Extract property candidates expressed as noun phrases preceding 'of'/'for'.

    Pattern: "<property-noun> of <entity>" — e.g. "capital of France",
    "president of the United States", "population of Tokyo".
    """
    nlp = _get_nlp()
    if nlp is not None:
        return _extract_np_properties_spacy(nlp, question)
    return _extract_np_properties_regex(question)


_QUESTION_STOPWORDS = frozenset({
    "who", "what", "where", "when", "which", "how", "why", "is", "are",
    "was", "were", "did", "do", "does", "the", "a", "an", "of", "in",
    "on", "at", "to", "for", "by", "with", "from", "and", "or", "not",
    "be", "been", "being", "have", "has", "had",
    # imperative verbs used as query commands — never Wikidata properties
    "list", "show", "find", "give", "name", "tell", "get",
})


# Properties that are external identifiers or media — not useful for SPARQL generation
_IDENTIFIER_PIDS: set[str] = {
    "P18", "P94", "P154", "P158", "P207", "P214", "P215", "P217", "P218",
    "P219", "P220", "P221", "P222", "P223", "P224", "P225", "P226", "P227",
    "P228", "P229", "P230", "P231", "P232", "P233", "P234", "P235", "P236",
    "P237", "P238", "P239", "P240", "P241", "P242", "P243", "P244", "P245",
    "P246", "P247", "P248", "P268", "P269", "P270", "P271", "P272", "P349",
    "P351", "P352", "P353", "P354", "P355", "P373", "P377", "P380", "P381",
    "P382", "P396", "P402", "P405", "P406", "P407", "P409", "P428", "P432",
    "P433", "P434", "P435", "P436", "P439", "P440", "P441", "P442", "P443",
    "P444", "P490", "P492", "P493", "P494", "P495", "P496", "P497", "P498",
    "P502", "P506", "P508", "P509", "P510", "P511", "P512", "P535", "P536",
    "P557", "P560", "P590", "P591", "P592", "P593", "P594", "P595", "P596",
    "P597", "P598", "P599", "P600", "P604", "P605", "P606", "P607", "P608",
    "P609", "P610", "P611", "P612", "P613", "P614", "P615", "P616", "P617",
    "P618", "P619", "P620", "P621", "P622", "P623", "P624", "P625", "P626",
    "P627", "P628", "P629", "P630", "P631", "P632", "P633", "P634", "P635",
    "P636", "P637", "P638", "P639", "P640", "P641", "P642", "P643", "P644",
    "P645", "P646", "P648", "P649", "P650", "P651", "P652", "P653", "P654",
    "P655", "P656", "P657", "P658", "P659", "P660", "P661", "P662", "P663",
    "P664", "P665", "P666", "P667", "P668", "P669", "P670", "P671", "P672",
    "P673", "P674", "P675", "P676", "P677", "P678", "P679", "P680", "P681",
    "P682", "P683", "P684", "P685", "P686", "P687", "P688", "P689", "P690",
    "P691", "P692", "P693", "P694", "P695", "P696", "P697", "P698", "P699",
    "P700", "P701", "P702", "P703", "P704", "P705", "P706", "P707", "P708",
    "P709", "P710", "P856", "P910", "P935", "P949", "P950", "P951", "P952",
    "P953", "P954", "P1036", "P1051", "P1096", "P1566", "P1667", "P1748",
    "P2163", "P2397", "P2860", "P3417",
}


def fetch_entity_properties(qid: str) -> list[dict]:
    """Fetch the properties available on a Wikidata entity as [{pid, label}].

    Filters out external identifiers and media properties so only semantically
    useful properties are returned. Used to give the LLM context about what
    predicates actually exist on the entity before generating SPARQL.

    Returns [] on any error or if the endpoint is unreachable.
    """
    try:
        # Step 1: get all claim PIDs for this entity
        resp = requests.get(
            WIKIDATA_SEARCH_URL,
            params={
                "action": "wbgetentities",
                "ids": qid,
                "props": "claims",
                "format": "json",
            },
            timeout=_REQUEST_TIMEOUT,
            headers={"User-Agent": "NL2SPARQL-prototype/1.0"},
        )
        resp.raise_for_status()
        claims = resp.json().get("entities", {}).get(qid, {}).get("claims", {})
        if not claims:
            return []

        # Step 2: filter out identifier/media PIDs and keep top 30
        pids = [p for p in claims if p not in _IDENTIFIER_PIDS]
        pids = pids[:30]
        if not pids:
            return []

        # Step 3: batch-fetch English labels for remaining PIDs
        label_resp = requests.get(
            WIKIDATA_SEARCH_URL,
            params={
                "action": "wbgetentities",
                "ids": "|".join(pids),
                "props": "labels",
                "languages": "en",
                "format": "json",
            },
            timeout=_REQUEST_TIMEOUT,
            headers={"User-Agent": "NL2SPARQL-prototype/1.0"},
        )
        label_resp.raise_for_status()
        label_data = label_resp.json().get("entities", {})

        result = []
        for pid in pids:
            label = (
                label_data.get(pid, {})
                .get("labels", {})
                .get("en", {})
                .get("value", pid)
            )
            result.append({"pid": f"wdt:{pid}", "label": label})
        return result
    except Exception:
        logger.warning("fetch_entity_properties failed for %s", qid, exc_info=True)
        return []


def _search_wikidata_property(term: str) -> list[dict]:
    """Search Wikidata for a property matching term; returns [{pid, label, description}]. Never raises."""
    try:
        resp = requests.get(
            WIKIDATA_SEARCH_URL,
            params={
                "action": "wbsearchentities",
                "search": term,
                "type": "property",
                "language": "en",
                "format": "json",
                "limit": 5,
            },
            timeout=_REQUEST_TIMEOUT,
            headers={"User-Agent": "NL2SPARQL-prototype/1.0"},
        )
        resp.raise_for_status()
        results = []
        for item in resp.json().get("search", []):
            pid_raw = item.get("id", "")
            if not pid_raw.startswith("P"):
                continue
            results.append({
                "pid": f"wdt:{pid_raw}",
                "label": item.get("label", term),
                "description": item.get("description", ""),
            })
        return results
    except Exception:
        return []


def _dynamic_property_search(question: str, entity_words: set[str] | None = None) -> list[dict]:
    """Fall back to live Wikidata property search for the first meaningful term in question."""
    skip = _QUESTION_STOPWORDS | (entity_words or set())
    words = re.sub(r"[^a-z\s]", "", question.lower()).split()
    for word in words:
        if word in skip or len(word) < 4:
            continue
        # Try static dict first (avoids live API returning the wrong property)
        if word in _VERB_TO_PROPERTY:
            prop = _VERB_TO_PROPERTY[word]
            return [{"surface": word, "pid": prop["pid"], "label": prop["label"]}]
        if word in _NOUN_PHRASE_TO_PROPERTY:
            prop = _NOUN_PHRASE_TO_PROPERTY[word]
            return [{"surface": word, "pid": prop["pid"], "label": prop["label"]}]
        hits = _search_wikidata_property(word)
        if hits:
            top = hits[0]
            return [{"surface": word, "pid": top["pid"], "label": top["label"]}]
    return []


def _resolve_relation_name(name: str) -> dict | None:
    """Map a relation name string to a Wikidata PID.

    Tries the live Wikidata property search first (most accurate), then falls
    back to the static dicts if the API is unavailable.
    Returns a hint dict or None if unresolvable.
    """
    # Live Wikidata property search — most accurate, context-aware ranking
    hits = _search_wikidata_property(name)
    if hits:
        top = hits[0]
        return {"surface": name, "pid": top["pid"], "label": top["label"]}

    # Fallback: static dicts (used when API is unreachable)
    key = name.lower().strip()
    for lookup_key in [key] + key.split():
        if lookup_key in _VERB_TO_PROPERTY:
            prop = _VERB_TO_PROPERTY[lookup_key]
            return {"surface": name, "pid": prop["pid"], "label": prop["label"]}
        if lookup_key in _NOUN_PHRASE_TO_PROPERTY:
            prop = _NOUN_PHRASE_TO_PROPERTY[lookup_key]
            return {"surface": name, "pid": prop["pid"], "label": prop["label"]}
    return None


def lookup_relations(
    question: str,
    config: dict,
    model: str | None = None,
    entity_hints: list[dict] | None = None,
) -> list[dict]:
    """Extract predicate hints from the question and map them to Wikidata PIDs.

    If model is provided, asks the LLM for relation names first and maps each
    via _resolve_relation_name. Falls back to the existing spaCy/regex pipeline
    when the LLM returns nothing or fails.

    entity_hints: resolved entity dicts (from lookup_entities) — surface words are
    excluded from _dynamic_property_search so entity names like "albert" are never
    mistaken for predicate terms.

    Returns [] if the config endpoint is not Wikidata or any error occurs.
    """
    try:
        if _WIKIDATA_HOST not in config.get("endpoint", ""):
            return []

        if model:
            _, llm_relations = _extract_via_llm(question, model)
            results: list[dict] = []
            seen_pids: set[str] = set()
            for name in llm_relations:
                hint = _resolve_relation_name(name)
                if hint and hint["pid"] not in seen_pids:
                    seen_pids.add(hint["pid"])
                    results.append(hint)
            return results

        # No model: rule-based pipeline
        results = []
        seen_pids = set()

        for r in _extract_relations(question):
            if r["pid"] not in seen_pids:
                seen_pids.add(r["pid"])
                results.append(r)

        for r in _extract_noun_phrase_properties(question):
            if r["pid"] not in seen_pids:
                seen_pids.add(r["pid"])
                results.append(r)

        if not results:
            entity_words: set[str] = set()
            for eh in (entity_hints or []):
                entity_words.update(
                    re.sub(r"[^a-z\s]", "", eh.get("surface", "").lower()).split()
                )
            results = _dynamic_property_search(question, entity_words)

        return results
    except Exception:
        logger.warning("entity_linker.lookup_relations failed silently", exc_info=True)
        return []


def _extract_entities(question: str) -> list[tuple[str, bool]]:
    """Extract entity candidates from question text.

    Primary: spaCy NER (proper named entities — people, orgs, places, works, NORP).
    When NER finds entities, noun chunks not overlapping with NER tokens are added
    as concept supplements (captures occupations like "Tennis Player").
    Fallback: noun chunks only when NER finds nothing entirely.
    Articles/determiners are stripped from chunk text.

    Returns list of (surface_text, is_class) tuples where is_class=True for common
    nouns extracted via the noun-chunk fallback (e.g. "galaxy", "tennis player").
    """
    nlp = _get_nlp()
    if nlp is None:
        return _extract_entities_without_spacy(question)
    doc = nlp(question)

    ner_seen: dict[str, None] = {}
    ner_token_ids: set[int] = set()

    for ent in doc.ents:
        if ent.label_ in _KEEP_TYPES:
            ner_seen[ent.text.strip()] = None
            for tok in ent:
                ner_token_ids.add(tok.i)

    if not ner_seen:
        # Pure fallback: noun chunks when NER finds nothing — these are class/type nouns
        class_seen: dict[str, None] = {}
        for chunk in doc.noun_chunks:
            if chunk.root.pos_ not in ("NOUN", "PROPN"):
                continue
            tokens = [t for t in chunk if t.pos_ != "DET"]
            if not tokens:
                continue
            # Use lemma for common nouns so "scientists" → "scientist" matches Wikidata labels
            text = " ".join(
                t.lemma_ if t.pos_ == "NOUN" else t.text for t in tokens
            ).strip()
            if text.lower() in _CHUNK_STOPWORDS or len(text) < 3:
                continue
            class_seen[text] = None
        return [(text, True) for text in class_seen]
    else:
        result: dict[str, tuple[str, bool]] = {k: (k, False) for k in ner_seen}
        # Supplement: concept noun chunks not overlapping with NER entities
        for chunk in doc.noun_chunks:
            if chunk.root.pos_ not in ("NOUN", "PROPN"):
                continue
            if any(tok.i in ner_token_ids for tok in chunk):
                continue
            tokens = [t for t in chunk if t.pos_ not in ("DET", "ADJ", "NUM")]
            if not tokens:
                continue
            # Use lemma for common nouns so "scientists" → "scientist" matches Wikidata labels
            text = " ".join(
                t.lemma_ if t.pos_ == "NOUN" else t.text for t in tokens
            ).strip()
            if text.lower() in _CHUNK_STOPWORDS or len(text) < 3:
                continue
            if text not in result:
                result[text] = (text, True)
        return list(result.values())


def _extract_via_llm(question: str, model: str) -> tuple[list[str], list[str]]:
    """Ask the LLM which entities and relations to look up for this question.

    Returns (entity_names, relation_names). Results are cached so both
    lookup_entities and lookup_relations share one LLM call per question.
    Never raises — returns ([], []) on any failure.
    """
    cache_key = (question, model)
    if cache_key in _llm_cache:
        return _llm_cache[cache_key]

    result: tuple[list[str], list[str]] = ([], [])
    try:
        import src.llm_client as llm_client  # lazy to avoid circular import

        system = (
            "You are a named entity and relation extractor. "
            "Given a question, output ONLY a JSON object with two keys: "
            '"entities" (list of entity or concept strings to look up in a knowledge graph, '
            'including proper nouns AND concept classes like "galaxy", "novel", "country") and '
            '"relations" (list of predicate or property name strings). '
            "No explanation, no markdown fences, no extra text."
        )
        raw = llm_client.chat(
            f'Question: "{question}"',
            model=model,
            system_prompt=system,
            temperature=0,
        )
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            data = json.loads(m.group(0))
            entities = [str(e).strip() for e in data.get("entities", []) if e]
            relations = [str(r).strip() for r in data.get("relations", []) if r]
            result = (entities, relations)
    except Exception:
        logger.debug("_extract_via_llm failed", exc_info=True)

    # Keep cache small — evict if it grows beyond 10 entries
    if len(_llm_cache) >= 10:
        _llm_cache.clear()
    _llm_cache[cache_key] = result
    return result


def llm_extract(question: str, model: str) -> tuple[list[str], list[str]]:
    """Return (entity_names, relation_names) the LLM identified for this question.

    Populates the internal cache so subsequent lookup_entities / lookup_relations
    calls for the same (question, model) are free.
    """
    return _extract_via_llm(question, model)


def _extract_entities_without_spacy(question: str) -> list[tuple[str, bool]]:
    """Best-effort entity extraction when the optional spaCy model is missing."""
    seen: dict[str, None] = {}
    for match in _TITLECASE_ENTITY_RE.finditer(question):
        text = match.group(0).strip()
        if text.lower() in _CHUNK_STOPWORDS or len(text) < 3:
            continue
        seen[text] = None
    # Titlecase regex only matches proper nouns — never class entities
    return [(text, False) for text in seen]


def _search_wikidata(entity: str, limit: int = 3) -> list[dict]:
    """Call Wikidata wbsearchentities; return [{id, label, description}]. Never raises."""
    try:
        resp = requests.get(
            WIKIDATA_SEARCH_URL,
            params={
                "action": "wbsearchentities",
                "search": entity,
                "language": "en",
                "format": "json",
                "limit": limit,
            },
            timeout=_REQUEST_TIMEOUT,
            headers={"User-Agent": "NL2SPARQL-prototype/1.0"},
        )
        resp.raise_for_status()
        return [
            {
                "id": item["id"],
                "label": item.get("label", entity),
                "description": item.get("description", ""),
            }
            for item in resp.json().get("search", [])
        ]
    except Exception:
        return []


_HIGH_VALUE_DESCRIPTION_WORDS = frozenset({
    "country", "nation", "state", "city", "town", "river", "mountain",
    "person", "human", "politician", "scientist", "musician", "actor",
    "writer", "author", "athlete", "company", "organization", "film",
    "movie", "book", "novel", "song", "album", "award", "university",
    "planet", "element", "language",
    # academic and professional roles that describe notable persons
    "philosopher", "mathematician", "physicist", "astronomer", "biologist",
    "chemist", "historian", "economist", "architect", "engineer", "explorer",
    "theologian", "physician", "composer", "painter", "sculptor",
})


def _pick_best_candidate(candidates: list[dict], context_words: frozenset | None = None) -> dict | None:
    """Score candidates and return the best-ranked one.

    Scoring (lower tuple = better, used with min()):
      -2  description contains a word from context_words (question-derived)
      -1  description contains a word from _HIGH_VALUE_DESCRIPTION_WORDS
      +1  QID numeric value > 10_000_000 (very obscure items)
      tie-break: lower QID numeric value wins (earlier = more notable)
    """
    if not candidates:
        return None

    def _qid_num(c: dict) -> int:
        try:
            return int(c["id"][1:])
        except (ValueError, IndexError):
            return 10 ** 9

    def _score(c: dict) -> tuple[int, int]:
        desc_words = set(c.get("description", "").lower().split())
        bonus = 0
        if context_words:
            bonus += 2 * int(bool(desc_words & context_words))
        bonus += int(bool(desc_words & _HIGH_VALUE_DESCRIPTION_WORDS))
        qid_n = _qid_num(c)
        bonus -= int(qid_n > 10_000_000)
        return (-bonus, qid_n)

    return min(candidates, key=_score)


def lookup_entities(question: str, config: dict, model: str | None = None) -> list[dict]:
    """
    Extract named entities from question and resolve them to Wikidata QIDs.

    If model is provided, asks the LLM to identify entities first; falls back
    to spaCy/regex extraction when the LLM returns nothing or fails.

    Returns a list of dicts:
        {"surface": "Albert Einstein", "qid": "Q937", "label": "...", "description": "..."}

    Returns [] if the config endpoint is not Wikidata, no entities are found,
    or any error occurs.
    """
    try:
        if _WIKIDATA_HOST not in config.get("endpoint", ""):
            return []

        if model:
            llm_entities, _ = _extract_via_llm(question, model)
            # LLM returns lowercase strings for concept classes ("galaxy") and
            # capitalized strings for proper nouns ("Apple Inc.") — use that to tag.
            entities_tagged: list[tuple[str, bool]] = [
                (e, bool(e and e[0].islower())) for e in llm_entities
            ]
        else:
            entities_tagged = _extract_entities(question)
        if not entities_tagged:
            return []

        context_words = frozenset(question.lower().split()) - _QUESTION_STOPWORDS
        results = []
        for surface, is_class in entities_tagged:
            search_term = _NATIONALITY_TO_COUNTRY.get(surface.lower(), surface)
            candidates = _search_wikidata(search_term, limit=7)
            best = _pick_best_candidate(candidates, context_words=context_words)
            if best:
                results.append({
                    "surface": surface,
                    "qid": best["id"],
                    "label": best["label"],
                    "description": best["description"],
                    "is_class": is_class,
                })
        return results
    except Exception:
        logger.warning("entity_linker.lookup_entities failed silently", exc_info=True)
        return []
