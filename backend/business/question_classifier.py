# Imports
from __future__ import annotations
import re

# Function: classify question
def classify_question(question: str) -> dict:
    # Set up values
    q = question.lower()
    categories = {
        "recommendation": ["recommend", "improve", "should we", "how can", "opportunity", "action", "increase", "reduce", "strategy"],
        "ranking": ["top", "bottom", "highest", "lowest", "rank", "best", "worst"],
        "trend": ["trend", "over time", "monthly", "weekly", "daily", "growth", "decline"],
        "comparison": ["compare", "versus", " vs ", "difference", "compared with", "year over year", "month over month"],
        "customer": ["customer", "client", "retention", "churn", "repeat purchase", "rfm", "cohort"],
        "product": ["product", "sku", "stock code", "category", "basket", "cross-sell", "cross sell"],
        "forecast": ["forecast", "predict", "next month", "future", "expected"],
        "anomaly": ["anomaly", "unusual", "outlier", "unexpected", "spike"],
        "aggregation": ["total", "average", "count", "sum", "how many", "percentage", "share", "revenue", "sales", "profit"],
    }
    matched = [name for name, terms in categories.items() if any(t in q for t in terms)]
    # Return result
    return {"primary_intent": matched[0] if matched else "exploration", "intents": matched or ["exploration"], "is_compound": len(matched) > 1 or bool(re.search(r"\b(and|also|along with|plus)\b", q)), "requires_clarification": any(x in q for x in ["better", "best", "successful", "performance"]) and not any(x in q for x in ["revenue", "sales", "profit", "quantity", "customer", "orders"])}
