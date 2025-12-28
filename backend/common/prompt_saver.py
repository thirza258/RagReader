def vote_prompt(query: str, chunk: str, response: str) -> str:
    return f"""
    Question: {query}
    Context Chunk: {chunk}
    Proposed Answer: {response}
    
    Evaluate if the Proposed Answer makes sense given the Context Chunk.
    """

def rag_prompt(query: str, context: str) -> str:
    return f"""
    Based on the following context, answer the question:
    Question: {query}
    Context: {context}
    """

def prompt_generator(query: str) -> str:
    return f"""
    Answer the question: {query}
    """