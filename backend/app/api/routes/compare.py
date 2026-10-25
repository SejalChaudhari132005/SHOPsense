"""
ShopSense AI — Compare Endpoint
POST /api/compare
Compares 2 to 4 products side-by-side with attribute matrices and price delta analysis.
"""

from fastapi import APIRouter, HTTPException
from app.models.api_schemas import CompareRequest, CompareResponse
from app.services.comparison_service import compare_products_side_by_side
from app.agents.orchestrator import shared_orchestrator as orchestrator

router = APIRouter(prefix="/api/compare", tags=["Compare"])


@router.post("/", response_model=CompareResponse)
async def compare_products(request: CompareRequest):
    """
    Compares 2 to 4 selected products side-by-side with attribute matrices.
    """
    session = None
    if request.session_id:
        session = orchestrator.session_memory_agent.get_or_create_session(request.session_id)

    try:
        response = compare_products_side_by_side(request.product_ids, session=session)
        return response
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Comparison failed: {str(e)}")
