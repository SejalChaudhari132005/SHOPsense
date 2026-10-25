"""
Agent 4: Catalog Attribute Mapping Agent
Translates colloquial user language, implicit needs, and synonyms into normalized
catalog attributes and filter keys without inventing unsubstantiated specs.
"""

from typing import Dict, Any, List
from app.models.state import ExtractedIntent, AttributeMappingResult
from app.services.catalog_service import (
    canonicalize_category,
    normalize_attribute_values,
    FEATURE_SYNONYMS
)


class CatalogAttributeMappingAgent:
    """
    Normalizes everyday conversational terms into canonical catalog filters.
    """

    # Colloquial use-case & attribute mapping table
    COLLOQUIAL_MAP: Dict[str, Dict[str, Any]] = {
        "good for long walks": {
            "type": "use_case",
            "target": "walking",
            "explanation": "Mapped 'good for long walks' to walking use-case."
        },
        "not too expensive": {
            "type": "budget_preference",
            "target": "budget",
            "explanation": "Interpreted 'not too expensive' as preference for economy/value without inventing arbitrary hard cap."
        },
        "lightweight": {
            "type": "spec_filter",
            "target": "weight_kg",
            "operator": "<=",
            "max_weight": 1.5,
            "explanation": "Mapped 'lightweight' to weight <= 1.5kg where documented."
        },
        "waterproof": {
            "type": "attribute_match",
            "target": "waterproof",
            "value": True,
            "explanation": "Mapped 'waterproof' to strict waterproof membrane requirement."
        },
        "water-resistant": {
            "type": "attribute_match",
            "target": "water_resistant",
            "value": True,
            "explanation": "Treated 'water-resistant' as surface repellent DWR, distinct from full submersible waterproof."
        },
        "long battery": {
            "type": "spec_filter",
            "target": "battery_hours",
            "operator": ">=",
            "min_hours": 12.0,
            "explanation": "Mapped 'long battery' to battery_hours >= 12."
        },
        "noise cancelling": {
            "type": "attribute_match",
            "target": "noise_cancellation",
            "value": True,
            "explanation": "Mapped 'noise cancelling' to active noise cancellation (ANC)."
        }
    }

    def map_attributes(self, intent: ExtractedIntent) -> AttributeMappingResult:
        mapped_attrs: Dict[str, Any] = {}
        mapped_use_cases: List[str] = []
        applied_synonyms: Dict[str, str] = {}
        explanations: List[str] = []

        # 1. Canonicalize Category
        norm_cat = None
        if intent.category:
            norm_cat = canonicalize_category(intent.category)
            if norm_cat != intent.category:
                applied_synonyms[intent.category] = norm_cat
                explanations.append(f"Mapped category '{intent.category}' to canonical '{norm_cat}'.")

        # 2. Map Intended Use
        if intent.intended_use:
            clean_use = intent.intended_use.lower()
            mapped_use_cases.append(clean_use)
            explanations.append(f"Retained intended use: {clean_use}.")

        # 3. Map Soft Preferences & Features
        for pref in intent.soft_preferences:
            clean_pref = pref.lower().strip()
            if clean_pref in self.COLLOQUIAL_MAP:
                mapping = self.COLLOQUIAL_MAP[clean_pref]
                if mapping["type"] == "attribute_match":
                    mapped_attrs[mapping["target"]] = mapping["value"]
                elif mapping["type"] == "spec_filter":
                    mapped_attrs[mapping["target"]] = {
                        "operator": mapping["operator"],
                        "value": mapping.get("max_weight") or mapping.get("min_hours")
                    }
                elif mapping["type"] == "use_case":
                    mapped_use_cases.append(mapping["target"])
                explanations.append(mapping["explanation"])
            else:
                # Generic preference check
                mapped_attrs[clean_pref] = True
                explanations.append(f"Recorded preference '{clean_pref}'.")

        # 4. Map Hard Constraints
        for hk, hv in intent.hard_constraints.items():
            mapped_attrs[hk] = hv
            explanations.append(f"Enforced hard constraint '{hk}' = {hv}.")

        # 5. Normalize Physical Attributes
        if intent.size:
            norm_size = normalize_attribute_values("size", intent.size)
            mapped_attrs["size"] = norm_size
            explanations.append(f"Normalized size '{intent.size}' to '{norm_size}'.")

        if intent.colour:
            norm_colour = normalize_attribute_values("colour", intent.colour)
            mapped_attrs["colour"] = norm_colour
            explanations.append(f"Normalized color '{intent.colour}' to '{norm_colour}'.")

        return AttributeMappingResult(
            normalized_category=norm_cat,
            mapped_attributes=mapped_attrs,
            mapped_use_cases=list(dict.fromkeys(mapped_use_cases)),
            applied_synonyms=applied_synonyms,
            explanations=explanations
        )
