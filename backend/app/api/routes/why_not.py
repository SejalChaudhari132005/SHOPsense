"""
ShopSense AI — 'Why Not' Mode Endpoint
POST /api/why-not
Explains why a candidate product was not recommended based on current session constraints.
"""

from fastapi import APIRouter, HTTPException
from app.models.api_schemas import WhyNotRequest, WhyNotResponse
from app.services.comparison_service import analyze_why_not
from app.agents.orchestrator import shared_orchestrator as orchestrator

router = APIRouter(prefix="/api/why-not", tags=["Why Not Mode"])



@router.post("/", response_model=WhyNotResponse)
async def explain_why_not_recommended(request: WhyNotRequest):
    """
    Explains why a specific product was excluded or scored lower for the session.
    """
    try:
        session = orchestrator.session_memory_agent.get_or_create_session(request.session_id)
        response = analyze_why_not(
            request.product_id, 
            session=session, 
            compare_with_id=request.compare_with_id
        )
        return response
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Why-Not analysis failed: {str(e)}")
