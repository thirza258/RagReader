import instructor
from openai import OpenAI
from anthropic import Anthropic
import google.generativeai as genai
import os
from backend.common.schema import VoteDecision

# --- 1. Setup Clients wrapped with Instructor ---

# OpenAI
openai_client = instructor.from_openai(OpenAI())

# Anthropic (Claude)
anthropic_client = instructor.from_anthropic(Anthropic())

# Gemini (Google) - Instructor also supports Gemini via the OpenAI-compatible interface or direct wrapping
# For simplicity, let's assume standard OpenAI usage for the example, 
# but Instructor handles the specific API differences internally.

def get_vote(client, model_name: str, query: str, chunk: str, response: str) -> VoteDecision:
    """
    Generic function to get a structured Pydantic response from any supported LLM.
    """
    prompt = f"""
    Question: {query}
    Context Chunk: {chunk}
    Proposed Answer: {response}
    
    Evaluate if the Proposed Answer makes sense given the Context Chunk.
    """

    # The magic happens here: response_model=VoteDecision
    resp = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
        response_model=VoteDecision, 
        max_retries=2
    )
    return resp

def vote_response_pydantic(response: str, query: str, chunk: str) -> dict:
    """
    Orchestrates the voting process across multiple models.
    """
    votes = {}

    # 1. ChatGPT Vote
    try:
        votes["chatgpt"] = get_vote(openai_client, "gpt-4o", query, chunk, response)
    except Exception as e:
        votes["chatgpt"] = f"Error: {e}"

    # 2. Claude Vote
    try:
        votes["claude"] = get_vote(anthropic_client, "claude-3-opus-20240229", query, chunk, response)
    except Exception as e:
        votes["claude"] = f"Error: {e}"

    # 3. Gemini Vote (Pseudo-code using OpenAI client compatible endpoint or similar)
    # For actual Gemini SDK, you might need a specific adapter, but logic remains the same.
    # votes["gemini"] = ... 

    return votes

def calculate_vote_result_pydantic(vote_results: dict):
    yes_count = 0
    no_count = 0
    details = {}

    for model, result in vote_results.items():
        # Check if it's a valid Pydantic object
        if isinstance(result, VoteDecision):
            # Access fields directly! No parsing needed.
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
            # Handle error strings
            details[model] = {
                "vote": "error",
                "reason": str(result),
                "status": "failed"
            }

    # Majority Logic
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