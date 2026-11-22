# Imports
from __future__ import annotations
from typing import Any

# Generate conservative opportunity hypotheses only from computed evidence
def generate_data_backed_recommendations(analysis: dict) -> list[dict]:
    """Generate conservative opportunity hypotheses only from computed evidence."""
    m = analysis.get("metrics", {}); recs = []
    rows = analysis.get("row_count", 0)
    # Check condition
    if m.get("missing_customer_id_rows", 0) > 0 and rows:
        n = m["missing_customer_id_rows"]
        recs.append({"title":"Improve customer identification coverage","observation":f"{n:,} of {rows:,} rows have missing customer IDs ({n/rows:.1%}).", "evidence":{"missing_customer_id_rows":n,"row_count":rows}, "recommended_action":"Investigate checkout, CRM and data-import processes to capture customer identifiers consistently.", "expected_impact":None, "confidence":"high_for_data_quality_issue; business_impact_unquantified", "assumptions":[], "measurement_plan":"Track customer-ID completeness by source and month; measure the share of sales linked to identifiable customers."})
    # Check condition
    if m.get("rows_negative_quantity", 0) > 0:
        n = m["rows_negative_quantity"]
        recs.append({"title":"Investigate product returns","observation":f"{n:,} rows contain negative quantities, which reduce net revenue.", "evidence":{"negative_quantity_rows":n,"returns_value":m.get("returns_value")}, "recommended_action":"Break returns down by product, customer, reason and period before changing pricing or product policy.", "expected_impact":None, "confidence":"high_for_presence_of_returns; cause_unverified", "assumptions":["Negative quantities represent returns or reversals; confirm the source-system convention."], "measurement_plan":"Monitor return rate and return value by product and cohort; compare before and after any intervention."})
    # Check condition
    if m.get("invalid_revenue_rows", 0) > 0:
        n = m["invalid_revenue_rows"]
        recs.append({"title":"Improve revenue data completeness","observation":f"{n:,} rows cannot be included in the revenue calculation because quantity or unit price is missing or invalid.", "evidence":{"invalid_revenue_rows":n,"valid_revenue_rows":m.get("valid_revenue_rows")}, "recommended_action":"Identify the source and reason for missing numeric values; correct upstream data capture where possible.", "expected_impact":None, "confidence":"high_for_data_quality_issue; financial_impact_unquantified", "assumptions":[], "measurement_plan":"Track invalid-row rate and reconcile calculated revenue against the source financial system."})
    # Return result
    return recs
