"""
ShopSense AI — Consented Preferences Database Service
Manages local SQLite storage for cross-session preferences using aiosqlite.
Strictly requires explicit user consent before storing any data.
Distinguishes durable preferences (sizes, favorite brands, materials) from
temporary shopping constraints (gifts, occasions), and provides complete
view, edit, disable, and wipe controls.
"""

import json
import os
import aiosqlite
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

from app.core.config import settings

# Non-durable temporary keys that must NEVER be persisted across sessions
TEMPORARY_CONSTRAINT_KEYS = {
    "recipient", "occasion", "gift", "deadline", "event", "temporary_budget",
    "trip_destination", "season_only", "gift_exchange", "urgent"
}


def separate_durable_from_temporary(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Strips out ephemeral shopping constraints (e.g., gift recipient, one-off occasion)
    to retain only durable, minimal preferences.
    """
    clean_durable = {}
    for k, v in raw_data.items():
        k_lower = k.lower()
        if k_lower in TEMPORARY_CONSTRAINT_KEYS or any(t in k_lower for t in TEMPORARY_CONSTRAINT_KEYS):
            continue
        # Do not persist sensitive keys or blank entries
        if v is not None and v != "" and v != []:
            clean_durable[k] = v
    return clean_durable


class PreferenceDBService:
    """
    Manages consented user preferences stored in SQLite with strict privacy controls.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.SQLITE_DB_PATH
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

    async def init_db(self):
        """Initializes preferences SQLite table with migration safety."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_preferences (
                    user_id TEXT PRIMARY KEY,
                    consent_given INTEGER NOT NULL,
                    is_memory_enabled INTEGER NOT NULL DEFAULT 1,
                    preferred_categories TEXT,
                    preferred_brands TEXT,
                    shoe_size TEXT,
                    apparel_size TEXT,
                    budget_tier TEXT,
                    durable_preferences TEXT,
                    custom_notes TEXT,
                    updated_at TEXT NOT NULL
                )
            """)
            await db.commit()

            # Ensure columns exist if table was created in an older schema
            cursor = await db.execute("PRAGMA table_info(user_preferences)")
            cols = [row[1] for row in await cursor.fetchall()]
            if "is_memory_enabled" not in cols:
                await db.execute("ALTER TABLE user_preferences ADD COLUMN is_memory_enabled INTEGER NOT NULL DEFAULT 1")
                await db.commit()
            if "durable_preferences" not in cols:
                await db.execute("ALTER TABLE user_preferences ADD COLUMN durable_preferences TEXT")
                await db.commit()

    async def get_preferences(self, user_id: str = "default_user") -> Dict[str, Any]:
        """
        Retrieves user preferences only if explicit consent was granted.
        If memory is disabled by user, returns memory_status="disabled" with empty preferences.
        """
        await self.init_db()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM user_preferences WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            if not row:
                return {
                    "user_id": user_id,
                    "consent_given": False,
                    "is_memory_enabled": False,
                    "memory_status": "no_consent",
                    "preferences": None,
                    "durable_preferences": None,
                    "last_updated_at": None
                }

            consent = bool(row["consent_given"])
            is_enabled = bool(row["is_memory_enabled"]) if "is_memory_enabled" in row.keys() else True

            if not consent:
                return {
                    "user_id": user_id,
                    "consent_given": False,
                    "is_memory_enabled": False,
                    "memory_status": "no_consent",
                    "preferences": None,
                    "durable_preferences": None,
                    "last_updated_at": row["updated_at"]
                }

            if not is_enabled:
                return {
                    "user_id": user_id,
                    "consent_given": True,
                    "is_memory_enabled": False,
                    "memory_status": "disabled",
                    "preferences": None,
                    "durable_preferences": None,
                    "last_updated_at": row["updated_at"]
                }

            categories = json.loads(row["preferred_categories"] or "[]")
            brands = json.loads(row["preferred_brands"] or "[]")
            durable_raw = json.loads(row["durable_preferences"] or "{}") if "durable_preferences" in row.keys() and row["durable_preferences"] else {}

            durable = {
                "preferred_categories": categories,
                "preferred_brands": brands,
                "shoe_size": row["shoe_size"],
                "apparel_size": row["apparel_size"],
                "budget_tier": row["budget_tier"],
                **durable_raw
            }

            return {
                "user_id": user_id,
                "consent_given": True,
                "is_memory_enabled": True,
                "memory_status": "active",
                "preferences": durable,
                "durable_preferences": durable,
                "last_updated_at": row["updated_at"]
            }

    async def save_preferences(
        self,
        user_id: str,
        consent_given: bool,
        is_memory_enabled: bool = True,
        preferred_categories: Optional[list] = None,
        preferred_brands: Optional[list] = None,
        shoe_size: Optional[str] = None,
        apparel_size: Optional[str] = None,
        budget_tier: Optional[str] = None,
        durable_preferences: Optional[Dict[str, Any]] = None,
        custom_notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Saves preferences only when affirmative consent is given.
        Strips out temporary constraints to store minimal, relevant durable preferences.
        """
        await self.init_db()

        if not consent_given:
            await self.delete_preferences(user_id)
            return {
                "user_id": user_id,
                "consent_given": False,
                "is_memory_enabled": False,
                "memory_status": "no_consent",
                "preferences": None,
                "durable_preferences": None,
                "last_updated_at": None,
                "message": "Preferences deleted because user consent was not granted."
            }

        now_str = datetime.utcnow().isoformat()
        clean_cats = [c for c in (preferred_categories or []) if c]
        clean_brands = [b for b in (preferred_brands or []) if b]

        # Filter durable preferences against temporary keys
        durable_filtered = separate_durable_from_temporary(durable_preferences or {})

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO user_preferences (
                    user_id, consent_given, is_memory_enabled, preferred_categories, preferred_brands,
                    shoe_size, apparel_size, budget_tier, durable_preferences, custom_notes, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    consent_given = excluded.consent_given,
                    is_memory_enabled = excluded.is_memory_enabled,
                    preferred_categories = excluded.preferred_categories,
                    preferred_brands = excluded.preferred_brands,
                    shoe_size = excluded.shoe_size,
                    apparel_size = excluded.apparel_size,
                    budget_tier = excluded.budget_tier,
                    durable_preferences = excluded.durable_preferences,
                    custom_notes = excluded.custom_notes,
                    updated_at = excluded.updated_at
            """, (
                user_id,
                1 if consent_given else 0,
                1 if is_memory_enabled else 0,
                json.dumps(clean_cats),
                json.dumps(clean_brands),
                shoe_size,
                apparel_size,
                budget_tier,
                json.dumps(durable_filtered),
                custom_notes,
                now_str
            ))
            await db.commit()

        durable_out = {
            "preferred_categories": clean_cats,
            "preferred_brands": clean_brands,
            "shoe_size": shoe_size,
            "apparel_size": apparel_size,
            "budget_tier": budget_tier,
            **durable_filtered
        }

        return {
            "user_id": user_id,
            "consent_given": True,
            "is_memory_enabled": is_memory_enabled,
            "memory_status": "active" if is_memory_enabled else "disabled",
            "preferences": durable_out if is_memory_enabled else None,
            "durable_preferences": durable_out if is_memory_enabled else None,
            "last_updated_at": now_str
        }

    async def toggle_memory(self, user_id: str, is_enabled: bool) -> Dict[str, Any]:
        """
        Disables or enables preference memory across sessions without wiping saved data.
        """
        await self.init_db()
        now_str = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE user_preferences
                SET is_memory_enabled = ?, updated_at = ?
                WHERE user_id = ?
            """, (1 if is_enabled else 0, now_str, user_id))
            await db.commit()

        return await self.get_preferences(user_id)

    async def delete_preferences(self, user_id: str = "default_user") -> bool:
        """
        Permanently wipes stored user preferences (Right to be Forgotten).
        """
        await self.init_db()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM user_preferences WHERE user_id = ?", (user_id,))
            await db.commit()
        return True


# Global instance
preference_db = PreferenceDBService()
