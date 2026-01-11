import instructor
from openai import OpenAI
import os
from common.schema import VoteDecision

# --- 1. Setup Single OpenRouter Client ---

# OpenRouter uses the standard OpenAI SDK.
# We just point the base_url to OpenRouter and use the OpenRouter API Key.
client = instructor.from_openai(
    OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"),
        default_headers={
            "HTTP-Referer": "https://rag.nevatal.tech", # Replace with your URL
            "X-Title": "RagReader",         # Replace with your App Name
        }
    ),
    mode=instructor.Mode.MD_JSON 
)

def get_vote(model_name: str, query: str, chunk: str, response: str) -> VoteDecision:
    """
    Generic function to get a structured Pydantic response via OpenRouter.
    """
    prompt = f"""
    Question: {query}
    Context Chunk: {chunk}
    Proposed Answer: {response}
    
    Evaluate if the Proposed Answer makes sense given the Context Chunk.
    """

    resp = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
        response_model=VoteDecision, 
        max_retries=2
    )
    return resp

def vote_response_pydantic(response: str, query: str, chunk: str) -> dict:
    """
    Orchestrates the voting process across multiple models via OpenRouter.
    """
    votes = {}

    # Define the specific OpenRouter model IDs you want to use
    # See full list at: https://openrouter.ai/models
    models_to_query = {
        "gpt4o": "openai/gpt-4o",
        "claude3": "anthropic/claude-3-opus", # or "anthropic/claude-3.5-sonnet"
        "gemini": "google/gemini-pro-1.5"
    }

    for simple_name, openrouter_id in models_to_query.items():
        try:
            # We use the same client for all providers now!
            votes[simple_name] = get_vote(openrouter_id, query, chunk, response)
        except Exception as e:
            votes[simple_name] = f"Error: {e}"

    return votes

def calculate_vote_result_pydantic(vote_results: dict):
    """
    (Logic remains unchanged from your original code)
    """
    yes_count = 0
    no_count = 0
    details = {}

    for model, result in vote_results.items():
        if isinstance(result, VoteDecision):
            vote_val = result.decision 
            reason = result.justification
            
            if vote_val == "yes":
                yes_count += 1
            else:
                no_count += 1
                
            details[model] = {
                "vote": vote_val,
                "reason": reason,
                "status": "success"
            }
        else:
            details[model] = {
                "vote": "error",
                "reason": str(result),
                "status": "failed"
            }

    if yes_count > no_count:
        majority = "yes"
    elif no_count > yes_count:
        majority = "no"
    else:
        majority = "tie"

    return {
        "yes_votes": yes_count,
        "no_votes": no_count,
        "final_verdict": majority,
        "details": details
    }