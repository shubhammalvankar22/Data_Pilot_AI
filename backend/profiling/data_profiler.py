# Imports
from __future__ import annotations

from typing import Any
import math
import pandas as pd


# Helper: safe value
def _safe_value(value: Any) -> Any:
    # Check condition
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    # Try, handle errors
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    # Check condition
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    # Check condition
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    # Check condition
    if isinstance(value, float) and not math.isfinite(value):
        return None
    # Check condition
    if isinstance(value, (str, int, float, bool)):
        return value
    # Return result
    return str(value)


# Helper: detected type
def _detected_type(series: pd.Series) -> str:
    # Check condition
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    # Check condition
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    # Check condition
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"

    # Set up values
    non_null = series.dropna()
    # Check condition
    if non_null.empty:
        return "unknown"

    # Test date parsing on a bounded sample to avoid expensive full-column inference.
    sample = non_null.astype("string").head(200)
    parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
    # Check condition
    if len(sample) and parsed.notna().mean() >= 0.85:
        return "datetime"

    # Set up values
    lowered = non_null.astype("string").str.strip().str.lower()
    # Check condition
    if lowered.isin(["true", "false", "yes", "no", "y", "n"]).mean() >= 0.9:
        return "boolean"

    # Set up values
    numeric = pd.to_numeric(non_null.head(200), errors="coerce")
    # Check condition
    if len(numeric) and numeric.notna().mean() >= 0.9:
        return "numeric"

    # Return result
    return "text"


# Create a compact, JSON-safe profile of a DataFrame
def profile_dataframe(df: pd.DataFrame, sample_size: int = 5) -> dict[str, Any]:
    """Create a compact, JSON-safe profile of a DataFrame."""
    total_rows = int(len(df))
    total_columns = int(len(df.columns))
    column_profiles: list[dict[str, Any]] = []

    # Loop over items
    for column in df.columns:
        series = df[column]
        missing = int(series.isna().sum())
        non_null = series.dropna()
        distinct = int(non_null.nunique(dropna=True))
        examples = [_safe_value(v) for v in non_null.head(sample_size).tolist()]

        item: dict[str, Any] = {
            "column": str(column),
            "detected_type": _detected_type(series),
            "row_count": total_rows,
            "missing_count": missing,
            "missing_percentage": round((missing / total_rows * 100), 2) if total_rows else 0.0,
            "non_missing_count": int(total_rows - missing),
            "distinct_count": distinct,
            "distinct_percentage_of_non_missing": round(
                (distinct / len(non_null) * 100), 2
            ) if len(non_null) else 0.0,
            "examples": examples,
        }

        if pd.api.types.is_numeric_dtype(series):
            numeric = pd.to_numeric(series, errors="coerce").dropna()
            if not numeric.empty:
                item["numeric_summary"] = {
                    "min": _safe_value(numeric.min()),
                    "max": _safe_value(numeric.max()),
                    "mean": _safe_value(numeric.mean()),
                    "zero_count": int((numeric == 0).sum()),
                    "negative_count": int((numeric < 0).sum()),
                }

        column_profiles.append(item)

    # Return result
    return {
        "row_count": total_rows,
        "column_count": total_columns,
        "duplicate_row_count": int(df.duplicated().sum()) if total_rows else 0,
        "total_missing_cells": int(df.isna().sum().sum()),
        "columns": column_profiles,
    }
