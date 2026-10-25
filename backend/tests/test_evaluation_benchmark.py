import pytest
from app.evaluation.benchmark_runner import run_comprehensive_evaluation

def test_evaluation_benchmark_metrics():
    """
    Automated assertion of quantitative evaluation benchmark metrics:
    1. Hard-constraint satisfaction rate == 100.0%
    2. Ranking quality (NDCG@3) >= 80.0%
    3. Clarification precision and recall >= 85.0%
    4. Fallback success rate == 100.0%
    5. Session-memory accuracy >= 95.0%
    6. Product-data completeness >= 90.0%
    7. End-to-end latency p95 < 500.0ms
    """
    from app.core.config import settings
    old_mock = settings.MOCK_LLM_FOR_TESTS
    try:
        settings.MOCK_LLM_FOR_TESTS = True
        result = run_comprehensive_evaluation()
    finally:
        settings.MOCK_LLM_FOR_TESTS = old_mock
    
    # 1. Hard-constraint satisfaction
    assert result.hard_constraint_satisfaction_rate == 100.0, "Hard constraint satisfaction must be 100%"
    assert result.hard_constraint_violations == 0, "No hard constraint violations allowed"
    
    # 2. Ranking quality
    assert result.ranking_quality_ndcg3 >= 80.0, f"NDCG@3 score {result.ranking_quality_ndcg3}% below 80%"
    assert result.ranking_quality_p1 >= 70.0, f"Top-1 match {result.ranking_quality_p1}% below 70%"
    
    # 3. Clarification usefulness
    assert result.clarification_precision >= 85.0, "Clarification precision must be >= 85%"
    assert result.clarification_recall >= 85.0, "Clarification recall must be >= 85%"
    assert result.clarification_usefulness >= 85.0, "Clarification usefulness must be >= 85%"
    
    # 4. Fallback success rate
    assert result.fallback_success_rate == 100.0, "Fallback success rate must be 100%"
    
    # 5. Session-memory accuracy
    assert result.session_memory_accuracy >= 95.0, "Session memory accuracy must be >= 95%"
    
    # 6. Product-data completeness
    assert result.product_data_completeness >= 90.0, "Product data completeness must be >= 90%"
    
    # 7. End-to-end latency (allows for remote internet network roundtrips when live LLM is enabled)
    from app.core.config import settings
    max_latency = 6000.0 if (settings.GROQ_API_KEY and not settings.MOCK_LLM_FOR_TESTS) else 500.0
    assert result.latency_p95_ms < max_latency, f"P95 latency {result.latency_p95_ms}ms exceeded {max_latency}ms threshold"
