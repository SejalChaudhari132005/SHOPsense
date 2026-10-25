"""
ShopSense AI — Consented Preferences Endpoints
GET /api/preferences — Retrieve consented user preferences
POST /api/preferences — Save or update user preferences with explicit consent
PUT /api/preferences/toggle — Pause or re-enable cross-session preference memory
DELETE /api/preferences — Delete stored preferences (Right to be Forgotten)
"""

from fastapi import APIRouter, HTTPException, Query, Body
from app.models.api_schemas import PreferenceSaveRequest, PreferenceResponse
from app.services.preference_db import preference_db

router = APIRouter(prefix="/api/preferences", tags=["Preferences"])


@router.get("/", response_model=PreferenceResponse)
async def get_user_preferences(user_id: str = Query(default="default_user")):
    """
    Retrieves stored preferences only if user has granted affirmative consent.
    Respects memory_status ("active", "disabled", or "no_consent").
    """
    record = await preference_db.get_preferences(user_id)
    return PreferenceResponse(
        user_id=record["user_id"],
        consent_given=record["consent_given"],
        is_memory_enabled=record.get("is_memory_enabled", True),
        memory_status=record.get("memory_status", "no_consent"),
        preferences=record.get("preferences"),
        durable_preferences=record.get("durable_preferences"),
        last_updated_at=record.get("last_updated_at")
    )


@router.post("/", response_model=PreferenceResponse)
async def save_user_preferences(request: PreferenceSaveRequest):
    """
    Saves or updates user preferences with explicit affirmative consent.
    Strips out ephemeral shopping constraints to retain only durable preferences.
    """
    if not request.consent_given:
        await preference_db.delete_preferences(request.user_id)
        return PreferenceResponse(
            user_id=request.user_id,
            consent_given=False,
            is_memory_enabled=False,
            memory_status="no_consent",
            preferences=None,
            durable_preferences=None,
            last_updated_at=None
        )

    saved = await preference_db.save_preferences(
        user_id=request.user_id,
        consent_given=request.consent_given,
        is_memory_enabled=request.is_memory_enabled,
        preferred_categories=request.preferred_categories,
        preferred_brands=request.preferred_brands,
        shoe_size=request.shoe_size,
        apparel_size=request.apparel_size,
        budget_tier=request.budget_tier,
        durable_preferences=request.durable_preferences,
        custom_notes=request.custom_notes
    )

    return PreferenceResponse(
        user_id=saved["user_id"],
        consent_given=saved["consent_given"],
        is_memory_enabled=saved["is_memory_enabled"],
        memory_status=saved["memory_status"],
        preferences=saved.get("preferences"),
        durable_preferences=saved.get("durable_preferences"),
        last_updated_at=saved.get("last_updated_at")
    )


@router.put("/toggle", response_model=PreferenceResponse)
async def toggle_preference_memory(
    user_id: str = Query(default="default_user"),
    enabled: bool = Body(..., embed=True)
):
    """
    Disables or enables cross-session preference memory without deleting stored preferences.
    """
    updated = await preference_db.toggle_memory(user_id=user_id, is_enabled=enabled)
    return PreferenceResponse(
        user_id=updated["user_id"],
        consent_given=updated["consent_given"],
        is_memory_enabled=updated.get("is_memory_enabled", True),
        memory_status=updated.get("memory_status", "active"),
        preferences=updated.get("preferences"),
        durable_preferences=updated.get("durable_preferences"),
        last_updated_at=updated.get("last_updated_at")
    )


@router.delete("/")
async def delete_user_preferences(user_id: str = Query(default="default_user")):
    """
    Permanently wipes stored user preferences from SQLite (Right to be Forgotten).
    """
    await preference_db.delete_preferences(user_id)
    return {
        "status": "deleted",
        "user_id": user_id,
        "message": "All stored preferences have been permanently deleted."
    }
