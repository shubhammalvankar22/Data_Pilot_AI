"""SQL dialect adapters for multi-warehouse support.

Each dialect translates common SQL operations into the syntax required
by a specific warehouse backend (DuckDB, PostgreSQL, BigQuery, Snowflake).
Used by sql/policy.py.
"""

# Imports
from sql.dialects.base import SQLDialect
from sql.dialects.duckdb_dialect import DuckDBDialect
from sql.dialects.postgres import PostgresDialect
from sql.dialects.bigquery import BigQueryDialect
from sql.dialects.snowflake import SnowflakeDialect

# Constants and settings
__all__ = [
    "SQLDialect",
    "DuckDBDialect",
    "PostgresDialect",
    "BigQueryDialect",
    "SnowflakeDialect",
]
