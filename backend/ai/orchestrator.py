"""Dynamic, safety-bounded tool orchestration for the AI Analyst.

The orchestrator selects registered tools from the user's question. It never
executes model-written Python or arbitrary SQL. DuckDB is optional; when it is
not installed, the SQL step is marked unavailable and safe pandas tools remain.
"""
# Imports
from __future__ import annotations

import re
import time
from typing import Any

import pandas as pd

# Module-level setup
try:
    import duckdb  # Optional dependency
except ImportError:  # pragma: no cover - environment dependent
    duckdb = None


# Helper: norm
def _norm(value: Any) -> str:
    # Return result
    return re.sub(r"\s+", " ", str(value).strip().lower().replace("_", " ").replace("-", " "))


# Helper: find column
def _find_column(df: pd.DataFrame, exact: tuple[str, ...], terms: tuple[str, ...] = ()):
    # Set up values
    normalized = {_norm(c): c for c in df.columns}
    # Loop over items
    for name in exact:
        if name in normalized:
            return normalized[name]
    # Loop over items
    for column in df.columns:
        name = _norm(column)
        if any(term in name for term in terms):
            return column
    # Return result
    return None


# Helper: columns
def _columns(df: pd.DataFrame) -> dict[str, Any]:
    # Return result
    return {
        "quantity": _find_column(df, ("quantity", "qty"), ("quantity", "qty")),
        "price": _find_column(df, ("price", "unit price", "unitprice"), ("unit price", "unitprice", "selling price", "item price", "price")),
        "revenue": _find_column(df, ("sales", "revenue", "total sales", "total revenue", "line total"), ("sales", "revenue", "turnover", "line total", "total amount")),
        "date": _find_column(df, ("invoice date", "order date", "transaction date", "date"), ("invoice date", "order date", "transaction date", "date")),
        "invoice": _find_column(df, ("invoice", "invoice number", "invoice no", "order id", "order number"), ("invoice", "order id", "order number")),
        "customer": _find_column(df, ("customer id", "client id", "account id", "customer"), ("customer id", "client id", "account id")),
        "product": _find_column(df, ("description", "product name", "product", "item name", "item"), ("description", "product name", "product", "item name")),
        "country": _find_column(df, ("country",), ("country", "market", "region")),
    }


# Helper: metric
def _metric(df: pd.DataFrame, cols: dict[str, Any]) -> pd.Series | None:
    # Check condition
    if cols["revenue"] is not None:
        return pd.to_numeric(df[cols["revenue"]], errors="coerce")
    # Check condition
    if cols["quantity"] is not None and cols["price"] is not None:
        return (pd.to_numeric(df[cols["quantity"]], errors="coerce") *
                pd.to_numeric(df[cols["price"]], errors="coerce"))
    # Return result
    return None


# Compile a small, validated natural-language subset into a safe query plan
def _structured_group_plan(question: str, df: pd.DataFrame) -> dict[str, Any] | None:
    """Compile a small, validated natural-language subset into a safe query plan.

    This is deliberately rule-based: no model-authored SQL or Python is executed.
    Supported now: one business grouping, SUM of the detected sales metric, and
    one numeric HAVING threshold (>, >=, <, <=).
    """
    q = _norm(question)
    cols = _columns(df)
    metric = _metric(df, cols)
    # Check condition
    if metric is None:
        return None

    # Set up values
    group_key = None
    # Loop over items
    for key, terms in (
        ("customer", ("customer", "customers", "client")),
        ("product", ("product", "products", "item", "stock code")),
        ("country", ("country", "countries", "region", "market")),
    ):
        if cols.get(key) is not None and any(term in q for term in terms):
            group_key = key
            break
    # Check condition
    if group_key is None:
        return None

    # Set up values
    threshold_match = re.search(
        r"\b(more than|greater than|above|over|at least|greater than or equal to|less than|below|under|at most|less than or equal to)\s*(?:₹|rs\.?\s*)?([0-9][0-9,]*(?:\.\d+)?)",
        q,
        flags=re.IGNORECASE,
    )
    # Check condition
    if not threshold_match:
        return None

    # Set up values
    operator_text = threshold_match.group(1).lower()
    threshold = float(threshold_match.group(2).replace(",", ""))
    # Check condition
    if operator_text in ("more than", "greater than", "above", "over"):
        operator = ">"
    elif operator_text in ("at least", "greater than or equal to"):
        operator = ">="
    elif operator_text in ("less than", "below", "under"):
        operator = "<"
    else:
        operator = "<="

    # Set up values
    group_col = cols[group_key]
    # Return result
    return {
        "operation": "group_aggregate_filter",
        "group_by": str(group_col),
        "group_role": group_key,
        "aggregate": "sum",
        "metric": "detected_sales_metric",
        "metric_formula": (
            str(cols["revenue"]) if cols["revenue"] is not None
            else f"{cols['quantity']} × {cols['price']}"
        ),
        "having": {"field": "aggregate_value", "operator": operator, "value": threshold},
        "order_by": {"field": "aggregate_value", "direction": "desc"},
        "limit": 500,
        "null_group_values": "excluded",
    }


# Execute only the allow-listed plan produced by _structured_group_plan
def _execute_structured_group_plan(df: pd.DataFrame, plan: dict[str, Any]) -> dict[str, Any]:
    """Execute only the allow-listed plan produced by _structured_group_plan."""
    allowed_ops = {">", ">=", "<", "<="}
    # Check condition
    if plan.get("operation") != "group_aggregate_filter":
        raise ValueError("Unsupported structured query operation.")
    # Set up values
    group_col = plan.get("group_by")
    # Check condition
    if group_col not in df.columns:
        raise ValueError("The requested grouping column is not available.")
    # Set up values
    having = plan.get("having") or {}
    operator = having.get("operator")
    # Check condition
    if operator not in allowed_ops:
        raise ValueError("Unsupported threshold operator.")
    # Set up values
    threshold = float(having.get("value"))
    cols = _columns(df)
    metric = _metric(df, cols)
    # Check condition
    if metric is None:
        raise ValueError("No numeric sales/revenue metric is available.")

    # Set up values
    work = pd.DataFrame({"group_name": df[group_col], "metric": metric}).dropna()
    grouped = work.groupby("group_name", dropna=True)["metric"].sum(min_count=1).dropna()
    # Check condition
    if operator == ">":
        matched = grouped[grouped > threshold]
    elif operator == ">=":
        matched = grouped[grouped >= threshold]
    elif operator == "<":
        matched = grouped[grouped < threshold]
    else:
        matched = grouped[grouped <= threshold]
    # Set up values
    matched = matched.sort_values(ascending=False)
    total_matches = int(len(matched))
    limit = min(max(int(plan.get("limit", 500)), 1), 500)
    rows = [
        {"group_name": str(name), "aggregate_value": round(float(value), 6)}
        for name, value in matched.head(limit).items()
    ]
    # Return result
    return {
        "plan": plan,
        "rows": rows,
        "matched_groups": total_matches,
        "returned_groups": len(rows),
        "truncated": total_matches > len(rows),
        "threshold_applied_after_aggregation": True,
        "source_rows_used": int(len(work)),
        "metric_formula": plan["metric_formula"],
    }


# Choose tools dynamically using question intent and available columns
def select_tools(question: str, df: pd.DataFrame) -> list[dict[str, str]]:
    """Choose tools dynamically using question intent and available columns."""
    q = question.lower()
    cols = _columns(df)
    selected = [{"name": "python_profile", "reason": "Profile the loaded DataFrame and identify usable fields."}]

    structured_plan = _structured_group_plan(question, df)
    # Check condition
    if structured_plan is not None:
        selected.append({"name": "validated_structured_query", "reason": "Compile a supported grouped threshold question into an allow-listed plan."})

    # Check condition
    if any(x in q for x in ("missing", "null", "duplicate", "negative", "return", "quality", "clean")):
        selected.append({"name": "python_data_quality", "reason": "Measure missing, duplicate, or return-related records."})
    # Check condition
    if any(x in q for x in ("correlation", "correlat", "relationship", "outlier", "distribution", "variance", "standard deviation", "forecast", "predict", "trend", "decline", "growth", "compare", "comparison", "why")):
        selected.append({"name": "python_statistics", "reason": "Compute numeric/statistical evidence for comparisons or patterns."})
    # Check condition
    if any(x in q for x in ("top", "highest", "lowest", "rank", "group", "by country", "by product", "by customer", "monthly", "month", "year", "segment", "breakdown", "contribution", "decline", "growth", "compare", "comparison", "why")):
        if duckdb is not None:
            selected.append({"name": "duckdb_read_only_sql", "reason": "Use SQL aggregation for grouped or time-based analysis."})
        else:
            selected.append({"name": "pandas_grouped_analysis", "reason": "DuckDB is not installed; use pandas for grouped analysis."})
    # Check condition
    if any(x in q for x in ("customer", "product", "country", "invoice", "order", "sales", "revenue")) and len(selected) == 1:
        if duckdb is not None:
            selected.append({"name": "duckdb_read_only_sql", "reason": "Use SQL to aggregate business entities."})
        else:
            selected.append({"name": "pandas_grouped_analysis", "reason": "Use pandas aggregation because DuckDB is unavailable."})

    # Avoid scheduling a tool that cannot operate on the available schema.
    if _metric(df, cols) is None and any(x["name"] in ("duckdb_read_only_sql", "pandas_grouped_analysis") for x in selected):
        selected = [x for x in selected if x["name"] not in ("duckdb_read_only_sql", "pandas_grouped_analysis")]
    # Return result
    return selected


# Helper: python profile
def _python_profile(df: pd.DataFrame) -> dict[str, Any]:
    # Set up values
    cols = _columns(df)
    metric = _metric(df, cols)
    result: dict[str, Any] = {
        "rows": int(len(df)), "columns": int(len(df.columns)),
        "column_names": [str(c) for c in df.columns],
        "detected_columns": {k: (str(v) if v is not None else None) for k, v in cols.items()},
        "missing_cells": int(df.isna().sum().sum()),
    }
    # Check condition
    if metric is not None:
        result["revenue_formula"] = str(cols["revenue"]) if cols["revenue"] is not None else f"{cols['quantity']} × {cols['price']}"
        result["valid_metric_rows"] = int(metric.notna().sum())
        result["net_revenue"] = float(metric.sum(min_count=1)) if metric.notna().any() else None
    # Return result
    return result


# Helper: python data quality
def _python_data_quality(df: pd.DataFrame) -> dict[str, Any]:
    # Set up values
    cols = _columns(df)
    output: dict[str, Any] = {
        "duplicate_rows": int(df.duplicated().sum()),
        "missing_by_column": {str(k): int(v) for k, v in df.isna().sum().items()},
    }
    qcol = cols["quantity"]
    # Check condition
    if qcol is not None:
        q = pd.to_numeric(df[qcol], errors="coerce")
        valid = int(q.notna().sum())
        negative = int((q < 0).sum())
        output["negative_quantity_rows"] = negative
        output["valid_numeric_quantity_rows"] = valid
        output["negative_quantity_row_percent"] = (negative / valid * 100) if valid else None
        if cols["invoice"] is not None:
            invoice_frame = pd.DataFrame({"invoice": df[cols["invoice"]], "negative": q < 0}).dropna(subset=["invoice"])
            invoices = int(invoice_frame["invoice"].nunique())
            negative_invoices = int(invoice_frame.groupby("invoice")["negative"].any().sum())
            output["invoices_with_negative_quantity"] = negative_invoices
            output["distinct_invoices"] = invoices
            output["negative_invoice_percent"] = (negative_invoices / invoices * 100) if invoices else None
    # Return result
    return output


# Helper: python statistics
def _python_statistics(df: pd.DataFrame) -> dict[str, Any]:
    # Set up values
    numeric = df.select_dtypes(include="number")
    result: dict[str, Any] = {"numeric_columns": [str(c) for c in numeric.columns]}
    # Check condition
    if numeric.shape[1] >= 2:
        corr = numeric.corr(numeric_only=True).round(4)
        pairs = []
        for i, left in enumerate(corr.columns):
            for right in corr.columns[i + 1:]:
                value = corr.loc[left, right]
                if pd.notna(value):
                    pairs.append({"column_a": str(left), "column_b": str(right), "correlation": float(value)})
        result["correlations"] = sorted(pairs, key=lambda x: abs(x["correlation"]), reverse=True)[:15]
    # Set up values
    metric = _metric(df, _columns(df))
    # Check condition
    if metric is not None:
        clean = metric.dropna()
        if not clean.empty:
            result["metric_distribution"] = {
                "mean": float(clean.mean()), "median": float(clean.median()),
                "std": float(clean.std()), "min": float(clean.min()),
                "max": float(clean.max()),
                "p05": float(clean.quantile(0.05)), "p95": float(clean.quantile(0.95)),
            }
        date_col = _columns(df)["date"]
        if date_col is not None:
            dates = pd.to_datetime(df[date_col], errors="coerce", dayfirst=True)
            time_frame = pd.DataFrame({"date": dates, "metric": metric}).dropna()
            if not time_frame.empty:
                time_frame["month"] = time_frame["date"].dt.to_period("M").astype(str)
                monthly = time_frame.groupby("month")["metric"].sum().sort_index()
                result["monthly_metric_totals"] = {str(k): float(v) for k, v in monthly.tail(36).items()}
                annual = time_frame.assign(year=time_frame["date"].dt.year).groupby("year")["metric"].sum().sort_index()
                result["annual_metric_totals"] = {str(k): float(v) for k, v in annual.items()}
    # Return result
    return result


# Helper: safe ident
def _safe_ident(identifier: Any) -> str:
    # Return result
    return '"' + str(identifier).replace('"', '""') + '"'


# Helper: duckdb grouped
def _duckdb_grouped(df: pd.DataFrame, question: str) -> dict[str, Any]:
    """Run safe, internally constructed SELECT aggregations for every requested grouping."""
    # Check condition
    if duckdb is None:
        raise RuntimeError("DuckDB is not installed. Install it with: pip install duckdb")

    # Set up values
    cols = _columns(df)
    metric = _metric(df, cols)
    # Check condition
    if metric is None:
        raise ValueError("No numeric sales/revenue metric could be detected.")

    # Set up values
    work = df.copy(deep=False).copy()
    work["__ai_metric"] = metric
    q = question.lower()
    con = duckdb.connect(database=":memory:")
    outputs: dict[str, Any] = {}

    # Try, handle errors
    try:
        con.register("dataset_view", work)

        requested_groups = []
        for key, phrases in (
            ("country", ("country", "countries", "region", "market")),
            ("product", ("product", "products", "item", "stock code")),
            ("customer", ("customer", "customers", "client")),
        ):
            if cols[key] is not None and any(p in q for p in phrases):
                requested_groups.append((key, cols[key]))

        for key, group_col in requested_groups:
            sql = (
                f"SELECT {_safe_ident(group_col)} AS group_name, "
                "SUM(__ai_metric) AS net_revenue, COUNT(*) AS line_rows "
                f"FROM dataset_view WHERE {_safe_ident(group_col)} IS NOT NULL "
                "AND __ai_metric IS NOT NULL GROUP BY 1 "
                "ORDER BY net_revenue DESC LIMIT 20"
            )
            rows = con.execute(sql).fetchdf()
            outputs[f"{key}_revenue"] = {
                "sql": sql,
                "grouped_by": str(group_col),
                "rows": rows.to_dict(orient="records"),
            }

        asks_time = any(term in q for term in (
            "monthly", "month", "trend", "over time", "by year", "yearly"
        ))
        if asks_time and cols["date"] is not None:
            dates = pd.to_datetime(df[cols["date"]], errors="coerce", dayfirst=True)
            work["__ai_date"] = dates
            con.unregister("dataset_view")
            con.register("dataset_view", work)
            sql = (
                "SELECT strftime(__ai_date, '%Y-%m') AS period, "
                "SUM(__ai_metric) AS net_revenue, COUNT(*) AS line_rows "
                "FROM dataset_view WHERE __ai_date IS NOT NULL AND __ai_metric IS NOT NULL "
                "GROUP BY 1 ORDER BY 1"
            )
            rows = con.execute(sql).fetchdf()
            outputs["monthly_revenue"] = {
                "sql": sql,
                "grouped_by": "month",
                "rows": rows.tail(36).to_dict(orient="records"),
            }

        if not outputs:
            raise ValueError("No requested supported grouping or date analysis was detected.")
        return {"analyses": outputs}
    finally:
        con.close()


# Select and run safe tools, returning evidence for the existing AI provider chain
def run_analytics_orchestrator(question: str, df: pd.DataFrame) -> dict[str, Any]:
    """Select and run safe tools, returning evidence for the existing AI provider chain."""
    # Check condition
    if not isinstance(df, pd.DataFrame) or df.empty:
        return {"status": "skipped", "reason": "No non-empty DataFrame was supplied.", "tools": [], "results": {}}

    # Set up values
    plan = select_tools(question, df)
    results: dict[str, Any] = {}
    trace = []
    # Loop over items
    for item in plan:
        name = item["name"]
        started = time.perf_counter()
        try:
            if name == "python_profile":
                output = _python_profile(df)
            elif name == "validated_structured_query":
                structured_plan = _structured_group_plan(question, df)
                if structured_plan is None:
                    output = {"status": "not_applicable", "reason": "No supported structured query plan could be compiled."}
                else:
                    output = _execute_structured_group_plan(df, structured_plan)
            elif name == "python_data_quality":
                output = _python_data_quality(df)
            elif name == "python_statistics":
                output = _python_statistics(df)
            elif name == "duckdb_read_only_sql":
                output = _duckdb_grouped(df, question)
            elif name == "pandas_grouped_analysis":
                cols = _columns(df)
                metric = _metric(df, cols)
                q = question.lower()
                analyses = {}
                for key, terms in (
                    ("country", ("country", "countries", "region", "market")),
                    ("product", ("product", "products", "item", "stock code")),
                    ("customer", ("customer", "customers", "client")),
                ):
                    group_col = cols[key]
                    if group_col is not None and any(term in q for term in terms) and metric is not None:
                        table = pd.DataFrame({"group_name": df[group_col], "metric": metric}).dropna()
                        grouped = table.groupby("group_name")["metric"].agg(["sum", "count"]).sort_values("sum", ascending=False).head(20)
                        analyses[f"{key}_revenue"] = {
                            "grouped_by": str(group_col),
                            "rows": [{"group_name": str(i), "net_revenue": float(r["sum"]), "line_rows": int(r["count"])} for i, r in grouped.iterrows()],
                        }
                if cols["date"] is not None and metric is not None and any(term in q for term in ("monthly", "month", "trend", "over time", "by year", "yearly")):
                    dates = pd.to_datetime(df[cols["date"]], errors="coerce", dayfirst=True)
                    table = pd.DataFrame({"date": dates, "metric": metric}).dropna()
                    table["month"] = table["date"].dt.to_period("M").astype(str)
                    grouped = table.groupby("month")["metric"].agg(["sum", "count"]).sort_index().tail(36)
                    analyses["monthly_revenue"] = {
                        "grouped_by": "month",
                        "rows": [{"group_name": str(i), "net_revenue": float(r["sum"]), "line_rows": int(r["count"])} for i, r in grouped.iterrows()],
                    }
                output = {"analyses": analyses} if analyses else {"status": "not_applicable", "reason": "No supported grouping field detected."}
            else:  # Defensive: only registered tools are callable.
                output = {"status": "not_registered"}
            results[name] = output
            trace.append({"tool": name, "status": "success", "elapsed_ms": round((time.perf_counter() - started) * 1000, 1), "reason": item["reason"]})
        except Exception as exc:
            results[name] = {"error": str(exc)[:300]}
            trace.append({"tool": name, "status": "failed", "elapsed_ms": round((time.perf_counter() - started) * 1000, 1), "reason": item["reason"], "error": str(exc)[:300]})

    # Return result
    return {
        "status": "completed" if any(x["status"] == "success" for x in trace) else "partial",
        "selection_mode": "dynamic",
        "execution_permission": "automatic_safe_tools_only",
        "tools": plan,
        "execution_trace": trace,
        "results": results,
        "safety": {
            "model_generated_python_executed": False,
            "model_generated_sql_executed": False,
            "structured_plan_source": "validated deterministic natural-language compiler",
            "arbitrary_operations_allowed": False,
            "sql_access": "read-only internally generated SELECT statements only",
        },
    }
