"""
ShopSense AI — Chat API Endpoints
Connects the Chrome extension and clients to the Orchestrator Agent.
"""

from typing import Optional, Dict, Any
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.models.state import OrchestratorResponse
from app.agents.orchestrator import shared_orchestrator as orchestrator

router = APIRouter(prefix="/api/chat", tags=["Chat"])



class ChatRequest(BaseModel):
    message: str = Field(..., description="User message or voice transcript")
    session_id: str = Field(default="demo_session_001", description="Session identifier")
    turn_id: int = Field(default=1, ge=1, description="Dialogue turn number")
    input_source: str = Field(default="text", description="'text' or 'voice'")
    client_context: Optional[Dict[str, Any]] = Field(default=None, description="Active tab context if present")


class FeedbackRequest(BaseModel):
    session_id: str
    product_id: str
    accepted: bool


@router.post("/", response_model=OrchestratorResponse)
async def process_chat_message(request: ChatRequest):
    """
    Main conversational endpoint: runs query through the 10-agent pipeline.
    """
    return orchestrator.process_turn(
        session_id=request.session_id,
        message=request.message,
        turn_id=request.turn_id,
        input_source=request.input_source,
        client_context=request.client_context
    )


@router.post("/feedback")
async def record_user_feedback(request: FeedbackRequest):
    """
    Records positive or negative user engagement on specific product recommendations.
    """
    orchestrator.session_memory_agent.record_feedback(
        session_id=request.session_id,
        product_id=request.product_id,
        accepted=request.accepted
    )
    return {"status": "success", "session_id": request.session_id}


@router.delete("/session/{session_id}")
async def reset_session(session_id: str):
    """
    Wipes temporary session memory for a fresh conversation.
    """
    orchestrator.session_memory_agent.reset_session(session_id)
    return {"status": "session_reset", "session_id": session_id}
