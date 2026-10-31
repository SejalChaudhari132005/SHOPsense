"""Cached BM25, dense-vector, and RRF retrieval over the local product catalog."""

import hashlib
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from app.core.config import settings
from app.models.product import Product
from app.services.catalog_service import match_synonyms

logger = logging.getLogger(__name__)

try:
    import faiss
except ImportError:
    faiss = None

try:
    import numpy as np
except ImportError:
    np = None

try:
    from rank_bm25 import BM25Okapi
except ImportError:
    BM25Okapi = None

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_MODEL_LOCK = threading.Lock()
_SHARED_MODEL = None
_MODEL_LOAD_ERROR: Optional[Exception] = None
_EMBEDDING_BACKEND = "fastembed-onnx"
_INDEX_LOCK = threading.RLock()
_CACHED_INDEX: Optional["HybridCatalogIndex"] = None
_CACHED_INDEX_FINGERPRINT: Optional[str] = None


def _flatten_value(value: object) -> List[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        flattened: List[str] = []
        for key in sorted(value, key=lambda item: str(item).casefold()):
            flattened.append(str(key))
            flattened.extend(_flatten_value(value[key]))
        return flattened
    if isinstance(value, (list, tuple, set)):
        flattened = []
        for item in value:
            flattened.extend(_flatten_value(item))
        return flattened
    if isinstance(value, bool):
        return ["true" if value else "false"]
    return [str(value)]


def build_product_document(product: Product) -> str:
    """Build a safe text document from fields supported by the product schema."""
    fields = (
        "product_name",
        "brand",
        "category",
        "subcategory",
        "description",
        "features",
        "specifications",
        "use_cases",
        "good_for",
        "review_snippets",
        "tags",
        "attributes",
    )
    values: List[str] = []
    for field in fields:
        value = getattr(product, field, None)
        values.extend(_flatten_value(value))
    return " ".join(values)


def tokenize(text: str) -> List[str]:
    return _TOKEN_PATTERN.findall(text.casefold())


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Tuple[str, Sequence[str]]],
    k: int = 60,
) -> Tuple[List[str], Dict[str, float], Dict[str, List[str]]]:
    """Fuse named ranked lists while retaining product-ID provenance."""
    scores: Dict[str, float] = {}
    sources: Dict[str, List[str]] = {}
    for source, ranked_ids in ranked_lists:
        seen: Set[str] = set()
        for rank, product_id in enumerate(ranked_ids, start=1):
            if product_id in seen:
                continue
            seen.add(product_id)
            scores[product_id] = scores.get(product_id, 0.0) + 1.0 / (k + rank)
            sources.setdefault(product_id, []).append(source)
    ordered_ids = sorted(scores, key=lambda product_id: (-scores[product_id], product_id))
    return ordered_ids, scores, sources


@dataclass(frozen=True)
class HybridSearchResult:
    bm25_ids: List[str]
    semantic_ids: List[str]
    product_ids: List[str]
    rrf_scores: Dict[str, float]
    retrieval_sources: Dict[str, List[str]]
    semantic_available: bool
    retrieval_mode: str
    latency_ms: Dict[str, float]
    semantic_scores: Dict[str, float] = field(default_factory=dict)
    bm25_coverage: Dict[str, float] = field(default_factory=dict)


def cosine_to_relevance(
    cosine: float,
    floor: Optional[float] = None,
    ceil: Optional[float] = None,
) -> float:
    low = settings.HYBRID_COSINE_FLOOR if floor is None else floor
    high = settings.HYBRID_COSINE_CEIL if ceil is None else ceil
    if high <= low:
        return 1.0 if cosine >= high else 0.0
    return max(0.0, min(1.0, (cosine - low) / (high - low)))


def _catalog_fingerprint(products: Sequence[Product], model_name: str) -> str:
    serialized = json.dumps(
        {
            "backend": _EMBEDDING_BACKEND,
            "model": model_name,
            "products": [
                product.model_dump(mode="json")
                for product in sorted(products, key=lambda item: item.product_id)
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class _FastEmbedEncoder:
    """Adapt FastEmbed's ONNX Runtime API to the index's encode interface."""

    def __init__(self, model_name: str):
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model_name)

    def encode(
        self,
        texts: Sequence[str],
        batch_size: int = 32,
        convert_to_numpy: bool = True,
        normalize_embeddings: bool = True,
        show_progress_bar: bool = False,
    ):
        if np is None:
            raise ImportError("numpy is required for ONNX embedding retrieval")
        embeddings = list(self._model.embed(list(texts), batch_size=batch_size))
        vectors = np.asarray(embeddings, dtype="float32")
        if normalize_embeddings and vectors.size:
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            np.divide(vectors, norms, out=vectors, where=norms > 0)
        return vectors


def _load_embedding_model(model_name: str):
    global _SHARED_MODEL, _MODEL_LOAD_ERROR
    with _MODEL_LOCK:
        if _SHARED_MODEL is None:
            if _MODEL_LOAD_ERROR is not None:
                raise RuntimeError(
                    f"ONNX embedding model is unavailable: {_MODEL_LOAD_ERROR}"
                ) from _MODEL_LOAD_ERROR
            try:
                _SHARED_MODEL = _FastEmbedEncoder(model_name)
            except Exception as exc:
                _MODEL_LOAD_ERROR = exc
                raise
        return _SHARED_MODEL


def _normalized_vectors(embeddings, expected_rows: int):
    vectors = np.asarray(embeddings, dtype="float32")
    if (
        vectors.ndim != 2
        or vectors.shape[0] != expected_rows
        or not np.isfinite(vectors).all()
    ):
        raise ValueError("Embedding model returned an invalid vector matrix")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    np.divide(vectors, norms, out=vectors, where=norms > 0)
    return vectors


class HybridCatalogIndex:
    """One catalog snapshot with a cached BM25 index and persisted FAISS vectors."""

    def __init__(
        self,
        products: Sequence[Product],
        model_name: Optional[str] = None,
        cache_dir: Optional[Path] = None,
        embedder=None,
        rrf_k: Optional[int] = None,
    ):
        self.model_name = model_name or settings.HYBRID_EMBEDDING_MODEL
        self.rrf_k = rrf_k if rrf_k is not None else settings.HYBRID_RRF_K
        self.cache_dir = Path(cache_dir or settings.HYBRID_INDEX_CACHE_DIR)
        products_by_id: Dict[str, Product] = {}
        for product in products:
            products_by_id.setdefault(product.product_id, product)
        self.products_by_id = dict(sorted(products_by_id.items()))
        self.product_ids = list(self.products_by_id)
        self.documents = {
            product_id: build_product_document(product)
            for product_id, product in self.products_by_id.items()
        }
        self.fingerprint = _catalog_fingerprint(
            list(self.products_by_id.values()), self.model_name
        )
        self._embedder = embedder
        self._vector_index = None
        self._semantic_error: Optional[str] = None
        self._vector_lock = threading.Lock()
        self._bm25 = None
        self._bm25_tokens: Dict[str, List[str]] = {}
        self._last_semantic_scores: Dict[str, float] = {}
        self._build_bm25()

    def _build_bm25(self) -> None:
        if not self.product_ids:
            return
        self._bm25_tokens = {
            product_id: tokenize(document)
            for product_id, document in self.documents.items()
        }
        if BM25Okapi is not None:
            self._bm25 = BM25Okapi(
                [self._bm25_tokens[product_id] for product_id in self.product_ids]
            )
        else:
            logger.error("rank-bm25 is unavailable; using term-count fallback for local retrieval.")

    def _index_files(self) -> Tuple[Path, Path]:
        directory = self.cache_dir / self.fingerprint
        return directory / "products.faiss", directory / "metadata.json"

    def _read_persisted_vector_index(self):
        if faiss is None:
            raise ImportError("faiss-cpu is not installed")
        index_path, metadata_path = self._index_files()
        if not index_path.is_file() or not metadata_path.is_file():
            return None
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if (
            metadata.get("fingerprint") != self.fingerprint
            or metadata.get("backend") != _EMBEDDING_BACKEND
            or metadata.get("model_name") != self.model_name
            or metadata.get("product_ids") != self.product_ids
        ):
            return None
        index = faiss.read_index(str(index_path))
        if index.ntotal != len(self.product_ids):
            return None
        return index

    def _persist_vector_index(self, index) -> None:
        if faiss is None:
            return
        index_path, metadata_path = self._index_files()
        index_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_index = index_path.with_suffix(".faiss.tmp")
        temporary_metadata = metadata_path.with_suffix(".json.tmp")
        faiss.write_index(index, str(temporary_index))
        temporary_metadata.write_text(
            json.dumps(
                {
                    "backend": _EMBEDDING_BACKEND,
                    "fingerprint": self.fingerprint,
                    "model_name": self.model_name,
                    "product_ids": self.product_ids,
                },
                ensure_ascii=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        os.replace(temporary_index, index_path)
        os.replace(temporary_metadata, metadata_path)

    def _ensure_vector_index(self):
        with self._vector_lock:
            return self._ensure_vector_index_locked()

    def _ensure_vector_index_locked(self):
        if self._vector_index is not None:
            return self._vector_index
        if self._semantic_error:
            return None
        if not self.product_ids:
            return None
        if faiss is None or np is None:
            self._semantic_error = "faiss-cpu and numpy are required for vector retrieval"
            logger.error("Semantic retrieval is unavailable: %s", self._semantic_error)
            return None

        try:
            index = self._read_persisted_vector_index()
            if index is None:
                embedder = self._embedder or _load_embedding_model(self.model_name)
                embeddings = embedder.encode(
                    [self.documents[product_id] for product_id in self.product_ids],
                    batch_size=32,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
                vectors = _normalized_vectors(embeddings, len(self.product_ids))
                index = faiss.IndexFlatIP(vectors.shape[1])
                index.add(vectors)
                try:
                    self._persist_vector_index(index)
                except (OSError, RuntimeError):
                    logger.exception("Could not persist the hybrid vector index; keeping it in memory.")
            self._vector_index = index
            return index
        except Exception as exc:
            self._semantic_error = str(exc)
            if _MODEL_LOAD_ERROR is not None and not self._embedder:
                logger.error(
                    "Semantic index initialization failed; continuing with keyword retrieval: %s",
                    exc,
                )
            else:
                logger.exception(
                    "Semantic index initialization failed; continuing with keyword retrieval."
                )
            return None

    def _expanded_bm25_query(self, query: str) -> List[str]:
        primary_tokens = tokenize(query)
        expanded_terms = list(primary_tokens)
        for term in primary_tokens:
            expanded_terms.extend(tokenize(" ".join(match_synonyms(term))))
        return list(dict.fromkeys(expanded_terms))

    def _bm25_coverage(
        self, query_tokens: Sequence[str], product_id: str
    ) -> float:
        original = [token for token in query_tokens if len(token) > 2]
        if not original:
            return 0.0
        product_tokens = set(self._bm25_tokens.get(product_id, []))
        return sum(token in product_tokens for token in original) / len(original)

    def _rank_bm25(self, query: str, allowed_ids: Set[str], limit: int) -> List[str]:
        query_tokens = self._expanded_bm25_query(query)
        if not query_tokens:
            return []
        if self._bm25 is not None:
            scores = self._bm25.get_scores(query_tokens)
            ranked = sorted(
                (
                    (self.product_ids[position], float(score))
                    for position, score in enumerate(scores)
                    if self.product_ids[position] in allowed_ids and score > 0.0
                ),
                key=lambda item: (-item[1], item[0]),
            )
            if ranked:
                return [product_id for product_id, _ in ranked[:limit]]

        # BM25 can assign zero/negative scores to every result in tiny corpora.
        term_counts = {
            product_id: sum(
                1 for token in query_tokens if token in self._bm25_tokens.get(product_id, [])
            )
            for product_id in allowed_ids
        }
        ranked = sorted(
            ((product_id, count) for product_id, count in term_counts.items() if count > 0),
            key=lambda item: (-item[1], item[0]),
        )
        return [product_id for product_id, _ in ranked[:limit]]

    def _rank_semantic(
        self,
        query: str,
        allowed_ids: Set[str],
        limit: int,
    ) -> Optional[List[str]]:
        index = self._ensure_vector_index()
        if index is None:
            self._last_semantic_scores = {}
            return None
        try:
            embedder = self._embedder or _load_embedding_model(self.model_name)
            embedding = embedder.encode(
                [query],
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            query_vector = _normalized_vectors(embedding, 1)
            if query_vector.shape[1] != index.d:
                raise ValueError("Query embedding dimension does not match the catalog index")
            similarities, positions = index.search(query_vector, index.ntotal)
            ranked_ids = []
            self._last_semantic_scores = {}
            seen: Set[str] = set()
            for similarity, position in zip(similarities[0], positions[0]):
                if position < 0:
                    continue
                if float(similarity) < settings.HYBRID_MIN_COSINE_SIMILARITY:
                    continue
                product_id = self.product_ids[int(position)]
                if product_id in allowed_ids and product_id not in seen:
                    seen.add(product_id)
                    self._last_semantic_scores[product_id] = float(similarity)
                    ranked_ids.append(product_id)
                    if len(ranked_ids) >= limit:
                        break
            return ranked_ids
        except Exception as exc:
            self._semantic_error = str(exc)
            logger.exception(
                "Semantic query encoding failed; continuing with keyword retrieval."
            )
            return None

    def search(
        self,
        query: str,
        allowed_product_ids: Optional[Iterable[str]] = None,
        limit: Optional[int] = None,
    ) -> HybridSearchResult:
        if not query.strip() or not self.product_ids:
            return HybridSearchResult([], [], [], {}, {}, False, "empty", {})

        allowed_ids = set(
            self.product_ids if allowed_product_ids is None else allowed_product_ids
        )
        allowed_ids.intersection_update(self.product_ids)
        if not allowed_ids:
            return HybridSearchResult(
                [], [], [], {}, {}, False, "no_eligible_products", {}
            )

        result_limit = limit if limit is not None else settings.HYBRID_RETRIEVAL_LIMIT
        started = time.perf_counter()
        bm25_ids = self._rank_bm25(query, allowed_ids, result_limit)
        original_tokens = tokenize(query)
        bm25_coverage = {
            product_id: self._bm25_coverage(original_tokens, product_id)
            for product_id in allowed_ids
        }
        bm25_latency = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        semantic_ids = self._rank_semantic(query, allowed_ids, result_limit)
        semantic_scores = getattr(self, "_last_semantic_scores", {})
        semantic_latency = (time.perf_counter() - started) * 1000
        ranked_lists: List[Tuple[str, Sequence[str]]] = []
        if bm25_ids:
            ranked_lists.append(("bm25", bm25_ids))
        if semantic_ids:
            ranked_lists.append(("semantic", semantic_ids))

        started = time.perf_counter()
        product_ids, scores, sources = reciprocal_rank_fusion(
            ranked_lists,
            k=self.rrf_k,
        )
        fusion_latency = (time.perf_counter() - started) * 1000
        max_score = len(ranked_lists) / (self.rrf_k + 1) if ranked_lists else 1.0
        normalized_scores = {
            product_id: min(100.0, round(score / max_score * 100.0, 2))
            for product_id, score in scores.items()
        }
        mode = (
            "hybrid"
            if len(ranked_lists) == 2
            else "semantic_only"
            if semantic_ids
            else "bm25_only"
            if bm25_ids
            else "no_matches"
        )
        return HybridSearchResult(
            bm25_ids=bm25_ids,
            semantic_ids=semantic_ids or [],
            product_ids=product_ids,
            rrf_scores=normalized_scores,
            retrieval_sources=sources,
            semantic_available=semantic_ids is not None,
            retrieval_mode=mode,
            latency_ms={
                "bm25": round(bm25_latency, 3),
                "semantic": round(semantic_latency, 3),
                "hybrid_rrf": round(bm25_latency + semantic_latency + fusion_latency, 3),
            },
            semantic_scores=semantic_scores,
            bm25_coverage=bm25_coverage,
        )


def get_hybrid_catalog_index(
    products: Sequence[Product],
    model_name: Optional[str] = None,
    cache_dir: Optional[Path] = None,
) -> HybridCatalogIndex:
    """Reuse the current catalog index and rebuild it when catalog/model content changes."""
    global _CACHED_INDEX, _CACHED_INDEX_FINGERPRINT
    effective_model = model_name or settings.HYBRID_EMBEDDING_MODEL
    fingerprint = _catalog_fingerprint(products, effective_model)
    with _INDEX_LOCK:
        if _CACHED_INDEX is None or _CACHED_INDEX_FINGERPRINT != fingerprint:
            _CACHED_INDEX = HybridCatalogIndex(
                products,
                model_name=effective_model,
                cache_dir=cache_dir,
            )
            _CACHED_INDEX_FINGERPRINT = fingerprint
        return _CACHED_INDEX
