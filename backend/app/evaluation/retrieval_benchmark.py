"""Compare the legacy lexical baseline with BM25, semantic, and fused retrieval."""

import json
import math
import time
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from app.core.config import settings
from app.models.state import ExtractedIntent
from app.services.catalog_service import load_and_validate_catalog, search_by_category_and_keywords
from app.services.hybrid_retrieval import HybridCatalogIndex
from app.services.retrieval_constraints import evaluate_hard_constraints


_LEGACY_STOP_WORDS = {
    "find",
    "me",
    "the",
    "for",
    "under",
    "show",
    "suggest",
    "recommend",
    "please",
    "want",
    "need",
}


def _legacy_keywords(query: str, intent: ExtractedIntent) -> List[str]:
    keywords = []
    if intent.product_query:
        keywords.append(intent.product_query)
    else:
        if intent.category:
            keywords.append(intent.category)
        if intent.subcategory:
            keywords.append(intent.subcategory)
        keywords.extend(
            term
            for term in query.lower().split()
            if len(term) > 2 and term not in _LEGACY_STOP_WORDS
        )
        if intent.intended_use:
            keywords.append(intent.intended_use)
        keywords.extend(intent.soft_preferences)
    return keywords


def _legacy_search(catalog, query: str, intent: ExtractedIntent) -> List[str]:
    keywords = _legacy_keywords(query, intent)
    matches = search_by_category_and_keywords(
        catalog,
        category=intent.category,
        keywords=keywords or None,
        match_all_keywords=False,
    )
    if not matches and keywords:
        matches = search_by_category_and_keywords(
            catalog,
            category=None,
            keywords=keywords,
            match_all_keywords=False,
        )
    return [
        product.product_id
        for product in matches
        if evaluate_hard_constraints(product, intent).is_eligible
    ]


def _ranking_metrics(
    ranked_ids: Sequence[str],
    relevant_ids: Iterable[str],
) -> Dict[str, float]:
    relevant = set(relevant_ids)
    if not relevant:
        return {"recall_at_5": 0.0, "recall_at_10": 0.0, "mrr": 0.0, "ndcg_at_10": 0.0}
    top_5 = ranked_ids[:5]
    top_10 = ranked_ids[:10]
    reciprocal_rank = next(
        (1.0 / rank for rank, product_id in enumerate(ranked_ids, start=1) if product_id in relevant),
        0.0,
    )
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, product_id in enumerate(top_10, start=1)
        if product_id in relevant
    )
    ideal_relevant_count = min(len(relevant), 10)
    idcg = sum(
        1.0 / math.log2(rank + 1)
        for rank in range(1, ideal_relevant_count + 1)
    )
    return {
        "recall_at_5": sum(product_id in relevant for product_id in top_5) / len(relevant),
        "recall_at_10": sum(product_id in relevant for product_id in top_10) / len(relevant),
        "mrr": reciprocal_rank,
        "ndcg_at_10": dcg / idcg if idcg else 0.0,
    }


def _mean(values: List[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def run_retrieval_benchmark() -> Dict[str, object]:
    """Run the labeled local-catalog evaluation and return per-method metrics."""
    data_path = Path(__file__).with_name("retrieval_dataset.json")
    cases = json.loads(data_path.read_text(encoding="utf-8"))
    catalog = load_and_validate_catalog(settings.CATALOG_PATH)
    catalog_by_id = {product.product_id: product for product in catalog}
    index = HybridCatalogIndex(catalog)

    methods = ("legacy_keyword", "bm25", "semantic", "hybrid_rrf")
    results: Dict[str, Dict[str, object]] = {
        method: {"groups": {}, "overall": {}} for method in methods
    }
    per_case: Dict[str, Dict[str, object]] = {}

    for case in cases:
        intent = ExtractedIntent(**case["intent"])
        allowed_ids = {
            product.product_id
            for product in catalog
            if evaluate_hard_constraints(product, intent).is_eligible
        }
        measured: Dict[str, List[str]] = {}
        latencies: Dict[str, float] = {}

        started = time.perf_counter()
        measured["legacy_keyword"] = _legacy_search(catalog, case["query"], intent)
        latencies["legacy_keyword"] = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        hybrid = index.search(case["query"], allowed_product_ids=allowed_ids)
        latencies["bm25"] = (time.perf_counter() - started) * 1000
        measured["bm25"] = hybrid.bm25_ids
        measured["semantic"] = hybrid.semantic_ids
        measured["hybrid_rrf"] = hybrid.product_ids
        latencies.update(hybrid.latency_ms)

        per_case[case["id"]] = {
            "group": case["group"],
            "relevant_product_ids": case["relevant_product_ids"],
            "semantic_available": hybrid.semantic_available,
            "retrieval_mode": hybrid.retrieval_mode,
            "methods": {
                method: {
                    **_ranking_metrics(ranked_ids, case["relevant_product_ids"]),
                    "latency_ms": round(latencies.get(method, 0.0), 3),
                    "hard_constraint_violation_rate": (
                        sum(
                            not evaluate_hard_constraints(
                                catalog_by_id[product_id], intent
                            ).is_eligible
                            for product_id in ranked_ids
                            if product_id in catalog_by_id
                        )
                        / len(ranked_ids)
                        if ranked_ids
                        else 0.0
                    ),
                }
                for method, ranked_ids in measured.items()
            },
        }

    for method in methods:
        for group in sorted({case["group"] for case in cases} | {"overall"}):
            group_cases = (
                cases
                if group == "overall"
                else [case for case in cases if case["group"] == group]
            )
            metrics = [
                per_case[case["id"]]["methods"][method]
                for case in group_cases
            ]
            results[method]["groups"][group] = {
                name: _mean([item[name] for item in metrics])
                for name in (
                    "recall_at_5",
                    "recall_at_10",
                    "mrr",
                    "ndcg_at_10",
                    "hard_constraint_violation_rate",
                    "latency_ms",
                )
            }
        results[method]["overall"] = results[method]["groups"]["overall"]

    return {
        "dataset_size": len(cases),
        "model": settings.HYBRID_EMBEDDING_MODEL,
        "rrf_k": settings.HYBRID_RRF_K,
        "results": results,
        "per_case": per_case,
    }


if __name__ == "__main__":
    print(json.dumps(run_retrieval_benchmark(), indent=2))
