"""
ShopSense AI — LangGraph Orchestration State Machine
Coordinates all 10 specialized agents using LangGraph's StateGraph and Checkpointing.
Implements validated transitions, confidence-gated clarification branches, zero-result
fallbacks, and thread-safe session checkpointing.
"""

import logging
from typing import Dict, Any, Optional, List, Tuple
from threading import Lock

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from app.models.state import (
    ShopSenseGraphState,
    IngestedQuery,
    ExtractedIntent,
    ClarificationDecision,
    AttributeMappingResult,
    CandidateRetrievalResult,
    ProductFitScore,
    ProductRecommendation,
    FallbackSuggestion,
    SessionContext,
    OrchestratorResponse
)
from app.models.product import Product

from app.agents.query_ingestion import QueryIngestionAgent
from app.agents.intent_extraction import IntentExtractionAgent
from app.agents.ambiguity_clarification import AmbiguityClarificationAgent
from app.agents.catalog_mapping import CatalogAttributeMappingAgent
from app.agents.candidate_retrieval import CandidateRetrievalAgent
from app.agents.ranking_fit import RankingFitScoringAgent
from app.agents.explanation_generation import ExplanationGenerationAgent
from app.agents.zero_result_fallback import ZeroResultFallbackAgent
from app.agents.session_memory import SessionMemoryAgent

logger = logging.getLogger(__name__)


class ShopSenseWorkflow:
    """
    Encapsulates the compiled LangGraph state machine and agent instances.
    """

    def __init__(self, checkpointer: Optional[Any] = None):
        self.query_ingestion_agent = QueryIngestionAgent()
        self.intent_extraction_agent = IntentExtractionAgent()
        self.ambiguity_clarification_agent = AmbiguityClarificationAgent()
        self.catalog_mapping_agent = CatalogAttributeMappingAgent()
        self.candidate_retrieval_agent = CandidateRetrievalAgent()
        self.ranking_fit_agent = RankingFitScoringAgent()
        self.explanation_agent = ExplanationGenerationAgent()
        self.fallback_agent = ZeroResultFallbackAgent()
        self.session_memory_agent = SessionMemoryAgent()

        # Session concurrency locks to ensure safe concurrent turns per session
        self._session_locks: Dict[str, Lock] = {}
        self._global_lock = Lock()

        # MemorySaver for LangGraph checkpointing
        self.checkpointer = checkpointer or MemorySaver()
        self.graph = self._build_graph().compile(checkpointer=self.checkpointer)

    def _get_session_lock(self, session_id: str) -> Lock:
        with self._global_lock:
            if session_id not in self._session_locks:
                self._session_locks[session_id] = Lock()
            return self._session_locks[session_id]

    # ==========================================
    # Graph Node Definitions (10 Logical Agents)
    # ==========================================

    def node_query_ingestion(self, state: ShopSenseGraphState) -> Dict[str, Any]:
        """Node 1 (Agent 1): Ingest and normalize raw message."""
        session_id = state.get("session_id", "default_session")
        turn_id = state.get("turn_id", 1)
        raw_msg = state.get("original_user_message", "")
        source = state.get("input_source", "text")
        client_ctx = state.get("client_context", {})

        ingested = self.query_ingestion_agent.ingest(
            session_id=session_id,
            raw_message=raw_msg,
            turn_id=turn_id,
            input_source=source,
            client_context=client_ctx
        )

        if ingested.is_empty:
            return {
                "normalized_query": ingested,
                "error_information": ingested.rejection_reason,
                "workflow_status": "error"
            }

        return {
            "normalized_query": ingested,
            "error_information": None,
            "workflow_status": "ingested"
        }

    def node_session_memory_in(self, state: ShopSenseGraphState) -> Dict[str, Any]:
        """Node 2 (Agent 9 - In): Retrieve prior session context and previous intent."""
        session_id = state.get("session_id", "default_session")
        session = self.session_memory_agent.get_or_create_session(session_id)
        return {
            "session_memory": session,
            "previous_intent": session.current_intent,
            "workflow_status": "context_merged"
        }

    def node_intent_extraction(self, state: ShopSenseGraphState) -> Dict[str, Any]:
        """Node 3 (Agent 2): Extract structured intent and merge context."""
        ingested = state.get("normalized_query")
        prev_intent = state.get("previous_intent")

        try:
            intent = self.intent_extraction_agent.extract(
                ingested=ingested,
                conversation_history=None,
                previous_intent=prev_intent
            )
            return {
                "current_intent": intent,
                "workflow_status": "extracted"
            }
        except Exception as e:
            logger.warning(f"Intent extraction encountered error: {e}. Falling back to deterministic extraction.")
            from app.services.llm_service import deterministic_extract_intent
            raw_text = ingested.sanitized_message if ingested else ""
            fallback_intent = deterministic_extract_intent(raw_text)
            return {
                "current_intent": fallback_intent,
                "error_information": None,
                "workflow_status": "extracted"
            }

    def node_ambiguity_clarification(self, state: ShopSenseGraphState) -> Dict[str, Any]:
        """Node 4 (Agent 3): Evaluate completeness & confidence-gated clarification."""
        intent = state.get("current_intent")
        session = state.get("session_memory")
        asked = session.questions_asked if session else []

        raw_msg = state.get("original_user_message", "")
        decision = self.ambiguity_clarification_agent.evaluate(
            intent=intent,
            already_asked_questions=asked,
            raw_user_message=raw_msg
        )

        status = "clarifying" if decision.needs_clarification else "clarification_passed"
        return {
            "clarification": decision,
            "workflow_status": status
        }

    def node_catalog_mapping(self, state: ShopSenseGraphState) -> Dict[str, Any]:
        """Node 5 (Agent 4): Map terms, units, and synonyms to catalog attributes."""
        intent = state.get("current_intent")
        mapping = self.catalog_mapping_agent.map_attributes(intent)
        return {
            "catalog_mapping": mapping,
            "workflow_status": "mapped"
        }

    def node_candidate_retrieval(self, state: ShopSenseGraphState) -> Dict[str, Any]:
        """Node 6 (Agent 5): Retrieve candidates and apply verified hard filters."""
        intent = state.get("current_intent")
        mapping = state.get("catalog_mapping")

        try:
            retrieval = self.candidate_retrieval_agent.retrieve(intent, mapping)
            return {
                "retrieved_candidates": retrieval.candidates,
                "eligible_candidates": retrieval.candidates,
                "data_source_status": "catalog_ready",
                "sources_consulted": retrieval.sources_consulted,
                "store_statuses": retrieval.store_statuses,
                "workflow_status": "retrieved"
            }
        except Exception as e:
            logger.error(f"Candidate retrieval error: {e}")
            return {
                "retrieved_candidates": [],
                "eligible_candidates": [],
                "data_source_status": "source_error",
                "error_information": str(e),
                "workflow_status": "retrieved"
            }

    def node_ranking_fit(self, state: ShopSenseGraphState) -> Dict[str, Any]:
        """Node 7 (Agent 6): Deterministic multi-factor scoring (0-100)."""
        candidates = state.get("eligible_candidates", [])
        intent = state.get("current_intent")

        ranked_pairs = self.ranking_fit_agent.rank(candidates, intent)
        return {
            "ranked_candidates": ranked_pairs,
            "workflow_status": "ranked"
        }

    def node_explanation_generation(self, state: ShopSenseGraphState) -> Dict[str, Any]:
        """Node 8 (Agent 7): Evidence-grounded natural language justifications."""
        ranked_pairs = state.get("ranked_candidates", [])
        intent = state.get("current_intent")

        recommendations = self.explanation_agent.explain(ranked_pairs, intent, top_k=3)

        # Feature 5: Context-Aware Follow-Up Suggestion (At most one relevant accessory)
        follow_up = None
        if recommendations:
            from app.services.follow_up_service import find_complementary_suggestion
            follow_up = find_complementary_suggestion(recommendations[0].product, intent)

        return {
            "recommendations": recommendations,
            "follow_up_suggestion": follow_up,
            "workflow_status": "explained"
        }

    def node_zero_result_fallback(self, state: ShopSenseGraphState) -> Dict[str, Any]:
        """Node 9 (Agent 8): Intelligent constraint relaxation and alternative generation."""
        intent = state.get("current_intent")
        fallback = self.fallback_agent.generate_fallback(intent)
        return {
            "fallback": fallback,
            "workflow_status": "fallback_invoked"
        }

    def node_session_memory_out(self, state: ShopSenseGraphState) -> Dict[str, Any]:
        """Node 10 (Agent 9 - Out): Update and persist in-memory session memory."""
        session_id = state.get("session_id", "default_session")
        intent = state.get("current_intent")
        clarification = state.get("clarification")
        recommendations = state.get("recommendations", [])

        shown_ids = [r.product.product_id for r in recommendations] if recommendations else None
        asked_q = clarification.clarification_question if (clarification and clarification.needs_clarification) else None

        if intent:
            updated_session = self.session_memory_agent.update_session(
                session_id=session_id,
                intent=intent,
                shown_product_ids=shown_ids,
                asked_question=asked_q
            )
            return {
                "session_memory": updated_session,
                "workflow_status": "session_saved"
            }
        return {"workflow_status": "session_saved"}

    def node_save_session_and_respond(self, state: ShopSenseGraphState) -> Dict[str, Any]:
        """Node 11 (Agent 10 Response Packaging): Assembles final OrchestratorResponse."""
        session_id = state.get("session_id", "default_session")
        turn_id = state.get("turn_id", 1)
        clarification = state.get("clarification")
        fallback = state.get("fallback")
        recommendations = state.get("recommendations", [])
        intent = state.get("current_intent")
        session = state.get("session_memory")
        error_info = state.get("error_information")

        # 1. Error response
        if state.get("workflow_status") == "error" or error_info:
            resp = OrchestratorResponse(
                session_id=session_id,
                turn_id=turn_id,
                action_taken="error",
                message=error_info or "An error occurred while processing your shopping request."
            )
            return {"final_response": resp, "workflow_status": "completed"}

        # 2. Clarification response (CRITICAL: Does NOT trigger retrieval)
        if clarification and clarification.needs_clarification and clarification.clarification_question:
            resp = OrchestratorResponse(
                session_id=session_id,
                turn_id=turn_id,
                action_taken="clarify",
                message=clarification.clarification_question,
                clarification=clarification,
                session_summary={
                    "session_id": session_id,
                    "turn_count": session.turn_count if session else turn_id
                }
            )
            return {"final_response": resp, "workflow_status": "completed"}

        # 3. Fallback response
        if fallback and fallback.fallback_needed and not recommendations:
            resp = OrchestratorResponse(
                session_id=session_id,
                turn_id=turn_id,
                action_taken="fallback",
                message=fallback.explanation,
                fallback=fallback,
                session_summary={
                    "session_id": session_id,
                    "turn_count": session.turn_count if session else turn_id
                },
                sources_consulted=state.get("sources_consulted", []),
                store_statuses=state.get("store_statuses", [])
            )
            return {"final_response": resp, "workflow_status": "completed"}

        # 4. Standard recommendation response
        comparison_breakdown = []
        for rec in recommendations:
            comparison_breakdown.append({
                "product_id": rec.product.product_id,
                "product_name": rec.product.product_name,
                "price": rec.product.price,
                "currency": rec.product.currency,
                "total_score": rec.fit_score.total_score,
                "category_score": rec.fit_score.category_score,
                "use_case_score": rec.fit_score.use_case_score,
                "feature_score": rec.fit_score.feature_score,
                "budget_score": rec.fit_score.budget_score,
                "key_benefit": rec.key_benefits[0] if rec.key_benefits else "Solid overall match"
            })

        curr_symbol = "₹" if (intent and intent.budget_currency == "INR") else "$"
        intro = f"I've analyzed our catalog and found {len(recommendations)} great options for you"
        if intent and intent.recipient:
            intro += f" (ideal for your {intent.recipient})"
        if intent and intent.budget_max:
            intro += f" staying within your {curr_symbol}{intent.budget_max:,.0f} limit"
        intro += "."

        resp = OrchestratorResponse(
            session_id=session_id,
            turn_id=turn_id,
            action_taken="recommend",
            message=intro,
            recommendations=recommendations,
            follow_up_suggestion=state.get("follow_up_suggestion"),
            top_three_comparison=comparison_breakdown,
            session_summary={
                "session_id": session_id,
                "turn_count": session.turn_count if session else turn_id,
                "confirmed_constraints": session.confirmed_constraints if session else {}
            },
            sources_consulted=state.get("sources_consulted", []),
            store_statuses=state.get("store_statuses", [])
        )
        return {"final_response": resp, "workflow_status": "completed"}

    # ==========================================
    # Conditional Router Functions
    # ==========================================

    def route_after_ingestion(self, state: ShopSenseGraphState) -> str:
        """Routes to error response if input was empty or invalid."""
        if state.get("workflow_status") == "error":
            return "node_save_session_and_respond"
        return "node_session_memory_in"

    def route_after_clarification(self, state: ShopSenseGraphState) -> str:
        """
        CRITICAL ROUTING RULE:
        If clarification is required, jump straight to session-save and respond.
        Do NOT trigger candidate retrieval until user clarifies on the next turn.
        """
        clarification = state.get("clarification")
        if clarification and clarification.needs_clarification:
            return "node_session_memory_out"
        return "node_catalog_mapping"

    def route_after_retrieval(self, state: ShopSenseGraphState) -> str:
        """
        Routes to zero-result fallback if no eligible candidates were retrieved.
        """
        eligible = state.get("eligible_candidates", [])
        if not eligible:
            return "node_zero_result_fallback"
        return "node_ranking_fit"

    # ==========================================
    # LangGraph StateGraph Assembly
    # ==========================================

    def _build_graph(self) -> StateGraph:
        builder = StateGraph(ShopSenseGraphState)

        # Register nodes
        builder.add_node("node_query_ingestion", self.node_query_ingestion)
        builder.add_node("node_session_memory_in", self.node_session_memory_in)
        builder.add_node("node_intent_extraction", self.node_intent_extraction)
        builder.add_node("node_ambiguity_clarification", self.node_ambiguity_clarification)
        builder.add_node("node_catalog_mapping", self.node_catalog_mapping)
        builder.add_node("node_candidate_retrieval", self.node_candidate_retrieval)
        builder.add_node("node_zero_result_fallback", self.node_zero_result_fallback)
        builder.add_node("node_ranking_fit", self.node_ranking_fit)
        builder.add_node("node_explanation_generation", self.node_explanation_generation)
        builder.add_node("node_session_memory_out", self.node_session_memory_out)
        builder.add_node("node_save_session_and_respond", self.node_save_session_and_respond)

        # Wire transitions
        builder.add_edge(START, "node_query_ingestion")

        builder.add_conditional_edges(
            "node_query_ingestion",
            self.route_after_ingestion,
            {
                "node_session_memory_in": "node_session_memory_in",
                "node_save_session_and_respond": "node_save_session_and_respond"
            }
        )

        builder.add_edge("node_session_memory_in", "node_intent_extraction")
        builder.add_edge("node_intent_extraction", "node_ambiguity_clarification")

        # Clarification branch: Stop and respond vs. Proceed to search
        builder.add_conditional_edges(
            "node_ambiguity_clarification",
            self.route_after_clarification,
            {
                "node_session_memory_out": "node_session_memory_out",
                "node_catalog_mapping": "node_catalog_mapping"
            }
        )

        builder.add_edge("node_catalog_mapping", "node_candidate_retrieval")

        # Retrieval branch: Empty candidates -> Fallback vs. Rank eligible
        builder.add_conditional_edges(
            "node_candidate_retrieval",
            self.route_after_retrieval,
            {
                "node_zero_result_fallback": "node_zero_result_fallback",
                "node_ranking_fit": "node_ranking_fit"
            }
        )

        builder.add_edge("node_zero_result_fallback", "node_session_memory_out")
        builder.add_edge("node_ranking_fit", "node_explanation_generation")
        builder.add_edge("node_explanation_generation", "node_session_memory_out")
        builder.add_edge("node_session_memory_out", "node_save_session_and_respond")
        builder.add_edge("node_save_session_and_respond", END)

        return builder

    def execute_turn(
        self,
        session_id: str,
        message: str,
        turn_id: int = 1,
        input_source: str = "text",
        client_context: Optional[Dict[str, Any]] = None
    ) -> OrchestratorResponse:
        """
        Executes a turn through the LangGraph workflow with thread safety and checkpointing.
        """
        lock = self._get_session_lock(session_id)
        with lock:
            initial_state: ShopSenseGraphState = {
                "session_id": session_id,
                "turn_id": turn_id,
                "original_user_message": message,
                "input_source": input_source,
                "client_context": client_context or {},
                "workflow_status": "initialized",
                "data_source_status": "ready",
                "clarification": None,
                "fallback": None,
                "recommendations": [],
                "retrieved_candidates": [],
                "eligible_candidates": [],
                "ranked_candidates": [],
                "catalog_mapping": None,
                "follow_up_suggestion": None,
                "error_information": None,
                "final_response": None,
            }

            config = {"configurable": {"thread_id": session_id}}
            result = self.graph.invoke(initial_state, config=config)
            return result.get("final_response")
