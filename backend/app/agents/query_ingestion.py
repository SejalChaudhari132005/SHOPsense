"""
Agent 1: Query Ingestion Agent
Normalizes user input, preserves numerical qualifiers and negations, handles voice text,
sanitizes input, and gracefully rejects empty/malformed requests.
"""

import re
from typing import Optional, Dict, Any
from app.models.state import IngestedQuery


class QueryIngestionAgent:
    """
    Ingests and normalizes incoming client queries while protecting vital query tokens.
    """

    def ingest(
        self,
        session_id: str,
        raw_message: str,
        turn_id: int = 1,
        input_source: str = "text",
        client_context: Optional[Dict[str, Any]] = None
    ) -> IngestedQuery:
        context = client_context or {}

        # 1. Validation for empty or whitespace-only queries
        if not raw_message or not raw_message.strip():
            return IngestedQuery(
                session_id=session_id,
                turn_id=turn_id,
                raw_message=raw_message or "",
                sanitized_message="",
                input_source=input_source,
                client_context=context,
                is_empty=True,
                rejection_reason="Query is empty. Please describe what you are looking for."
            )

        # 2. Basic sanitization: strip dangerous control characters while preserving unicode symbols (₹, €, £, $)
        sanitized = raw_message.strip()
        # Remove consecutive whitespaces, tabs, or newlines
        sanitized = re.sub(r"[\r\n\t]+", " ", sanitized)
        sanitized = re.sub(r"\s{2,}", " ", sanitized)

        # 3. Preserve critical punctuation (e.g. ₹8,000, $1,500, 16.5h, 14", 10.5)
        # Protect currency comma-groupings like 8,000 from being split
        # Clean stray quotes that aren't measurement marks (e.g. 14")
        sanitized = re.sub(r"[^\w\s\$\₹\€\£\.\,\-\"\']+", " ", sanitized)
        sanitized = re.sub(r"\s{2,}", " ", sanitized).strip()

        # Check if query became empty after strip
        if len(sanitized) < 2:
            return IngestedQuery(
                session_id=session_id,
                turn_id=turn_id,
                raw_message=raw_message,
                sanitized_message=sanitized,
                input_source=input_source,
                client_context=context,
                is_empty=True,
                rejection_reason="Query contains insufficient recognizable search characters."
            )

        return IngestedQuery(
            session_id=session_id,
            turn_id=turn_id,
            raw_message=raw_message,
            sanitized_message=sanitized,
            input_source=input_source,
            client_context=context,
            is_empty=False
        )
