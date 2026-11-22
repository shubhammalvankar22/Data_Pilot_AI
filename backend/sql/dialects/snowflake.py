"""Snowflake SQL dialect adapter.

Snowflake uses UPPERCASED identifiers by default, DIV0NULL for safe
division, LISTAGG for string aggregation, and SAMPLE (n ROWS) for
random sampling.
"""

# Imports
from __future__ import annotations

from sql.dialects.base import SQLDialect


# SQL dialect for Snowflake
class SnowflakeDialect(SQLDialect):
    """SQL dialect for Snowflake."""

    name: str = "snowflake"

    # ------------------------------------------------------------------
    # Table qualification
    # ------------------------------------------------------------------

    def qualify_table(self, table: str, schema: str | None = None) -> str:
        """Snowflake ``database.schema.table`` — uppercased by convention.

        *schema* can be ``database.schema`` or just ``schema``.

        >>> SnowflakeDialect().qualify_table('orders', 'ANALYTICS_DB.PUBLIC')
        'ANALYTICS_DB.PUBLIC.ORDERS'
        >>> SnowflakeDialect().qualify_table('orders')
        'ORDERS'
        """
        from sql.policy import identifier_parts, render_parts
        # Set up values
        parts = identifier_parts(table)
        # Check condition
        if schema and len(parts) < 3:
            prefix = identifier_parts(schema)
            # Fully qualified objects and schema-qualified objects must not be
            # double-prefixed. A partial prefix remains partial, never guessed.
            parts = prefix[:max(0, 3 - len(parts))] + parts if len(parts) > 1 else prefix + parts
        # Return result
        return render_parts(parts)

    # limit_clause — inherited (LIMIT N)

    # ------------------------------------------------------------------
    # Date / time functions
    # ------------------------------------------------------------------

    def date_trunc(self, field: str, unit: str) -> str:
        """Snowflake DATE_TRUNC — quoted unit first, then field.

        >>> SnowflakeDialect().date_trunc('order_date', 'month')
        "DATE_TRUNC('MONTH', order_date)"
        """
        # Return result
        return f"DATE_TRUNC('{unit.upper()}', {field})"

    # Snowflake DATEDIFF — quoted unit, start, end
    def date_diff(self, unit: str, start: str, end: str) -> str:
        """Snowflake DATEDIFF — quoted unit, start, end.

        >>> SnowflakeDialect().date_diff('day', 'start_date', 'end_date')
        "DATEDIFF('DAY', start_date, end_date)"
        """
        # Return result
        return f"DATEDIFF('{unit.upper()}', {start}, {end})"

    # ------------------------------------------------------------------
    # Safe math
    # ------------------------------------------------------------------

    def safe_divide(self, numerator: str, denominator: str) -> str:
        """Snowflake DIV0NULL — returns NULL on zero denominator.

        >>> SnowflakeDialect().safe_divide('revenue', 'orders')
        'DIV0NULL(revenue, orders)'
        """
        # Return result
        return f"DIV0NULL({numerator}, {denominator})"

    # ------------------------------------------------------------------
    # String aggregation
    # ------------------------------------------------------------------

    def string_agg(self, column: str, delimiter: str = ",") -> str:
        """Snowflake LISTAGG with WITHIN GROUP ordering.

        >>> SnowflakeDialect().string_agg('category')
        "LISTAGG(category, ',') WITHIN GROUP (ORDER BY category)"
        """
        # Return result
        return f"LISTAGG({column}, '{delimiter}') WITHIN GROUP (ORDER BY {column})"

    # current_timestamp — inherited (CURRENT_TIMESTAMP)

    # ------------------------------------------------------------------
    # Temp tables
    # ------------------------------------------------------------------

    def create_temp_table(self, name: str, query: str) -> str:
        """Snowflake temporary table (session-scoped).

        >>> SnowflakeDialect().create_temp_table('TMP_AGG', 'SELECT 1')
        'CREATE TEMPORARY TABLE TMP_AGG AS (SELECT 1)'
        """
        # Return result
        return f"CREATE TEMPORARY TABLE {name} AS ({query})"

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------

    def sample_rows(self, table: str, n: int) -> str:
        """Snowflake SAMPLE (n ROWS) — efficient built-in sampling.

        >>> SnowflakeDialect().sample_rows('orders', 100)
        'SELECT * FROM orders SAMPLE (100 ROWS)'
        """
        # Return result
        return f"SELECT * FROM {table} SAMPLE ({int(n)} ROWS)"

    # ------------------------------------------------------------------
    # Schema introspection
    # ------------------------------------------------------------------

    def describe_table(self, table: str) -> str:
        """Snowflake DESCRIBE TABLE statement.

        >>> SnowflakeDialect().describe_table('customers')
        'DESCRIBE TABLE customers'
        """
        # Return result
        return f"DESCRIBE TABLE {table}"

    # ------------------------------------------------------------------
    # Validation methods
    # ------------------------------------------------------------------

    def count_distinct(self, table: str, column: str,
                       approximate: bool = False) -> str:
        """Snowflake: use APPROX_COUNT_DISTINCT (HLL) when approximate=True."""
        # Check condition
        if approximate:
            return f"SELECT APPROX_COUNT_DISTINCT({column}) AS distinct_count FROM {table}"
        # Return result
        return f"SELECT COUNT(DISTINCT {column}) AS distinct_count FROM {table}"

    # Snowflake: use TO_VARCHAR for casting (CAST AS VARCHAR also works)
    def row_checksum(self, table: str, columns: list[str]) -> str:
        """Snowflake: use TO_VARCHAR for casting (CAST AS VARCHAR also works)."""
        col_concat = " || '|' || ".join(
            f"COALESCE(TO_VARCHAR({c}), '')" for c in columns
        )
        # Return result
        return f"SELECT MD5({col_concat}) AS row_hash FROM {table}"
