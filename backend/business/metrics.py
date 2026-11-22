# Imports
from __future__ import annotations
import re
from typing import Any
import pandas as pd

# Constants and settings
ALIASES = {
    "customer_id": ["customer_id", "customer id", "customerid", "client_id", "client id"],
    "order_id": ["invoice", "invoice_no", "invoice no", "order_id", "order id", "transaction_id"],
    "product": ["description", "product", "product_name", "item", "stock_code", "sku"],
    "date": ["invoice_date", "order_date", "date", "transaction_date", "created_at"],
    "quantity": ["quantity", "qty", "units", "units_sold"],
    "unit_price": ["price", "unit_price", "unit price", "selling_price", "amount_per_unit"],
    "cost": ["cost", "unit_cost", "cost_price", "cogs"],
    "category": ["category", "product_category", "segment", "department"],
    "region": ["country", "region", "state", "city", "territory", "market"],
}

# Helper: norm
def _norm(value: Any) -> str:
    # Return result
    return re.sub(r"[^a-z0-9]", "", str(value).lower())

# Function: resolve column
def resolve_column(df: pd.DataFrame, semantic: str, schema: dict | None = None) -> str | None:
    # Set up values
    schema = schema or {}
    mapping = (schema.get("mappings") or {}).get(semantic, {})
    # Check condition
    if isinstance(mapping, dict):
        col = mapping.get("column") or mapping.get("column_name")
        confidence = mapping.get("confidence", 0)
        try:
            confidence = float(confidence); confidence = confidence / 100 if confidence > 1 else confidence
        except (TypeError, ValueError): confidence = 0
        if mapping.get("status") == "accepted" and col in df.columns and confidence >= 0.90:
            return col
    # Set up values
    lookup = {_norm(c): str(c) for c in df.columns}
    # Loop over items
    for alias in ALIASES.get(semantic, []):
        if _norm(alias) in lookup: return lookup[_norm(alias)]
    # Return result
    return None

# Build metric catalog
def build_metric_catalog(df: pd.DataFrame, schema: dict | None = None) -> dict:
    # Set up values
    cols = {k: resolve_column(df, k, schema) for k in ALIASES}
    has_qty_price = bool(cols["quantity"] and cols["unit_price"])
    # Return result
    return {
        "columns": cols,
        "metrics": {
            "gross_sales_revenue": {"available": has_qty_price, "definition": "Sum of positive quantity × unit price; excludes negative-quantity returns."},
            "returns_value": {"available": has_qty_price, "definition": "Absolute value of negative quantity × unit price."},
            "net_revenue": {"available": has_qty_price, "definition": "Sum of signed quantity × unit price; negative quantities reduce revenue."},
            "net_quantity": {"available": bool(cols["quantity"]), "definition": "Sum of signed quantity, including returns."},
            "distinct_customers": {"available": bool(cols["customer_id"]), "definition": "Distinct non-null customer identifiers."},
            "distinct_orders": {"available": bool(cols["order_id"]), "definition": "Distinct non-null order/invoice identifiers."},
            "gross_margin": {"available": bool(cols["cost"] and cols["quantity"] and cols["unit_price"]), "definition": "Revenue less cost; requires a valid cost column and an agreed cost basis."},
            "aov": {"available": bool(has_qty_price and cols["order_id"]), "definition": "Net revenue divided by distinct non-null orders; confirm whether returns should be netted."},
        },
        "limitations": ["Metric availability is inferred from column names and accepted semantic mappings; verify ambiguous mappings before relying on results."]
    }

# Function: calculate core metrics
def calculate_core_metrics(df: pd.DataFrame, schema: dict | None = None) -> dict:
    # Set up values
    catalog = build_metric_catalog(df, schema); c = catalog["columns"]; out = {}
    # Check condition
    if c["quantity"]:
        q = pd.to_numeric(df[c["quantity"]], errors="coerce")
        out["net_quantity"] = float(q.sum())
        out["positive_quantity"] = float(q[q > 0].sum())
        out["negative_quantity"] = float(q[q < 0].sum())
        out["rows_negative_quantity"] = int((q < 0).sum())
    # Check condition
    if c["quantity"] and c["unit_price"]:
        q = pd.to_numeric(df[c["quantity"]], errors="coerce")
        p = pd.to_numeric(df[c["unit_price"]], errors="coerce")
        valid = q.notna() & p.notna()
        value = q * p
        out["net_revenue"] = float(value[valid].sum())
        out["gross_sales_revenue"] = float(value[valid & (q > 0)].sum())
        out["returns_value"] = float(-value[valid & (q < 0)].sum())
        out["valid_revenue_rows"] = int(valid.sum())
        out["invalid_revenue_rows"] = int((~valid).sum())
    # Check condition
    if c["customer_id"]:
        ids = df[c["customer_id"]].astype("string").str.strip().replace(["", "nan", "None", "<NA>"], pd.NA)
        out["distinct_customers"] = int(ids.nunique(dropna=True))
        out["missing_customer_id_rows"] = int(ids.isna().sum())
    # Check condition
    if c["order_id"]:
        ids = df[c["order_id"]].astype("string").str.strip().replace(["", "nan", "None", "<NA>"], pd.NA)
        out["distinct_orders"] = int(ids.nunique(dropna=True))
    # Check condition
    if "net_revenue" in out and out.get("distinct_orders", 0):
        out["aov_net"] = out["net_revenue"] / out["distinct_orders"]
    # Return result
    return {"catalog": catalog, "metrics": out, "row_count": int(len(df))}
