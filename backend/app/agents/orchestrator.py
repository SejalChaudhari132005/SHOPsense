"""
Agent 10: Orchestrator Agent
Wraps and exposes the LangGraph StateGraph workflow for the 10-Agent shopping assistant.
Coordinates workflow transitions, safe session checkpointing, and response generation.
"""

from typing import Dict, Any, Optional
from app.models.state import OrchestratorResponse
from app.agents.graph_orchestrator import ShopSenseWorkflow


class OrchestratorAgent:
    """
    Central controller orchestrating all 10 specialized agents via a LangGraph state machine.
    """

    def __init__(self, checkpointer: Optional[Any] = None):
        self.workflow = ShopSenseWorkflow(checkpointer=checkpointer)
        # Expose sub-agents for backwards compatibility and direct inspection
        self.query_ingestion_agent = self.workflow.query_ingestion_agent
        self.intent_extraction_agent = self.workflow.intent_extraction_agent
        self.ambiguity_clarification_agent = self.workflow.ambiguity_clarification_agent
        self.catalog_mapping_agent = self.workflow.catalog_mapping_agent
        self.candidate_retrieval_agent = self.workflow.candidate_retrieval_agent
        self.ranking_fit_agent = self.workflow.ranking_fit_agent
        self.explanation_agent = self.workflow.explanation_agent
        self.fallback_agent = self.workflow.fallback_agent
        self.session_memory_agent = self.workflow.session_memory_agent
        self.graph = self.workflow.graph

    def process_turn(
        self,
        session_id: str,
        message: str,
        turn_id: int = 1,
        input_source: str = "text",
        client_context: Optional[Dict[str, Any]] = None
    ) -> OrchestratorResponse:
        """
        Executes a turn through the compiled LangGraph workflow.
        """
        return self.workflow.execute_turn(
            session_id=session_id,
            message=message,
            turn_id=turn_id,
            input_source=input_source,
            client_context=client_context
        )


# Shared singleton orchestrator for API routes and FastAPI dependency injection
shared_orchestrator = OrchestratorAgent()


def get_orchestrator() -> OrchestratorAgent:
    """Provides the singleton orchestrator instance for FastAPI routes."""
    return shared_orchestrator

