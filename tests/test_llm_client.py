from src import llm_client


def test_extract_content_from_openai_response():
    data = {
        "choices": [
            {"message": {"content": "SELECT ?x WHERE { ?x ?p ?o . }"}}
        ]
    }

    assert llm_client._extract_content(data) == "SELECT ?x WHERE { ?x ?p ?o . }"


def test_extract_content_from_ollama_chat_response():
    data = {
        "message": {
            "role": "assistant",
            "content": "SELECT ?x WHERE { ?x ?p ?o . }",
        }
    }

    assert llm_client._extract_content(data) == "SELECT ?x WHERE { ?x ?p ?o . }"


def test_extract_content_rejects_null_response():
    assert llm_client._extract_content(None) is None
