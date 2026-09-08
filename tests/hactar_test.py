"""
Hactar API Test Script v2
=========================
Open WebUI can use different endpoint structures.
This script tries all of them and finds the one that works.
"""

import requests
import json
import os

# ============================================================
# Try to read key from .env file, otherwise set it directly
# ============================================================
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, no problem

API_KEY = os.getenv("HACTAR_API_KEY")
BASE_URL = "https://hactar.unige.ch"
MODEL = "llama3.3:latest"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}


def try_endpoints_for_models():
    """Try different endpoints to fetch the model list"""
    print("=" * 50)
    print("TEST 1: Model List (trying different endpoints)")
    print("=" * 50)

    endpoints = [
        "/ollama/api/tags",
        "/api/tags",
        "/api/models",
        "/ollama/api/models",
    ]

    for ep in endpoints:
        try:
            resp = requests.get(f"{BASE_URL}{ep}", headers=HEADERS, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                print(f"  {ep} worked!")
                print(f"  Response keys: {list(data.keys())}")

                models = data.get("models", data.get("data", []))
                if models:
                    print(f"  {len(models)} models found:")
                    for m in models[:5]:
                        name = m.get("name", m.get("id", m.get("model", "?")))
                        print(f"    - {name}")
                    print()
                    return ep
                else:
                    print(f"  Model list empty. Raw response: {json.dumps(data)[:200]}")
            else:
                print(f"  {ep} -> {resp.status_code}")
        except Exception as e:
            print(f"  {ep} -> Error: {e}")

    print()
    return None


def try_endpoints_for_chat():
    """Try different chat endpoints"""
    print("=" * 50)
    print("TEST 2: Chat (trying different endpoints)")
    print("=" * 50)

    message = "Say hello in one sentence."

    attempts = [
        {
            "name": "OpenAI-compatible (/api/chat/completions)",
            "url": f"{BASE_URL}/api/chat/completions",
            "body": {
                "model": MODEL,
                "messages": [{"role": "user", "content": message}],
                "stream": False
            },
            "extract": lambda d: d.get("choices", [{}])[0].get("message", {}).get("content", "EMPTY")
        },
        {
            "name": "Open WebUI (/api/chat)",
            "url": f"{BASE_URL}/api/chat",
            "body": {
                "model": MODEL,
                "messages": [{"role": "user", "content": message}],
                "stream": False
            },
            "extract": lambda d: d.get("choices", [{}])[0].get("message", {}).get("content",
                                  d.get("message", {}).get("content", "EMPTY"))
        },
        {
            "name": "Ollama native (/ollama/api/chat)",
            "url": f"{BASE_URL}/ollama/api/chat",
            "body": {
                "model": MODEL,
                "messages": [{"role": "user", "content": message}],
                "stream": False
            },
            "extract": lambda d: d.get("message", {}).get("content", "EMPTY")
        },
        {
            "name": "Ollama generate (/ollama/api/generate)",
            "url": f"{BASE_URL}/ollama/api/generate",
            "body": {
                "model": MODEL,
                "prompt": message,
                "stream": False
            },
            "extract": lambda d: d.get("response", "EMPTY")
        },
    ]

    working_endpoint = None

    for attempt in attempts:
        print(f"\n  Trying: {attempt['name']}")
        try:
            resp = requests.post(
                attempt["url"],
                headers=HEADERS,
                json=attempt["body"],
                timeout=120
            )
            print(f"  Status: {resp.status_code}")

            if resp.status_code == 200:
                data = resp.json()
                print(f"  Response keys: {list(data.keys())}")
                answer = attempt["extract"](data)
                if answer and answer != "EMPTY":
                    print(f"  WORKING! Response: {answer[:100]}")
                    working_endpoint = attempt
                    break
                else:
                    print(f"  Got 200 but response is empty. Raw data:")
                    print(f"  {json.dumps(data, ensure_ascii=False)[:300]}")
            else:
                print(f"  Error response: {resp.text[:200]}")
        except Exception as e:
            print(f"  Error: {e}")

    print()
    return working_endpoint


def test_sparql_generation(endpoint_info):
    """Test SPARQL generation using the working endpoint"""
    print("=" * 50)
    print("TEST 3: SPARQL Generation")
    print("=" * 50)

    prompt = """You are a SPARQL query generator for Wikidata.

Rules:
- Use Wikidata prefixes: wd: for entities, wdt: for properties
- Return ONLY the SPARQL query, no explanation, no markdown
- Always include a LIMIT clause

Question: List 10 diseases.

SPARQL:"""

    body = endpoint_info["body"].copy()
    if "messages" in body:
        body["messages"] = [{"role": "user", "content": prompt}]
    elif "prompt" in body:
        body["prompt"] = prompt

    try:
        resp = requests.post(
            endpoint_info["url"],
            headers=HEADERS,
            json=body,
            timeout=120
        )
        data = resp.json()
        sparql = endpoint_info["extract"](data)
        print(f"Generated SPARQL:\n{sparql}\n")

        if sparql and "SELECT" in sparql.upper():
            test_sparql_execution(sparql)
        return sparql
    except Exception as e:
        print(f"Error: {e}\n")
        return None


def test_sparql_execution(sparql_query):
    """Execute the generated SPARQL on Wikidata"""
    print("--- Executing SPARQL on Wikidata ---")

    clean = sparql_query.strip()
    if "```" in clean:
        parts = clean.split("```")
        for part in parts:
            if "SELECT" in part.upper():
                clean = part.replace("sparql", "").strip()
                break

    try:
        resp = requests.get(
            "https://query.wikidata.org/sparql",
            params={"query": clean, "format": "json"},
            headers={"User-Agent": "KOS-Project-Test/1.0"},
            timeout=30
        )

        if resp.status_code == 200:
            results = resp.json()
            bindings = results.get("results", {}).get("bindings", [])
            print(f"Query successful! {len(bindings)} results returned.\n")
            for i, row in enumerate(bindings[:3]):
                print(f"  Result {i+1}:")
                for key, val in row.items():
                    print(f"    {key}: {val.get('value', 'N/A')}")
                print()
        else:
            print(f"Wikidata error: {resp.status_code}")
            print(f"  {resp.text[:200]}\n")
    except Exception as e:
        print(f"Execution error: {e}\n")


# ============================================================
if __name__ == "__main__":
    print("\nHACTAR API TEST v2\n")

    # 1. Find models
    try_endpoints_for_models()

    # 2. Find working chat endpoint
    working = try_endpoints_for_chat()

    if working:
        print(f"Working endpoint: {working['name']}\n")
        # 3. SPARQL generation test
        test_sparql_generation(working)
    else:
        print("No chat endpoint worked.")
        print("Check your API key and model name.")

    print("=" * 50)
    print("TESTS COMPLETED")
    print("=" * 50)
