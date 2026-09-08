"""
Natural Language to SPARQL
===========================
Translates natural language questions into SPARQL queries
using few-shot prompting with domain-specific examples.
"""

from src import entity_linker
from src import llm_client


def build_prompt(
    question: str,
    config: dict,
    entity_hints: list | None = None,
    predicate_hints: list | None = None,
    entity_properties: dict[str, list[dict]] | None = None,
) -> str:
    """
    Build the full prompt for the LLM, including:
    - System instructions
    - Ontology hints from the domain config
    - Few-shot examples from the domain config
    - The actual user question

    Args:
        question: Natural language question from the user
        config: Domain configuration dictionary (loaded from YAML)
        entity_hints: Pre-resolved Wikidata entity QIDs
        predicate_hints: Pre-resolved Wikidata property IDs for verbs in the question
        entity_properties: Map of QID → [{pid, label}] of all properties live on that entity

    Returns:
        Complete prompt string to send to the LLM
    """
    # Gather ontology hints
    ontology = config.get("ontology_hints", "")
    prefixes = config.get("prefixes", "")

    # Build few-shot examples section
    examples_text = ""
    for ex in config.get("few_shot_examples", []):
        examples_text += f"\nQuestion: {ex.get('question') or ex.get('nl', '')}\nSPARQL:\n{ex['sparql'].strip()}\n"

    # Build entity hints block (empty string when no hints)
    entity_block = ""
    if entity_hints:
        named_hints = [h for h in entity_hints if not h.get("is_class")]
        class_hints = [h for h in entity_hints if h.get("is_class")]
        lines = []
        if named_hints:
            lines.append("ENTITY LOOKUP RESULTS (verified Wikidata IDs from live lookup):")
            for hint in named_hints:
                lines.append(f'- "{hint["surface"]}" → wd:{hint["qid"]} ({hint["description"]})')
            lines.append(
                "Prefer these verified IDs over guessing. "
                "Use label-based fallback only if an entity is not listed here."
            )
        if class_hints:
            if lines:
                lines.append("")
            lines.append("TYPE/CLASS LOOKUP RESULTS (concept types — list their instances):")
            for hint in class_hints:
                lines.append(
                    f'- "{hint["surface"]}" is a TYPE → wd:{hint["qid"]} ({hint["description"]})'
                    f" — list instances with: ?item wdt:P31/wdt:P279* wd:{hint['qid']}"
                )
            lines.append(
                "IMPORTANT: For type/class entities above, wd:Q_CLASS must be the OBJECT of wdt:P31 "
                "(not the subject). Use pattern: ?item wdt:P31/wdt:P279* wd:Q_CLASS ."
            )
        entity_block = "\n".join(lines) + "\n\n"

    # Build predicate hints block (empty string when no hints)
    predicate_block = ""
    if predicate_hints:
        lines = ["RELATION LOOKUP RESULTS (verified Wikidata property IDs for this question):"]
        for hint in predicate_hints:
            lines.append(f'- "{hint["surface"]}" → {hint["pid"]} ({hint["label"]})')
        lines.append("Prefer these verified predicates over guessing.")
        predicate_block = "\n".join(lines) + "\n\n"

    # Build entity properties block — actual properties live on each resolved entity
    properties_block = ""
    if entity_properties:
        lines = [
            "ENTITY PROPERTIES (real properties fetched from Wikidata for each resolved entity):",
            "Use these to pick the correct predicate — do not guess PIDs not listed here.",
        ]
        for qid, props in entity_properties.items():
            label = next(
                (h["description"] for h in (entity_hints or []) if h["qid"] == qid),
                qid,
            )
            lines.append(f"wd:{qid} ({label}):")
            for p in props:
                lines.append(f'  {p["pid"]} — {p["label"]}')
        properties_block = "\n".join(lines) + "\n\n"

    prompt = f"""You are a SPARQL query generator.

RULES:
- Generate valid SPARQL queries using the prefixes provided below
- Return ONLY the SPARQL query, no explanations, no markdown fences
- Always use SELECT DISTINCT to avoid duplicate rows in results
- Always include a mechanism for human-readable labels (SERVICE wikibase:label for Wikidata, or rdfs:label with language filter for DBpedia)
- For Wikidata, SERVICE wikibase:label auto-populates ?xLabel AND ?xDescription for any entity variable ?x — always add ?entityDescription to the SELECT when the question asks who/what an entity is (e.g. "Who is X?", "What is X?", "Tell me about X")
- Use LIMIT when the question does not specify an exact count (default LIMIT 20)
- Think step by step about which properties and entities to use

TYPE CONSTRAINT RULES (Wikidata):
- When the question asks for real people (scientists, athletes, politicians, musicians, actors, etc.), always add: ?person wdt:P31 wd:Q5 . (instance of human)
- This prevents fictional characters from appearing alongside real people in results
- For other real-world entity types, use an appropriate type constraint (e.g. ?org wdt:P31 wd:Q4830453 for businesses, ?country wdt:P31 wd:Q6256 for countries)

ENTITY ID RULES (IMPORTANT):
- ONLY use specific entity IDs (like wd:Q12206 or dbr:Inception) if you are CERTAIN they are correct
- If you are not sure about an entity ID, do NOT guess — instead use a variable with rdfs:label and FILTER
- Example: instead of guessing "brain = wd:Q9604", write:
    ?organ rdfs:label "brain"@en .
    ?disease wdt:P927 ?organ .
- Prefer label-based matching over guessed IDs to avoid returning empty results
- The entity IDs shown in the examples below are verified — those are safe to reuse
- When using a verified entity ID from ENTITY LOOKUP RESULTS, use it as the SUBJECT of the property:
    wd:Q{{qid}} wdt:P{{pid}} ?value   — NOT   ?value wdt:P{{pid}} wd:Q{{qid}}
  Exception: reverse the direction only when the question asks "what X does entity Y belong to?"

NEGATION / EXCLUSION RULES (IMPORTANT):
- NEVER use FILTER(?x != "label") — string comparison against URIs always fails and returns wrong results
- For exclusion by type or property, use MINUS:
    Example: "scientists who are not physicists"
    MINUS {{ ?scientist wdt:P106 wd:Q169470 . }}
- For exclusion by label when no entity ID is known, use FILTER NOT EXISTS with rdfs:label:
    Example: "diseases excluding cancer"
    FILTER NOT EXISTS {{ ?disease rdfs:label "cancer"@en . }}
- NEVER write FILTER(?x != wd:QXXX) unless you are certain the ID is correct — use MINUS instead

AVAILABLE PREFIXES:
{prefixes}

DOMAIN KNOWLEDGE:
{ontology}

EXAMPLES:
{examples_text}
{entity_block}{predicate_block}{properties_block}Now translate this question into SPARQL:

Question: {question}
SPARQL:
"""
    return prompt


def build_retry_prompt(question: str, config: dict, failed_sparql: str) -> str:
    """Build a follow-up prompt when the first query returned 0 results or had an error."""
    prefixes = config.get("prefixes", "")
    ontology = config.get("ontology_hints", "")
    return f"""You are a SPARQL query generator.

The previous query for the question below returned ZERO results or had a syntax/execution error. This usually means a hardcoded entity ID was wrong, did not exist, or the query structure was invalid.

PREVIOUS (broken) QUERY:
{failed_sparql}

FIX INSTRUCTIONS:
- Do NOT guess entity IDs (like wd:Q12345 or dbr:SomeName)
- Instead, match entities by label using rdfs:label or skos:altLabel with a FILTER or VALUES clause
- For Wikidata: use ?entity rdfs:label "{{}}"@en or wikibase:label service
- For DBpedia: use ?entity rdfs:label "{{}}"@en with FILTER(LANG(?label) = "en")
- Keep the same semantic intent as the original question

AVAILABLE PREFIXES:
{prefixes}

DOMAIN KNOWLEDGE:
{ontology}

Now rewrite the SPARQL for this question, fixing the entity matching:

Question: {question}
SPARQL:
"""


def explain_query(sparql: str, question: str, model: str = None) -> str:
    """Return a one-sentence explanation of what a SPARQL query retrieves."""
    prompt = (
        f'Given this SPARQL query:\n{sparql}\n\n'
        f'For the question: "{question}"\n\n'
        "Summarize in exactly one sentence what this query retrieves. "
        "Be specific about the entity and the property being queried. "
        "Reply with the sentence only, no preamble."
    )
    return llm_client.chat(prompt, model=model)


def results_to_nl(question: str, results: list, model: str = None) -> str:
    """Convert SPARQL result rows into a one-sentence natural language answer."""
    if not results:
        return "No results found."
    rows_text = "\n".join(
        ", ".join(f"{k}: {v}" for k, v in row.items())
        for row in results[:5]
    )
    prompt = (
        f'Question: "{question}"\n\n'
        f"Results from a knowledge base query:\n{rows_text}\n\n"
        "Answer the question in one natural language sentence using these results. "
        "Reply with the sentence only."
    )
    return llm_client.chat(prompt, model=model)


def translate(
    question: str,
    config: dict,
    model: str = None,
    temperature: float = None,
    entity_hints: list | None = None,
    predicate_hints: list | None = None,
    entity_properties: dict[str, list[dict]] | None = None,
) -> str:
    """
    Translate a natural language question to a SPARQL query.

    Args:
        question: Natural language question
        config: Domain configuration dictionary
        model: Optional model override
        entity_hints: Pre-computed entity lookup results. If None, lookup runs
                      automatically. Pass an explicit empty list [] to skip lookup.
        predicate_hints: Pre-computed predicate/relation lookup results. If None,
                         lookup runs automatically. Pass [] to skip.
        entity_properties: Map of QID → [{pid, label}] fetched from Wikidata for
                           each resolved entity. Injected into the prompt so the LLM
                           knows which predicates actually exist on the entity.

    Returns:
        Generated SPARQL query string
    """
    if entity_hints is None:
        entity_hints = entity_linker.lookup_entities(question, config)
    if predicate_hints is None:
        predicate_hints = entity_linker.lookup_relations(question, config)
    prompt = build_prompt(
        question, config,
        entity_hints=entity_hints,
        predicate_hints=predicate_hints,
        entity_properties=entity_properties,
    )
    response = llm_client.chat(prompt, model=model, temperature=temperature)
    return response
