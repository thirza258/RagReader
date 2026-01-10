from pydantic import BaseModel, Field
from typing import Literal, Dict, Any
import time

class VoteDecision(BaseModel):
    decision: Literal["yes", "no"] = Field(
        ..., 
        description="Select 'yes' if the response is accurate based on the chunk, 'no' otherwise."
    )
    justification: str = Field(
        ..., 
        description="A concise one-sentence explanation of why you voted this way."
    )

class RAGResponse(BaseModel):
    def response_200(self, response: str) -> Dict[str, Any]:
        return {
            "status": 200,
            "message": "Response generated successfully",
            "timestamp": time.time(),
            "data": {
                "response": response
            }
        }

    def response_400(self, error: str) -> Dict[str, Any]:
        return {
            "status": 400,
            "message": error,
            "timestamp": time.time(),
            "data": {
                "response": None
            }
        }

    def response_500(self, error: str) -> Dict[str, Any]:
        return {
            "status": 500,
            "message": error,
            "timestamp": time.time(),
            "data": {
                "response": None
            }
        }

    def response_404(self, error: str) -> Dict[str, Any]:
        return {
            "status": 404,
            "message": error,
            "timestamp": time.time(),
            "data": {
                "response": None
            }
        }
        
    def response_201(self, response: str) -> Dict[str, Any]:
        return {
            "status": 201,
            "message": "Response created successfully",
            "timestamp": time.time(),
            "data": {
                "response": response
            }
        }

responses = RAGResponse()