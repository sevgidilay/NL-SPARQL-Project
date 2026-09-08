"""
Generic Wikidata config used when "Wikidata lookup only" mode is active.

No domain-specific few-shot examples or ontology hints are injected.
Entity/predicate lookup still runs via the Wikidata Search API.
All queries target the public Wikidata SPARQL endpoint.
"""

WIKIDATA_GENERIC_CONFIG: dict = {
    "domain_name": "Wikidata (Generic)",
    "endpoint": "https://query.wikidata.org/sparql",
    "prefixes": (
        "PREFIX wd: <http://www.wikidata.org/entity/>\n"
        "PREFIX wdt: <http://www.wikidata.org/prop/direct/>\n"
        "PREFIX wikibase: <http://wikiba.se/ontology#>\n"
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
        "PREFIX schema: <http://schema.org/>\n"
        "PREFIX skos: <http://www.w3.org/2004/02/skos/core#>\n"
        "PREFIX bd: <http://www.bigdata.com/rdf#>"
    ),
    "ontology_hints": "",
    "few_shot_examples": [
        # Pattern: list instances of a type using P31/P279* type hierarchy
        {
            "nl": "List 10 countries",
            "sparql": (
                "SELECT DISTINCT ?country ?countryLabel WHERE {\n"
                "  ?country wdt:P31/wdt:P279* wd:Q6256 .\n"
                "  SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . }\n"
                "}\n"
                "LIMIT 10"
            ),
        },
        # Pattern: list instances of a creative-works type
        {
            "nl": "List 10 novels",
            "sparql": (
                "SELECT DISTINCT ?novel ?novelLabel WHERE {\n"
                "  ?novel wdt:P31/wdt:P279* wd:Q8261 .\n"
                "  SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . }\n"
                "}\n"
                "LIMIT 10"
            ),
        },
        # Pattern: reverse property lookup — entity is the object, find subjects
        {
            "nl": "Who founded Apple Inc.?",
            "sparql": (
                "SELECT DISTINCT ?founder ?founderLabel WHERE {\n"
                "  wd:Q312 wdt:P112 ?founder .\n"
                "  SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . }\n"
                "}"
            ),
        },
        # Pattern: membership / part-of using P361
        {
            "nl": "Which states are part of Germany?",
            "sparql": (
                "SELECT DISTINCT ?state ?stateLabel WHERE {\n"
                "  ?state wdt:P361 wd:Q183 .\n"
                "  SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . }\n"
                "}"
            ),
        },
        # Pattern: influence relationship using P737
        {
            "nl": "Who influenced Charles Darwin?",
            "sparql": (
                "SELECT DISTINCT ?person ?personLabel WHERE {\n"
                "  wd:Q1035 wdt:P737 ?person .\n"
                "  SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . }\n"
                "}"
            ),
        },
        # Pattern: multi-filter combining type, nationality and date range
        {
            "nl": "List French philosophers born before 1800",
            "sparql": (
                "SELECT DISTINCT ?person ?personLabel WHERE {\n"
                "  ?person wdt:P31 wd:Q5 .\n"
                "  ?person wdt:P106 wd:Q4964182 .\n"
                "  ?person wdt:P27 wd:Q142 .\n"
                "  ?person wdt:P569 ?birth .\n"
                "  FILTER(YEAR(?birth) < 1800)\n"
                "  SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . }\n"
                "}\n"
                "LIMIT 20"
            ),
        },
        # Pattern: parent astronomical body using P397 (reversed: moons whose parent is the planet)
        {
            "nl": "Which moons orbit Mars?",
            "sparql": (
                "SELECT DISTINCT ?moon ?moonLabel WHERE {\n"
                "  ?moon wdt:P397 wd:Q111 .\n"
                "  SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . }\n"
                "}"
            ),
        },
        # Pattern: list instances of a class type (astronomical) — TYPE is OBJECT of P31
        {
            "nl": "List 10 galaxies",
            "sparql": (
                "SELECT DISTINCT ?galaxy ?galaxyLabel WHERE {\n"
                "  ?galaxy wdt:P31/wdt:P279* wd:Q318 .\n"
                "  SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . }\n"
                "}\n"
                "LIMIT 10"
            ),
        },
        # Pattern: list people by occupation — combine instance-of-human (Q5) with occupation
        {
            "nl": "List 10 tennis players",
            "sparql": (
                "SELECT DISTINCT ?player ?playerLabel WHERE {\n"
                "  ?player wdt:P31 wd:Q5 .\n"
                "  ?player wdt:P106 wd:Q10833314 .\n"
                "  SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . }\n"
                "}\n"
                "LIMIT 10"
            ),
        },
    ],
    "keywords": [],
}
