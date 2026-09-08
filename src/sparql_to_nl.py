"""
SPARQL to Natural Language
===========================
Translates SPARQL queries into human-readable natural language.

Uses a two-layer approach:
1. Rule-based: Parse simple SELECT queries and build a sentence
2. LLM fallback: For complex queries, ask the LLM to explain
"""

import re
from src import llm_client


# A SPARQL term: a variable or a prefixed name whose local part may contain
# hyphens and dots (e.g. dbr:Nineteen_Eighty-Four, wdt:P279).
_TERM = r'(\?\w+|(?:\w+:[\w\-\.]+))'

# Predicates that only fetch display labels — no semantic content.
_LABEL_PREDICATES = {
    'rdfs:label', 'schema:name', 'foaf:name', 'schema:description',
}

# FILTER sub-expressions that are purely technical (language, type casts).
_TECHNICAL_FILTER_RE = re.compile(
    r'LANG\s*\(|LANGMATCHES\s*\(|DATATYPE\s*\(|isURI\s*\(|isLiteral\s*\(',
    re.IGNORECASE,
)

# Variable-name suffixes that indicate a display-label alias.
_DISPLAY_SUFFIXES = ('label', 'name')

# English irregular plurals for SPARQL class local names.
_IRREGULAR_PLURALS = {
    'country':    'countries',
    'city':       'cities',
    'galaxy':     'galaxies',
    'category':   'categories',
    'century':    'centuries',
    'discovery':  'discoveries',
    'body':       'bodies',
    'entity':     'entities',
    'property':   'properties',
    'territory':  'territories',
    'university': 'universities',
}


def rule_based_translate(query: str, config: dict) -> str:
    """
    Attempt to translate a SPARQL query using simple rules.

    Returns a natural-language description, or None when the query is too
    complex or contains identifiers that cannot be translated.
    """
    query_upper = query.upper()

    # --- Complexity gates: defer to LLM ----------------------------------
    if 'UNION' in query_upper or 'MINUS' in query_upper:
        return None
    if query_upper.count('SELECT') > 1:
        return None
    if 'GROUP BY' in query_upper:
        return None

    # --- Load domain lookups ---------------------------------------------
    property_labels = _extract_property_labels(config)
    entity_labels   = _extract_entity_labels(config)

    # Wikidata QIDs not in the config lookup cannot be translated
    for qid in re.findall(r'\bwd:Q\d+\b', query):
        if qid not in entity_labels:
            return None

    # --- WHERE body ------------------------------------------------------
    where_body = _extract_where_body(query)
    if where_body is None:
        return None

    # --- Type constraints (?var a dbo:Class  /  ?var rdf:type ...) -------
    var_types: dict[str, str] = {}

    type_re = re.compile(
        r'(\?\w+)\s+(?:a\b|rdf:type)\s+(' + _TERM[1:],
        re.IGNORECASE,
    )
    for m in type_re.finditer(where_body):
        var, cls = m.group(1), m.group(2)
        if not cls.startswith('?'):
            var_types[var] = _humanize_local_name(cls)

    # Wikidata: wdt:P31 wd:QXXX is "instance of <type>"
    p31_re = re.compile(r'(\?\w+)\s+wdt:P31\s+(wd:Q\d+)', re.IGNORECASE)
    for m in p31_re.finditer(where_body):
        var, qid = m.group(1), m.group(2)
        if qid in entity_labels:
            var_types.setdefault(var, entity_labels[qid].lower())

    # --- SELECT variables ------------------------------------------------
    select_match = re.search(
        r'SELECT\s+(?:DISTINCT\s+)?(.*?)\s+WHERE',
        query, re.IGNORECASE | re.DOTALL,
    )
    if not select_match:
        return None
    all_vars = re.findall(r'\?(\w+)', select_match.group(1))

    content_vars = [
        v for v in all_vars
        if not any(v.lower().endswith(s) for s in _DISPLAY_SUFFIXES)
    ]

    # When every SELECT variable is a display alias, find the semantic var
    if not content_vars:
        for typed_var in var_types:
            content_vars = [typed_var.lstrip('?')]
            break

    if not content_vars:
        content_vars = all_vars[:1]
    if not content_vars:
        return None

    # --- Wikidata property guard -----------------------------------------
    # Any wdt:P... not in the config lookup would render as "p123" — defer to LLM
    for m in re.finditer(r'\bwdt:(P\d+)\b', where_body):
        pred = 'wdt:' + m.group(1)
        if pred not in property_labels and pred != 'wdt:P31':
            return None

    # --- Meaningful triples ----------------------------------------------
    triple_re = re.compile(_TERM + r'\s+' + _TERM + r'\s+' + _TERM, re.IGNORECASE)

    clauses = []
    for m in triple_re.finditer(where_body):
        subj, pred, obj = m.group(1), m.group(2), m.group(3)

        if pred.lower() in ('a', 'rdf:type'):
            continue
        if pred.lower() in _LABEL_PREDICATES:
            continue
        if pred.startswith('?'):
            continue
        if re.match(r'wdt:P31$', pred, re.IGNORECASE):
            continue

        subj_is_var = subj.startswith('?')
        obj_is_var  = obj.startswith('?')

        if not subj_is_var and obj_is_var:
            clauses.append(('fixed_subj', _format_entity(subj), pred, obj))
        elif subj_is_var and not obj_is_var:
            obj_label = entity_labels.get(obj, _format_entity(obj))
            clauses.append(('fixed_obj', subj, pred, obj_label))
        elif subj_is_var and obj_is_var:
            obj_name = obj.lstrip('?').lower()
            if any(obj_name.endswith(s) for s in _DISPLAY_SUFFIXES):
                continue
            clauses.append(('join', subj, pred, obj))

    # --- Sentence construction ------------------------------------------
    primary_var  = '?' + content_vars[0]
    primary_type = var_types.get(primary_var)

    subject_phrase = _pluralize(primary_type) if primary_type else (
        _pluralize(_humanize_local_name(content_vars[0]))
    )

    fixed_subj_clauses = [c for c in clauses if c[0] == 'fixed_subj']
    constraint_clauses = [c for c in clauses if c[0] == 'fixed_obj']
    join_clauses       = [c for c in clauses if c[0] == 'join']

    # Remove constraints that just restate the type (e.g. "instance of disease"
    # when the subject is already labelled "diseases")
    constraint_clauses = [
        c for c in constraint_clauses
        if not (c[1] == primary_var and c[3].lower() == (primary_type or '').lower())
    ]

    if fixed_subj_clauses and not constraint_clauses and len(content_vars) == 1:
        retrievals = [
            f"the {_noun_label(c[2], property_labels)} of {c[1]}"
            for c in fixed_subj_clauses
        ]
        main = 'This query retrieves ' + ' and '.join(retrievals) + '.'
    else:
        parts = []
        for c in constraint_clauses:
            parts.append(f'where the {_verb_label(c[2], property_labels)} is {c[3]}')
        for c in join_clauses:
            vl    = _verb_label(c[2], property_labels)
            otype = var_types.get(c[3])
            parts.append(f'along with their {vl}' + (f' ({_pluralize(otype)})' if otype else ''))

        if parts:
            main = f"This query searches for {subject_phrase} {', '.join(parts)}."
        elif primary_type:
            main = f'This query lists {subject_phrase}.'
        else:
            main = f'This query retrieves {subject_phrase}.'

    # --- Extra sentences -------------------------------------------------
    extra = []

    filter_mentioned = False
    for fm in re.finditer(r'FILTER\s*\((.+?)\)', where_body, re.IGNORECASE | re.DOTALL):
        ftext = fm.group(1).strip()
        if _TECHNICAL_FILTER_RE.search(ftext):
            continue
        if not filter_mentioned:
            extra.append('Results are narrowed by a specific filter condition.')
            filter_mentioned = True

    if re.search(r'FILTER\s+NOT\s+EXISTS', where_body, re.IGNORECASE):
        extra.append('Certain items are excluded based on a specific condition.')

    order_match = re.search(
        r'ORDER\s+BY\s+(DESC|ASC)?\s*\(?(\?\w+)\)?', query, re.IGNORECASE,
    )
    if order_match:
        direction = (order_match.group(1) or 'ASC').upper()
        order_var = _humanize_local_name(order_match.group(2))
        order_var = re.sub(r'\blabel\b', 'name', order_var).strip()
        if direction == 'DESC':
            extra.append(f'Results are sorted by {order_var} from highest to lowest.')
        else:
            extra.append(f'Results are sorted by {order_var}.')

    limit_match = re.search(r'LIMIT\s+(\d+)', query, re.IGNORECASE)
    if limit_match:
        extra.append(f"It returns up to {limit_match.group(1)} results.")

    return ' '.join([main] + extra)


def llm_translate(query: str, model: str = None) -> str:
    """
    Use the LLM to explain a SPARQL query in natural language.
    Used as fallback when rule-based translation is too complex.
    """
    prompt = f"""You are a SPARQL query explainer. Explain what the query below is looking for in clear, natural English — the way a knowledgeable human would describe it to someone unfamiliar with SPARQL.

Rules you must follow:
1. Never expose internal identifiers such as wd:Q12136, wdt:P31, rdfs:label, dbr:, dbo:, or any prefixed URI. Always translate them to their human-readable meaning.
2. Never use arrow notation (like A → B → C) or triple-pattern notation. Write full sentences.
3. Describe WHAT the query is looking for and WHY, not HOW the triples are structured.
4. Mention filters, limits, ordering, or grouping only if they add meaningful context, described in plain language.
5. Keep the explanation to 2-3 sentences. Do not use bullet points.

SPARQL Query:
{query}

Explanation:"""

    return llm_client.chat(prompt, model=model)


def translate(query: str, config: dict, model: str = None) -> str:
    """
    Translate a SPARQL query to natural language.
    Tries rule-based first, falls back to LLM for complex queries.
    """
    result = rule_based_translate(query, config)
    if result:
        return result
    return llm_translate(query, model=model)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _extract_where_body(query: str) -> str | None:
    clean = re.sub(
        r'SERVICE\s+\S+\s*\{[^{}]*\}', '', query,
        flags=re.IGNORECASE | re.DOTALL,
    )
    m = re.search(r'WHERE\s*\{(.*)\}', clean, re.IGNORECASE | re.DOTALL)
    return m.group(1) if m else None


def _extract_property_labels(config: dict) -> dict:
    labels: dict[str, str] = {}
    hints = config.get('ontology_hints', '')
    prefix = r'(?:wdt|dbo|dbp|rdfs|rdf|foaf|schema)'

    for m in re.finditer(rf'({prefix}:\w+)\s*=\s*"([^"]+)"', hints):
        labels[m.group(1)] = _clean_label(m.group(2))

    for m in re.finditer(rf'({prefix}:\w+)\s*[—\-]{{1,2}}\s*([^(\n]+)', hints):
        pred = m.group(1)
        if pred in labels:
            continue
        desc = _clean_label(m.group(2).strip())
        if desc:
            labels[pred] = desc

    return labels


def _extract_entity_labels(config: dict) -> dict:
    labels: dict[str, str] = {}
    hints = config.get('ontology_hints', '')
    for m in re.finditer(r'(wd:Q\d+)\s*=\s*"([^"]+)"', hints):
        labels[m.group(1)] = m.group(2)
    return labels


def _clean_label(label: str) -> str:
    label = label.split(' / ')[0].strip()
    label = re.sub(r'\s*\([^)]*\)', '', label).strip()
    return label


def _pluralize(word: str) -> str:
    if not word:
        return word
    if word in _IRREGULAR_PLURALS:
        return _IRREGULAR_PLURALS[word]
    if word.endswith('y') and len(word) > 1 and word[-2] not in 'aeiou':
        return word[:-1] + 'ies'
    if re.search(r'(?:s|x|z|ch|sh)$', word):
        return word + 'es'
    return word + 's'


def _humanize_local_name(name: str) -> str:
    name = name.lstrip('?')
    name = re.sub(r'^\w+:', '', name)
    name = name.replace('_', ' ').replace('-', ' ')
    name = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
    return name.lower().strip()


def _format_entity(term: str) -> str:
    if term.startswith('?'):
        return _humanize_local_name(term[1:])
    local = re.sub(r'^\w+:', '', term)
    return local.replace('_', ' ').replace('-', ' ')


def _noun_label(pred: str, property_labels: dict) -> str:
    if re.match(r'wdt:P\d+$', pred):
        return property_labels.get(pred, _humanize_local_name(pred))
    config = property_labels.get(pred, '')
    if config and ' of ' not in config.lower():
        return config
    return _humanize_local_name(pred)


def _verb_label(pred: str, property_labels: dict) -> str:
    if re.match(r'wdt:P\d+$', pred):
        return property_labels.get(pred, _humanize_local_name(pred))
    return _humanize_local_name(pred)
