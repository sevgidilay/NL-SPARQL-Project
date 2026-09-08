## Bidirectional Translation Between Natural Language and SPARQL

This project builds a prototype that converts natural language to SPARQL queries and SPARQL queries back to natural language, with a focus on feasibility and prompt-engineering strategies.

## Repository Setup

```bash
git clone https://gitlab.unige.ch/kos_2026/group_b_lamia.git
cd group_b_lamia
git config --local user.name "Your Name"
git config --local user.email "your.email@etu.unige.ch"
```

## Prerequisites

- Python 3.9+
- Access to the UNIGE network (VPN or on-campus) — required to reach the Hactar LLM at `hactar.unige.ch`
- A Hactar API key

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

Create a `.env` file in the project root with your Hactar credentials:

```
HACTAR_API_KEY=your_key_here
HACTAR_BASE_URL=https://hactar.unige.ch
HACTAR_MODEL=llama3.3:latest
```

## Running the App

```bash
python3 -m streamlit run app.py
```

Then open http://localhost:8501 in your browser.

The sidebar lets you select:
- **Domain** — one of four pre-configured knowledge bases (Movies/DBpedia, Diseases, Astronomy, Philosophy)
- **LLM Model** — fetched live from Hactar; falls back to a text input if unreachable

**Tab 1 — Natural Language → SPARQL:** type a question, click *Translate & Execute*. The app generates SPARQL, runs it against the live endpoint, and (optionally) summarises the results in plain English.

**Tab 2 — SPARQL → Natural Language:** paste a SPARQL query to get a plain-English explanation, plus live execution to verify the query is valid.

## Adding a New Domain

Create a new YAML file in `configs/`. Use `configs/dbpedia_movies.yaml` as a template. The app loads all `.yaml` files in that directory automatically — no code changes needed.


