"""
Domain Router
==============
Automatically detects which domain best matches a natural language question.
First tries a fast keyword pre-filter; falls back to LLM classification only
when no keyword match is found.
"""

import re
from src import llm_client


_WEAK_KEYWORDS = {
    # Country names are useful for geography-only questions, but they should
    # not overpower a concrete non-geography domain signal such as "archers".
    "turkey",
    "türkiye",
}


def _keyword_score(question_lower: str, keywords: list[str]) -> float:
    score = 0.0
    for kw in keywords:
        kw_lower = kw.lower()
        if re.search(r'\b' + re.escape(kw_lower) + r'\b', question_lower):
            score += 0.5 if kw_lower in _WEAK_KEYWORDS else 1.0
    return score


def _keyword_match(question: str, configs: dict) -> str | None:
    """
    Check each domain's keyword list against the question.
    Returns the domain name if exactly one domain matches,
    or the highest-scoring domain if scores are unambiguous.
    Returns None if the result is ambiguous or no keywords match.
    """
    question_lower = question.lower()
    scores = {}

    for name, cfg in configs.items():
        keywords = cfg.get("keywords", [])
        score = _keyword_score(question_lower, keywords)
        if score > 0:
            scores[name] = score

    if not scores:
        return None

    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best_name, best_score = sorted_scores[0]

    if len(sorted_scores) == 1:
        return best_name

    second_score = sorted_scores[1][1]
    if best_score > second_score:
        return best_name

    return None


def detect_domain(question: str, configs: dict, model: str = None) -> str:
    """
    Given a natural language question and all available domain configs,
    return the name of the best-matching domain.

    Args:
        question: The user's natural language question
        configs: Dict of {domain_name: config_dict} for all available domains
        model: Optional model override

    Returns:
        Name of the best-matching domain (key from configs dict)
    """
    if len(configs) == 1:
        return list(configs.keys())[0]

    keyword_result = _keyword_match(question, configs)
    if keyword_result:
        return keyword_result

    domain_list = []
    for name, cfg in configs.items():
        desc = cfg.get("description", "")
        domain_list.append(f"- {name}: {desc}")
    domains_text = "\n".join(domain_list)

    domain_names = list(configs.keys())

    prompt = f"""You are a domain classifier. Given a user's question, pick the single best domain from the list below.

Available domains:
{domains_text}

User question: "{question}"

Rules:
- Return ONLY the exact domain name, nothing else
- No explanation, no quotes, no punctuation
- Pick exactly one from: {", ".join(domain_names)}

Best domain:"""

    response = llm_client.chat(prompt, model=model).strip()

    response = response.strip().strip('"').strip("'").strip(".")

    if response in configs:
        return response

    for name in configs:
        if name.lower() == response.lower():
            return name

    for name in configs:
        if name.lower() in response.lower() or response.lower() in name.lower():
            return name

    return list(configs.keys())[0]
