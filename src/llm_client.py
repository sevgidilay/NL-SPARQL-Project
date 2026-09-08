"""
LLM Client
===========
Abstraction layer for communicating with the Hactar LLM API.
Uses the OpenAI-compatible endpoint (/api/chat/completions).

This module is model-agnostic: change the MODEL variable to use
any model available on Hactar (llama3.3, qwen3, dbrx, etc.)
"""

import os
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_URL = os.getenv("HACTAR_BASE_URL", "https://hactar.unige.ch")
API_KEY = os.getenv("HACTAR_API_KEY")
DEFAULT_MODEL = os.getenv("HACTAR_MODEL", "llama3.3:latest")
FALLBACK_MODELS = ["llama3:latest", "llama3.2:3b", "qwen3.5:9b", "qwen3:8b"]
HF_API_KEY = os.getenv("HF_API_KEY")
HF_MODELS = [
    "Qwen/Qwen2.5-Coder-32B-Instruct",
    "meta-llama/Meta-Llama-3-8B-Instruct"
]


def _extract_content(data) -> str | None:
    """Extract assistant text from OpenAI-compatible or Ollama responses."""
    if not isinstance(data, dict):
        return None

    choices = data.get("choices")
    if choices:
        try:
            content = choices[0]["message"]["content"]
            if content:
                return content
        except (KeyError, IndexError, TypeError):
            pass

    message = data.get("message")
    if isinstance(message, dict) and message.get("content"):
        return message["content"]

    if data.get("response"):
        return data["response"]

    return None


def _error_detail(response: requests.Response) -> str:
    try:
        data = response.json()
        if isinstance(data, dict) and data.get("detail"):
            return str(data["detail"])
    except ValueError:
        pass
    return response.text[:300]


def chat(prompt: str, model: str = None, system_prompt: str = None, temperature: float = None) -> str:
    """
    Send a message to the LLM and get a response.

    Args:
        prompt: The user message to send
        model: Which model to use (defaults to DEFAULT_MODEL)
        system_prompt: Optional system-level instruction

    Returns:
        The LLM's response as a string
    """
    model = model or DEFAULT_MODEL

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    # Route to Hugging Face if model is prefixed with 'HuggingFace: '
    if model.startswith("HuggingFace: "):
        hf_model = model[13:]
        url = "https://router.huggingface.co/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {HF_API_KEY}",
            "Content-Type": "application/json"
        }
        body = {
            "model": hf_model,
            "messages": messages,
            "stream": False,
            **({"temperature": temperature} if temperature is not None else {}),
        }
        try:
            response = requests.post(url, headers=headers, json=body, timeout=120)
            if response.status_code >= 400:
                return f"[ERROR] Hugging Face API: {_error_detail(response)}"
            content = _extract_content(response.json())
            if content:
                return content
            return "[ERROR] Hugging Face returned no usable text."
        except requests.exceptions.Timeout:
            return "[ERROR] Hugging Face request timed out."
        except Exception as e:
            return f"[ERROR] Hugging Face request failed: {e}"

    try:
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        errors = []
        model_candidates = []
        for candidate in [model, *FALLBACK_MODELS]:
            if candidate not in model_candidates:
                model_candidates.append(candidate)

        for candidate_model in model_candidates:
            body = {
                "model": candidate_model,
                "messages": messages,
                "stream": False,
                **({"temperature": temperature} if temperature is not None else {}),
            }

            for path in ("/api/chat/completions", "/ollama/api/chat"):
                response = requests.post(
                    f"{BASE_URL}{path}",
                    headers=headers,
                    json=body,
                    timeout=120
                )
                label = f"{candidate_model} via {path}"
                if response.status_code >= 400:
                    errors.append(f"{label}: {_error_detail(response)}")
                    continue

                content = _extract_content(response.json())
                if content:
                    return content
                errors.append(f"{label}: empty or unsupported response")

        return "[ERROR] LLM returned no usable text. " + " | ".join(errors)

    except requests.exceptions.Timeout:
        return "[ERROR] LLM request timed out. Try a smaller model."
    except requests.exceptions.RequestException as e:
        return f"[ERROR] LLM request failed: {e}"
    except (KeyError, IndexError, TypeError, ValueError):
        return "[ERROR] Unexpected response format from LLM."


def list_models() -> list:
    """
    Fetch the list of available models on Hactar.

    Returns:
        List of model name strings
    """
    try:
        response = requests.get(
            f"{BASE_URL}/ollama/api/tags",
            headers={"Authorization": f"Bearer {API_KEY}"},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        models = [m["name"] for m in data.get("models", [])]
        for hf_m in HF_MODELS:
            models.append(f"HuggingFace: {hf_m}")
        return models
    except Exception:
        return [f"HuggingFace: {hf_m}" for hf_m in HF_MODELS]


def _check_ollama_ps() -> set:
    """Return names of Ollama models currently loaded and active via /api/ps."""
    try:
        resp = requests.get(
            f"{BASE_URL}/ollama/api/ps",
            headers={"Authorization": f"Bearer {API_KEY}"},
            timeout=5,
        )
        resp.raise_for_status()
        return {m["name"] for m in resp.json().get("models", [])}
    except Exception:
        return set()


def check_models_status(models: list) -> dict:
    running = _check_ollama_ps()
    installed = set(list_models())
    status = {}
    for m in models:
        if m.startswith("HuggingFace: "):
            status[m] = m in installed
        else:
            status[m] = m in running
    return status
