import ollama

from larklab.models import ScholarPaper

DEFAULT_SUMMARY_MODEL = "qwen3:8b"
_TIMEOUT_SECONDS = 120  # a summary takes seconds; the default client waits forever
_MAX_TOKENS = 512  # three bullets need about 150
_client = ollama.Client(timeout=_TIMEOUT_SECONDS)

_PROMPT_TEMPLATE = (
    "Summarize this paper as exactly 3 bullet points using '•'. "
    "No labels, no headers, no 'Why/How/Result' prefixes. Just the content.\n\n"
    "• Problem and motivation (1 sentence)\n"
    "• Specific model/algorithm/architecture, input representation, "
    "and technical novelty (1-2 sentences)\n"
    "• Main finding (1 sentence)\n\n"
    "Be technical. Never use vague phrases like "
    "'AI algorithms' or 'advanced methods'. "
    "Name the exact technique. Always respond in English. "
    "Do NOT include numbers or metrics not explicitly in the abstract. "
    "Do not repeat the title. No preamble.\n\n"
    "Title: {title}\n"
    "Abstract: {abstract}"
)


def summarize_abstract(paper: ScholarPaper, model: str = DEFAULT_SUMMARY_MODEL) -> str:
    """Summarize a paper's abstract into 3 bullets using a local LLM."""
    if not paper.abstract:
        return ""

    response = _client.chat(
        model=model,
        messages=[
            {
                "role": "user",
                "content": _PROMPT_TEMPLATE.format(
                    title=paper.title, abstract=paper.abstract
                ),
            }
        ],
        options={"num_predict": _MAX_TOKENS},
        # qwen3 "thinks" first by default: ~6x slower here (17 s vs 3 s per
        # abstract) for the same bullets, and the thinking eats the token budget
        think=False,
    )
    return response["message"]["content"].strip()
