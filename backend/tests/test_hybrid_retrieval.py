import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import List, Sequence

import numpy as np
import pytest

from app.agents.candidate_retrieval import CandidateRetrievalAgent
from app.models.product import AvailabilityStatus, Product
from app.models.state import AttributeMappingResult, ExtractedIntent
from app.services.hybrid_retrieval import (
    _FastEmbedEncoder,
    HybridCatalogIndex,
    build_product_document,
    reciprocal_rank_fusion,
)
from app.services.catalog_service import load_and_validate_catalog
from app.services.retrieval_constraints import evaluate_hard_constraints


class ConceptEncoder:
    """Deterministic test encoder for vector-index behavior without model downloads."""

    concepts = {
        "knee": 0,
        "knees": 0,
        "joint": 0,
        "joints": 0,
        "painful": 0,
        "soreness": 0,
        "relief": 0,
        "descent": 1,
        "descents": 1,
        "downhill": 1,
        "steep": 1,
        "slopes": 1,
        "hiking": 2,
        "hiker": 2,
        "trekking": 2,
        "trail": 2,
        "trails": 2,
        "mountain": 2,
    }

    def __init__(self):
        self.calls: List[List[str]] = []

    def encode(self, texts: Sequence[str], **kwargs):
        self.calls.append(list(texts))
        vectors = np.zeros((len(texts), 4), dtype="float32")
        for row, text in enumerate(texts):
            for token in re.findall(r"[a-z0-9]+", text.lower()):
                concept = self.concepts.get(token)
                if concept is not None:
                    vectors[row, concept] += 1.0
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vectors / norms


def _product(
    product_id: str,
    product_name: str,
    *,
    category: str = "fitness_outdoor",
    subcategory: str = "trekking_poles",
    description: str = "Supports hikers on descents.",
    price: float = 65.0,
    tags=None,
    availability=AvailabilityStatus.IN_STOCK,
    attributes=None,
    specifications=None,
) -> Product:
    return Product(
        product_id=product_id,
        product_name=product_name,
        brand="TestBrand",
        category=category,
        subcategory=subcategory,
        description=description,
        price=price,
        currency="USD",
        tags=tags or [],
        attributes=attributes or {},
        specifications=specifications or {},
        availability=availability,
    )


def _index(products, tmp_path: Path, embedder=None) -> HybridCatalogIndex:
    return HybridCatalogIndex(
        products,
        model_name="test-concept-encoder",
        cache_dir=tmp_path,
        embedder=embedder or ConceptEncoder(),
    )


def test_searchable_document_handles_optional_and_nested_catalog_fields():
    product = _product(
        "pole-1",
        "Trek Poles",
        tags=["hiking"],
        attributes={"collapsible": True, "grip": {"type": "cork"}},
        specifications={"weight_kg": 0.4},
    )

    document = build_product_document(product)

    assert "Trek Poles" in document
    assert "cork" in document
    assert "true" in document
    assert "0.4" in document


def test_fastembed_onnx_encoder_normalizes_generator_output(monkeypatch):
    class FakeTextEmbedding:
        def __init__(self, model_name):
            assert model_name == "sentence-transformers/all-MiniLM-L6-v2"

        def embed(self, texts, batch_size):
            assert texts == ["product", "query"]
            assert batch_size == 8
            yield np.array([3.0, 4.0], dtype="float32")
            yield np.array([0.0, 2.0], dtype="float32")

    monkeypatch.setitem(
        sys.modules,
        "fastembed",
        SimpleNamespace(TextEmbedding=FakeTextEmbedding),
    )
    encoder = _FastEmbedEncoder("sentence-transformers/all-MiniLM-L6-v2")

    vectors = encoder.encode(["product", "query"], batch_size=8)

    assert vectors == pytest.approx(
        np.array([[0.6, 0.8], [0.0, 1.0]], dtype="float32")
    )


def test_exact_keyword_query_is_retrieved_by_bm25(tmp_path):
    adapter = _product(
        "adapter-1",
        "AdapterKind USB-C Travel Adapter",
        subcategory="travel_adapters",
        category="travel_accessories",
        tags=["adapterkind"],
    )
    index = _index([adapter], tmp_path)

    result = index.search("AdapterKind")

    assert result.bm25_ids == ["adapter-1"]
    assert result.product_ids[0] == "adapter-1"
    assert "bm25" in result.retrieval_sources["adapter-1"]


def test_semantic_vector_retrieval_finds_different_vocabulary(tmp_path):
    poles = _product(
        "poles-1",
        "Peak Trek Poles",
        description="Knee relief on descents for hikers.",
        tags=["trekking poles"],
    )
    unrelated = _product(
        "tent-1",
        "Camping Tent",
        subcategory="camping_tents",
        description="Shelter for overnight camping.",
        tags=["tent"],
    )
    index = _index([poles, unrelated], tmp_path)

    result = index.search("painful joints downhill slopes")

    assert "poles-1" not in result.bm25_ids
    assert result.semantic_ids[0] == "poles-1"
    assert result.product_ids[0] == "poles-1"
    assert result.retrieval_sources["poles-1"] == ["semantic"]


def test_catalog_grounded_knee_support_case_is_found_semantically(tmp_path):
    catalog_path = Path(__file__).resolve().parents[2] / "catalog" / "demo_products.json"
    catalog = load_and_validate_catalog(str(catalog_path))
    target = next(product for product in catalog if product.product_id == "prod_fit_004")
    index = _index([target], tmp_path)

    result = index.search(
        "I need support for painful joints while going down steep slopes."
    )

    assert result.semantic_ids == ["prod_fit_004"]
    assert "prod_fit_004" in result.product_ids


def test_bm25_only_candidate_is_preserved_when_vector_has_no_match(tmp_path):
    product = _product(
        "adapter-1",
        "AdapterKind USB-C Travel Adapter",
        category="travel_accessories",
        subcategory="travel_adapters",
        tags=["adapterkind"],
    )
    index = _index([product], tmp_path)

    result = index.search("AdapterKind")

    assert result.bm25_ids == ["adapter-1"]
    assert result.semantic_ids == []
    assert result.product_ids == ["adapter-1"]
    assert result.retrieval_mode == "bm25_only"


def test_embedding_backend_failure_is_logged_and_falls_back_to_bm25(tmp_path):
    class UnavailableEncoder:
        def encode(self, texts, **kwargs):
            raise ImportError("PyTorch import blocked by application policy")

    product = _product(
        "adapter-1",
        "AdapterKind USB-C Travel Adapter",
        category="travel_accessories",
        subcategory="travel_adapters",
        tags=["adapterkind"],
    )
    index = _index([product], tmp_path, UnavailableEncoder())

    result = index.search("AdapterKind")

    assert result.product_ids == ["adapter-1"]
    assert result.semantic_available is False
    assert result.retrieval_mode == "bm25_only"


def test_products_found_by_both_retrievers_have_both_provenance_sources(tmp_path):
    poles = _product(
        "poles-1",
        "Hiking Trekking Poles",
        description="Support for knee relief on descents.",
    )
    index = _index([poles], tmp_path)

    result = index.search("hiking trekking poles")

    assert result.bm25_ids == ["poles-1"]
    assert result.semantic_ids == ["poles-1"]
    assert result.retrieval_sources["poles-1"] == ["bm25", "semantic"]
    assert result.rrf_scores["poles-1"] == 100.0


def test_reciprocal_rank_fusion_merges_ranks_and_deduplicates_ids():
    ids, scores, sources = reciprocal_rank_fusion(
        [
            ("bm25", ["shared", "keyword-only", "shared"]),
            ("semantic", ["shared", "vector-only"]),
        ],
        k=60,
    )

    assert ids == ["shared", "keyword-only", "vector-only"]
    assert scores["shared"] == pytest.approx((1 / 61) + (1 / 61))
    assert sources["shared"] == ["bm25", "semantic"]
    assert sources["keyword-only"] == ["bm25"]
    assert sources["vector-only"] == ["semantic"]


def test_duplicate_product_ids_are_indexed_once_and_keep_original_mapping(tmp_path):
    original = _product("stable-id", "Original Product")
    duplicate = _product("stable-id", "Duplicate Product")
    index = _index([original, duplicate], tmp_path)

    assert index.product_ids == ["stable-id"]
    assert index.products_by_id["stable-id"].product_name == "Original Product"
    assert index.search("Original Product").product_ids[0] == "stable-id"


def test_index_persistence_reloads_without_reembedding_documents(tmp_path):
    product = _product(
        "poles-1",
        "Hiking Trekking Poles",
        description="Knee relief on descents for hikers.",
    )
    first_embedder = ConceptEncoder()
    first = _index([product], tmp_path, first_embedder)
    first.search("hiking poles")
    assert len(first_embedder.calls[0]) == 1

    second_embedder = ConceptEncoder()
    second = _index([product], tmp_path, second_embedder)
    result = second.search("hiking poles")

    assert result.product_ids[0] == "poles-1"
    assert len(second_embedder.calls) == 1
    assert second_embedder.calls[0] == ["hiking poles"]


def test_catalog_fingerprint_changes_when_product_document_changes(tmp_path):
    first = _product("poles-1", "Hiking Trekking Poles")
    changed = first.model_copy(update={"tags": ["knee support"]})

    first_index = _index([first], tmp_path)
    changed_index = _index([changed], tmp_path)

    assert first_index.fingerprint != changed_index.fingerprint


def test_empty_catalog_and_empty_query_return_no_results(tmp_path):
    empty_index = _index([], tmp_path)
    product_index = _index([_product("poles-1", "Hiking Poles")], tmp_path)

    assert empty_index.search("hiking").product_ids == []
    assert product_index.search(" ").product_ids == []


def test_hard_constraints_cover_category_budget_stock_and_exclusions():
    in_stock = _product(
        "pole-1",
        "Trekking Poles",
        category="fitness_outdoor",
        price=60,
        tags=["hiking"],
        availability=AvailabilityStatus.IN_STOCK,
        attributes={"waterproof": True},
    )
    intent = ExtractedIntent(
        category="fitness_outdoor",
        category_is_explicit=True,
        budget_min=50,
        budget_max=100,
        budget_currency="USD",
        hard_constraints={"availability": "in_stock", "waterproof": True},
        exclusions=["leather"],
    )

    assert evaluate_hard_constraints(in_stock, intent).is_eligible
    assert not evaluate_hard_constraints(
        in_stock, intent, excluded_product_ids=["pole-1"]
    ).is_eligible
    assert not evaluate_hard_constraints(
        in_stock.model_copy(update={"price": 120}), intent
    ).is_eligible
    assert not evaluate_hard_constraints(
        in_stock.model_copy(update={"availability": AvailabilityStatus.OUT_OF_STOCK}),
        intent,
    ).is_eligible
    assert not evaluate_hard_constraints(
        in_stock.model_copy(update={"category": "footwear"}), intent
    ).is_eligible
    assert not evaluate_hard_constraints(
        in_stock.model_copy(update={"tags": ["leather"]}), intent
    ).is_eligible


def test_unknown_mandatory_attributes_are_not_treated_as_matches():
    product = _product("item-1", "Outdoor Product")
    intent = ExtractedIntent(hard_constraints={"waterproof": True})

    result = evaluate_hard_constraints(product, intent)

    assert not result.is_eligible
    assert "waterproof" in result.unknown_attributes


def test_inferred_category_does_not_hard_filter_semantic_candidates(tmp_path, monkeypatch):
    poles = _product("poles-1", "Hiking Trekking Poles")
    shoe = _product(
        "shoe-1",
        "Trail Running Shoes",
        category="footwear",
        subcategory="trail_running",
        description="Footwear for hiking on trails.",
        tags=["hiking"],
    )
    index = _index([poles, shoe], tmp_path)
    monkeypatch.setattr(
        "app.agents.candidate_retrieval.get_hybrid_catalog_index",
        lambda products: index,
    )
    intent = ExtractedIntent(
        category="footwear",
        category_is_explicit=False,
        intended_use="hiking",
    )

    result = CandidateRetrievalAgent(catalog=[poles, shoe]).retrieve(
        intent,
        AttributeMappingResult(normalized_category="footwear"),
        query_text="support for downhill hiking",
    )

    assert "poles-1" in {product.product_id for product in result.candidates}


def test_hybrid_candidates_take_precedence_over_exact_name_match(monkeypatch):
    catalog = load_and_validate_catalog()
    exact_product = next(
        product for product in catalog if product.product_id == "prod_elec_004"
    )
    hybrid_product = next(
        product for product in catalog if product.product_id == "prod_elec_005"
    )

    class FakeHybridIndex:
        products_by_id = {
            exact_product.product_id: exact_product,
            hybrid_product.product_id: hybrid_product,
        }

        def search(self, query, allowed_product_ids):
            return SimpleNamespace(
                product_ids=[hybrid_product.product_id],
                rrf_scores={hybrid_product.product_id: 90.0},
                retrieval_sources={hybrid_product.product_id: ["bm25", "semantic"]},
                retrieval_mode="hybrid",
            )

    monkeypatch.setattr(
        "app.agents.candidate_retrieval.get_hybrid_catalog_index",
        lambda products: FakeHybridIndex(),
    )
    intent = ExtractedIntent(
        category="electronics",
        category_is_explicit=True,
        product_query=exact_product.product_name,
    )
    query = f"Tell me about {exact_product.product_name}"

    result = CandidateRetrievalAgent(catalog=catalog).retrieve(
        intent,
        AttributeMappingResult(normalized_category="electronics"),
        query_text=query,
    )

    assert [product.product_id for product in result.candidates] == [
        hybrid_product.product_id
    ]
    assert result.retrieval_mode == "hybrid"
    assert result.retrieval_sources[hybrid_product.product_id] == ["bm25", "semantic"]


def test_low_confidence_hybrid_results_use_exact_product_fallback(monkeypatch):
    catalog = load_and_validate_catalog()
    exact_product = next(
        product for product in catalog if product.product_id == "prod_elec_004"
    )
    hybrid_product = next(
        product for product in catalog if product.product_id == "prod_elec_005"
    )

    class FakeHybridIndex:
        products_by_id = {
            exact_product.product_id: exact_product,
            hybrid_product.product_id: hybrid_product,
        }

        def search(self, query, allowed_product_ids):
            return SimpleNamespace(
                product_ids=[hybrid_product.product_id],
                rrf_scores={hybrid_product.product_id: 30.0},
                retrieval_sources={hybrid_product.product_id: ["bm25"]},
                retrieval_mode="bm25_only",
            )

    monkeypatch.setattr(
        "app.agents.candidate_retrieval.get_hybrid_catalog_index",
        lambda products: FakeHybridIndex(),
    )
    intent = ExtractedIntent(
        category="electronics",
        category_is_explicit=True,
        product_query=exact_product.product_name,
    )
    query = f"Tell me about {exact_product.product_name}"

    result = CandidateRetrievalAgent(catalog=catalog).retrieve(
        intent,
        AttributeMappingResult(normalized_category="electronics"),
        query_text=query,
    )

    assert [product.product_id for product in result.candidates] == [
        exact_product.product_id
    ]
    assert result.retrieval_mode == "exact_fallback"
    assert result.retrieval_sources[exact_product.product_id] == ["exact_fallback"]


def test_incomplete_hybrid_comparison_falls_back_to_all_named_products(monkeypatch):
    catalog = load_and_validate_catalog()
    headphones = next(
        product for product in catalog if product.product_id == "prod_elec_004"
    )
    earbuds = next(
        product for product in catalog if product.product_id == "prod_elec_005"
    )

    class FakeHybridIndex:
        products_by_id = {
            headphones.product_id: headphones,
            earbuds.product_id: earbuds,
        }

        def search(self, query, allowed_product_ids):
            return SimpleNamespace(
                product_ids=[headphones.product_id],
                rrf_scores={headphones.product_id: 100.0},
                retrieval_sources={headphones.product_id: ["bm25", "semantic"]},
                retrieval_mode="hybrid",
            )

    monkeypatch.setattr(
        "app.agents.candidate_retrieval.get_hybrid_catalog_index",
        lambda products: FakeHybridIndex(),
    )
    intent = ExtractedIntent(
        category="electronics",
        subcategory="audio",
        category_is_explicit=True,
        subcategory_is_explicit=True,
        comparison_product_ids=[headphones.product_id, earbuds.product_id],
        purchase_intent="comparison",
    )

    result = CandidateRetrievalAgent(catalog=catalog).retrieve(
        intent,
        AttributeMappingResult(normalized_category="electronics"),
        query_text=f"Compare {headphones.product_name} and {earbuds.product_name}",
    )

    assert {
        product.product_id for product in result.candidates
    } == {headphones.product_id, earbuds.product_id}
    assert result.retrieval_mode == "exact_fallback"
