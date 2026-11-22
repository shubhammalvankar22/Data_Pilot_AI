# Imports
from __future__ import annotations
from typing import Any
import pandas as pd
from .question_classifier import classify_question
from .metrics import calculate_core_metrics
from .recommendations import generate_data_backed_recommendations

# Produce a safe, evidence-first analysis context; does not invent SQL or facts
def analyze_business_question(question: str, df: pd.DataFrame, schema: dict | None = None) -> dict[str, Any]:
    """Produce a safe, evidence-first analysis context; does not invent SQL or facts."""
    # Check condition
    if not isinstance(df, pd.DataFrame): raise TypeError("df must be a pandas DataFrame")
    # Set up values
    classification = classify_question(question)
    analysis = calculate_core_metrics(df, schema)
    recommendations = generate_data_backed_recommendations(analysis)
    # Return result
    return {
        "question": question,
        "classification": classification,
        "analysis": analysis,
        "evidence_backed_recommendations": recommendations,
        "guardrails": [
            "Use calculated metrics as the source of truth; never fabricate values.",
            "Do not claim causation from correlation or observational patterns.",
            "Do not estimate profit without cost data.",
            "Clarify gross versus net revenue when the user's wording is ambiguous.",
            "If required columns are absent, explain the limitation rather than guessing."
        ]
    }
