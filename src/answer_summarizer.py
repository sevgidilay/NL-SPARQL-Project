"""
Answer Summarizer
==================
Takes SPARQL query results and generates a natural language summary
using the LLM. This provides a ChatGPT-like answer experience on top
of the structured table output.
"""

from src import llm_client


def summarize(question: str, results: list, max_rows: int = 20, model: str = None, entity_hints: list | None = None) -> str:
    """
    Generate a natural language summary of SPARQL query results.

    Args:
        question: The original natural language question
        results: List of result dicts from sparql_executor
        max_rows: Max number of rows to send to the LLM (to avoid huge prompts)
        entity_hints: Optional list of resolved entities from the entity lookup step

    Returns:
        Natural language summary string
    """
    if not results:
        return "The query returned no results, so there is nothing to summarize."

    # Take only the first N rows to keep the prompt manageable
    rows_to_send = results[:max_rows]
    total_count = len(results)

    # Format results as a readable table for the LLM
    formatted_rows = []
    for i, row in enumerate(rows_to_send, 1):
        # Filter out URI columns, keep only label columns for readability
        readable_row = {
            key: val for key, val in row.items()
            if not val.startswith("http://") and not val.startswith("https://")
        }
        if readable_row:
            parts = [f"{k}: {v}" for k, v in readable_row.items()]
            formatted_rows.append(f"{i}. " + " | ".join(parts))

    results_text = "\n".join(formatted_rows)

    truncation_note = ""
    if total_count > max_rows:
        truncation_note = f"\n(Showing first {max_rows} of {total_count} total results)"

    # Build optional background context from entity lookup
    entity_context_block = ""
    if entity_hints:
        lines = ["Background context from entity lookup (use only to supplement the table below, not to override it):"]
        for hint in entity_hints:
            desc = hint.get("description", "")
            label = hint.get("label", hint.get("surface", ""))
            qid = hint.get("qid", "")
            if desc:
                lines.append(f'- "{label}" (wd:{qid}) — {desc}')
        if len(lines) > 1:
            entity_context_block = "\n".join(lines) + "\n\n"

    prompt = f"""You are a helpful assistant that summarizes data retrieved from a knowledge graph.

The user asked: "{question}"

{entity_context_block}Here are the facts retrieved:
{results_text}{truncation_note}

Write a concise, natural-language answer to the user's question using the facts above.
Rules:
- Keep it 2-4 sentences maximum
- Base your answer primarily on the retrieved facts table; you may use the background context only if the table does not already answer the question
- Do NOT invent, infer, or recall any names, IDs, dates, or facts beyond what is provided above
- Do NOT repeat raw entity IDs (like Q130416875) verbatim — use the human-readable label instead
- Do NOT mention "SPARQL", "query", or "results" in your answer
- If neither the table nor the background context contains enough information to answer fully, say so
- Answer as if you are directly answering the user's question

Answer:"""

    return llm_client.chat(prompt, model=model)
