# ShopSense AI — Architecture & Multi-Agent Design

This document details the internal architecture, LangGraph state machine, agent contracts, state flow, and deterministic vs. LLM boundary for **ShopSense AI**.

---

## 1. Hybrid Agent Philosophy

A common anti-pattern in conversational commerce is delegating pure computation (e.g., "is price <= $1000", sorting items, calculating discounts) to an LLM. This leads to non-deterministic errors, budget hallucinations, and unnecessary API costs and latency.

ShopSense AI strictly separates concerns:
1. **Deterministic Logic**: Constraint evaluation, catalog indexing, mathematical scoring, unit conversion, and hard filtering.
2. **LLM Intelligence (Groq)**: Linguistic entity extraction, nuanced intent parsing, empathetic clarification questioning, and tailored natural-language explanations.

---

## 2. LangGraph State Machine Workflow

ShopSense AI uses **LangGraph `StateGraph`** with in-memory thread checkpointing (`MemorySaver`) to orchestrate all 10 agents.

```mermaid
graph TD
    Start([START]) --> N1[node_query_ingestion<br>Agent 1: Ingestion & Normalization]
    
    N1 --> CondIngest{Input Valid?}
    CondIngest -- Invalid / Empty --> N11[node_save_session_and_respond<br>Agent 10: Error Response]
    CondIngest -- Valid Query --> N2[node_session_memory_in<br>Agent 9: In-Memory / Checkpoint Context]
    
    N2 --> N3[node_intent_extraction<br>Agent 2: Entity & Constraint Extraction]
    N3 --> N4[node_ambiguity_clarification<br>Agent 3: Confidence-Gated Autonomy]
    
    N4 --> CondClarify{Needs Clarification?}
    CondClarify -- Yes: Ambiguous --> N10[node_session_memory_out<br>Agent 9: Record Question Asked]
    CondClarify -- No: Clear Query --> N5[node_catalog_mapping<br>Agent 4: Colloquial & Synonym Mapping]
    
    N5 --> N6[node_candidate_retrieval<br>Agent 5: Broad Retrieval & Hard Filter]
    
    N6 --> CondRetrieve{Eligible Candidates?}
    CondRetrieve -- 0 Items --> N7[node_zero_result_fallback<br>Agent 8: Budget Relaxation Diff]
    CondRetrieve -- >= 1 Items --> N8[node_ranking_fit<br>Agent 6: Multi-Factor Scoring 0-100]
    
    N8 --> N9[node_explanation_generation<br>Agent 7: Evidence-Based Associate Justification]
    N9 --> N10
    N7 --> N10
    
    N10 --> N11[node_save_session_and_respond<br>Agent 10: Response Packaging & Comparison]
    N11 --> EndNode([END])
```

---

## 3. Shared Graph State (`ShopSenseGraphState`)

The state machine shares a strongly typed `ShopSenseGraphState` dictionary across all nodes:

| State Key | Type | Description |
|-----------|------|-------------|
| `session_id` | `str` | Unique thread identifier isolating user sessions |
| `turn_id` | `int` | Dialogue turn counter |
| `original_user_message` | `str` | Raw input text or voice transcript |
| `input_source` | `str` | Input origin (`text` or `voice`) |
| `client_context` | `Dict[str, Any]` | Active browser tab URL and product context |
| `normalized_query` | `IngestedQuery` | Sanitized message with protected entities |
| `current_intent` | `ExtractedIntent` | Structured category, budget ceiling, use case, negations |
| `previous_intent` | `ExtractedIntent` | Carried over from prior turns for context merging |
| `session_memory` | `SessionContext` | Questions asked, confirmed constraints, shown items |
| `clarification` | `ClarificationDecision` | Confidence score, questions, and suggested options |
| `catalog_mapping` | `AttributeMappingResult` | Normalized catalog filters and applied synonyms |
| `retrieved_candidates` | `List[Product]` | Broad candidate pool from catalog |
| `eligible_candidates` | `List[Product]` | Candidates surviving strict hard constraints |
| `ranked_candidates` | `List[Tuple[Product, FitScore]]` | Scored items (0 - 100) with factor breakdowns |
| `recommendations` | `List[ProductRecommendation]` | Top recommendations with associate explanations |
| `fallback` | `FallbackSuggestion` | Budget relaxation diff and suggested alternatives |
| `data_source_status` | `str` | `ready`, `catalog_ready`, or `source_error` |
| `error_information` | `Optional[str]` | Error message if pipeline encountered non-recoverable error |
| `workflow_status` | `str` | Workflow stage tracker |
| `final_response` | `OrchestratorResponse` | Complete unified API response payload |

---

## 4. Graph Transitions & Routing Rules

1. **Query Normalization (`node_query_ingestion`)**:
   - Sanitizes text while preserving units (`16.5h`, `14"`), negations (`not leather`), and budget values (`₹8,000`, `$1,000`).
   - If empty/whitespace, branches directly to error response.
2. **Context Merging (`node_session_memory_in`)**:
   - Reads conversation history for `session_id`. Merges past category and budget for follow-ups (e.g. "make it cheaper").
   - Resets filters cleanly when the user switches topics (e.g. "now find a travel bag").
3. **Structured Extraction (`node_intent_extraction`)**:
   - Extracts structured criteria into `ExtractedIntent` via Groq LLM with deterministic regex fallback.
4. **Confidence-Gated Clarification (`node_ambiguity_clarification`)**:
   - Computes structural completeness score (0.0 to 1.0).
   - **Critical Rule**: If clarification is required, routes directly to `node_session_memory_out` and responds with the question. **Candidate retrieval is NOT triggered**.
   - On the next turn, user's answer is merged and workflow resumes.
   - Prevents asking identical questions repeatedly.
5. **Catalog Mapping (`node_catalog_mapping`)**:
   - Maps colloquial terms ("good for long walks" ➔ `walking`, "lightweight" ➔ `weight_kg <= 1.5`).
6. **Candidate Retrieval (`node_candidate_retrieval`)**:
   - Enforces strict hard constraints (budget ceilings and exclusions).
   - If 0 items survive, branches to `node_zero_result_fallback`.
7. **Ranking & Fit Scoring (`node_ranking_fit`)**:
   - Weighted scoring matrix: Category (20%) + Use-Case (25%) + Features (25%) + Budget (20%) + Preferences (10%).
   - Violating a hard constraint zeroes out eligibility.
8. **Explanation Generation (`node_explanation_generation`)**:
   - Produces evidence-based explanations highlighting verified features and honest trade-offs.
9. **Response Packaging (`node_save_session_and_respond`)**:
   - Assembles `OrchestratorResponse` with top 3 visual comparison breakdown.

---

## 5. Safe Session Handling & Concurrency

- **LangGraph Checkpointing**: Built with `MemorySaver` using `{"configurable": {"thread_id": session_id}}`. State snapshots are persisted per session thread.
- **Thread Concurrency Locks**: Uses a thread-safe mutex dictionary per `session_id` to guarantee that concurrent requests on the same session do not clobber state.
- **Session Isolation**: Requests for separate session IDs run independently without leaking constraints or preferences.

---

## 6. Failure Resilience & Graceful Fallbacks

| Failure Scenario | Mitigation Strategy |
|------------------|---------------------|
| **Groq API Timeout / Network Drop** | Centralized in `llm_service.py` with 5.0s timeout; seamlessly falls back to `deterministic_extract_intent` without crashing. |
| **Invalid LLM JSON Output** | Caught by Pydantic validation; defaults applied cleanly. |
| **Missing Catalog Attributes** | Unknown attributes classified as `UNKNOWN` (Rule #10), never assumed as matches. |
| **Zero Matching Candidates** | Branches to `ZeroResultFallbackAgent`, providing a +25% budget relaxation diff and alternative options. |
| **Malformed / Empty Input** | Rejected gracefully by `QueryIngestionAgent` with user-friendly guidance. |
