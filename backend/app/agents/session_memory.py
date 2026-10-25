"""
Agent 9: Session Memory Agent
Maintains conversation state across multi-turn sessions in memory.
Tracks confirmed constraints, questions asked, shown/rejected candidates,
refinements, and prevents outdated constraints from leaking across topic changes.
"""

from typing import Dict, Optional, List
from datetime import datetime
from app.models.state import SessionContext, ExtractedIntent


class SessionMemoryAgent:
    """
    Manages in-memory dialogue history and multi-turn state per session.
    """

    _global_sessions: Dict[str, SessionContext] = {}

    def __init__(self):
        # In-memory dictionary keyed by session_id
        self._sessions: Dict[str, SessionContext] = SessionMemoryAgent._global_sessions

    def get_or_create_session(self, session_id: str) -> SessionContext:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionContext(
                session_id=session_id,
                turn_count=0
            )
        return self._sessions[session_id]

    def update_session(
        self,
        session_id: str,
        intent: ExtractedIntent,
        shown_product_ids: Optional[List[str]] = None,
        asked_question: Optional[str] = None
    ) -> SessionContext:
        session = self.get_or_create_session(session_id)
        session.turn_count += 1
        session.current_intent = intent
        session.last_updated_at = datetime.utcnow()

        # Update confirmed constraints
        if intent.budget_max is not None:
            session.confirmed_constraints["budget_max"] = intent.budget_max
            session.confirmed_constraints["budget_currency"] = intent.budget_currency
            session.confirmed_constraints["is_budget_strict"] = intent.is_budget_strict

        if intent.category:
            session.confirmed_constraints["category"] = intent.category

        if intent.intended_use:
            session.confirmed_constraints["intended_use"] = intent.intended_use

        if intent.size:
            session.confirmed_constraints["size"] = intent.size

        if intent.colour:
            session.confirmed_constraints["colour"] = intent.colour

        # Record soft preferences
        session.soft_preferences = list(dict.fromkeys(session.soft_preferences + intent.soft_preferences))

        # Record questions asked to prevent repetitive badgering
        if asked_question and asked_question not in session.questions_asked:
            session.questions_asked.append(asked_question)

        # Record shown products
        if shown_product_ids:
            session.shown_product_ids = list(dict.fromkeys(session.shown_product_ids + shown_product_ids))

        return session

    def record_feedback(self, session_id: str, product_id: str, accepted: bool):
        """Records user feedback or rejection of a candidate product."""
        session = self.get_or_create_session(session_id)
        if not accepted and product_id not in session.rejected_product_ids:
            session.rejected_product_ids.append(product_id)

    def reset_session(self, session_id: str):
        """Wipes temporary in-memory state for a given session."""
        if session_id in self._sessions:
            del self._sessions[session_id]
