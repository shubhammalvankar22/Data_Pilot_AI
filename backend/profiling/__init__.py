"""Automatic dataset profiling and semantic column mapping."""

# Imports
from .data_profiler import profile_dataframe
from .semantic_mapper import infer_semantic_schema

# Constants and settings
__all__ = ["profile_dataframe", "infer_semantic_schema"]
