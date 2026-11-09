import re

def vote_prompt(query: str, chunk: str, response: str) -> str:
    return f"""
    Question: {query}
    Context Chunk: {chunk}
    Proposed Answer: {response}
    
    Evaluate if the Proposed Answer makes sense given the Context Chunk.
    """

def rag_prompt(query: str, context: str) -> str:
    if not context:
        return f"""You are a helpful assistant. You were asked the following question but no relevant information was found in the document.

        Question: {query}

        Please respond with: "I don't have enough information in the provided document to answer this question." Then briefly suggest what kind of information would be needed."""

    return f"""You are a helpful assistant. Answer the question based only on the context below.

        Context:
        {context}

        Question: {query}

        Answer:"""

def prompt_generator(query: str) -> str:
    return f"""
    Answer the question: {query}
    """


# ── Workspace chat (prompt version common.constant.CHAT_PROMPT_VERSION) ──────
# Changing what the model is told below changes answers, so bump
# CHAT_PROMPT_VERSION with it: every stored answer records the version.

CITED_CHAT_SYSTEM_PROMPT = """You are RAGReader, a research assistant. Answer the user's question using only the numbered sources in their message.

Rules:
1. Use only information stated in the sources. Do not add outside knowledge.
2. After each sentence or claim a source supports, cite it with the source number in square brackets, for example [1] or [2][3].
3. Cite only numbers that appear in the sources list. Never invent a citation number.
4. If the sources do not contain enough information to answer, say so plainly and say what is missing.
5. Earlier turns of the conversation are context only; citation numbers in them do not refer to the current sources.
6. Answer in the language of the question."""

# Citation markers such as [1] or [2, 3] in earlier answers.
_HISTORY_MARKERS = re.compile(r"\s?\[\d+(?:\s*,\s*\d+)*\]")


def _history_text(turn) -> str:
    content = (turn.get("content") or "").strip()
    if turn.get("role") == "assistant":
        # Old [n] markers point at old sources; left in, they invite the model
        # to cite numbers the current sources do not have.
        content = _HISTORY_MARKERS.sub("", content)
    return content


def cited_chat_messages(question: str, sources: list, history: list = ()) -> list:
    """Chat messages for a grounded, cited answer.

    `sources` are evidence dicts in prompt order (source n is `[n]`), with at
    least `text` and optionally `document_title` and `page_number`.
    `history` is earlier completed turns, oldest first, as
    {"role": "user" | "assistant", "content": str}.
    """
    messages = [{"role": "system", "content": CITED_CHAT_SYSTEM_PROMPT}]
    for turn in history:
        content = _history_text(turn)
        if content and turn.get("role") in ("user", "assistant"):
            messages.append({"role": turn["role"], "content": content})
    if sources:
        blocks = []
        for number, source in enumerate(sources, 1):
            heading = f"[{number}] {source.get('document_title') or 'Untitled document'}"
            if source.get("page_number"):
                heading += f", page {source['page_number']}"
            blocks.append(f"{heading}\n{(source.get('text') or '').strip()}")
        sources_text = "\n\n".join(blocks)
    else:
        sources_text = "(No passages were found for this question.)"
    messages.append({"role": "user", "content": f"Sources:\n\n{sources_text}\n\nQuestion: {question}"})
    return messages


def standalone_query_prompt(question: str, history: list) -> str:
    """Rewrite a follow-up ("what about its limits?") into a search query that
    makes sense without the conversation."""
    lines = []
    for turn in history:
        content = " ".join(_history_text(turn).split())
        if content:
            speaker = "User" if turn.get("role") == "user" else "Assistant"
            lines.append(f"{speaker}: {content[:600]}")
    conversation = "\n".join(lines)
    return (
        "Rewrite the latest question as a standalone search query for a document search engine. "
        "Use the conversation only to resolve references such as pronouns or 'the second one'. "
        "Output exactly one line of at most 200 characters, with no explanation, quotes or prefix. "
        "Keep the language of the question.\n\n"
        f"Conversation:\n{conversation}\n\n"
        f"Latest question: {question}\n"
        "Standalone query:"
    )