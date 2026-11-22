"""Fast retrieval of labelled dataset-question examples for AI Analyst.

The 100K corpus is an intent/example bank, not model fine-tuning data. It is
queried locally with SQLite FTS5; only a handful of examples are supplied to
the LLM as context. It never reads workbook rows and never computes answers.
"""
# Imports
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any


# Helper: database path
def _database_path() -> Path:
    # Return result
    return Path(__file__).resolve().parent / "question_bank.sqlite"


# Helper: fts query
def _fts_query(question: str) -> str:
    # Set up values
    tokens = re.findall(r"[a-zA-Z0-9]+", str(question or "").lower())
    # Ignore very common terms to give distinctive business terms more weight.
    stop = {"the", "a", "an", "is", "are", "of", "in", "on", "for", "to", "and", "by", "with", "show", "list", "give", "me", "please", "what", "which", "how"}
    tokens = [t for t in tokens if t not in stop]
    # Check condition
    if not tokens:
        return ""
    # OR retrieval tolerates paraphrases and reordered wording. FTS quoting
    # prevents user text from becoming an FTS operator or expression.
    return " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens[:24])


# Return closest labelled examples; gracefully return [] if unavailable
def retrieve_question_examples(question: str, limit: int = 5) -> list[dict[str, Any]]:
    """Return closest labelled examples; gracefully return [] if unavailable."""
    db_path = _database_path()
    query = _fts_query(question)
    # Check condition
    if not query or not db_path.is_file():
        return []
    # Set up values
    limit = max(1, min(int(limit), 8))
    # Try, handle errors
    try:
        # Read-only access prevents accidental changes to the training corpus.
        uri = f"file:{db_path.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=1.5) as connection:
            rows = connection.execute(
                "SELECT question, intent, bm25(questions_fts) AS score "
                "FROM questions_fts WHERE questions_fts MATCH ? "
                "ORDER BY score LIMIT ?",
                (query, limit),
            ).fetchall()
        return [
            {"question": str(row[0]), "intent": str(row[1]), "rank_score": round(float(row[2]), 6)}
            for row in rows
        ]
    except (sqlite3.Error, OSError, ValueError, TypeError):
        return []


# Return the nearest example's intent as a hint, never as execution authority
def best_question_intent(question: str) -> str | None:
    """Return the nearest example's intent as a hint, never as execution authority."""
    examples = retrieve_question_examples(question, limit=1)
    # Return result
    return examples[0]["intent"] if examples else None
