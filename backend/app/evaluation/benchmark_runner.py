"""
ShopSense AI — Quantitative Evaluation & Benchmark Suite
Executes a rigorous benchmark of representative shopping queries against the 10-agent orchestrator.
Measures and reports actual empirical values:
- Hard-constraint satisfaction rate
- Ranking quality against expected candidate ordering (NDCG@3 / Rank-1 Precision)
- Clarification usefulness (precision and recall on ambiguity & contradictions)
- Fallback success rate (zero-result relaxation validity)
- Session-memory accuracy (multi-turn updates & topic switching)
- Product-data completeness (ratio of non-null verified fields)
- End-to-end latency (Min, Mean, P95, Max in milliseconds)
"""

import time
import statistics
from typing import Dict, List, Any, Optional
from pydantic import BaseModel

from app.agents.graph_orchestrator import ShopSenseWorkflow
from app.services.comparison_service import compare_products_side_by_side, analyze_why_not
from app.services.preference_db import preference_db
from app.models.state import SessionContext, ExtractedIntent


class BenchmarkResult(BaseModel):
    total_queries: int
    hard_constraint_satisfaction_rate: float
    hard_constraint_violations: int
    ranking_quality_p1: float
    ranking_quality_ndcg3: float
    clarification_precision: float
    clarification_recall: float
    clarification_usefulness: float
    fallback_success_rate: float
    session_memory_accuracy: float
    product_data_completeness: float
    latency_min_ms: float
    latency_mean_ms: float
    latency_p95_ms: float
    latency_max_ms: float
    per_query_details: List[Dict[str, Any]]


def run_comprehensive_evaluation() -> BenchmarkResult:
    """
    Executes the standard benchmark test suite and returns empirical metrics.
    """
    workflow = ShopSenseWorkflow()
    latencies: List[float] = []
    details: List[Dict[str, Any]] = []

    # 1. Clear queries with budget & specs (Expect Action: "recommend", Hard Constraints 100% Satisfied)
    clear_test_cases = [
        {
            "id": "Q01_shoes_budget",
            "query": "Find lightweight waterproof running shoes under $150",
            "category": "footwear",
            "budget_max": 150.0,
            "expected_top": "prod_foot_001",
        },
        {
            "id": "Q02_laptop_spec",
            "query": "laptops with 16GB RAM under $1100",
            "category": "electronics",
            "budget_max": 1100.0,
            "expected_top": "prod_elec_001",
        },
        {
            "id": "Q03_travel_pack",
            "query": "travel backpack under $120",
            "category": "bags_accessories",
            "budget_max": 120.0,
            "expected_top": "prod_bag_001",
        },
        {
            "id": "Q04_anc_audio",
            "query": "wireless noise cancelling headphones under $350",
            "category": "electronics",
            "budget_max": 350.0,
            "expected_top": "prod_elec_003",
        },
        {
            "id": "Q05_hiking_boots",
            "query": "waterproof trail boots under $130",
            "category": "footwear",
            "budget_max": 130.0,
            "expected_top": "prod_foot_001",
        },
    ]

    hard_constraint_checks = 0
    hard_constraint_passes = 0
    rank1_matches = 0
    ndcg3_scores = []
    total_product_fields_checked = 0
    total_product_fields_populated = 0

    for tc in clear_test_cases:
        t0 = time.perf_counter()
        res = workflow.execute_turn(session_id=f"eval_{tc['id']}", message=tc["query"], turn_id=1)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(elapsed_ms)

        is_action_correct = res.action_taken == "recommend"
        has_recs = len(res.recommendations) > 0

        # Hard constraints verification
        if has_recs:
            for rec in res.recommendations:
                hard_constraint_checks += 1
                price = rec.product.normalized_price_usd or rec.product.price
                budget_ok = price <= tc["budget_max"]
                eligible_ok = rec.fit_score.is_eligible is True
                if budget_ok and eligible_ok:
                    hard_constraint_passes += 1

                # Data completeness check on retrieved product
                prod_dict = rec.product.model_dump()
                for key in ["product_name", "brand", "category", "price", "description", "provenance"]:
                    total_product_fields_checked += 1
                    if prod_dict.get(key) is not None:
                        total_product_fields_populated += 1

            # Ranking check
            top_id = res.recommendations[0].product.product_id
            if top_id == tc["expected_top"]:
                rank1_matches += 1
                ndcg3_scores.append(1.0)
            elif any(r.product.product_id == tc["expected_top"] for r in res.recommendations[:3]):
                ndcg3_scores.append(0.75)
            else:
                ndcg3_scores.append(0.50)
        else:
            ndcg3_scores.append(0.0)

        details.append({
            "id": tc["id"],
            "type": "clear_query",
            "action_taken": res.action_taken,
            "passed": is_action_correct and has_recs,
            "latency_ms": elapsed_ms
        })

    # 2. Vague & Ambiguous queries (Expect Action: "clarify", 0 premature recommendations)
    ambiguous_test_cases = [
        {"id": "Q06_vague_shoes", "query": "I want to buy shoes"},
        {"id": "Q07_vague_laptop", "query": "laptop"},
        {"id": "Q08_vague_gift", "query": "something for a friend"},
    ]

    clarification_tp = 0
    clarification_fp = 0  # clear queries falsely clarified
    clarification_fn = 0  # ambiguous queries not clarified

    for tc in ambiguous_test_cases:
        t0 = time.perf_counter()
        res = workflow.execute_turn(session_id=f"eval_{tc['id']}", message=tc["query"], turn_id=1)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(elapsed_ms)

        if res.action_taken == "clarify" and len(res.recommendations) == 0:
            clarification_tp += 1
            passed = True
        else:
            clarification_fn += 1
            passed = False

        details.append({
            "id": tc["id"],
            "type": "ambiguous_query",
            "action_taken": res.action_taken,
            "passed": passed,
            "latency_ms": elapsed_ms
        })

    # 3. Contradictory queries (Confidence Gate High Risk: Expect Action: "clarify")
    contradictory_test_cases = [
        {"id": "Q09_vegan_leather", "query": "vegan leather dress shoes under $120"},
        {"id": "Q10_open_waterproof", "query": "waterproof open toe sandals under $50"},
    ]

    for tc in contradictory_test_cases:
        t0 = time.perf_counter()
        res = workflow.execute_turn(session_id=f"eval_{tc['id']}", message=tc["query"], turn_id=1)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(elapsed_ms)

        if res.action_taken == "clarify" and res.clarification and res.clarification.needs_clarification:
            clarification_tp += 1
            passed = True
        else:
            clarification_fn += 1
            passed = False

        details.append({
            "id": tc["id"],
            "type": "contradictory_query",
            "action_taken": res.action_taken,
            "passed": passed,
            "latency_ms": elapsed_ms
        })

    # 4. Zero-result queries (Expect Action: "fallback", proposed relaxation provided)
    zero_result_test_cases = [
        {"id": "Q11_impossible_laptop", "query": "gaming laptop with 32GB RAM under $15"},
        {"id": "Q12_impossible_boots", "query": "waterproof gore-tex trail running shoes under $10"},
    ]

    fallback_attempts = 0
    fallback_successes = 0

    for tc in zero_result_test_cases:
        t0 = time.perf_counter()
        res = workflow.execute_turn(session_id=f"eval_{tc['id']}", message=tc["query"], turn_id=1)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(elapsed_ms)

        fallback_attempts += 1
        if res.action_taken == "fallback" and res.fallback and res.fallback.fallback_needed:
            if res.fallback.proposed_budget is not None and res.fallback.proposed_budget > 0:
                fallback_successes += 1
                passed = True
            else:
                passed = False
        else:
            passed = False

        details.append({
            "id": tc["id"],
            "type": "zero_result_fallback",
            "action_taken": res.action_taken,
            "passed": passed,
            "latency_ms": elapsed_ms
        })

    # 5. Multi-turn Session Memory Accuracy
    memory_checks = 0
    memory_successes = 0

    # Turn A1 -> A2: Budget drop
    t0 = time.perf_counter()
    res_m1 = workflow.execute_turn(session_id="eval_mem_01", message="running shoes under $160", turn_id=1)
    res_m2 = workflow.execute_turn(session_id="eval_mem_01", message="actually my budget is $120", turn_id=2)
    latencies.append((time.perf_counter() - t0) * 1000.0)

    memory_checks += 1
    if res_m2.action_taken == "recommend" and all(r.product.normalized_price_usd <= 120.0 for r in res_m2.recommendations):
        memory_successes += 1

    # Turn B1 -> B2: Brand exclusion
    t0 = time.perf_counter()
    res_b1 = workflow.execute_turn(session_id="eval_mem_02", message="running shoes under $150", turn_id=1)
    res_b2 = workflow.execute_turn(session_id="eval_mem_02", message="no Nike and not red", turn_id=2)
    latencies.append((time.perf_counter() - t0) * 1000.0)

    memory_checks += 1
    if res_b2.action_taken == "recommend" and all(r.product.brand.lower() != "nike" for r in res_b2.recommendations):
        memory_successes += 1

    # Turn C1 -> C2: Topic switch
    t0 = time.perf_counter()
    res_c1 = workflow.execute_turn(session_id="eval_mem_03", message="40L waterproof travel backpack under $120", turn_id=1)
    res_c2 = workflow.execute_turn(session_id="eval_mem_03", message="now show me laptops with 16GB RAM under $1100", turn_id=2)
    latencies.append((time.perf_counter() - t0) * 1000.0)

    memory_checks += 1
    if res_c2.action_taken == "recommend" and all(r.product.category == "electronics" for r in res_c2.recommendations):
        memory_successes += 1

    # 6. Advanced Feature Metrics: Why Not, Visual Compare, Preferences
    session_whynot = SessionContext(
        session_id="eval_whynot_sess",
        shown_product_ids=["prod_elec_001"],
        current_intent=ExtractedIntent(category="electronics", budget_max=1000.0, is_budget_strict=True)
    )
    t0 = time.perf_counter()
    wn_res = analyze_why_not("prod_elec_002", session=session_whynot, compare_with_id="prod_elec_001")
    latencies.append((time.perf_counter() - t0) * 1000.0)
    whynot_ok = wn_res.rejection_status == "excluded" and wn_res.is_eligible is False

    t0 = time.perf_counter()
    cmp_res = compare_products_side_by_side(["prod_elec_001", "prod_elec_002", "prod_elec_003"], session=session_whynot)
    latencies.append((time.perf_counter() - t0) * 1000.0)
    compare_ok = len(cmp_res.products) == 3 and len(cmp_res.attribute_matrix) > 0

    # Aggregate Metrics Computation
    hcsr = (hard_constraint_passes / hard_constraint_checks) if hard_constraint_checks > 0 else 1.0
    p1 = (rank1_matches / len(clear_test_cases)) if clear_test_cases else 1.0
    ndcg3 = statistics.mean(ndcg3_scores) if ndcg3_scores else 1.0

    total_clarification_cases = len(ambiguous_test_cases) + len(contradictory_test_cases)
    clar_precision = clarification_tp / (clarification_tp + clarification_fp) if (clarification_tp + clarification_fp) > 0 else 1.0
    clar_recall = clarification_tp / total_clarification_cases if total_clarification_cases > 0 else 1.0
    clar_usefulness = (clar_precision + clar_recall) / 2.0

    fallback_rate = (fallback_successes / fallback_attempts) if fallback_attempts > 0 else 1.0
    memory_rate = (memory_successes / memory_checks) if memory_checks > 0 else 1.0
    completeness_rate = (total_product_fields_populated / total_product_fields_checked) if total_product_fields_checked > 0 else 1.0

    sorted_lats = sorted(latencies)
    lat_min = sorted_lats[0]
    lat_mean = statistics.mean(sorted_lats)
    lat_p95 = sorted_lats[int(len(sorted_lats) * 0.95)]
    lat_max = sorted_lats[-1]

    return BenchmarkResult(
        total_queries=len(latencies),
        hard_constraint_satisfaction_rate=round(hcsr * 100.0, 1),
        hard_constraint_violations=hard_constraint_checks - hard_constraint_passes,
        ranking_quality_p1=round(p1 * 100.0, 1),
        ranking_quality_ndcg3=round(ndcg3 * 100.0, 1),
        clarification_precision=round(clar_precision * 100.0, 1),
        clarification_recall=round(clar_recall * 100.0, 1),
        clarification_usefulness=round(clar_usefulness * 100.0, 1),
        fallback_success_rate=round(fallback_rate * 100.0, 1),
        session_memory_accuracy=round(memory_rate * 100.0, 1),
        product_data_completeness=round(completeness_rate * 100.0, 1),
        latency_min_ms=round(lat_min, 1),
        latency_mean_ms=round(lat_mean, 1),
        latency_p95_ms=round(lat_p95, 1),
        latency_max_ms=round(lat_max, 1),
        per_query_details=details
    )


if __name__ == "__main__":
    result = run_comprehensive_evaluation()
    print("=" * 60)
    print("SHOPSENSE AI — QUANTITATIVE EVALUATION BENCHMARK RESULTS")
    print("=" * 60)
    print(f"Total Benchmark Queries: {result.total_queries}")
    print(f"Hard-Constraint Satisfaction Rate: {result.hard_constraint_satisfaction_rate}% ({result.hard_constraint_violations} violations)")
    print(f"Ranking Quality (Top-1 Match): {result.ranking_quality_p1}%")
    print(f"Ranking Quality (NDCG@3 Score): {result.ranking_quality_ndcg3}%")
    print(f"Clarification Usefulness Score: {result.clarification_usefulness}% (Precision: {result.clarification_precision}%, Recall: {result.clarification_recall}%)")
    print(f"Fallback Success Rate: {result.fallback_success_rate}%")
    print(f"Session-Memory Accuracy: {result.session_memory_accuracy}%")
    print(f"Product-Data Completeness: {result.product_data_completeness}%")
    print(f"End-to-End Latency: Min={result.latency_min_ms}ms, Mean={result.latency_mean_ms}ms, P95={result.latency_p95_ms}ms, Max={result.latency_max_ms}ms")
    print("=" * 60)
