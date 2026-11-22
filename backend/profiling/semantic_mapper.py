# Imports
from __future__ import annotations

from typing import Any
import re
import pandas as pd

# Aliases are evidence, not absolute truth. Scores are combined with data-pattern checks.
ALIASES: dict[str, tuple[str, ...]] = {
    "customer_id": (
        "customer id", "customer_id", "customerid", "client id", "clientno",
        "client number", "cust id", "cust_id", "custcode", "customer number",
        "customer no", "buyer id", "account id",
    ),
    "product_id": (
        "product id", "product_id", "sku", "stock code", "stock_code",
        "item code", "itemnumber", "item number", "product code",
    ),
    "invoice_id": (
        "invoice", "invoice id", "invoice number", "invoice no",
        "order id", "order number", "transaction id", "receipt id",
    ),
    "date": (
        "date", "order date", "orderdate", "invoice date", "invoicedate",
        "created at", "createdat", "timestamp", "transaction date",
        "purchase date", "ship date",
    ),
    "quantity": (
        "quantity", "qty", "units", "units sold", "unitssold",
        "order quantity", "item quantity", "count",
    ),
    "unit_price": (
        "unit price", "unitprice", "price", "selling price", "sellingprice",
        "item price", "cost per unit", "rate",
    ),
    "revenue": (
        "revenue", "sales", "total sales", "total_sales", "sales amount",
        "salesamount", "total amount", "totalamount", "net revenue",
        "net_revenue", "amount", "turnover",
    ),
    "product": (
        "product", "product name", "item", "item name", "description",
        "product description", "stock description",
    ),
    "region": (
        "region", "country", "state", "province", "territory", "market",
        "sales region", "location",
    ),
    "employee_id": (
        "employee id", "employee_id", "employee number", "staff id",
        "worker id", "associate id",
    ),
    "department": (
        "department", "dept", "team", "business unit", "function",
    ),
    "email": ("email", "email address", "e-mail", "email_address"),
}

# Helper: normalize
def _normalize(value: str) -> str:
    # Return result
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


# Helper: alias score
def _alias_score(column: str, aliases: tuple[str, ...]) -> float:
    # Set up values
    normalized = _normalize(column)
    alias_norms = {_normalize(alias) for alias in aliases}
    # Check condition
    if normalized in alias_norms:
        return 0.98
    # Check condition
    if any(len(a) >= 5 and (normalized in a or a in normalized) for a in alias_norms):
        return 0.78
    # Return result
    return 0.0


# Helper: pattern bonus
def _pattern_bonus(semantic: str, series: pd.Series) -> float:
    # Set up values
    non_null = series.dropna()
    # Check condition
    if non_null.empty:
        return 0.0

    # Set up values
    sample = non_null.astype("string").str.strip().head(300)
    # Check condition
    if semantic == "date":
        parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
        return 0.12 if parsed.notna().mean() >= 0.85 else 0.0

    # Check condition
    if semantic in {"quantity", "unit_price", "revenue"}:
        numeric = pd.to_numeric(non_null.head(300), errors="coerce")
        return 0.10 if len(numeric) and numeric.notna().mean() >= 0.90 else 0.0

    # Check condition
    if semantic in {"customer_id", "product_id", "invoice_id", "employee_id"}:
        # Identifier-like columns often have many distinct values and are not mostly numeric measures.
        distinct_ratio = non_null.nunique(dropna=True) / max(len(non_null), 1)
        if distinct_ratio >= 0.05:
            return 0.04
    # Check condition
    if semantic == "email":
        return 0.15 if sample.str.contains(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", regex=True).mean() >= 0.7 else 0.0
    # Return result
    return 0.0


# Infer likely business meanings for columns
def infer_semantic_schema(df: pd.DataFrame) -> dict[str, Any]:
    """
    Infer likely business meanings for columns.
    Returns mappings with confidence and alternatives. Ambiguous mappings are not silently accepted.
    """
    candidates: dict[str, list[dict[str, Any]]] = {}

    # Loop over items
    for semantic, aliases in ALIASES.items():
        ranked = []
        for column in df.columns:
            name_score = _alias_score(str(column), aliases)
            # Value patterns should strengthen a plausible name match, not create
            # a semantic mapping from a numeric-looking column alone.
            pattern = _pattern_bonus(semantic, df[column]) if name_score > 0 else 0.0
            score = min(0.99, name_score + pattern)
            if score > 0:
                ranked.append({
                    "column": str(column),
                    "confidence": round(score, 2),
                    "evidence": [
                        evidence for evidence, present in (
                            ("column_name_match", name_score > 0),
                            ("value_pattern_match", pattern > 0),
                        ) if present
                    ],
                })
        ranked.sort(key=lambda x: x["confidence"], reverse=True)
        candidates[semantic] = ranked

    # Set up values
    mappings: dict[str, Any] = {}
    # Loop over items
    for semantic, ranked in candidates.items():
        if not ranked:
            mappings[semantic] = {
                "column": None,
                "confidence": 0.0,
                "status": "not_found",
                "alternatives": [],
            }
            continue

        best = ranked[0]
        second_score = ranked[1]["confidence"] if len(ranked) > 1 else 0.0
        ambiguous = second_score >= best["confidence"] - 0.05

        if best["confidence"] >= 0.90 and not ambiguous:
            status = "accepted"
        elif best["confidence"] >= 0.60 or ambiguous:
            status = "needs_confirmation"
        else:
            status = "low_confidence"

        mappings[semantic] = {
            "column": best["column"] if status == "accepted" else None,
            "suggested_column": best["column"],
            "confidence": best["confidence"],
            "status": status,
            "alternatives": ranked[:3],
        }

    # Revenue may be directly available or derivable from quantity × unit price.
    if mappings["revenue"]["status"] == "not_found":
        quantity = mappings["quantity"]
        unit_price = mappings["unit_price"]
        if quantity["status"] == "accepted" and unit_price["status"] == "accepted":
            mappings["revenue"] = {
                "column": None,
                "confidence": min(quantity["confidence"], unit_price["confidence"]),
                "status": "derivable",
                "formula": f"{quantity['column']} * {unit_price['column']}",
                "alternatives": [],
            }

    # Return result
    return {
        "mappings": mappings,
        "needs_review": [
            semantic for semantic, value in mappings.items()
            if value["status"] in {"needs_confirmation", "low_confidence"}
        ],
        "unmapped": [
            semantic for semantic, value in mappings.items()
            if value["status"] == "not_found"
        ],
        "policy": {
            "auto_accept_threshold": 0.90,
            "confirmation_threshold": 0.60,
            "note": "Uncertain mappings are suggestions, not confirmed facts.",
        },
    }
