"""
ShopSense AI — Constraint Refinement Endpoint
POST /api/refine
Mutates session constraints (budget, color, size, brand, preferences) and reranks candidates.
"""

from fastapi import APIRouter
from app.models.api_schemas import RefineRequest
from app.models.state import OrchestratorResponse, ExtractedIntent
from app.agents.orchestrator import shared_orchestrator as orchestrator
from app.services.currency_service import convert_currency

router = APIRouter(prefix="/api/refine", tags=["Refine"])



@router.post("/", response_model=OrchestratorResponse)
async def refine_session_constraints(request: RefineRequest):
    """
    Applies constraint updates to an ongoing session and recalculates recommendations.
    """
    session = orchestrator.session_memory_agent.get_or_create_session(request.session_id)
    intent = session.current_intent or ExtractedIntent()

    # Apply explicit mutations
    if request.new_budget_max is not None:
        currency = (request.new_budget_currency or "INR").upper()
        intent.budget_max = convert_currency(request.new_budget_max, currency, "INR")
        intent.budget_currency = "INR"
        intent.is_budget_strict = True

    if request.new_colour:
        intent.colour = request.new_colour

    if request.new_size:
        intent.size = request.new_size

    if request.new_brand:
        intent.brand = request.new_brand

    if request.added_preferences:
        intent.soft_preferences = list(dict.fromkeys(intent.soft_preferences + request.added_preferences))

    if request.removed_preferences:
        intent.soft_preferences = [p for p in intent.soft_preferences if p not in request.removed_preferences]

    intent.is_refinement = True
    session.current_intent = intent

    # Natural language prompt for turn execution
    prompt = request.message or "Update my constraints and show top recommendations."

    return orchestrator.process_turn(
        session_id=request.session_id,
        message=prompt,
        turn_id=session.turn_count + 1
    )
