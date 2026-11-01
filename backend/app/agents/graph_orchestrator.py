"""
ShopSense AI — LangGraph Orchestration State Machine
Coordinates all 10 specialized agents using LangGraph's StateGraph and Checkpointing.
Implements validated transitions, confidence-gated clarification branches, zero-result
fallbacks, and thread-safe session checkpointing.
"""

import json
import logging
import re
from time import perf_counter
from typing import Dict, Any, Callable, Optional, List, Tuple
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
from app.core.config import settings
from app.agents.session_memory import SessionMemoryAgent
from app.services.retrieval_constraints import evaluate_recommendation_candidate
from app.services.catalog_service import load_and_validate_catalog

logger = logging.getLogger(__name__)


def _log_summary(value: Any, max_length: int = 1600) -> str:
    """Render bounded, single-line structured details for workflow logs."""
    serialized = json.dumps(value, ensure_ascii=True, separators=(",", ":"), default=str)
    if len(serialized) > max_length:
        return f"{serialized[:max_length]}... (truncated)"
    return serialized


AGENT_LOG_DETAILS = {
    "node_query_ingestion": ("01", "Query Ingestion"),
    "node_intent_extraction": ("02", "Intent & Constraint Extraction"),
    "node_ambiguity_clarification": ("03", "Ambiguity & Clarification"),
    "node_catalog_mapping": ("04", "Catalog Attribute Mapping"),
    "node_candidate_retrieval": ("05", "Candidate Retrieval"),
    "node_ranking_fit": ("06", "Ranking & Fit Scoring"),
    "node_explanation_generation": ("07", "Explanation Generation"),
    "node_zero_result_fallback": ("08", "Zero-Result & Fallback"),
    "node_session_memory_in": ("09", "Session Memory Load"),
    "node_session_memory_out": ("09", "Session Memory Save"),
    "node_comparison": ("07", "Comparison"),
    "node_save_session_and_respond": ("10", "Orchestrator Response"),
}


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

    def _logged_agent_node(
        self,
        node_name: str,
        node: Callable[[ShopSenseGraphState], Dict[str, Any]],
    ) -> Callable[[ShopSenseGraphState], Dict[str, Any]]:
        agent_number, agent_name = AGENT_LOG_DETAILS[node_name]

        def run(state: ShopSenseGraphState) -> Dict[str, Any]:
            session_id = state.get("session_id", "default_session")
            turn_id = state.get("turn_id", 1)
            log_context = f"session={session_id} turn={turn_id}"
            logger.info("[Agent %s/10] START %s | %s", agent_number, agent_name, log_context)

            try:
                result = node(state)
            except Exception:
                logger.exception("[Agent %s/10] FAILED %s | %s", agent_number, agent_name, log_context)
                raise

            details = []
            if "workflow_status" in result:
                details.append(f"status={result['workflow_status']}")
            if result.get("current_intent") is not None:
                details.append(
                    "intent="
                    + _log_summary(result["current_intent"].model_dump(exclude_none=True))
                )
            if "clarification" in result and result["clarification"] is not None:
                decision = result["clarification"]
                action = "clarify" if decision.needs_clarification else "search"
                details.append(f"decision={action} confidence={decision.confidence_score:.2f}")
                details.append(
                    "clarification="
                    + _log_summary(decision.model_dump(exclude_none=True))
                )
            if result.get("catalog_mapping") is not None:
                details.append(
                    "mapping="
                    + _log_summary(result["catalog_mapping"].model_dump(exclude_none=True))
                )
            if "retrieved_candidates" in result:
                details.append(f"candidates={len(result['retrieved_candidates'])}")
                details.append(
                    "candidate_preview="
                    + _log_summary([
                        {
                            "name": product.product_name,
                            "price": product.price,
                            "currency": product.currency,
                        }
                        for product in result["retrieved_candidates"][:5]
                    ])
                )
            if "sources_consulted" in result:
                details.append(f"sources={_log_summary(result['sources_consulted'])}")
            if "ranked_candidates" in result:
                details.append(f"ranked={len(result['ranked_candidates'])}")
                details.append(
                    "ranking_preview="
                    + _log_summary([
                        {
                            "name": product.product_name,
                            "score": score.total_score,
                            "eligible": score.is_eligible,
                        }
                        for product, score in result["ranked_candidates"][:3]
                    ])
                )
            if "recommendations" in result:
                details.append(f"recommendations={len(result['recommendations'])}")
                details.append(
                    "recommendation_preview="
                    + _log_summary([
                        {
                            "name": recommendation.product.product_name,
                            "price": recommendation.product.price,
                            "currency": recommendation.product.currency,
                            "score": recommendation.fit_score.total_score,
                            "explanation": recommendation.explanation,
                            "key_benefits": recommendation.key_benefits,
                        }
                        for recommendation in result["recommendations"][:3]
                    ])
                )
            if "fallback" in result and result["fallback"] is not None:
                details.append(f"fallback_needed={result['fallback'].fallback_needed}")
                details.append(
                    "fallback="
                    + _log_summary(result["fallback"].model_dump(exclude_none=True))
                )
            if "final_response" in result and result["final_response"] is not None:
                response = result["final_response"]
                details.append(f"action={response.action_taken}")
                details.append(
                    "final_recommendations="
                    + _log_summary([
                        {
                            "name": recommendation.product.product_name,
                            "price": recommendation.product.price,
                            "currency": recommendation.product.currency,
                            "score": recommendation.fit_score.total_score,
                            "explanation": recommendation.explanation,
                            "key_benefits": recommendation.key_benefits,
                        }
                        for recommendation in response.recommendations[:3]
                    ])
                )

            detail_text = f" | {' '.join(details)}" if details else ""
            logger.info(
                "[Agent %s/10] DONE %s | %s%s",
                agent_number,
                agent_name,
                log_context,
                detail_text,
            )
            return result

        return run

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
        boundary = self.classify_session_boundary(
            state.get("original_user_message", ""),
            session.current_intent,
            session.awaiting_clarification,
        )
        return {
            "session_memory": session,
            "previous_intent": session.current_intent,
            "session_boundary": boundary,
            "workflow_status": "context_merged"
        }

    @staticmethod
    def classify_session_boundary(
        message: str,
        previous: Optional[ExtractedIntent],
        awaiting_clarification: bool = False,
    ) -> str:
        """Classify whether prior intent is safe to carry into this turn."""
        lower = message.casefold().strip()
        if re.search(r"\b(compare|comparison|versus|vs\.?)\b", lower):
            return "compare"
        if previous is None:
            return "new"
        if awaiting_clarification:
            return "clarification_answer"
        if re.search(r"\b(?:new request|start over|new search|reset)\b", lower):
            return "new"
        return "refine"

    def node_intent_extraction(self, state: ShopSenseGraphState) -> Dict[str, Any]:
        """Node 3 (Agent 2): Extract structured intent and merge context."""
        ingested = state.get("normalized_query")
        prev_intent = state.get("previous_intent")

        try:
            previous_for_extraction = (
                prev_intent
                if state.get("session_boundary") in {"refine", "clarification_answer"}
                else None
            )
            intent = self.intent_extraction_agent.extract(
                ingested=ingested,
                conversation_history=None,
                previous_intent=previous_for_extraction,
                clarification_answer=state.get("session_boundary") == "clarification_answer",
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

    def node_comparison(self, state: ShopSenseGraphState) -> Dict[str, Any]:
        """Build a comparison only from exact catalog product IDs."""
        from app.services.comparison_service import compare_products_side_by_side

        intent = state.get("current_intent")
        relevance_scores = state.get("relevance_scores", {})
        session = state.get("session_memory")
        try:
            comparison = compare_products_side_by_side(
                intent.comparison_product_ids if intent else [],
                session=session,
            )
            response = OrchestratorResponse(
                session_id=state.get("session_id", "default_session"),
                turn_id=state.get("turn_id", 1),
                action_taken="compare",
                message=comparison.recommendation_summary,
                top_three_comparison=[
                    {
                        "product_id": item.product_id,
                        "product_name": item.product_name,
                        "price": item.price,
                        "currency": item.currency,
                        "key_specs": item.key_specs,
                        "hard_constraint_satisfaction": item.hard_constraint_satisfaction,
                    }
                    for item in comparison.products
                ],
                session_summary={
                    "session_id": state.get("session_id", "default_session"),
                    "comparison_product_ids": intent.comparison_product_ids if intent else [],
                },
            )
            return {
                "comparison_response": response.model_dump(),
                "workflow_status": "comparison_ready",
            }
        except (ValueError, TypeError) as exc:
            logger.warning("Comparison request could not be completed: %s", exc)
            return {
                "error_information": str(exc),
                "workflow_status": "error",
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
        if decision.suggested_options and not decision.actions:
            decision.actions = [
                {
                    "type": "select_option",
                    "label": option,
                    "payload": {"value": option},
                }
                for option in decision.suggested_options
            ]

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
            ingested = state.get("normalized_query")
            session = state.get("session_memory")
            raw_query = ingested.sanitized_message.casefold() if ingested else ""
            request_more = bool(re.search(
                r"\b(?:show|give|suggest|recommend)\s+more\b|"
                r"\b(?:more|other)\s+options\b|"
                r"\bany\s+other\s+options?\b",
                raw_query,
            ))
            excluded_product_ids = set(
                session.rejected_product_ids if session else []
            )
            if request_more and session:
                excluded_product_ids.update(session.shown_product_ids)
            retrieval = self.candidate_retrieval_agent.retrieve(
                intent,
                mapping,
                query_text=ingested.sanitized_message if ingested else None,
                excluded_product_ids=list(excluded_product_ids),
            )
            return {
                "retrieved_candidates": retrieval.candidates,
                "eligible_candidates": retrieval.candidates,
                "retrieval_scores": retrieval.retrieval_scores,
                "relevance_scores": retrieval.relevance_scores,
                "near_misses": retrieval.near_misses,
                "retrieval_sources": retrieval.retrieval_sources,
                "retrieval_mode": retrieval.retrieval_mode,
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
        session = state.get("session_memory")

        ranked_pairs = self.ranking_fit_agent.rank(
            candidates,
            intent,
            retrieval_scores=state.get("retrieval_scores", {}),
            retrieval_sources=state.get("retrieval_sources", {}),
            excluded_product_ids=session.rejected_product_ids if session else None,
        )
        return {
            "ranked_candidates": ranked_pairs,
            "workflow_status": "ranked"
        }

    def node_explanation_generation(self, state: ShopSenseGraphState) -> Dict[str, Any]:
        """Node 8 (Agent 7): Evidence-grounded natural language justifications."""
        ranked_pairs = state.get("ranked_candidates", [])
        intent = state.get("current_intent")

        validated_pairs = [
            (product, score)
            for product, score in ranked_pairs
            if (
                evaluate_recommendation_candidate(product, intent).is_eligible
                and score.is_eligible
                and score.relevance >= settings.MIN_RELEVANCE
                and score.total_score >= settings.MIN_FIT_SCORE
            )
        ]
        if not validated_pairs:
            _, analysis_summary = self.explanation_agent.explain_with_analysis(
                [],
                intent,
            )
            return {
                "recommendations": [],
                "analysis_summary": analysis_summary,
                "follow_up_suggestion": None,
                "fallback": self.fallback_agent.generate_fallback(
                    intent,
                    near_misses=state.get("near_misses", []),
                    relevance_scores=state.get("relevance_scores", {}),
                ),
                "workflow_status": "fallback_invoked",
            }

        recommendations, analysis_summary = self.explanation_agent.explain_with_analysis(
            validated_pairs,
            intent,
            top_k=3,
        )

        # Feature 5: Context-Aware Follow-Up Suggestion (At most one relevant accessory)
        follow_up = None
        if recommendations:
            from app.services.follow_up_service import find_complementary_suggestion
            follow_up = find_complementary_suggestion(recommendations[0].product, intent)

        return {
            "recommendations": recommendations,
            "analysis_summary": analysis_summary,
            "follow_up_suggestion": follow_up,
            "workflow_status": "explained"
        }

    def node_zero_result_fallback(self, state: ShopSenseGraphState) -> Dict[str, Any]:
        """Node 9 (Agent 8): Intelligent constraint relaxation and alternative generation."""
        intent = state.get("current_intent")
        relevance_scores = state.get("relevance_scores", {})
        fallback = self.fallback_agent.generate_fallback(
            intent,
            near_misses=state.get("near_misses", []),
            relevance_scores=relevance_scores,
        )
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
            previous = state.get("previous_intent")
            topic_changed = state.get("session_boundary") == "new" or bool(
                previous
                and intent.category
                and previous.category
                and intent.category != previous.category
            )
            updated_session = self.session_memory_agent.update_session(
                session_id=session_id,
                intent=intent,
                shown_product_ids=shown_ids,
                asked_question=asked_q,
                topic_changed=topic_changed,
            )
            updated_session.awaiting_clarification = bool(
                clarification and clarification.needs_clarification
            )
            if clarification and clarification.needs_clarification:
                updated_session.last_response_kind = "clarify"
            elif state.get("comparison_response"):
                updated_session.last_response_kind = "compare"
            elif state.get("fallback"):
                updated_session.last_response_kind = "fallback"
            else:
                updated_session.last_response_kind = "recommend"
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
        analysis_summary = state.get("analysis_summary")
        intent = state.get("current_intent")
        session = state.get("session_memory")
        error_info = state.get("error_information")
        comparison_response = state.get("comparison_response")

        if comparison_response:
            return {
                "final_response": OrchestratorResponse.model_validate(comparison_response),
                "workflow_status": "completed",
            }

        # 1. Error response
        if state.get("workflow_status") == "error" or error_info:
            resp = OrchestratorResponse(
                session_id=session_id,
                turn_id=turn_id,
                action_taken="error",
                message=error_info or "An error occurred while processing your shopping request."
            )
            return {"final_response": resp, "workflow_status": "completed"}

        if intent and intent.shopping_intent == "category_discovery":
            counts: Dict[str, int] = {}
            for product in load_and_validate_catalog():
                counts[product.category] = counts.get(product.category, 0) + 1
            labels = {
                "beauty_personal_care": "Beauty & Personal Care",
                "fashion_accessories": "Fashion Accessories",
                "fitness_outdoor": "Fitness & Outdoor",
                "home_kitchen": "Home & Kitchen",
                "bags_accessories": "Bags & Accessories",
            }
            categories = [
                {
                    "name": labels.get(name, name.replace("_", " ").title()),
                    "product_count": count,
                }
                for name, count in sorted(counts.items())
            ]
            message = "Our catalog currently includes: " + "; ".join(
                f"{item['name']} ({item['product_count']} products)"
                for item in categories
            ) + "."
            resp = OrchestratorResponse(
                session_id=session_id,
                turn_id=turn_id,
                action_taken="recommend",
                message=message,
                session_summary={
                    "session_id": session_id,
                    "turn_count": session.turn_count if session else turn_id,
                    "available_categories": categories,
                },
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

        if intent and recommendations:
            validated_recommendations = []
            rejected_count = 0
            for recommendation in recommendations:
                evaluation = evaluate_recommendation_candidate(
                    recommendation.product,
                    intent,
                )
                score = recommendation.fit_score
                if (
                    evaluation.is_eligible
                    and score.is_eligible
                    and score.relevance >= settings.MIN_RELEVANCE
                    and score.total_score >= settings.MIN_FIT_SCORE
                ):
                    validated_recommendations.append(recommendation)
                else:
                    rejected_count += 1
                    logger.warning(
                        "Final validation rejected product_id=%s: %s",
                        recommendation.product.product_id,
                        "; ".join(evaluation.violations),
                    )
            recommendations = validated_recommendations
            if rejected_count and not recommendations:
                fallback = self.fallback_agent.generate_fallback(
                    intent,
                    near_misses=state.get("near_misses", []),
                    relevance_scores=relevance_scores,
                )

        # 3. Fallback response
        if fallback and fallback.fallback_needed and not recommendations:
            resp = OrchestratorResponse(
                session_id=session_id,
                turn_id=turn_id,
                action_taken="fallback",
                message=fallback.explanation,
                analysis_summary=analysis_summary,
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
                "retrieval_score": rec.fit_score.retrieval_score,
                "key_benefit": rec.key_benefits[0] if rec.key_benefits else "Solid overall match"
            })

        intro = f"I've analyzed our catalog and found {len(recommendations)} great options for you"
        if intent and intent.recipient:
            intro += f" (ideal for your {intent.recipient})"
        if intent and intent.budget_max:
            budget_word = "around" if intent.budget_is_approximate else "within"
            intro += f" {budget_word} your ₹{intent.budget_max:,.0f} limit"
        intro += "."

        resp = OrchestratorResponse(
            session_id=session_id,
            turn_id=turn_id,
            action_taken="recommend",
            message=intro,
            analysis_summary=analysis_summary,
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
        intent = state.get("current_intent")
        if intent and intent.shopping_intent == "category_discovery":
            return "node_session_memory_out"
        if intent and intent.shopping_intent == "comparison":
            return "node_comparison"
        if clarification and clarification.needs_clarification:
            return "node_session_memory_out"
        return "node_catalog_mapping"

    def route_after_intent(self, state: ShopSenseGraphState) -> str:
        intent = state.get("current_intent")
        if intent and intent.shopping_intent == "comparison":
            return "node_comparison"
        return "node_ambiguity_clarification"

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
        agent_nodes = [
            ("node_query_ingestion", self.node_query_ingestion),
            ("node_session_memory_in", self.node_session_memory_in),
            ("node_intent_extraction", self.node_intent_extraction),
            ("node_ambiguity_clarification", self.node_ambiguity_clarification),
            ("node_catalog_mapping", self.node_catalog_mapping),
            ("node_candidate_retrieval", self.node_candidate_retrieval),
            ("node_zero_result_fallback", self.node_zero_result_fallback),
            ("node_ranking_fit", self.node_ranking_fit),
            ("node_explanation_generation", self.node_explanation_generation),
            ("node_session_memory_out", self.node_session_memory_out),
            ("node_comparison", self.node_comparison),
            ("node_save_session_and_respond", self.node_save_session_and_respond),
        ]
        for node_name, node in agent_nodes:
            builder.add_node(node_name, self._logged_agent_node(node_name, node))

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
        builder.add_conditional_edges(
            "node_intent_extraction",
            self.route_after_intent,
            {
                "node_comparison": "node_comparison",
                "node_ambiguity_clarification": "node_ambiguity_clarification",
            },
        )
        builder.add_edge("node_comparison", "node_session_memory_out")

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
            started_at = perf_counter()
            logger.info(
                "[Workflow] START session=%s turn=%s source=%s",
                session_id,
                turn_id,
                input_source,
            )
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
                "retrieval_scores": {},
                "relevance_scores": {},
                "near_misses": [],
                "retrieval_sources": {},
                "retrieval_mode": "hybrid",
                "catalog_mapping": None,
                "follow_up_suggestion": None,
                "error_information": None,
                "final_response": None,
                "session_boundary": "new",
                "comparison_response": None,
            }

            config = {"configurable": {"thread_id": session_id}}
            try:
                result = self.graph.invoke(initial_state, config=config)
            except Exception:
                logger.exception("[Workflow] FAILED session=%s turn=%s", session_id, turn_id)
                raise

            response = result.get("final_response")
            logger.info(
                "[Workflow] DONE session=%s turn=%s action=%s recommendations=%s elapsed_ms=%.1f",
                session_id,
                turn_id,
                response.action_taken if response else "missing",
                len(response.recommendations) if response else 0,
                (perf_counter() - started_at) * 1000,
            )
            return response
