"""
ShopSense AI — Session State Endpoint
GET /api/session/{session_id}
Safely inspects active in-memory session dialogue state without exposing internal secrets.
"""

from fastapi import APIRouter, HTTPException
from app.agents.orchestrator import shared_orchestrator as orchestrator

router = APIRouter(prefix="/api/session", tags=["Session"])



@router.get("/{session_id}")
async def get_session_state(session_id: str):
    """
    Safely retrieves confirmed constraints, turn count, and shown items for a session.
    """
    sessions = orchestrator.session_memory_agent._sessions
    if session_id not in sessions:
        raise HTTPException(
            status_code=404, 
            detail=f"Session '{session_id}' not found or has expired."
        )

    session = sessions[session_id]

    # Return safe, non-sensitive audit state
    return {
        "session_id": session.session_id,
        "turn_count": session.turn_count,
        "confirmed_constraints": session.confirmed_constraints,
        "soft_preferences": session.soft_preferences,
        "questions_asked": session.questions_asked,
        "shown_product_ids": session.shown_product_ids,
        "rejected_product_ids": session.rejected_product_ids,
        "last_updated_at": session.last_updated_at.isoformat()
    }
