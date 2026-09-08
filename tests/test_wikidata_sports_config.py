from pathlib import Path

import yaml


CONFIG_PATH = Path(__file__).parent.parent / "configs" / "wikidata_sports.yaml"


def _sports_config():
    with open(CONFIG_PATH) as fh:
        return yaml.safe_load(fh)


def test_fifa_world_cup_example_uses_competition_edition_property():
    cfg = _sports_config()
    example = next(
        ex for ex in cfg["few_shot_examples"]
        if ex["question"] == "Who won the FIFA World Cup?"
    )

    assert "wdt:P3450 wd:Q19317" in example["sparql"]
    assert "wdt:P31 wd:Q19317" not in example["sparql"]


def test_olympic_gold_medal_qid_is_not_station_qid():
    cfg = _sports_config()
    example = next(
        ex for ex in cfg["few_shot_examples"]
        if ex["question"] == "List Olympic gold medalists in athletics"
    )

    assert 'wd:Q15243387 = "Olympic gold medal"' in cfg["ontology_hints"]
    assert "wd:Q15243387" in example["sparql"]
    assert "wd:Q319921" not in cfg["ontology_hints"]
    assert "wd:Q319921" not in example["sparql"]


def test_spanish_club_member_examples_use_verified_club_qids():
    cfg = _sports_config()
    examples = {
        ex["question"]: ex["sparql"]
        for ex in cfg["few_shot_examples"]
    }

    assert 'wd:Q7156 = "FC Barcelona"' in cfg["ontology_hints"]
    assert 'wd:Q8682 = "Real Madrid Club de Fútbol"' in cfg["ontology_hints"]
    assert "wdt:P54 wd:Q7156" in examples["List players who were members of FC Barcelona"]
    assert "wdt:P54 wd:Q8682" in examples["List players who were members of Real Madrid"]


def test_verified_english_club_qids_do_not_point_to_unrelated_entities():
    cfg = _sports_config()
    hints = cfg["ontology_hints"]

    assert 'wd:Q18656 = "Manchester United F.C."' in hints
    assert 'wd:Q50602 = "Manchester City F.C."' in hints
    assert 'wd:Q9617 = "Arsenal F.C."' in hints
    assert 'wd:Q9616 = "Chelsea F.C."' in hints

    assert "wd:Q18602070" not in hints  # ferrous hexacyanomanganate
    assert "wd:Q4803" not in hints  # Surakarta
    assert "wd:Q9599" not in hints  # Susanne Albers
    assert "wd:Q503" not in hints  # banana


def test_tennis_player_examples_use_tennis_player_occupation():
    cfg = _sports_config()
    examples = {
        ex["question"]: ex["sparql"]
        for ex in cfg["few_shot_examples"]
    }

    assert 'wd:Q10833314 = "tennis player"' in cfg["ontology_hints"]
    assert "wdt:P106 wd:Q10833314" in examples["List 10 tennis players"]
    assert "wdt:P106 wd:Q10833314" in examples["List tennis players from the United States"]
    assert "wdt:P641 wd:Q847" not in examples["List 10 tennis players"]
    assert "wdt:P641 wd:Q847" not in examples["List tennis players from the United States"]


def test_broad_player_examples_are_bounded_to_avoid_wdqs_timeouts():
    cfg = _sports_config()
    examples = {
        ex["question"]: ex["sparql"]
        for ex in cfg["few_shot_examples"]
    }

    for question in [
        "List 10 football players",
        "List 10 tennis players",
        "List 10 basketball players",
    ]:
        sparql = examples[question]
        assert "SERVICE bd:sample" in sparql
        assert "bd:sample.limit 30" in sparql
        assert "ORDER BY ?player" in sparql
        assert "LIMIT 10" in sparql


def test_count_athletes_by_sport_is_bounded_to_known_sports():
    cfg = _sports_config()
    example = next(
        ex for ex in cfg["few_shot_examples"]
        if ex["question"] == "Count athletes by sport"
    )

    assert "VALUES ?sport" in example["sparql"]
    assert "wd:Q2736" in example["sparql"]
    assert "wd:Q41466" in example["sparql"]
    assert "wd:Q847" in example["sparql"]
    assert "wd:Q5372" in example["sparql"]
    assert "wd:Q542" in example["sparql"]


def test_premier_league_example_filters_to_uk_clubs():
    cfg = _sports_config()
    example = next(
        ex for ex in cfg["few_shot_examples"]
        if ex["question"] == "List football clubs in the English Premier League"
    )

    assert "wdt:P118 wd:Q9448" in example["sparql"]
    assert "wdt:P17 wd:Q145" in example["sparql"]
    assert "ORDER BY ?clubLabel" in example["sparql"]


def test_hockey_players_from_turkey_uses_country_of_citizenship():
    cfg = _sports_config()
    example = next(
        ex for ex in cfg["few_shot_examples"]
        if ex["question"] == "List hockey players from Turkey"
    )

    assert 'wd:Q43 = "Turkey"' in cfg["ontology_hints"]
    assert "wdt:P106 wd:Q11774891" in example["sparql"]
    assert "wdt:P27 wd:Q43" in example["sparql"]
    assert "LIMIT 10" in example["sparql"]


def test_archers_from_turkey_uses_archer_occupation_and_country():
    cfg = _sports_config()
    example = next(
        ex for ex in cfg["few_shot_examples"]
        if ex["question"] == "Find 10 archers from Turkey"
    )

    assert "archers" in cfg["keywords"]
    assert 'wd:Q108429 = "archery"' in cfg["ontology_hints"]
    assert 'wd:Q13382355 = "archer"' in cfg["ontology_hints"]
    assert 'wd:Q43 = "Turkey"' in cfg["ontology_hints"]
    assert "wdt:P106 wd:Q13382355" in example["sparql"]
    assert "wdt:P27 wd:Q43" in example["sparql"]
    assert "LIMIT 10" in example["sparql"]
