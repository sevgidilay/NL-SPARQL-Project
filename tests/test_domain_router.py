from unittest.mock import patch

from src import domain_router


SPORTS_CONFIG = {
    "domain_name": "Sports (Wikidata)",
    "description": "Sports domain",
    "keywords": ["archer", "archers", "archery", "hockey"],
}

GEOGRAPHY_CONFIG = {
    "domain_name": "Geography (Wikidata)",
    "description": "Geography domain",
    "keywords": ["neighbour", "neighbours", "capital", "turkey", "türkiye"],
}


def test_archers_from_turkey_routes_to_sports_without_llm():
    configs = {
        "Sports (Wikidata)": SPORTS_CONFIG,
        "Geography (Wikidata)": GEOGRAPHY_CONFIG,
    }

    with patch("src.domain_router.llm_client.chat") as mock_chat:
        result = domain_router.detect_domain("find me 10 archers from Turkey", configs)

    assert result == "Sports (Wikidata)"
    mock_chat.assert_not_called()


def test_neighbours_of_turkey_still_routes_to_geography_without_llm():
    configs = {
        "Sports (Wikidata)": SPORTS_CONFIG,
        "Geography (Wikidata)": GEOGRAPHY_CONFIG,
    }

    with patch("src.domain_router.llm_client.chat") as mock_chat:
        result = domain_router.detect_domain("Count neighbours of Turkey", configs)

    assert result == "Geography (Wikidata)"
    mock_chat.assert_not_called()
