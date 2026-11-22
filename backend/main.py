# Imports
from __future__ import annotations
import datetime
import json
import io
import math
import os
import re
import sys
import time
import threading
import uuid
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
import pandas as pd
from collections import OrderedDict
# Bounded cache for deterministic answers. DataWorkspace replaces its current
# DataFrame on every committed edit/undo/redo, so object identity naturally
# invalidates cached results when the workbook changes.
_DETERMINISTIC_ANSWER_CACHE = OrderedDict()
_DETERMINISTIC_ANSWER_CACHE_MAX = 48


# Helper: cached dataframe answer
def _cached_dataframe_answer(cache_name, df, schema, parameters, calculate):
    # Set up values
    key = (cache_name, id(df), tuple(df.shape), repr(schema), tuple(parameters))
    cached = _DETERMINISTIC_ANSWER_CACHE.get(key)
    # Check condition
    if cached is not None and cached[0] is df:
        _DETERMINISTIC_ANSWER_CACHE.move_to_end(key)
        return cached[1]
    # Set up values
    result = calculate()
    # Check condition
    if result is not None:
        _DETERMINISTIC_ANSWER_CACHE[key] = (df, result)
        _DETERMINISTIC_ANSWER_CACHE.move_to_end(key)
        while len(_DETERMINISTIC_ANSWER_CACHE) > _DETERMINISTIC_ANSWER_CACHE_MAX:
            _DETERMINISTIC_ANSWER_CACHE.popitem(last=False)
    # Return result
    return result
# Imports
from profiling import profile_dataframe, infer_semantic_schema
# Evidence-first business intelligence layer (kept separate from existing analytics routes).
from business import (
    analyze_business_question,
    build_metric_catalog,
    calculate_core_metrics,
    generate_data_backed_recommendations,
)
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
# Resolve the repository root (the directory containing the top-level helpers/ package).
ROOT = Path(os.environ["AI_ANALYST_ROOT"]).resolve() if os.environ.get("AI_ANALYST_ROOT") else Path(__file__).resolve().parent
# Module-level setup
if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
# Constants and settings
app = FastAPI(title="AI Analyst API", version="0.1.1")
# Module-level setup
print("[AI ROUTER] RFM segment routing fix active", flush=True)
# Module-level setup
app.add_middleware(
        CORSMiddleware,
        allow_origins=[
                    "http://localhost:5173",
                    "https://data-pilot-ai-w3iu.vercel.app",
                    "http://127.0.0.1:5173",
                    "http://localhost:5174",
                    "http://127.0.0.1:5174",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
)
# Temporary in-memory sessions. No dataset/session pickle files are written.
SESSIONS: dict[str, dict[str, Any]] = {}
SESSION_INACTIVITY_SECONDS = 30 * 60
_SESSION_CLEANUP_INTERVAL_SECONDS = 60


# Remove inactive workbooks from RAM as a fallback if tab-close is missed
def _cleanup_expired_sessions() -> None:
    """Remove inactive workbooks from RAM as a fallback if tab-close is missed."""
    now = time.monotonic()
    expired = [
        sid for sid, state in list(SESSIONS.items())
        if now - state.get("_last_access", now) >= SESSION_INACTIVITY_SECONDS
    ]
    # Loop over items
    for sid in expired:
        SESSIONS.pop(sid, None)


# Helper: session cleanup worker
def _session_cleanup_worker() -> None:
    # Repeat until done
    while True:
        time.sleep(_SESSION_CLEANUP_INTERVAL_SECONDS)
        _cleanup_expired_sessions()
# Constants and settings
_cleanup_thread = threading.Thread(
    target=_session_cleanup_worker,
    name="ai-analyst-session-cleanup",
    daemon=True,
)
# Module-level setup
_cleanup_thread.start()


# Compatibility no-op: sessions are intentionally kept in RAM only
def persist_session(sid: str, state: dict[str, Any]) -> None:
    """Compatibility no-op: sessions are intentionally kept in RAM only."""
    state["_last_access"] = time.monotonic()


# Basic workspace used when the project's DataWorkspace cannot be imported
class FallbackWorkspace:
        """Basic workspace used when the project's DataWorkspace cannot be imported."""
        # Helper: init
        def __init__(self, df: pd.DataFrame):
                    # Set up values
                    self.original = df.copy(deep=True)
                    self.current = df.copy(deep=True)
                    self.undo_stack = []
                    self.redo_stack = []
                    self.history = []
        # Function: can undo
        @property
        def can_undo(self):
                    # Return result
                    return bool(self.undo_stack)
        # Function: can redo
        @property
        def can_redo(self):
                    # Return result
                    return bool(self.redo_stack)
        # Helper: push
        def _push(self, operation, details=None):
                    self.undo_stack.append(self.current.copy(deep=True))
                    self.redo_stack.clear()
                    self.history.append({"operation": operation, "details": details or {}})
        # Function: replace dataframe
        def replace_dataframe(self, df, operation="edit_cells", details=None):
                    self._push(operation, details)
                    self.current = df.copy(deep=True)
        # Function: undo
        def undo(self):
                    # Check condition
                    if self.undo_stack:
                            self.redo_stack.append(self.current.copy(deep=True))
                            self.current = self.undo_stack.pop()
        # Function: redo
        def redo(self):
                    # Check condition
                    if self.redo_stack:
                            self.undo_stack.append(self.current.copy(deep=True))
                            self.current = self.redo_stack.pop()
        # Function: reset
        def reset(self):
                    self._push("reset")
                    self.current = self.original.copy(deep=True)
        # Function: remove duplicates
        def remove_duplicates(self):
                    # Set up values
                    before = len(self.current)
                    self._push("remove_duplicates")
                    self.current = self.current.drop_duplicates().reset_index(drop=True)
                    # Return result
                    return {"rows_removed": before - len(self.current)}
        # Function: sort values
        def sort_values(self, column, ascending=True):
                    self._push("sort", {"column": column, "ascending": ascending})
                    self.current = self.current.sort_values(
                            column, ascending=ascending, na_position="last"
                    ).reset_index(drop=True)
        # Function: rename column
        def rename_column(self, old, new):
                    # Set up values
                    new = str(new).strip()
                    # Check condition
                    if not new:
                            raise ValueError("Enter a column name")
                    # Check condition
                    if new in self.current.columns and new != old:
                            raise ValueError("That column already exists")
                    # Check condition
                    if old not in self.current.columns:
                            raise ValueError("Unknown column")
                    self._push("rename_column", {"from": old, "to": new})
                    self.current = self.current.rename(columns={old: new})
        # Function: remove column
        def remove_column(self, col):
                    # Check condition
                    if col not in self.current.columns:
                            raise ValueError("Unknown column")
                    # Check condition
                    if len(self.current.columns) <= 1:
                            raise ValueError("At least one column must remain")
                    self._push("remove_column", {"column": col})
                    self.current = self.current.drop(columns=[col])
        # Create column
        def create_column(self, column_name, values, description=""):
                    # Check condition
                    if not column_name or column_name in self.current.columns:
                            raise ValueError("Column name is empty or already exists")
                    # Check condition
                    if len(values) != len(self.current):
                            raise ValueError("Column values do not match row count")
                    self._push("create_column", {"column": column_name, "description": description})
                    self.current[column_name] = list(values)
        # Function: convert column type
        def convert_column_type(self, column, kind):
                    # Check condition
                    if column not in self.current.columns:
                            raise ValueError("Unknown column")
                    # Set up values
                    series = self.current[column]
                    # Check condition
                    if kind == "Text":
                            converted = series.astype("string")
                    elif kind == "Whole number":
                            converted = pd.to_numeric(series, errors="raise").astype("Int64")
                    elif kind in ("Decimal number", "Percentage"):
                            converted = pd.to_numeric(series, errors="raise")
                    elif kind in ("Date", "Date/Time"):
                            converted = pd.to_datetime(series, errors="raise")
                    elif kind == "True/False":
                            mapping = {
                                        "true": True, "false": False, "1": True, "0": False,
                                        "yes": True, "no": False,
                            }
                            converted = series.astype(str).str.lower().map(mapping)
                            if converted.isna().any() and series.notna().any():
                                        raise ValueError("Some values are not recognizable as true/false")
                    else:
                            raise ValueError("Unsupported type")
                    self._push("convert_type", {"column": column, "type": kind})
                    self.current[column] = converted
        # Function: replace missing
        def replace_missing(self, column, value):
                    # Check condition
                    if column not in self.current.columns:
                            raise ValueError("Unknown column")
                    # Set up values
                    count = int(self.current[column].isna().sum())
                    self._push("replace_missing", {"column": column, "count": count})
                    self.current[column] = self.current[column].fillna(value)
                    # Return result
                    return {"cells_changed": count}
        # Get history
        def get_history(self):
                    # Return result
                    return self.history
        # Function: download csv
        def download_csv(self):
                    # Return result
                    return self.current.to_csv(index=False).encode("utf-8")


# Make workspace
def make_workspace(df: pd.DataFrame):
        # Try, handle errors
        try:
                    from spreadsheet.workspace import DataWorkspace
                    return DataWorkspace(df)
        except Exception:
                    return FallbackWorkspace(df)


# Get session
def get_session(sid: str):
    # Try, handle errors
    try:
        safe_id = str(uuid.UUID(str(sid)))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, "Invalid workbook session ID")
    _cleanup_expired_sessions()
    state = SESSIONS.get(safe_id)
    # Check condition
    if state is None:
        raise HTTPException(
            404,
            "Workbook session not found. It may have been closed or expired; upload the dataset again.",
        )
    # Set up values
    state["_last_access"] = time.monotonic()
    # Return result
    return state


# Convert pandas/numpy values, NaN/Inf and dates to JSON-safe values
def _json_safe_value(value):
        """Convert pandas/numpy values, NaN/Inf and dates to JSON-safe values."""
        # Check condition
        if value is None or value is pd.NA or value is pd.NaT:
                    return None
        # Check condition
        if isinstance(value, (pd.Timestamp, datetime.datetime, datetime.date)):
                    return None if pd.isna(value) else value.isoformat()
        # Check condition
        if hasattr(value, "item"):
                    try:
                            value = value.item()
                    except Exception:
                            pass
        # Check condition
        if value is None or value is pd.NA or value is pd.NaT:
                    return None
        # Check condition
        if isinstance(value, float):
                    return value if math.isfinite(value) else None
        # Try, handle errors
        try:
                    missing = pd.isna(value)
                    if not hasattr(missing, "__len__") and bool(missing):
                            return None
        except (TypeError, ValueError):
                    pass
        # Check condition
        if isinstance(value, (str, int, float, bool)):
                    return value
        # Return result
        return str(value)


# Recursively remove NaN/Infinity from nested API response data
def make_json_safe(value):
        """Recursively remove NaN/Infinity from nested API response data."""
        # Check condition
        if isinstance(value, dict):
                    return {str(key): make_json_safe(item) for key, item in value.items()}
        # Check condition
        if isinstance(value, (list, tuple)):
                    return [make_json_safe(item) for item in value]
        # Check condition
        if isinstance(value, pd.Series):
                    return [make_json_safe(item) for item in value.tolist()]
        # Check condition
        if isinstance(value, pd.DataFrame):
                    return make_json_safe(value.to_dict(orient="records"))
        # Return result
        return _json_safe_value(value)


# Return a copy with every cell converted to a JSON-safe Python scalar
def safe_df(df: pd.DataFrame) -> pd.DataFrame:
        """Return a copy with every cell converted to a JSON-safe Python scalar."""
        safe = df.copy()
        # Loop over items
        for column in safe.columns:
                    safe[column] = safe[column].map(_json_safe_value)
        # Return result
        return safe


# Function: workbook payload
def workbook_payload(sid, state):
        # Set up values
        df = state["workspace"].current
        payload = {
                    "sessionId": sid,
                    "filename": state["filename"],
                    "columns": [
                            {
                                        "field": str(column),
                                        "headerName": str(column),
                                        "type": (
                                                "number" if pd.api.types.is_numeric_dtype(df[column])
                                                else "date" if pd.api.types.is_datetime64_any_dtype(df[column])
                                                else "text"
                                        ),
                            }
                            for column in df.columns
                    ],
            "rows": safe_df(df.iloc[:500]).to_dict(orient="records"),
                "rowsPaginated": True,
                    "rowCount": int(len(df)),
                    "columnCount": int(len(df.columns)),
                    "missingCount": int(df.isna().sum().sum()),
                    "duplicateCount": int(df.duplicated().sum()),
                    "history": (
                            state["workspace"].get_history()
                            if hasattr(state["workspace"], "get_history") else []
                    ),
        }
        # Return result
        return make_json_safe(payload)


# Function: root
@app.get("/")
def root():
        # Return result
        return {"status": "ok", "message": "AI Analyst API is running", "docs": "/docs"}


# Function: health
@app.get("/api/health")
def health():
        # Return result
        return {"status": "ok", "root": str(ROOT)}
# ---------------------------------------------------------------------------
# AI settings
# ---------------------------------------------------------------------------
# API keys for custom AI mode are stored only on the backend. They are never
# returned by GET /api/settings/ai and are never written to browser storage.
AI_SETTINGS_FILE = ROOT / ".ai_analyst_settings.json"
AI_CUSTOM_PROVIDERS = {"gemini", "groq", "openrouter", "deepseek", "perplexity", "openai", "anthropic"}


# Helper: read ai settings
def _read_ai_settings(include_secret: bool = False) -> dict[str, Any]:
    # Check condition
    if not AI_SETTINGS_FILE.exists():
        return {
            "mode": "current",
            "provider": "",
            "model": "",
            "api_key": "" if include_secret else None,
        }
    # Try, handle errors
    try:
        raw = json.loads(AI_SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(500, f"Could not read AI settings: {exc}") from exc
    # Set up values
    provider = str(raw.get("provider") or "").strip().lower()
    model = str(raw.get("model") or "").strip()
    api_key = str(raw.get("api_key") or "").strip()
    mode = str(raw.get("mode") or "custom").strip().lower()
    # Check condition
    if mode not in {"current", "custom"}:
        mode = "custom"
    # Set up values
    result = {
        "mode": mode,
        "provider": provider,
        "model": model,
    }
    # Check condition
    if include_secret:
        result["api_key"] = api_key
    # Return result
    return result


# Helper: write ai settings
def _write_ai_settings(provider: str, model: str, api_key: str) -> None:
    # Set up values
    provider = str(provider or "").strip().lower()
    model = str(model or "").strip()
    api_key = str(api_key or "").strip()
    # Check condition
    if provider not in AI_CUSTOM_PROVIDERS:
        raise HTTPException(400, "Provider must be Gemini, Groq, OpenRouter, DeepSeek, Perplexity, OpenAI, or Anthropic.")
    # Check condition
    if not model:
        raise HTTPException(400, "Model ID cannot be empty.")
    # Check condition
    if not api_key:
        raise HTTPException(400, "API key cannot be empty.")
    # Set up values
    payload = {
        "mode": "custom",
        "provider": provider,
        "model": model,
        "api_key": api_key,
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    # Try, handle errors
    try:
        AI_SETTINGS_FILE.write_text(serialized, encoding="utf-8")
    except PermissionError as first_error:
        # A previous version attempted to change the Windows ACL of this file.
        # If that left the existing file non-writable, restore normal inherited
        # permissions and retry once. Do not modify ACLs after a successful write.
        if os.name != "nt":
            raise HTTPException(500, f"Could not save AI settings: {first_error}") from first_error
        try:
            import subprocess
            subprocess.run(
                ["icacls", str(AI_SETTINGS_FILE), "/reset"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            AI_SETTINGS_FILE.write_text(serialized, encoding="utf-8")
        except Exception as retry_error:
            raise HTTPException(500, f"Could not save AI settings: {retry_error}") from retry_error
    except Exception as exc:
        raise HTTPException(500, f"Could not save AI settings: {exc}") from exc


# Return a provider error without echoing an API key
def _safe_remote_error(exc: Exception) -> str:
    """Return a provider error without echoing an API key."""
    message = str(exc)
    settings = _read_ai_settings(include_secret=True)
    secret = str(settings.get("api_key") or "")
    # Check condition
    if secret:
        message = message.replace(secret, "[REDACTED]")
    # Return result
    return message[:2000]


# Helper: provider json request
def _provider_json_request(
    provider: str,
    api_key: str,
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Set up values
    headers = {
        "Accept": "application/json",
        "User-Agent": "AI-Analyst/1.0",
    }
    # Check condition
    if provider == "gemini":
        headers["x-goog-api-key"] = api_key
    elif provider == "anthropic":
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    else:
        headers["Authorization"] = f"Bearer {api_key}"
    # Check condition
    if payload is not None:
        headers["Content-Type"] = "application/json"
    # Set up values
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    # Try, handle errors
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            details = json.loads(raw)
            detail = details.get("error", details)
            if isinstance(detail, dict):
                detail = detail.get("message") or detail
            raise RuntimeError(f"{exc.code}: {detail}") from exc
        except json.JSONDecodeError:
            raise RuntimeError(f"{exc.code}: {raw[:1000]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc


# Helper: list custom models
def _list_custom_models(provider: str, api_key: str) -> list[dict[str, Any]]:
    # Set up values
    provider = provider.strip().lower()
    # Check condition
    if provider == "gemini":
        data = _provider_json_request(
            provider,
            api_key,
            "GET",
            "https://generativelanguage.googleapis.com/v1beta/models?pageSize=100",
        )
        models = []
        for item in data.get("models", []):
            methods = item.get("supportedGenerationMethods") or []
            if "generateContent" not in methods:
                continue
            name = str(item.get("name") or "").strip()
            model_id = name.split("/", 1)[1] if name.startswith("models/") else name
            if model_id:
                models.append({
                    "id": model_id,
                    "name": str(item.get("displayName") or model_id),
                })
        return models
    # Check condition
    if provider == "groq":
        data = _provider_json_request(
            provider,
            api_key,
            "GET",
            "https://api.groq.com/openai/v1/models",
        )
        return [
            {
                "id": str(item.get("id")),
                "name": str(item.get("id")),
            }
            for item in data.get("data", [])
            if item.get("id")
        ]
    # Check condition
    if provider == "openrouter":
        data = _provider_json_request(
            provider,
            api_key,
            "GET",
            "https://openrouter.ai/api/v1/models",
        )
        return [
            {
                "id": str(item.get("id")),
                "name": str(item.get("name") or item.get("id")),
            }
            for item in data.get("data", [])
            if item.get("id")
        ]
    # Set up values
    model_endpoints = {
        "deepseek": "https://api.deepseek.com/models",
        "perplexity": "https://api.perplexity.ai/models",
        "openai": "https://api.openai.com/v1/models",
        "anthropic": "https://api.anthropic.com/v1/models",
    }
    # Check condition
    if provider in model_endpoints:
        data = _provider_json_request(provider, api_key, "GET", model_endpoints[provider])
        items = data.get("data", [])
        return [
            {
                "id": str(item.get("id")),
                "name": str(item.get("display_name") or item.get("name") or item.get("id")),
            }
            for item in items
            if item.get("id")
        ]
    raise HTTPException(400, "Unsupported custom AI provider.")


# Test one explicitly selected custom provider/model
def _test_custom_model(provider: str, api_key: str, model: str) -> str:
    """
    Test one explicitly selected custom provider/model.

    This function is intentionally isolated from the normal AI fallback router.
    It only verifies the selected provider/model and does not change the
    existing Auto/current-project fallback behavior.

    Groq's GPT-OSS models can return reasoning separately from message.content,
    or message.content can be a structured list rather than a plain string.
    Handle those response shapes so a successful Groq request is not reported
    incorrectly as "Provider returned no text response."
    """
    provider = provider.strip().lower()
    model = model.strip()
    # Check condition
    if provider == "gemini":
        data = _provider_json_request(
            provider,
            api_key,
            "POST",
            f"https://generativelanguage.googleapis.com/v1beta/models/{urllib.parse.quote(model, safe='')}:generateContent",
            {
                "contents": [
                    {"parts": [{"text": "Reply with exactly: AI Analyst connection successful"}]}
                ]
            },
        )
        candidates = data.get("candidates") or []
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            answer = "".join(str(part.get("text") or "") for part in parts).strip()
            if answer:
                return answer
        raise RuntimeError("Gemini returned no text response.")
    # Check condition
    if provider in {"groq", "openrouter", "deepseek", "perplexity", "openai"}:
        url = {
            "groq": "https://api.groq.com/openai/v1/chat/completions",
            "openrouter": "https://openrouter.ai/api/v1/chat/completions",
            "deepseek": "https://api.deepseek.com/chat/completions",
            "perplexity": "https://api.perplexity.ai/chat/completions",
            "openai": "https://api.openai.com/v1/chat/completions",
        }[provider]
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": "Reply with exactly: AI Analyst connection successful",
                }
            ],
            "temperature": 0,
        }
        # GPT-OSS models on Groq are reasoning-capable. Use the parameters
        # supported by those models so the short connection test requests an
        # actual final answer instead of spending the tiny token budget on
        # reasoning only. Other providers keep the original simple request.
        if provider == "groq" and model.lower().startswith("openai/gpt-oss"):
            payload.update(
                {
                    "max_completion_tokens": 256,
                    "reasoning_effort": "low",
                    "include_reasoning": False,
                }
            )
        else:
            payload["max_tokens"] = 30
        data = _provider_json_request(
            provider,
            api_key,
            "POST",
            url,
            payload,
        )
        choices = data.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            # Standard OpenAI-compatible response:
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
            # Some OpenAI-compatible providers/models return structured
            # content blocks instead of a single string.
            if isinstance(content, list):
                parts = []
                for part in content:
                    if isinstance(part, dict):
                        text_value = part.get("text")
                        if text_value:
                            parts.append(str(text_value))
                    elif isinstance(part, str):
                        parts.append(part)
                answer = "".join(parts).strip()
                if answer:
                    return answer
            # GPT-OSS may successfully complete while exposing reasoning
            # separately. For a connection test, that still proves the API
            # key/model/request worked even if final content is absent.
            if message.get("reasoning") or message.get("reasoning_content"):
                return "AI Analyst connection successful"
        raise RuntimeError("Provider returned no usable text response.")
    # Check condition
    if provider == "anthropic":
        data = _provider_json_request(
            provider,
            api_key,
            "POST",
            "https://api.anthropic.com/v1/messages",
            {
                "model": model,
                "max_tokens": 32,
                "messages": [
                    {"role": "user", "content": "Reply with exactly: AI Analyst connection successful"}
                ],
            },
        )
        parts = data.get("content") or []
        answer = "".join(
            str(part.get("text") or "")
            for part in parts
            if isinstance(part, dict)
        ).strip()
        if answer:
            return answer
        raise RuntimeError("Anthropic returned no text response.")
    raise HTTPException(400, "Unsupported custom AI provider.")


# Class: aisettings request
class AISettingsRequest(BaseModel):
    mode: str = "custom"
    provider: str
    model: str
    api_key: str


# Class: aimodels request
class AIModelsRequest(BaseModel):
    provider: str
    api_key: str


# Class: aitest request
class AITestRequest(BaseModel):
    provider: str
    model: str
    api_key: str


# Get ai settings
@app.get("/api/settings/ai")
def get_ai_settings():
    # Set up values
    settings = _read_ai_settings(include_secret=False)
    # Return result
    return {
        "mode": settings.get("mode", "current"),
        "provider": settings.get("provider", ""),
        "model": settings.get("model", ""),
        "has_api_key": bool(
            _read_ai_settings(include_secret=True).get("api_key")
        ),
    }


# Get custom ai models
@app.post("/api/settings/ai/models")
def get_custom_ai_models(req: AIModelsRequest):
    # Set up values
    provider = str(req.provider or "").strip().lower()
    api_key = str(req.api_key or "").strip()
    # Check condition
    if provider not in AI_CUSTOM_PROVIDERS:
        raise HTTPException(400, "Provider must be Gemini, Groq, OpenRouter, DeepSeek, Perplexity, OpenAI, or Anthropic.")
    # Check condition
    if not api_key:
        raise HTTPException(400, "API key cannot be empty.")
    # Try, handle errors
    try:
        return {
            "provider": provider,
            "models": _list_custom_models(provider, api_key),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, _safe_remote_error(exc)) from exc


# Function: test custom ai
@app.post("/api/settings/ai/test")
def test_custom_ai(req: AITestRequest):
    # Set up values
    provider = str(req.provider or "").strip().lower()
    api_key = str(req.api_key or "").strip()
    model = str(req.model or "").strip()
    # Check condition
    if provider not in AI_CUSTOM_PROVIDERS:
        raise HTTPException(400, "Provider must be Gemini, Groq, OpenRouter, DeepSeek, Perplexity, OpenAI, or Anthropic.")
    # Check condition
    if not api_key:
        raise HTTPException(400, "API key cannot be empty.")
    # Check condition
    if not model:
        raise HTTPException(400, "Model ID cannot be empty.")
    # Try, handle errors
    try:
        answer = _test_custom_model(provider, api_key, model)
        return {
            "success": True,
            "provider": provider,
            "model": model,
            "message": answer,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, _safe_remote_error(exc)) from exc


# Save ai settings
@app.post("/api/settings/ai")
def save_ai_settings(req: AISettingsRequest):
    # Set up values
    mode = str(req.mode or "custom").strip().lower()
    # Check condition
    if mode == "current":
        try:
            if AI_SETTINGS_FILE.exists():
                AI_SETTINGS_FILE.unlink()
        except Exception as exc:
            raise HTTPException(500, f"Could not clear custom AI settings: {exc}") from exc
        return {
            "success": True,
            "mode": "current",
            "provider": "",
            "model": "",
            "has_api_key": False,
        }
    # Check condition
    if mode != "custom":
        raise HTTPException(400, "Mode must be current or custom.")
    _write_ai_settings(req.provider, req.model, req.api_key)
    saved = _read_ai_settings(include_secret=False)
    # Return result
    return {
        "success": True,
        "mode": "custom",
        "provider": saved["provider"],
        "model": saved["model"],
        "has_api_key": True,
    }


# Delete one temporary workbook session when its browser tab closes
@app.post("/api/session/{sid}/close")
def close_session(sid: str):
    """Delete one temporary workbook session when its browser tab closes."""
    # Try, handle errors
    try:
        safe_id = str(uuid.UUID(str(sid)))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, "Invalid workbook session ID")
    SESSIONS.pop(safe_id, None)
    # Return result
    return {"success": True, "message": "Temporary workbook session deleted"}


# Validate a saved workbook session and return reconnect metadata
@app.get("/api/session/{sid}")
def get_session_status(sid: str):
    """Validate a saved workbook session and return reconnect metadata."""
    state = get_session(sid)
    df = state["workspace"].current
    # Return result
    return {
        "sessionId": sid,
        "filename": state["filename"],
        "rowCount": int(len(df)),
        "columnCount": int(len(df.columns)),
        "status": "ready",
    }


# Get dataset schema
@app.get("/api/schema/{sid}")
def get_dataset_schema(sid: str):
    # Set up values
    state = get_session(sid)
    # Return result
    return {
        "filename": state["filename"],
        "profile": state.get("profile", {}),
        "schema": state.get("schema", {}),
    }


# Build a generic, read-only quality profile for any tabular DataFrame
def _data_quality_profile(df: pd.DataFrame) -> dict[str, Any]:
    """Build a generic, read-only quality profile for any tabular DataFrame."""
    row_count, column_count = df.shape
    columns = []
    numeric_columns = []
    date_columns = []
    text_columns = []
    missing_cells = 0
    missing_row_mask = pd.Series(False, index=df.index)
    whitespace_cells = 0
    mixed_type_cells = 0
    category_variations = 0
    outlier_count = 0
    invalid_date_count = 0
    empty_column_count = 0
    parsed_date_series: dict[str, pd.Series] = {}
    # Check if blank
    def is_blank(series: pd.Series) -> pd.Series:
        # Set up values
        blank_mask = series.isna()
        # Check condition
        if pd.api.types.is_object_dtype(series.dtype) or pd.api.types.is_string_dtype(series.dtype):
            blank_mask = blank_mask | series.astype("string").str.strip().eq("").fillna(False)
        # Return result
        return blank_mask
    # Function: fmt dtype
    def fmt_dtype(series: pd.Series) -> str:
        # Return result
        return str(series.dtype)
    # Loop over items
    for column in df.columns:
        series = df[column]
        blank_mask = is_blank(series)
        missing = int(blank_mask.sum())
        missing_cells += missing
        missing_row_mask |= blank_mask
        nonblank = series.loc[~blank_mask]
        unique_count = int(nonblank.nunique(dropna=True))
        dtype_name = fmt_dtype(series)
        if nonblank.empty:
            detected_type = "empty"
            empty_column_count += 1
        elif pd.api.types.is_numeric_dtype(series.dtype):
            detected_type = "numeric"
        elif pd.api.types.is_datetime64_any_dtype(series.dtype):
            detected_type = "datetime"
        else:
            sample = nonblank.astype("string").head(10000)
            numeric_sample = pd.to_numeric(sample.str.replace(",", "", regex=False), errors="coerce")
            numeric_ratio = float(numeric_sample.notna().mean()) if len(sample) else 0.0
            name_hint_date = bool(re.search(
                r"(^|[_\s-])(date|datetime|timestamp|time|dob|birth|created_at|updated_at|"
                r"created_on|modified_at|period)([_\s-]|$)|"
                r"(date|datetime|timestamp|time|created_at|updated_at|created_on|modified_at)$",
                str(column), re.I
            ))
            try:
                parsed_sample = pd.to_datetime(sample, errors="coerce", format="mixed")
            except (TypeError, ValueError):
                parsed_sample = pd.to_datetime(sample, errors="coerce")
            date_ratio = float(parsed_sample.notna().mean()) if len(sample) else 0.0
            if numeric_ratio >= 0.70:
                detected_type = "numeric (stored as text)"
                mixed_type_cells += int(
                    pd.to_numeric(nonblank.astype("string").str.replace(",", "", regex=False),
                                  errors="coerce").isna().sum()
                )
            elif name_hint_date or date_ratio >= 0.80:
                detected_type = "date-like"
            else:
                detected_type = "text"
                if numeric_ratio >= 0.20:
                    mixed_type_cells += int(
                        pd.to_numeric(nonblank.astype("string").str.replace(",", "", regex=False),
                                      errors="coerce").isna().sum()
                    )
        col_info = {
            "column": str(column),
            "dtype": dtype_name,
            "detectedType": detected_type,
            "nonNull": int(len(nonblank)),
            "missing": missing,
            "missingPercent": round((missing / row_count * 100), 3) if row_count else 0,
            "unique": unique_count,
        }
        columns.append(col_info)
        if detected_type in ("numeric", "numeric (stored as text)"):
            numeric = pd.to_numeric(
                series.astype("string").str.replace(",", "", regex=False),
                errors="coerce"
            ).dropna()
            numeric_columns.append({
                "column": str(column),
                "count": int(numeric.count()),
                "missing": missing + int(len(nonblank) - numeric.count()),
                "unique": int(numeric.nunique()),
                "mean": float(numeric.mean()) if len(numeric) else None,
                "std": float(numeric.std()) if len(numeric) > 1 else 0.0 if len(numeric) else None,
                "min": float(numeric.min()) if len(numeric) else None,
                "q25": float(numeric.quantile(0.25)) if len(numeric) else None,
                "median": float(numeric.median()) if len(numeric) else None,
                "q75": float(numeric.quantile(0.75)) if len(numeric) else None,
                "max": float(numeric.max()) if len(numeric) else None,
            })
            if len(numeric) >= 5:
                q1, q3 = numeric.quantile([0.25, 0.75])
                iqr = q3 - q1
                if iqr > 0:
                    outlier_count += int(((numeric < q1 - 1.5 * iqr) |
                                          (numeric > q3 + 1.5 * iqr)).sum())
        elif detected_type in ("datetime", "date-like"):
            if detected_type == "date-like":
                try:
                    parsed = pd.to_datetime(series, errors="coerce", format="mixed")
                except (TypeError, ValueError):
                    parsed = pd.to_datetime(series, errors="coerce")
            else:
                parsed = pd.to_datetime(series, errors="coerce")
            valid = parsed.dropna()
            parsed_date_series[str(column)] = parsed
            invalid = int((~blank_mask & parsed.isna()).sum())
            invalid_date_count += invalid
            date_columns.append({
                "column": str(column),
                "valid": int(valid.size),
                "invalid": invalid,
                "missing": missing,
                "min": valid.min().isoformat() if len(valid) else None,
                "max": valid.max().isoformat() if len(valid) else None,
                "unique": int(valid.nunique()) if len(valid) else 0,
            })
        else:
            text = nonblank.astype("string")
            whitespace_cells += int((text != text.str.strip()).sum())
            normalized = text.str.strip().str.casefold()
            variation_frame = pd.DataFrame({"normalized": normalized, "original": text})
            variation_sizes = variation_frame.groupby("normalized", dropna=True)["original"].nunique()
            category_variations += int((variation_sizes[variation_sizes > 1] - 1).sum())
            top_values = nonblank.astype("string").value_counts(dropna=True).head(8)
            text_columns.append({
                "column": str(column),
                "unique": unique_count,
                "blank": missing,
                "topValues": [{"value": str(value), "count": int(count)}
                              for value, count in top_values.items()],
            })
    # Validate chronology for semantically paired date columns. This is deliberately
    # name-guided: it only compares clearly identifiable start/order dates against
    # end/shipping/delivery dates, rather than making unsafe assumptions about every
    # pair of date columns in an arbitrary dataset.
    start_patterns = re.compile(r"order|purchase|created|booked|start|request|placed", re.I)
    end_patterns = re.compile(r"ship|dispatch|delivery|delivered|complete|closed|fulfilled|end_date|endtime", re.I)
    start_date_columns = [name for name in parsed_date_series if start_patterns.search(name)]
    end_date_columns = [name for name in parsed_date_series if end_patterns.search(name)]
    date_order_violations = 0
    date_order_comparisons = 0
    date_order_pairs = []
    # Loop over items
    for start_name in start_date_columns:
        for end_name in end_date_columns:
            if start_name == end_name:
                continue
            start_values = parsed_date_series[start_name]
            end_values = parsed_date_series[end_name]
            comparable = start_values.notna() & end_values.notna()
            comparisons = int(comparable.sum())
            violations = int((end_values[comparable] < start_values[comparable]).sum())
            date_order_comparisons += comparisons
            date_order_violations += violations
            date_order_pairs.append({
                "startColumn": start_name,
                "endColumn": end_name,
                "comparisons": comparisons,
                "violations": violations,
            })
    # Set up values
    duplicate_mask = df.duplicated(keep="first")
    duplicate_count = int(duplicate_mask.sum())
    # Check condition
    if column_count:
        empty_row_mask = pd.concat(
            [is_blank(df[column]).rename(str(column)) for column in df.columns],
            axis=1
        ).all(axis=1)
    else:
        empty_row_mask = pd.Series(False, index=df.index)
    # Set up values
    empty_row_count = int(empty_row_mask.sum())
    duplicate_sample = df.loc[df.duplicated(keep=False)].head(5).copy()
    duplicate_records = []
    # Loop over items
    for index, row in duplicate_sample.iterrows():
        duplicate_records.append({
            "rowNumber": int(df.index.get_loc(index)) + 1,
            "values": {str(col): (None if pd.isna(value) else str(value))
                       for col, value in row.items()}
        })
    # Return result
    return make_json_safe({
        "rowCount": int(row_count),
        "columnCount": int(column_count),
        "duplicateRows": duplicate_count,
        "rowsWithMissing": int(missing_row_mask.sum()),
        "missingCells": int(missing_cells),
        "invalidDates": int(invalid_date_count),
        "dateOrderViolations": int(date_order_violations),
        "dateOrderComparisons": int(date_order_comparisons),
        "dateOrderPairs": date_order_pairs,
        "whitespaceCells": int(whitespace_cells),
        "mixedTypeCells": int(mixed_type_cells),
        "numericOutliers": int(outlier_count),
        "categoryVariations": int(category_variations),
        "emptyRows": empty_row_count,
        "emptyColumns": empty_column_count,
        "columns": columns,
        "numericSummary": numeric_columns,
        "dateAnalysis": date_columns,
        "textAnalysis": text_columns,
        "duplicateSample": duplicate_records,
        "memoryBytes": int(df.memory_usage(index=True, deep=True).sum()),
    })


# Return full-dataset quality statistics without modifying the workbook
@app.get("/api/data-quality/{sid}")
def get_data_quality_profile(sid: str):
    """Return full-dataset quality statistics without modifying the workbook."""
    state = get_session(sid)
    df = state["workspace"].current
    # Try, handle errors
    try:
        return {
            "sessionId": sid,
            "filename": state["filename"],
            "profile": _data_quality_profile(df),
            "readOnly": True,
        }
    except Exception as exc:
        raise HTTPException(500, f"Could not profile dataset quality: {exc}") from exc


# Get workbook rows
@app.get("/api/rows/{sid}")
def get_workbook_rows(
    sid: str,
    offset: int = 0,
    limit: int = 500,
):
    # Check condition
    if offset < 0:
        raise HTTPException(400, "Offset cannot be negative")
    # Check condition
    if limit < 1 or limit > 2000:
        raise HTTPException(400, "Limit must be between 1 and 2000")
    # Set up values
    state = get_session(sid)
    df = state["workspace"].current
    page = df.iloc[offset:offset + limit]
    # Return result
    return make_json_safe({
        "sessionId": sid,
        "offset": offset,
        "limit": limit,
        "rowCount": len(df),
        "columns": [str(column) for column in df.columns],
        "rows": safe_df(page).to_dict(orient="records"),
    })


# Function: upload
@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
        # Set up values
        raw = await file.read()
        name = file.filename or "dataset.csv"
        # Try, handle errors
        try:
                    low = name.lower()
                    if low.endswith(".csv"):
                            df = pd.read_csv(io.BytesIO(raw))
                    elif low.endswith((".xlsx", ".xls")):
                            df = pd.read_excel(io.BytesIO(raw))
                    elif low.endswith(".json"):
                            df = pd.read_json(io.BytesIO(raw))
                    else:
                            raise ValueError("Supported formats: CSV, XLSX, XLS, JSON")
                    if df.empty:
                            raise ValueError("Dataset has no rows")
                    # Clean column labels into strings so the API response stays consistent.
                    df.columns = [str(column) for column in df.columns]
                    # Profile the dataset and infer likely business meanings for columns.
                    profile = profile_dataframe(df)
                    schema = infer_semantic_schema(df)
                    sid = str(uuid.uuid4())
                    SESSIONS[sid] = {
                        "workspace": make_workspace(df),
                        "filename": name,
                        "profile": profile,
                        "schema": schema,
                        # Cache date bounds during upload so simple year questions
                        # never need to parse one million date values on every chat turn.
                        "date_metadata": _build_dataset_date_metadata(df, schema),
                        "_last_access": time.monotonic(),
                    }
                    return workbook_payload(sid, SESSIONS[sid])
        except HTTPException:
                    raise
        except Exception as exc:
                    raise HTTPException(400, f"Could not read dataset: {exc}") from exc


# Class: session request
class SessionRequest(BaseModel):
        sessionId: str


# Class: edit request
class EditRequest(SessionRequest):
        rows: list[dict[str, Any]]
        columnHeaders: dict[str, str] = {}


# Class: cell patch request
class CellPatchRequest(SessionRequest):
    edits: list[dict[str, Any]]


# Class: column request
class ColumnRequest(SessionRequest):
        column: str


# Class: sort request
class SortRequest(SessionRequest):
        column: str
        ascending: bool = True


# Class: rename request
class RenameRequest(SessionRequest):
        oldName: str
        newName: str


# Class: add column request
class AddColumnRequest(SessionRequest):
        name: str
        expression: str


# Class: type request
class TypeRequest(SessionRequest):
        column: str
        dataType: str


# Class: replace missing request
class ReplaceMissingRequest(SessionRequest):
        column: str
        value: Any


# Class: ask request
class AskRequest(BaseModel):
    # sessionId is optional so general chat can work before a workbook is uploaded.
    sessionId: str | None = None
    question: str
    # The frontend may send recent chat turns to preserve conversational context.
    history: list[dict[str, Any]] = []
    # Selected model provider from the frontend: auto, gemini, gemini2, groq, openrouter, or ollama.
    provider: str = "auto"


# Use the configured AI provider chain to decide whether a question needs
def _classify_question_intent(
    question: str,
    df: pd.DataFrame,
    history: list[dict[str, Any]] | None = None,
    provider: str = "auto",
) -> dict[str, Any]:
    """
    Use the configured AI provider chain to decide whether a question needs
    general knowledge or analysis of the uploaded workbook.

    Only column names and basic workbook dimensions are sent for routing;
    workbook row data is never sent to the intent classifier.
    """
    from ai.analyst import answer_general_chat
    # Set up values
    columns = [str(column) for column in df.columns]
    prompt = {
        "task": (
            "Classify the user's latest question for an AI Analyst that has an "
            "uploaded spreadsheet. Return ONLY one valid JSON object. Do not "
            "answer the question and do not calculate anything."
        ),
        "allowed_intents": ["general_knowledge", "dataset_analysis"],
        "decision_rules": [
            "Use dataset_analysis when the user asks to calculate, count, "
            "aggregate, rank, compare, filter, summarize, or find patterns in "
            "the uploaded workbook, including implicit questions about its "
            "products, customers, sales, revenue, dates, or rows.",
            "Use general_knowledge when the user asks for external facts, "
            "geography, definitions, explanations, education, current affairs, "
            "or general concepts unrelated to workbook contents.",
            "Do not classify a question as dataset_analysis merely because a "
            "word also appears in a column name.",
            "Use the conversation history only to resolve references such as "
            "'it', 'that', or follow-up questions.",
            "If the user explicitly says 'in my dataset', 'in this workbook', "
            "or equivalent, choose dataset_analysis.",
        ],
        "question": question,
        "conversation_history": history[-8:] if isinstance(history, list) else [],
        "workbook_context": {
            "filename_context_only": True,
            "row_count": int(len(df)),
            "column_names": columns[:150],
        },
        "required_json": {
            "intent": "general_knowledge or dataset_analysis",
            "reason": "One short sentence explaining the routing decision",
            "confidence": "high, medium, or low",
        },
    }
    # Local 100K question bank supplies examples for ambiguous intent only.
    # Fast deterministic ranking routes return before this classifier is called.
    try:
        from ai.question_bank import retrieve_question_examples
        prompt["similar_question_examples"] = retrieve_question_examples(question, limit=5)
    except Exception as question_bank_error:
        print(f"[QUESTION BANK] Retrieval unavailable: {question_bank_error}", flush=True)
        prompt["similar_question_examples"] = []
    # Set up values
    started = time.perf_counter()
    result = answer_general_chat(
        "Classify this request. Return only the required JSON.\n\n"
        + json.dumps(prompt, ensure_ascii=False),
        history=None,
        provider=provider,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    raw = ""
    provider = None
    # Check condition
    if isinstance(result, dict):
        raw = str(result.get("answer") or "").strip()
        provider = result.get("provider")
        # Accommodate providers that return structured fields directly.
        if result.get("intent") in ("general_knowledge", "dataset_analysis"):
            parsed = result
        else:
            parsed = None
    else:
        raw = str(result).strip()
        parsed = None
    # Check condition
    if parsed is None:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I)
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            raise ValueError("Intent classifier did not return valid JSON.")
        parsed = json.loads(match.group(0))
    # Set up values
    intent = str(parsed.get("intent", "")).strip().lower()
    # Check condition
    if intent not in ("general_knowledge", "dataset_analysis"):
        raise ValueError(f"Intent classifier returned unsupported intent: {intent!r}")
    # Return result
    return {
        "intent": intent,
        "reason": str(parsed.get("reason") or "").strip(),
        "confidence": str(parsed.get("confidence") or "unknown").strip().lower(),
        "provider": provider,
        "elapsed_ms": elapsed_ms,
    }


# Return dataset_analysis only for clearly workbook-specific questions
def _fast_dataset_question_intent(question: str) -> str | None:
    """Return dataset_analysis only for clearly workbook-specific questions.

    This avoids an extra LLM round-trip for common spreadsheet questions while
    leaving ambiguous questions on the existing AI classifier path.
    """
    q = re.sub(r"\s+", " ", str(question or "").lower()).strip()
    strong_dataset_markers = (
        "in my dataset", "in this dataset", "in the dataset",
        "in my workbook", "in this workbook", "in the workbook",
        "in my spreadsheet", "in this spreadsheet",
        "uploaded dataset", "uploaded file", "this table", "these records",
        "data quality", "missing values", "missing value", "null values",
        "duplicate rows", "duplicate records", "duplicate values",
        "outliers", "negative quantity", "negative quantities",
        "negative price", "negative prices", "invoice date",
        "customer id", "stock code", "unit price", "top selling",
        "best selling", "least selling", "monthly sales", "total revenue",
        "average order value", "how many rows", "number of rows",
        "customers spent", "customer spent", "spent more than",
        "spent over", "customer spend", "customer spending",
        "how many customers", "top products", "top customers",
    )
    # Check condition
    if any(marker in q for marker in strong_dataset_markers):
        return "dataset_analysis"
    # Return result
    return None


# Skip the separate LLM intent-classifier call for obvious general questions
def _fast_general_question_intent(question: str) -> str | None:
    """Skip the separate LLM intent-classifier call for obvious general questions."""
    q = re.sub(r"\s+", " ", str(question or "").lower()).strip()
    # Explicit workbook references always take precedence over this shortcut.
    workbook_markers = (
        "dataset", "spreadsheet", "workbook", "uploaded file",
        "in this table", "in these records", "in my data",
        "in this data", "in the data",
    )
    # Check condition
    if any(marker in q for marker in workbook_markers):
        return None
    # Set up values
    general_markers = (
        "explain ", "define ", "meaning of ", "difference between ",
        "what is ", "what are ",
        "what is the difference", "what are the differences",
        "how does ", "how do ", "why does ", "why do ",
        "who is ", "who was ", "who said ", "who says ",
        "who invented ", "who created ", "who wrote ",
        "when was ", "where is ", "what color is ", "what colour is ",
        "capital of ", "population of ", "richest person", "largest company",
    )
    # Check condition
    if any(marker in q for marker in general_markers):
        return "general_knowledge"
    # Return result
    return None


# Conservative keyword fallback used only if the AI classifier fails
def _fallback_question_intent(question: str) -> str:
    """Conservative keyword fallback used only if the AI classifier fails."""
    q = str(question or "").lower()
    dataset_markers = (
        "dataset", "spreadsheet", "workbook", "uploaded data",
        "in my data", "in this data", "in the data", "in this table",
        "in these records", "in the file", "in this file", "column",
        "rows", "transactions", "invoice", "customer", "stock code",
        "product", "products", "quantity", "unit price", "revenue",
        "sales", "orders", "monthly sales", "top selling",
        "best selling", "most sold", "highest revenue",
    )
    general_markers = (
        "explain ", "define ", "meaning of ", "what is ", "what are ",
        "how does ", "how do ", "why does ", "why do ", "who is ",
        "who was ", "when was ", "where is ", "where are ",
        "capital of ", "population of ", "gdp of ", "biggest ",
        "largest ", "smallest ", "tallest ", "longest ", "area of ",
        "taluka ", "district ", "village ", "prime minister ",
        "president of ", "weather ", "exchange rate",
    )
    # Check condition
    if any(marker in q for marker in dataset_markers):
        return "dataset_analysis"
    # Check condition
    if any(marker in q for marker in general_markers):
        return "general_knowledge"
    # When the classifier is unavailable and the wording is ambiguous,
    # keep the request on the workbook path rather than inventing external facts.
    return "dataset_analysis"


# Class: search request
class SearchRequest(SessionRequest):
        query: str


# Function: edit
@app.post("/api/edit")
def edit(req: EditRequest):
        # Set up values
        state = get_session(req.sessionId)
        current = state["workspace"].current
        df = pd.DataFrame(req.rows)
        # Blank worksheet columns use internal field IDs in the browser. Convert only
        # columns that contain user-entered values to Excel-style headers (I, J, K...).
        # Drop any internal blank-column fields that were never used.
        internal_blank_fields = [c for c in df.columns if str(c).startswith("__blank_col_")]
        used_blank_fields = []
        # Loop over items
        for field in internal_blank_fields:
                    has_value = df[field].map(
                            lambda value: value is not None and not (isinstance(value, float) and math.isnan(value)) and str(value).strip() != ""
                    ).any()
                    if has_value and field in req.columnHeaders:
                            used_blank_fields.append(field)
        # Set up values
        df = df.drop(columns=[c for c in internal_blank_fields if c not in used_blank_fields], errors="ignore")
        # Check condition
        if used_blank_fields:
                    df = df.rename(columns={key: req.columnHeaders[key] for key in used_blank_fields})
        # Preserve existing column order, then append any new columns created in the grid.
        for column in current.columns:
                    if column not in df.columns:
                            df[column] = None
        # Set up values
        new_columns = [column for column in df.columns if column not in current.columns]
        df = df[list(current.columns) + new_columns]
        # Ignore entirely empty rows at the end; keep blank rows in the middle if a user
        # deliberately enters data farther down the worksheet.
        def row_is_blank(row):
                    # Return result
                    return all(value is None or (isinstance(value, float) and math.isnan(value)) or str(value).strip() == "" for value in row)
        # Repeat until done
        while len(df) > len(current) and row_is_blank(df.iloc[-1].tolist()):
                    df = df.iloc[:-1]
        state["workspace"].replace_dataframe(
                    df, operation="edit_cells", details={"source": "web_grid", "rows": len(df), "new_columns": new_columns}
        )
        _refresh_dataset_metadata(state)
        persist_session(req.sessionId, state)
        # Return result
        return workbook_payload(req.sessionId, state)


# Function: edit cells
@app.post("/api/edit-cells")
def edit_cells(req: CellPatchRequest):
    # Set up values
    state = get_session(req.sessionId)
    workspace = state["workspace"]
    current = workspace.current
    # Check condition
    if len(req.edits) > 2000:
        raise HTTPException(
            status_code=400,
            detail="Maximum 2000 cell edits per request",
        )
    # Validate all edits before applying any of them.
    for edit in req.edits:
        row_index = edit.get("rowIndex")
        column = edit.get("column")
        if not isinstance(row_index, int) or isinstance(row_index, bool):
            raise HTTPException(
                status_code=400,
                detail="rowIndex must be an integer",
            )
        if row_index < 0 or row_index >= len(current):
            raise HTTPException(
                status_code=400,
                detail="Row index is outside the dataset",
            )
        if column not in current.columns:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown column: {column}",
            )
    # Check condition
    if not req.edits:
        _refresh_dataset_metadata(state)
        persist_session(req.sessionId, state)
        return workbook_payload(req.sessionId, state)
    # Set up values
    updated = current.copy(deep=True)
    # Loop over items
    for edit in req.edits:
        updated.at[edit["rowIndex"], edit["column"]] = edit.get("value")
    workspace.replace_dataframe(
        updated,
        operation="edit_cells",
        details={
            "source": "web_grid_partial",
            "cell_count": len(req.edits),
        },
    )
    persist_session(req.sessionId, state)
    # Return result
    return workbook_payload(req.sessionId, state)


# Function: undo
@app.post("/api/undo")
def undo(req: SessionRequest):
        # Set up values
        state = get_session(req.sessionId)
        workspace = state["workspace"]
        # Check condition
        if not getattr(workspace, "can_undo", False):
                    raise HTTPException(400, "Nothing to undo")
        workspace.undo()
        _refresh_dataset_metadata(state)
        persist_session(req.sessionId, state)
        # Return result
        return workbook_payload(req.sessionId, state)


# Function: redo
@app.post("/api/redo")
def redo(req: SessionRequest):
        # Set up values
        state = get_session(req.sessionId)
        workspace = state["workspace"]
        # Check condition
        if not getattr(workspace, "can_redo", False):
                    raise HTTPException(400, "Nothing to redo")
        workspace.redo()
        _refresh_dataset_metadata(state)
        persist_session(req.sessionId, state)
        # Return result
        return workbook_payload(req.sessionId, state)


# Function: reset
@app.post("/api/reset")
def reset(req: SessionRequest):
        # Set up values
        state = get_session(req.sessionId)
        state["workspace"].reset()
        _refresh_dataset_metadata(state)
        persist_session(req.sessionId, state)
        # Return result
        return workbook_payload(req.sessionId, state)


# Function: duplicates
@app.post("/api/duplicates")
def duplicates(req: SessionRequest):
        # Set up values
        state = get_session(req.sessionId)
        result = state["workspace"].remove_duplicates()
        _refresh_dataset_metadata(state)
        persist_session(req.sessionId, state)
        payload = workbook_payload(req.sessionId, state)
        payload["message"] = f"Removed {result.get('rows_removed', 0)} duplicate rows"
        # Return result
        return payload


# Function: sort rows
@app.post("/api/sort")
def sort_rows(req: SortRequest):
        # Set up values
        state = get_session(req.sessionId)
        workspace = state["workspace"]
        # Check condition
        if req.column not in workspace.current.columns:
                    raise HTTPException(400, "Unknown column")
        workspace.sort_values(req.column, ascending=req.ascending)
        persist_session(req.sessionId, state)
        # Return result
        return workbook_payload(req.sessionId, state)


# Function: rename
@app.post("/api/rename")
def rename(req: RenameRequest):
        # Set up values
        state = get_session(req.sessionId)
        workspace = state["workspace"]
        # Try, handle errors
        try:
                    workspace.rename_column(req.oldName, req.newName)
        except Exception as exc:
                    raise HTTPException(400, str(exc)) from exc
        _refresh_dataset_metadata(state)
        persist_session(req.sessionId, state)
        # Return result
        return workbook_payload(req.sessionId, state)


# Function: remove column
@app.post("/api/remove-column")
def remove_column(req: ColumnRequest):
        # Set up values
        state = get_session(req.sessionId)
        # Try, handle errors
        try:
                    state["workspace"].remove_column(req.column)
        except Exception as exc:
                    raise HTTPException(400, str(exc)) from exc
        _refresh_dataset_metadata(state)
        persist_session(req.sessionId, state)
        # Return result
        return workbook_payload(req.sessionId, state)


# Function: convert type
@app.post("/api/type")
def convert_type(req: TypeRequest):
        # Set up values
        state = get_session(req.sessionId)
        # Try, handle errors
        try:
                    state["workspace"].convert_column_type(req.column, req.dataType)
        except Exception as exc:
                    raise HTTPException(400, str(exc)) from exc
        _refresh_dataset_metadata(state)
        persist_session(req.sessionId, state)
        # Return result
        return workbook_payload(req.sessionId, state)


# Function: replace missing
@app.post("/api/replace-missing")
def replace_missing(req: ReplaceMissingRequest):
        # Set up values
        state = get_session(req.sessionId)
        # Try, handle errors
        try:
                    state["workspace"].replace_missing(req.column, req.value)
        except Exception as exc:
                    raise HTTPException(400, str(exc)) from exc
        _refresh_dataset_metadata(state)
        persist_session(req.sessionId, state)
        # Return result
        return workbook_payload(req.sessionId, state)


# Function: add column
@app.post("/api/add-column")
def add_column(req: AddColumnRequest):
        # Set up values
        state = get_session(req.sessionId)
        workspace = state["workspace"]
        df = workspace.current
        # Check condition
        if not req.name.strip() or req.name in df.columns:
                    raise HTTPException(400, "Enter a new, unique column name")
        # Permit basic arithmetic expressions and column names; pandas evaluates them.
        if not re.fullmatch(r"[A-Za-z0-9_ .()+*/%\-]+", req.expression.strip()):
                    raise HTTPException(
                            400, "Use column names, numbers, parentheses and + - * / % only"
                    )
        # Try, handle errors
        try:
                    values = df.eval(req.expression, engine="python")
                    workspace.create_column(
                            column_name=req.name.strip(),
                            values=values,
                            description=f"Formula: {req.expression}",
                    )
        except Exception as exc:
                    raise HTTPException(400, f"Formula could not be evaluated: {exc}") from exc
        _refresh_dataset_metadata(state)
        persist_session(req.sessionId, state)
        # Return result
        return workbook_payload(req.sessionId, state)


# Function: search
@app.post("/api/search")
def search(req: SearchRequest):
        # Set up values
        state = get_session(req.sessionId)
        df = state["workspace"].current
        # Check condition
        if not req.query.strip():
                    return {"rows": safe_df(df.head(500)).to_dict(orient="records"), "matches": len(df)}
        # Set up values
        mask = df.astype(str).apply(
                    lambda column: column.str.contains(
                            re.escape(req.query), case=False, na=False
                    )
        ).any(axis=1)
        # Return result
        return {
                    "rows": safe_df(df.loc[mask].head(500)).to_dict(orient="records"),
                    "matches": int(mask.sum()),
        }


# Find a column by case-insensitive name, allowing spaces and underscores
def _find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Find a column by case-insensitive name, allowing spaces and underscores."""
    normalized = {
        re.sub(r"[^a-z0-9]", "", str(column).lower()): str(column)
        for column in df.columns
    }
    # Loop over items
    for candidate in candidates:
        key = re.sub(r"[^a-z0-9]", "", candidate.lower())
        if key in normalized:
            return normalized[key]
    # Return result
    return None


# Resolve an accepted semantic mapping, then safely fall back to column names
def _semantic_column(
    df: pd.DataFrame,
    schema: dict[str, Any] | None,
    semantic_key: str,
    fallback_candidates: list[str],
) -> str | None:
    """Resolve an accepted semantic mapping, then safely fall back to column names."""
    schema = schema if isinstance(schema, dict) else {}
    mappings = schema.get("mappings", {})
    mapping = mappings.get(semantic_key, {}) if isinstance(mappings, dict) else {}
    # Check condition
    if isinstance(mapping, dict):
        mapped_column = mapping.get("column") or mapping.get("column_name")
        confidence = mapping.get("confidence", 0)
        try:
            confidence = float(confidence)
            if confidence > 1:
                confidence /= 100.0
        except (TypeError, ValueError):
            confidence = 0.0
        status = str(mapping.get("status", "")).strip().lower()
        if (
            status == "accepted"
            and mapped_column is not None
            and str(mapped_column) in df.columns
            and confidence >= 0.90
        ):
            return str(mapped_column)
    # Return result
    return _find_column(df, fallback_candidates)


# Trim identifiers and remove common textual nulls without changing valid codes
def _clean_identifier_values(series: pd.Series) -> pd.Series:
    """Trim identifiers and remove common textual nulls without changing valid codes."""
    values = series.astype("string").str.strip()
    values = values.replace({"": pd.NA, "nan": pd.NA, "none": pd.NA, "null": pd.NA, "<na>": pd.NA})
    # Return result
    return values.str.replace(r"\.0$", "", regex=True)


# Parse common text dates, pandas dates, and Excel serial dates
def _parse_date_values(series: pd.Series) -> pd.Series:
    """Parse common text dates, pandas dates, and Excel serial dates."""
    # Check condition
    if pd.api.types.is_numeric_dtype(series):
        numeric = pd.to_numeric(series, errors="coerce")
        return pd.to_datetime(numeric, unit="D", origin="1899-12-30", errors="coerce")
    # Try, handle errors
    try:
        return pd.to_datetime(series, errors="coerce", format="mixed")
    except (TypeError, ValueError):
        return pd.to_datetime(series, errors="coerce")


# Parse the dataset date column once and cache its observed date range
def _build_dataset_date_metadata(
    df: pd.DataFrame, schema: dict[str, Any] | None
) -> dict[str, Any]:
    """Parse the dataset date column once and cache its observed date range."""
    date_col = _semantic_column(
        df, schema, "date",
        ["InvoiceDate", "Invoice Date", "Date", "OrderDate", "Order Date"],
    )
    # Check condition
    if not date_col:
        return {"available": False, "reason": "No date column was identified."}
    # Set up values
    parsed = _parse_date_values(df[date_col]).dropna()
    # Check condition
    if parsed.empty:
        return {
            "available": False,
            "column": str(date_col),
            "reason": "The date column contains no parseable dates.",
        }
    # Set up values
    minimum = parsed.min()
    maximum = parsed.max()
    # Return result
    return {
        "available": True,
        "column": str(date_col),
        "min_date": minimum.date().isoformat(),
        "max_date": maximum.date().isoformat(),
        "years": sorted(int(year) for year in parsed.dt.year.dropna().unique()),
        "valid_date_rows": int(parsed.size),
    }


# Refresh cached profile, semantic schema, and date metadata after
def _refresh_dataset_metadata(state: dict[str, Any]) -> None:
    """
    Refresh cached profile, semantic schema, and date metadata after
    a successful dataset or schema modification.

    If profiling fails, clear the cached metadata rather than leaving
    stale metadata that could mislead later analysis.
    """
    df = state["workspace"].current
    # Try, handle errors
    try:
        profile = profile_dataframe(df)
        schema = infer_semantic_schema(df)
        date_metadata = _build_dataset_date_metadata(df, schema)
        state["profile"] = profile
        state["schema"] = schema
        state["date_metadata"] = date_metadata
        state.pop("metadata_refresh_error", None)
    except Exception as exc:
        state["profile"] = {}
        state["schema"] = {}
        state["date_metadata"] = {
            "available": False,
            "reason": "Date metadata could not be refreshed.",
        }
        state["metadata_refresh_error"] = str(exc)


# Return semantic quantity/price columns and aligned numeric revenue components
def _revenue_components(
    df: pd.DataFrame, schema: dict[str, Any] | None
) -> tuple[str | None, str | None, pd.Series | None, pd.Series | None, pd.Series | None]:
    """Return semantic quantity/price columns and aligned numeric revenue components."""
    quantity_col = _semantic_column(df, schema, "quantity", ["quantity", "qty", "units"])
    price_col = _semantic_column(df, schema, "unit_price", ["price", "unit price", "unitprice", "selling price", "item price"])
    # Check condition
    if not quantity_col or not price_col:
        return quantity_col, price_col, None, None, None
    # Set up values
    quantity = pd.to_numeric(df[quantity_col], errors="coerce")
    price = pd.to_numeric(df[price_col], errors="coerce")
    valid = quantity.notna() & price.notna()
    revenue = quantity * price
    # Return result
    return quantity_col, price_col, quantity, price, valid


# Rank identifiable merchandise returns and report unidentified returns separately
def _product_return_analysis_answer(
    df: pd.DataFrame,
    schema: dict[str, Any] | None = None,
    limit: int = 10,
) -> dict[str, Any] | None:
    """Rank identifiable merchandise returns and report unidentified returns separately."""
    product_id_col = _semantic_column(
        df, schema, "product_id",
        ["stock_code", "stock code", "product_id", "product id",
        "item code", "product code"],
    )
    product_name_col = _semantic_column(
        df, schema, "product",
        ["description", "product", "product name", "item description", "name"],
    )
    quantity_col = _semantic_column(
        df, schema, "quantity", ["quantity", "qty", "units"]
    )
    price_col = _semantic_column(
        df, schema, "unit_price",
        ["price", "unit price", "unitprice", "selling price"],
    )
    invoice_col = _semantic_column(
        df, schema, "invoice_id",
        ["invoice", "invoice id", "invoice number", "invoice no",
        "order id", "order number"],
    )
    # Check condition
    if not all([product_id_col, quantity_col, price_col]):
        return None
    # Set up values
    product_ids = _clean_identifier_values(df[product_id_col])
    quantity = pd.to_numeric(df[quantity_col], errors="coerce")
    price = pd.to_numeric(df[price_col], errors="coerce")
    valid = product_ids.notna() & quantity.notna() & price.notna()
    # Check condition
    if not valid.any():
        return None
    # Set up values
    work = pd.DataFrame({
        "product_id": product_ids[valid],
        "quantity": quantity[valid],
        "revenue": quantity[valid] * price[valid],
    })
    # Check condition
    if product_name_col:
        work["product_name"] = (
            df.loc[valid, product_name_col].astype("string").str.strip()
        ).fillna("")
    else:
        work["product_name"] = ""
    # Check condition
    if invoice_col:
        work["invoice"] = _clean_identifier_values(df.loc[valid, invoice_col])
    else:
        work["invoice"] = pd.NA
    # Exclude transaction/adjustment rows at row level, not by dropping an
    # entire product code. Valid merchandise rows for the same code remain.
    non_product_codes = {
        "M", "AMAZONFEE", "BANKCHARGES", "POST", "D", "CRUK", "SAMPLES",
    }
    normalized_codes = (
        work["product_id"].astype("string").str.strip().str.upper()
        .str.replace(r"[^A-Z0-9]", "", regex=True)
    )
    normalized_names = (
        work["product_name"].astype("string").str.strip().str.lower()
        .str.replace(r"\s+", " ", regex=True)
    )
    exact_non_product_names = {
        "manual", "amazon fee", "bank charges", "bank charge", "postage",
        "discount", "cruk commission", "given away", "sample", "samples",
    }
    adjustment_name_pattern = (
        r"\b(?:damaged?|damages|lost|thrown\s+away|written\s+off|"
        r"write[- ]?off|adjustment)\b"
    )
    excluded_by_code = normalized_codes.isin(non_product_codes)
    excluded_by_name = (
        normalized_names.isin(exact_non_product_names)
        | normalized_names.str.contains(
            adjustment_name_pattern, regex=True, na=False
        )
    )
    excluded_non_product = excluded_by_code | excluded_by_name
    excluded_non_product_count = int(excluded_non_product.sum())
    excluded_non_product_ids = sorted(
        work.loc[excluded_non_product, "product_id"]
        .dropna().astype(str).unique().tolist()
    )
    work = work.loc[~excluded_non_product].copy()
    # Check condition
    if work.empty:
        return None
    # Missing descriptions are not confidently identifiable merchandise.
    # Keep their return activity visible, but do not rank them as products.
    work["has_product_name"] = work["product_name"].astype("string").str.strip().ne("")
    unidentified = work.loc[
        (~work["has_product_name"]) & (work["quantity"] < 0)
    ].copy()
    unidentified["returned_quantity"] = -unidentified["quantity"]
    unidentified_by_code = (
        unidentified.groupby("product_id", dropna=True)
        .agg(
            returned_quantity=("returned_quantity", "sum"),
            returned_value_signed=("revenue", "sum"),
            return_invoice_count=("invoice", "nunique"),
        )
        .reset_index()
    )
    unidentified_by_code["returned_value"] = (
        unidentified_by_code["returned_value_signed"].abs()
    )
    unidentified_by_code.drop(columns=["returned_value_signed"], inplace=True)
    unidentified_by_code = unidentified_by_code.sort_values(
        ["returned_quantity", "returned_value"],
        ascending=[False, False],
        kind="stable",
    )
    unidentified_return_quantity = float(
        unidentified["returned_quantity"].sum()
    )
    unidentified_return_value = float(
        unidentified["revenue"].sum()
    )
    unidentified_return_value = abs(unidentified_return_value)
    unidentified_return_rows = int(len(unidentified))
    work = work.loc[work["has_product_name"]].copy()
    # Check condition
    if work.empty:
        return None
    # Set up values
    is_return = work["quantity"] < 0
    work["returned_quantity"] = (-work["quantity"]).where(is_return, 0)
    work["returned_value_signed"] = work["revenue"].where(is_return, 0)
    work["sales_quantity"] = work["quantity"].where(work["quantity"] > 0, 0)
    work["return_invoice"] = work["invoice"].where(is_return)
    # Function: best product name
    def best_product_name(values: pd.Series) -> str:
        # Set up values
        names = values.dropna().astype(str).str.strip()
        names = names[names.ne("")]
        modes = names.mode()
        # Return result
        return str(modes.iloc[0]) if not modes.empty else ""
    # Set up values
    grouped = work.groupby("product_id", dropna=True).agg(
        returned_quantity=("returned_quantity", "sum"),
        returned_value_signed=("returned_value_signed", "sum"),
        total_sales_quantity=("sales_quantity", "sum"),
        return_invoice_count=("return_invoice", "nunique"),
        product_name=("product_name", best_product_name),
    ).reset_index()
    grouped["returned_value"] = grouped["returned_value_signed"].abs()
    grouped.drop(columns=["returned_value_signed"], inplace=True)
    grouped = grouped[grouped["returned_quantity"] > 0].copy()
    # Check condition
    if grouped.empty:
        return None
    # Set up values
    grouped["return_rate_percentage"] = (
        grouped["returned_quantity"]
        .div(grouped["total_sales_quantity"].where(
            grouped["total_sales_quantity"] > 0
        ))
        .mul(100)
    )
    grouped["returned_exceeds_sales"] = (
        grouped["returned_quantity"] > grouped["total_sales_quantity"]
    )
    top_quantity = grouped.sort_values(
        ["returned_quantity", "returned_value"],
        ascending=[False, False],
        kind="stable",
    ).head(max(1, min(int(limit), 100)))
    top_value = grouped.sort_values(
        ["returned_value", "returned_quantity"],
        ascending=[False, False],
        kind="stable",
    ).head(max(1, min(int(limit), 100)))
    flagged = grouped.loc[grouped["returned_exceeds_sales"]].sort_values(
        ["returned_quantity", "returned_value"],
        ascending=[False, False],
        kind="stable",
    )
    # Function: render table
    def render_table(frame: pd.DataFrame) -> list[str]:
        # Set up values
        lines = [
            "| Product | Product code | Returned quantity | Returned value | "
            "Positive sales quantity | Return rate | Return invoices |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
        # Loop over items
        for row in frame.itertuples(index=False):
            rate = (
                f"{float(row.return_rate_percentage):.2f}%"
                if pd.notna(row.return_rate_percentage) else "N/A"
            )
            invoice_count = (
                f"{int(row.return_invoice_count):,}"
                if invoice_col else "Unavailable"
            )
            lines.append(
                f"| {str(row.product_name).strip()} | {row.product_id} "
                f"| {float(row.returned_quantity):,.0f} "
                f"| {float(row.returned_value):,.2f} "
                f"| {float(row.total_sales_quantity):,.0f} "
                f"| {rate} | {invoice_count} |"
            )
        # Return result
        return lines
    # Function: records
    def records(frame: pd.DataFrame) -> list[dict[str, Any]]:
        # Set up values
        output = []
        # Loop over items
        for row in frame.to_dict(orient="records"):
            output.append({
                key: (
                    None if pd.isna(value)
                    else value.item() if hasattr(value, "item")
                    else value
                )
                for key, value in row.items()
            })
        # Return result
        return output
    # Set up values
    answer_lines = [
        "## Top identifiable products by returned quantity",
        *render_table(top_quantity),
        "",
        "## Top identifiable products by returned value",
        *render_table(top_value),
        "",
        "## Data-quality flags",
        (
            f"Found **{len(flagged):,} identifiable products** where returned "
            "quantity exceeds positive sales quantity."
        ),
    ]
    # Check condition
    if not flagged.empty:
        answer_lines.extend([
            "",
            "| Product | Product code | Returned quantity | Positive sales quantity | Excess returned quantity | Return rate |",
            "|---|---|---:|---:|---:|---:|",
        ])
        for row in flagged.head(50).itertuples(index=False):
            rate = (
                f"{float(row.return_rate_percentage):.2f}%"
                if pd.notna(row.return_rate_percentage) else "N/A"
            )
            excess = float(row.returned_quantity) - float(row.total_sales_quantity)
            answer_lines.append(
                f"| {str(row.product_name).strip()} | {row.product_id} "
                f"| {float(row.returned_quantity):,.0f} "
                f"| {float(row.total_sales_quantity):,.0f} "
                f"| {excess:,.0f} | {rate} |"
            )
        if len(flagged) > 50:
            answer_lines.append(
                f"Showing the first 50 of {len(flagged):,} flagged products; "
                "the complete list is available in the API details."
            )
    else:
        answer_lines.append("No identifiable products exceeded their positive sales quantity.")
    answer_lines.extend([
        "",
        "## Unidentified returns (description missing)",
        (
            f"Found **{unidentified_return_rows:,} return rows** with missing "
            f"product descriptions: **{unidentified_return_quantity:,.0f} units** "
            f"and **{unidentified_return_value:,.2f} return value**. "
            "These are reported separately and are not included in genuine-product rankings."
        ),
    ])
    # Check condition
    if not unidentified_by_code.empty:
        answer_lines.extend([
            "",
            "| Product code | Unidentified returned quantity | Returned value | Return invoices |",
            "|---|---:|---:|---:|",
        ])
        for row in unidentified_by_code.head(50).itertuples(index=False):
            answer_lines.append(
                f"| {row.product_id} | {float(row.returned_quantity):,.0f} "
                f"| {float(row.returned_value):,.2f} "
                f"| {int(row.return_invoice_count):,} |"
            )
    answer_lines.extend([
        "",
        "## Excluded non-product / adjustment transactions",
        (
            f"Excluded **{excluded_non_product_count:,} transaction rows** "
            "from this return analysis."
        ),
        (
            f"These rows affected **{len(excluded_non_product_ids):,} distinct "
            "product/transaction codes** (a code is listed if at least one of "
            "its rows was excluded): "
            + (", ".join(excluded_non_product_ids) if excluded_non_product_ids else "None")
            + "."
        ),
        "Excluded descriptions include manual entries, fees, bank charges, postage, discounts, commissions, samples, and adjustment/condition notes such as damaged, damages, lost, thrown away, and written off.",
        "",
        "## Calculation methodology",
        "- Returned quantity = absolute sum of negative quantities.",
        "- Returned value = absolute net sum of negative quantity × unit price.",
        "- Positive sales quantity = sum of positive quantities.",
        "- Return rate = returned quantity ÷ positive sales quantity × 100.",
        "- Return invoices = distinct invoices containing negative quantities.",
        "- Rows with missing product descriptions are separated as unidentified returns.",
        "- Return rate is N/A when positive sales quantity is zero.",
        "- Returned quantity above positive sales quantity is flagged; this may reflect incomplete date coverage or inconsistent source records and should be investigated.",
        "- The dataset has no return-reason field, so it cannot explain why items were returned.",
        "- Exclusions apply only to this return analysis; the uploaded workbook and other analyses are unchanged.",
    ])
    # Return result
    return {
        "answer": "\n".join(answer_lines),
        "details": {
            "analysis": "product_return_analysis",
            "product_id_column": product_id_col,
            "product_name_column": product_name_col,
            "quantity_column": quantity_col,
            "price_column": price_col,
            "invoice_column": invoice_col,
            "top_by_returned_quantity": records(top_quantity),
            "top_by_returned_value": records(top_value),
            "products_returned_exceeds_sales": records(flagged),
            "products_returned_exceeds_sales_count": int(len(flagged)),
            "unidentified_return_rows": unidentified_return_rows,
            "unidentified_return_quantity": unidentified_return_quantity,
            "unidentified_return_value": unidentified_return_value,
            "unidentified_returns_by_product_code": records(unidentified_by_code),
            "excluded_non_product_transaction_rows": excluded_non_product_count,
            "excluded_non_product_distinct_codes_affected": len(excluded_non_product_ids),
            "excluded_non_product_codes_with_at_least_one_excluded_row": excluded_non_product_ids,
            "non_product_exclusion_applied": True,
            "missing_product_descriptions_separated": True,
            "returns_identified_by_negative_quantity": True,
            "return_rate_denominator": "positive sales quantity",
            "return_invoice_count_available": bool(invoice_col),
        },
    }


# Return best- and least-selling products using signed net quantity
def _product_quantity_extremes_answer(
    df: pd.DataFrame,
    schema: dict[str, Any] | None = None,
    limit: int = 10,
) -> dict[str, Any] | None:
    """Return best- and least-selling products using signed net quantity."""
    product_id_col = _semantic_column(
        df, schema, "product_id", ["stock_code", "stock code", "product_id", "product id", "item code", "product code"]
    )
    product_name_col = _semantic_column(
        df, schema, "product", ["description", "product", "product name", "item description", "name"]
    )
    quantity_col = _semantic_column(df, schema, "quantity", ["quantity", "qty", "units"])
    price_col = _semantic_column(df, schema, "unit_price", ["price", "unit price", "unitprice", "selling price"])
    invoice_col = _semantic_column(df, schema, "order_id", ["invoice", "invoice number", "order id", "order number"])
    # Check condition
    if not product_id_col or not quantity_col or not price_col:
        return None
    # Set up values
    product_ids = _clean_identifier_values(df[product_id_col])
    quantity = pd.to_numeric(df[quantity_col], errors="coerce")
    price = pd.to_numeric(df[price_col], errors="coerce")
    valid = product_ids.notna() & quantity.notna() & price.notna()
    # Check condition
    if not valid.any():
        return None
    # Set up values
    work = pd.DataFrame({
        "product_id": product_ids[valid],
        "net_quantity": quantity[valid],
        "revenue": quantity[valid] * price[valid],
    })
    # Check condition
    if product_name_col:
        work["product_name"] = df.loc[valid, product_name_col].astype("string").str.strip()
    else:
        work["product_name"] = ""
    # Check condition
    if invoice_col:
        work["invoice"] = _clean_identifier_values(df.loc[valid, invoice_col])
    else:
        work["invoice"] = pd.NA
    # Set up values
    grouped = work.groupby("product_id", dropna=True).agg(
        net_quantity=("net_quantity", "sum"),
        total_revenue=("revenue", "sum"),
        transaction_rows=("product_id", "size"),
        transaction_count=("invoice", "nunique"),
        product_name=("product_name", lambda values: values.dropna().loc[lambda x: x.ne("")].mode().iloc[0] if not values.dropna().loc[lambda x: x.ne("")].mode().empty else ""),
    ).reset_index()
    # A product with zero net units is intentionally excluded as requested.
    grouped = grouped.loc[grouped["net_quantity"] != 0].copy()
    # Check condition
    if grouped.empty:
        return None
    # Set up values
    top = grouped.sort_values(["net_quantity", "total_revenue"], ascending=[False, False], kind="stable").head(limit)
    bottom = grouped.sort_values(["net_quantity", "total_revenue"], ascending=[True, True], kind="stable").head(limit)
    # Function: render table
    def render_table(frame: pd.DataFrame) -> list[str]:
        # Set up values
        lines = ["| Product | Product code | Net quantity | Total revenue | Transaction count |", "|---|---|---:|---:|---:|"]
        # Loop over items
        for row in frame.itertuples(index=False):
            name = str(row.product_name).strip() or "Product name unavailable"
            count = int(row.transaction_count) if invoice_col else int(row.transaction_rows)
            lines.append(f"| {name} | {row.product_id} | {float(row.net_quantity):,.0f} | {float(row.total_revenue):,.2f} | {count:,} |")
        # Return result
        return lines
    # Set up values
    transaction_definition = "distinct invoices per product" if invoice_col else "transaction rows (invoice column unavailable)"
    answer_lines = [
        "## Best-selling products by net quantity",
        *render_table(top),
        "",
        "## Least-selling products by net quantity",
        *render_table(bottom),
        "",
        "Returns are included: negative quantities reduce net quantity and signed revenue.",
        "Products with exactly zero net quantity are excluded.",
        f"Transaction count means {transaction_definition}.",
    ]
    # Return result
    return {
        "answer": "\n".join(answer_lines),
        "details": {
            "analysis": "product_quantity_extremes",
            "product_id_column": product_id_col,
            "product_name_column": product_name_col,
            "quantity_column": quantity_col,
            "price_column": price_col,
            "invoice_column": invoice_col,
            "top_products": top.to_dict(orient="records"),
            "bottom_products": bottom.to_dict(orient="records"),
            "zero_net_quantity_products_excluded": True,
            "returns_included": True,
            "transaction_count_definition": transaction_definition,
        },
    }


# Rank products using real grouped quantity or revenue calculations
def _top_product_answer_uncached(
    df: pd.DataFrame,
    schema: dict[str, Any] | None = None,
    metric: str = "quantity",
    top_n: int = 5,
    positive_only: bool = False,
) -> dict[str, Any] | None:
    """Rank products using real grouped quantity or revenue calculations."""
    product_id_col = _semantic_column(
        df, schema, "product_id", ["stock_code", "stock code", "product_id", "product id", "item code", "product code"]
    )
    product_name_col = _semantic_column(
        df, schema, "product", ["description", "product", "product name", "item description", "name"]
    )
    quantity_col = _semantic_column(df, schema, "quantity", ["quantity", "qty", "units"])
    # Check condition
    if not product_id_col or not quantity_col:
        return None
    # Set up values
    product_ids = _clean_identifier_values(df[product_id_col])
    quantity = pd.to_numeric(df[quantity_col], errors="coerce")
    valid = product_ids.notna() & quantity.notna()
    # Check condition
    if metric == "revenue":
        price_col = _semantic_column(df, schema, "unit_price", ["price", "unit price", "unitprice", "selling price"])
        if not price_col:
            return None
        price = pd.to_numeric(df[price_col], errors="coerce")
        valid &= price.notna()
        measure = quantity * price
        metric_label = "revenue"
    else:
        measure = quantity
        metric_label = "quantity"
    # Check condition
    if positive_only:
        valid &= quantity > 0
        if metric == "revenue":
            valid &= measure > 0
    # Check condition
    if not valid.any():
        return None
    # Set up values
    work = pd.DataFrame({"product_id": product_ids[valid], "measure": measure[valid], "quantity": quantity[valid]})
    # Check condition
    if product_name_col:
        work["product_name"] = df.loc[valid, product_name_col].astype("string").str.strip()
    else:
        work["product_name"] = pd.NA
    # Set up values
    grouped = work.groupby("product_id", dropna=True).agg(
        total_measure=("measure", "sum"),
        net_quantity=("quantity", "sum"),
        transaction_rows=("measure", "size"),
        product_name=("product_name", lambda values: values.dropna().loc[lambda x: x.ne("")].mode().iloc[0] if not values.dropna().loc[lambda x: x.ne("")].mode().empty else ""),
    ).reset_index()
    grouped = grouped.sort_values("total_measure", ascending=False, kind="stable").head(max(1, min(int(top_n), 20)))
    # Check condition
    if grouped.empty:
        return None
    # Set up values
    first = grouped.iloc[0]
    # Check condition
    if metric == "revenue":
        unit = f"{float(first['total_measure']):,.2f}"
        metric_description = "total revenue (quantity × unit price)"
    else:
        unit = f"{float(first['total_measure']):,.0f} units"
        metric_description = "net total quantity (negative quantities/returns reduce the total)"
    # Set up values
    name = str(first["product_name"]).strip() or "Product name unavailable"
    lines = [
        f"Top product by {metric_description}: **{name}** (stock/product code: {first['product_id']}).",
        f"Total {metric_label}: **{unit}**.",
    ]
    # Check condition
    if metric == "quantity":
        gross_positive = float(work.loc[work["product_id"] == first["product_id"]].loc[lambda x: x["quantity"] > 0, "quantity"].sum())
        lines.append(f"Positive quantity before subtracting returns: {gross_positive:,.0f} units.")
    lines.extend(["", f"Top {len(grouped)} products:", "", "| Rank | Product | Product code | Total " + ("revenue" if metric == "revenue" else "quantity") + " |", "|---:|---|---|---:|"])
    # Loop over items
    for rank, row in enumerate(grouped.itertuples(index=False), start=1):
        label = str(row.product_name).strip() or "Product name unavailable"
        value = f"{float(row.total_measure):,.2f}" if metric == "revenue" else f"{float(row.total_measure):,.0f}"
        lines.append(f"| {rank} | {label} | {row.product_id} | {value} |")
    # Return result
    return {
        "answer": "\n".join(lines),
        "details": {
            "analysis": "top_product_by_revenue" if metric == "revenue" else "top_product_by_quantity",
            "product_id_column": product_id_col,
            "product_name_column": product_name_col,
            "quantity_column": quantity_col,
            "metric": metric,
            "positive_only": positive_only,
            "top_products": grouped.to_dict(orient="records"),
            # Revenue uses signed quantity × unit price by default, so negative
            # quantity rows (returns/reversals) are included unless positive_only=True.
            "returns_included": not positive_only,
        },
    }


# Helper: top product answer
def _top_product_answer(df, schema=None, metric="quantity", top_n=5, positive_only=False):
    # Return result
    return _cached_dataframe_answer(
        "top_product", df, schema, (metric, int(top_n), bool(positive_only)),
        lambda: _top_product_answer_uncached(
            df, schema, metric=metric, top_n=top_n, positive_only=positive_only
        ),
    )


# Helper: country revenue answer
def _country_revenue_answer(df: pd.DataFrame, schema: dict[str, Any] | None = None) -> dict[str, Any] | None:
    # Set up values
    country_col = _semantic_column(df, schema, "region", ["country", "region", "market", "territory"])
    quantity_col, price_col, quantity, price, valid = _revenue_components(df, schema)
    # Check condition
    if not country_col or quantity is None or price is None or valid is None:
        return None
    # Set up values
    countries = _clean_identifier_values(df[country_col])
    valid &= countries.notna()
    # Check condition
    if not valid.any():
        return None
    # Set up values
    work = pd.DataFrame({"country": countries[valid], "revenue": (quantity[valid] * price[valid])})
    grouped = work.groupby("country")["revenue"].sum().sort_values(ascending=False).head(10)
    # Check condition
    if grouped.empty:
        return None
    # Set up values
    top_country, top_value = grouped.index[0], float(grouped.iloc[0])
    lines = [f"**{top_country}** generates the highest net revenue: **{top_value:,.2f}**.", "", "| Rank | Country/region | Revenue |", "|---:|---|---:|"]
    lines.extend(f"| {i} | {country} | {value:,.2f} |" for i, (country, value) in enumerate(grouped.items(), 1))
    # Return result
    return {"answer": "\n".join(lines), "details": {"analysis": "country_revenue", "country_column": country_col, "quantity_column": quantity_col, "price_column": price_col, "top_countries": [{"country": str(k), "revenue": round(float(v), 2)} for k, v in grouped.items()], "returns_included": True}}


# Helper: average order value answer
def _average_order_value_answer(df: pd.DataFrame, schema: dict[str, Any] | None = None) -> dict[str, Any] | None:
    # Set up values
    invoice_col = _semantic_column(df, schema, "invoice_id", ["invoice", "invoice id", "invoice number", "invoice no", "order id", "order number"])
    # Check condition
    if not invoice_col:
        invoice_col = _semantic_column(df, schema, "invoice", ["invoice", "invoice id", "invoice number", "order id"])
    # Set up values
    quantity_col, price_col, quantity, price, valid = _revenue_components(df, schema)
    # Check condition
    if not invoice_col or quantity is None or price is None or valid is None:
        return None
    # Set up values
    invoice_ids = _clean_identifier_values(df[invoice_col])
    valid &= invoice_ids.notna()
    # Check condition
    if not valid.any():
        return None
    # Set up values
    invoice_revenue = (quantity[valid] * price[valid]).groupby(invoice_ids[valid]).sum()
    # Check condition
    if invoice_revenue.empty:
        return None
    # Set up values
    total_revenue = float(invoice_revenue.sum())
    invoice_count = int(invoice_revenue.size)
    average = total_revenue / invoice_count
    # Return result
    return {
        "answer": (f"Average order value: **{average:,.2f}**.\n\n" f"Total net revenue: {total_revenue:,.2f}.\n" f"Distinct invoices included: {invoice_count:,}.\n" "Formula: total net revenue ÷ distinct invoice IDs. Negative quantities are included, so returns reduce revenue."),
        "details": {"analysis": "average_order_value", "invoice_column": invoice_col, "quantity_column": quantity_col, "price_column": price_col, "total_revenue": round(total_revenue, 2), "distinct_invoices": invoice_count, "average_order_value": round(average, 2), "returns_included": True},
    }


# Helper: total quantity answer
def _total_quantity_answer(df: pd.DataFrame, schema: dict[str, Any] | None = None) -> dict[str, Any] | None:
    # Set up values
    quantity_col = _semantic_column(df, schema, "quantity", ["quantity", "qty", "units"])
    # Check condition
    if not quantity_col:
        return None
    # Set up values
    quantity = pd.to_numeric(df[quantity_col], errors="coerce")
    valid = quantity.notna()
    # Check condition
    if not valid.any():
        return None
    # Set up values
    total = float(quantity[valid].sum())
    # Return result
    return {"answer": f"Total net quantity: **{total:,.0f} units**. Negative quantities are included, so returns reduce the total.", "details": {"analysis": "total_quantity", "quantity_column": quantity_col, "total_quantity": total, "valid_rows": int(valid.sum()), "excluded_rows": int((~valid).sum())}}


# Calculate explicit date ranges and two-year revenue comparisons
def _date_range_or_year_comparison_answer(
    df: pd.DataFrame,
    schema: dict[str, Any] | None,
    question: str,
) -> dict[str, Any] | None:
    """Calculate explicit date ranges and two-year revenue comparisons."""
    date_col = _semantic_column(
        df, schema, "date",
        ["InvoiceDate", "Invoice Date", "Date", "OrderDate", "Order Date"],
    )
    quantity_col = _semantic_column(df, schema, "quantity", ["Quantity", "Qty", "Units"])
    price_col = _semantic_column(
        df, schema, "unit_price",
        ["UnitPrice", "Unit Price", "Price", "SellingPrice"],
    )
    # Check condition
    if not date_col or not quantity_col or not price_col:
        return None
    # Set up values
    q = question.lower()
    dates = _parse_date_values(df[date_col])
    quantity = pd.to_numeric(df[quantity_col], errors="coerce")
    price = pd.to_numeric(df[price_col], errors="coerce")
    base_valid = dates.notna() & quantity.notna() & price.notna()
    row_revenue = quantity * price
    # Function: summarize
    def summarize(mask: pd.Series, label: str) -> dict[str, Any]:
        # Set up values
        valid = base_valid & mask
        total = float(row_revenue[valid].sum())
        # Return result
        return {
            "label": label,
            "revenue": round(total, 2),
            "rows": int(valid.sum()),
            "net_quantity": float(quantity[valid].sum()),
        }
    # Compare two explicit calendar years, e.g. "compare revenue in 2010 and 2011".
    years = [int(x) for x in re.findall(r"\b(?:19|20)\d{2}\b", q)]
    comparison_words = ("compare", "comparison", "versus", " vs ", "difference", "change")
    # Check condition
    if len(set(years)) >= 2 and any(word in q for word in comparison_words):
        year_a, year_b = list(dict.fromkeys(years))[:2]
        a = summarize(dates.dt.year.eq(year_a), str(year_a))
        b = summarize(dates.dt.year.eq(year_b), str(year_b))
        difference = b["revenue"] - a["revenue"]
        pct = (difference / abs(a["revenue"]) * 100) if a["revenue"] else None
        pct_text = f"{pct:+.2f}%" if pct is not None else "N/A (base year revenue is zero)"
        return {
            "answer": (
                f"## Revenue comparison: {year_a} vs {year_b}\n\n"
                f"- **{year_a}:** {a['revenue']:,.2f} ({a['rows']:,} rows)\n"
                f"- **{year_b}:** {b['revenue']:,.2f} ({b['rows']:,} rows)\n"
                f"- **Difference ({year_b} − {year_a}):** {difference:+,.2f}\n"
                f"- **Percentage change:** {pct_text}\n\n"
                "Revenue is calculated as Quantity × Unit Price. Negative quantities are included."
            ),
            "details": {
                "analysis": "year_over_year_revenue_comparison",
                "date_column": date_col,
                "quantity_column": quantity_col,
                "price_column": price_col,
                "periods": [a, b],
                "difference": round(difference, 2),
                "percentage_change": round(pct, 2) if pct is not None else None,
            },
        }
    # Parse two explicit date endpoints. Supports ISO (YYYY-MM-DD) and
    # day-first forms (DD/MM/YYYY or DD-MM-YYYY), common in the IKEA data.
    date_pattern = r"\b(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/-]\d{1,2}[/-]\d{4})\b"
    date_tokens = re.findall(date_pattern, question)
    # Check condition
    if len(date_tokens) >= 2 and any(word in q for word in ("between", "from", "to", "through", "until")):
        # Parse endpoint
        def parse_endpoint(token: str) -> pd.Timestamp:
            # Check condition
            if re.match(r"^\d{4}-", token):
                return pd.Timestamp(pd.to_datetime(token, errors="raise"))
            # Return result
            return pd.Timestamp(pd.to_datetime(token, dayfirst=True, errors="raise"))
        try:
            start_date, end_date = parse_endpoint(date_tokens[0]), parse_endpoint(date_tokens[1])
        except Exception:
            return {
                "answer": "I couldn't understand the dates. Use YYYY-MM-DD or DD/MM/YYYY.",
                "details": {"analysis": "date_range_revenue", "invalid_dates": date_tokens[:2]},
            }
        if start_date > end_date:
            return {
                "answer": "The start date is after the end date. Please provide a valid date range.",
                "details": {"analysis": "date_range_revenue", "start_date": str(start_date.date()),
                            "end_date": str(end_date.date()), "error": "start_after_end"},
            }
        mask = dates.ge(start_date) & dates.lt(end_date + pd.Timedelta(days=1))
        result = summarize(mask, f"{start_date.date()} to {end_date.date()}")
        return {
            "answer": (
                f"Revenue from {start_date.date()} to {end_date.date()}: "
                f"**{result['revenue']:,.2f}**.\n\n"
                f"Rows included: {result['rows']:,}.\n"
                f"Net quantity: {result['net_quantity']:,.0f} units.\n"
                "Formula: SUM(Quantity × Unit Price). Negative quantities are included."
            ),
            "details": {
                "analysis": "date_range_revenue",
                "start_date": str(start_date.date()),
                "end_date": str(end_date.date()),
                "date_column": date_col,
                "quantity_column": quantity_col,
                "price_column": price_col,
                "matched_rows": result["rows"],
                "total_revenue": result["revenue"],
                "net_quantity": result["net_quantity"],
            },
        }
    # Return result
    return None


# Calculate revenue for an explicitly requested month or calendar year
def _date_filtered_revenue_answer(df: pd.DataFrame, schema: dict[str, Any] | None, question: str) -> dict[str, Any] | None:
    """Calculate revenue for an explicitly requested month or calendar year."""
    date_col = _semantic_column(df, schema, "date", ["InvoiceDate", "Invoice Date", "Date", "OrderDate", "Order Date"])
    quantity_col = _semantic_column(df, schema, "quantity", ["Quantity", "Qty", "Units"])
    price_col = _semantic_column(df, schema, "unit_price", ["UnitPrice", "Unit Price", "Price", "SellingPrice"])
    # Check condition
    if not date_col or not quantity_col or not price_col:
        return None
    # Set up values
    dates = _parse_date_values(df[date_col])
    quantity = pd.to_numeric(df[quantity_col], errors="coerce")
    price = pd.to_numeric(df[price_col], errors="coerce")
    q = question.lower()
    month_names = ["january", "february", "march", "april", "may", "june",
                "july", "august", "september", "october", "november", "december"]
    month_number = next((i for i, name in enumerate(month_names, 1)
                        if re.search(rf"\b(?:{name}|{name[:3]})\b", q)), None)
    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", q)
    # Check condition
    if not year_match:
        return None
    # Set up values
    year = int(year_match.group(1))
    date_mask = dates.dt.year.eq(year)
    period = str(year)
    # Check condition
    if month_number is not None:
        date_mask &= dates.dt.month.eq(month_number)
        period = f"{year}-{month_number:02d}"
    # Set up values
    valid = date_mask & dates.notna() & quantity.notna() & price.notna()
    revenue = float((quantity[valid] * price[valid]).sum())
    # Return result
    return {
        "answer": (f"Total revenue for {period}: {revenue:,.2f}.\n"
                f"Rows included: {int(valid.sum()):,}.\n"
                "Formula: SUM(Quantity × Price). Negative quantities and prices are included."),
        "details": {"analysis": "date_filtered_revenue", "period": period,
                    "date_column": date_col, "quantity_column": quantity_col,
                    "price_column": price_col, "matched_rows": int(valid.sum()),
                    "total_revenue": round(revenue, 2)}
    }


# Build a real month-by-month sales trend, optionally restricted to a year
def _monthly_sales_answer(
    df: pd.DataFrame, schema: dict[str, Any] | None = None, year: int | None = None
) -> dict[str, Any] | None:
    """Build a real month-by-month sales trend, optionally restricted to a year."""
    date_col = _semantic_column(df, schema, "date", ["InvoiceDate", "Invoice Date", "Date", "OrderDate", "Order Date"])
    quantity_col = _semantic_column(df, schema, "quantity", ["Quantity", "Qty", "Units"])
    price_col = _semantic_column(df, schema, "unit_price", ["UnitPrice", "Unit Price", "Price", "SellingPrice"])
    # Check condition
    if not date_col or not quantity_col or not price_col:
        return None
    # Handle text dates, pandas timestamps, and Excel serial-date numbers.
    parsed_dates = _parse_date_values(df[date_col])
    quantity = pd.to_numeric(df[quantity_col], errors="coerce")
    unit_price = pd.to_numeric(df[price_col], errors="coerce")
    valid = parsed_dates.notna() & quantity.notna() & unit_price.notna()
    # Check condition
    if year is not None:
        valid &= parsed_dates.dt.year.eq(year)
    # Check condition
    if not valid.any():
        return None
    # Set up values
    working = pd.DataFrame({
        "month": parsed_dates[valid].dt.to_period("M").astype(str),
        "quantity": quantity[valid],
        "revenue": quantity[valid] * unit_price[valid],
    })
    monthly = working.groupby("month", sort=True).agg(
        revenue=("revenue", "sum"),
        units=("quantity", "sum"),
        records=("quantity", "size"),
    ).reset_index()
    # Check condition
    if monthly.empty:
        return None
    # Set up values
    lines = [
        f"Here is the monthly sales trend{f' for {year}' if year is not None else ''}.",
        "",
        "Revenue = Quantity × UnitPrice. Negative quantities are included, so returns reduce the total.",
        "",
        "| Month | Revenue | Net units | Records |",
        "|---|---:|---:|---:|",
    ]
    # Loop over items
    for _, row in monthly.iterrows():
        lines.append(
            f"| {row['month']} | {row['revenue']:,.2f} | "
            f"{row['units']:,.0f} | {int(row['records'])} |"
        )
    # Set up values
    peak = monthly.loc[monthly["revenue"].idxmax()]
    lowest = monthly.loc[monthly["revenue"].idxmin()]
    lines.extend([
        "",
        f"**Highest month:** {peak['month']} ({peak['revenue']:,.2f} revenue).",
        f"**Lowest month:** {lowest['month']} ({lowest['revenue']:,.2f} revenue).",
        f"**Date coverage:** {monthly['month'].iloc[0]} to {monthly['month'].iloc[-1]}.",
        "",
        "Note: these totals use the rows currently loaded. They are not a forecast.",
    ])
    # Return result
    return {
        "answer": "\n".join(lines),
        "details": {
            "analysis": "monthly_sales_trend",
            "date_column": date_col,
            "quantity_column": quantity_col,
            "price_column": price_col,
            "valid_rows": int(valid.sum()),
            "months": monthly.to_dict(orient="records"),
        },
    }


# Calculate a month range or compare two named calendar months
def _month_period_revenue_answer(
    df: pd.DataFrame,
    schema: dict[str, Any] | None,
    question: str,
) -> dict[str, Any] | None:
    """Calculate a month range or compare two named calendar months."""
    date_col = _semantic_column(
        df, schema, "date",
        ["InvoiceDate", "Invoice Date", "Date", "OrderDate", "Order Date"],
    )
    quantity_col = _semantic_column(df, schema, "quantity", ["Quantity", "Qty", "Units"])
    price_col = _semantic_column(
        df, schema, "unit_price",
        ["UnitPrice", "Unit Price", "Price", "SellingPrice"],
    )
    # Check condition
    if not date_col or not quantity_col or not price_col:
        return None
    # Set up values
    month_map = {
        "jan": 1, "january": 1, "feb": 2, "february": 2,
        "mar": 3, "march": 3, "apr": 4, "april": 4,
        "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
        "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10, "nov": 11, "november": 11,
        "dec": 12, "december": 12,
    }
    month_pattern = (
        r"\b(january|february|march|april|may|june|july|august|"
        r"september|sept|october|november|december|jan|feb|mar|apr|"
        r"jun|jul|aug|sep|oct|nov|dec)\b"
    )
    q = question.lower()
    matches = list(re.finditer(
        month_pattern + r"\s+(19\d{2}|20\d{2})\b", q, flags=re.IGNORECASE
    ))
    dates = _parse_date_values(df[date_col])
    quantity = pd.to_numeric(df[quantity_col], errors="coerce")
    price = pd.to_numeric(df[price_col], errors="coerce")
    valid_base = dates.notna() & quantity.notna() & price.notna()
    row_revenue = quantity * price
    # Function: period result
    def period_result(year: int, month: int) -> dict[str, Any]:
        # Set up values
        mask = valid_base & dates.dt.year.eq(year) & dates.dt.month.eq(month)
        # Return result
        return {
            "label": f"{year}-{month:02d}",
            "revenue": round(float(row_revenue[mask].sum()), 2),
            "rows": int(mask.sum()),
            "net_quantity": float(quantity[mask].sum()),
        }
    # Two explicit month-year pairs: compare December 2010 vs January 2011,
    # or accept "from December 2010 to January 2011".
    if len(matches) >= 2 and any(
        term in q for term in ("compare", "comparison", "versus", " vs ", "difference", "change")
    ):
        first, second = matches[0], matches[1]
        m1, y1 = month_map[first.group(1).lower()], int(first.group(2))
        m2, y2 = month_map[second.group(1).lower()], int(second.group(2))
        a, b = period_result(y1, m1), period_result(y2, m2)
        difference = b["revenue"] - a["revenue"]
        pct = difference / abs(a["revenue"]) * 100 if a["revenue"] else None
        pct_text = f"{pct:+.2f}%" if pct is not None else "N/A (first month revenue is zero)"
        return {
            "answer": (
                f"## Monthly revenue comparison: {a['label']} vs {b['label']}\n\n"
                f"- **{a['label']}:** {a['revenue']:,.2f} ({a['rows']:,} rows)\n"
                f"- **{b['label']}:** {b['revenue']:,.2f} ({b['rows']:,} rows)\n"
                f"- **Difference ({b['label']} − {a['label']}):** {difference:+,.2f}\n"
                f"- **Percentage change:** {pct_text}\n\n"
                "Revenue = Quantity × Unit Price. Negative quantities are included."
            ),
            "details": {
                "analysis": "month_over_month_revenue_comparison",
                "date_column": date_col,
                "quantity_column": quantity_col,
                "price_column": price_col,
                "periods": [a, b],
                "difference": round(difference, 2),
                "percentage_change": round(pct, 2) if pct is not None else None,
            },
        }
    # Month range in one calendar year, e.g. "January to March 2011".
    if len(matches) >= 2 and any(term in q for term in ("to", "through", "until", "between", "from")):
        first, second = matches[0], matches[1]
        start_month, start_year = month_map[first.group(1).lower()], int(first.group(2))
        end_month, end_year = month_map[second.group(1).lower()], int(second.group(2))
        start_period = pd.Period(year=start_year, month=start_month, freq="M")
        end_period = pd.Period(year=end_year, month=end_month, freq="M")
        if start_period > end_period:
            return {
                "answer": "The start month is after the end month. Please provide a valid month range.",
                "details": {"analysis": "month_range_revenue", "error": "start_after_end"},
            }
        start_date = start_period.start_time
        end_date_exclusive = (end_period + 1).start_time
        mask = valid_base & dates.ge(start_date) & dates.lt(end_date_exclusive)
        total = float(row_revenue[mask].sum())
        net_units = float(quantity[mask].sum())
        return {
            "answer": (
                f"Revenue from {start_period} to {end_period}: **{total:,.2f}**.\n\n"
                f"Rows included: {int(mask.sum()):,}.\n"
                f"Net quantity: {net_units:,.0f} units.\n"
                "Revenue = Quantity × Unit Price. Negative quantities are included."
            ),
            "details": {
                "analysis": "month_range_revenue",
                "start_period": str(start_period),
                "end_period": str(end_period),
                "date_column": date_col,
                "quantity_column": quantity_col,
                "price_column": price_col,
                "matched_rows": int(mask.sum()),
                "total_revenue": round(total, 2),
                "net_quantity": net_units,
            },
        }
    # Return result
    return None


# Calculate average revenue per valid transaction row deterministically
def _average_revenue_answer(
    df: pd.DataFrame, schema: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Calculate average revenue per valid transaction row deterministically."""
    quantity_col = _semantic_column(df, schema, "quantity", ["Quantity", "Qty", "Units"])
    price_col = _semantic_column(df, schema, "unit_price", ["UnitPrice", "Unit Price", "Price", "SellingPrice"])
    # Check condition
    if not quantity_col or not price_col:
        return None
    # Set up values
    quantity = pd.to_numeric(df[quantity_col], errors="coerce")
    unit_price = pd.to_numeric(df[price_col], errors="coerce")
    valid = quantity.notna() & unit_price.notna()
    date_col = _semantic_column(df, schema, "date", ["InvoiceDate", "Invoice Date", "Date", "OrderDate", "Order Date"])
    # Check condition
    if date_col:
        parsed_dates = _parse_date_values(df[date_col])
        valid &= parsed_dates.notna()
    # Set up values
    valid_rows = int(valid.sum())
    # Check condition
    if valid_rows == 0:
        return None
    # Set up values
    total_sales = float((quantity[valid] * unit_price[valid]).sum())
    average = total_sales / valid_rows
    answer = (
        f"Average revenue per row is {average:,.2f}.\n\n"
        f"Total sales = {total_sales:,.2f} (Quantity × UnitPrice).\n"
        f"Valid rows = {valid_rows:,}.\n"
        f"Formula: {total_sales:,.2f} ÷ {valid_rows:,} = {average:,.2f}."
    )
    # Return result
    return {"answer": answer, "details": {"analysis": "average_revenue_per_row", "quantity_column": quantity_col, "price_column": price_col, "valid_rows": valid_rows, "total_sales": round(total_sales, 2), "average_revenue_per_row": round(average, 2)}}


# Calculate total revenue from quantity × price using the loaded DataFrame
def _total_revenue_answer(
    df: pd.DataFrame, schema: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Calculate total revenue from quantity × price using the loaded DataFrame."""
    quantity_col = _semantic_column(df, schema, "quantity", ["Quantity", "Qty", "Units"])
    price_col = _semantic_column(df, schema, "unit_price", ["Price", "UnitPrice", "Unit Price", "SellingPrice"])
    # Check condition
    if not quantity_col or not price_col:
        return None
    # Set up values
    quantity = pd.to_numeric(df[quantity_col], errors="coerce")
    unit_price = pd.to_numeric(df[price_col], errors="coerce")
    valid = quantity.notna() & unit_price.notna()
    valid_rows = int(valid.sum())
    # Check condition
    if valid_rows == 0:
        return None
    # Set up values
    total_revenue = float((quantity[valid] * unit_price[valid]).sum())
    dataset_rows = int(len(df))
    excluded_rows = dataset_rows - valid_rows
    # Return result
    return {
        "answer": (
            f"Total revenue: {total_revenue:,.2f}.\n"
            f"Formula: sum of Quantity × Price across valid numeric rows.\n"
            f"Full dataset rows: {dataset_rows:,}.\n"
            f"Valid rows included: {valid_rows:,}.\n"
            f"Invalid rows excluded: {excluded_rows:,}. Negative quantities and prices are included."
        ),
        "details": {
            "analysis": "total_revenue",
            "quantity_column": quantity_col,
            "price_column": price_col,
            "dataset_rows": dataset_rows,
            "valid_rows": valid_rows,
            "excluded_rows": excluded_rows,
            "total_revenue": round(total_revenue, 2),
        },
    }


# Summarize missing customer IDs and sales for each customer-ID group
def _customer_id_sales_answer(
    df: pd.DataFrame, schema: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Summarize missing customer IDs and sales for each customer-ID group."""
    customer_col = _semantic_column(df, schema, "customer_id", ["customer_id", "customer id", "customerid", "customer number"])
    quantity_col = _semantic_column(df, schema, "quantity", ["Quantity", "Qty", "Units"])
    price_col = _semantic_column(df, schema, "unit_price", ["Price", "UnitPrice", "Unit Price", "SellingPrice"])
    # Check condition
    if customer_col is None or quantity_col is None or price_col is None:
        return None
    # Set up values
    customer_values = df[customer_col].astype("string").str.strip()
    missing_customer = customer_values.isna() | customer_values.str.lower().isin(
        ["", "nan", "none", "null", "<na>"]
    )
    quantity = pd.to_numeric(df[quantity_col], errors="coerce")
    price = pd.to_numeric(df[price_col], errors="coerce")
    valid_sales = quantity.notna() & price.notna()
    row_count = len(df)
    missing_count = int(missing_customer.sum())
    present_count = row_count - missing_count
    sales_with_id = float((quantity[valid_sales & ~missing_customer] * price[valid_sales & ~missing_customer]).sum())
    sales_without_id = float((quantity[valid_sales & missing_customer] * price[valid_sales & missing_customer]).sum())
    valid_with_id = int((valid_sales & ~missing_customer).sum())
    valid_without_id = int((valid_sales & missing_customer).sum())
    missing_pct = (missing_count / row_count * 100) if row_count else 0.0
    answer = (
        f"Total rows: {row_count:,}.\n"
        f"Rows missing customer_id: {missing_count:,} ({missing_pct:.2f}%).\n"
        f"Rows with customer_id: {present_count:,} ({100 - missing_pct:.2f}%).\n\n"
        f"Sales for rows with customer_id: {sales_with_id:,.2f} "
        f"(calculated from {valid_with_id:,} rows).\n"
        f"Sales for rows missing customer_id: {sales_without_id:,.2f} "
        f"(calculated from {valid_without_id:,} rows).\n\n"
        "Formula: Quantity × Price. Rows with non-numeric or missing quantity/price are excluded from sales totals. "
        "Negative quantities are included, so returns reduce sales."
    )
    # Return result
    return {
        "answer": answer,
        "details": {
            "analysis": "customer_id_missing_and_sales",
            "customer_column": customer_col,
            "quantity_column": quantity_col,
            "price_column": price_col,
            "dataset_rows": row_count,
            "missing_customer_id_rows": missing_count,
            "missing_customer_id_percentage": round(missing_pct, 2),
            "rows_with_customer_id": present_count,
            "sales_with_customer_id": round(sales_with_id, 2),
            "sales_without_customer_id": round(sales_without_id, 2),
            "valid_sales_rows_with_customer_id": valid_with_id,
            "valid_sales_rows_without_customer_id": valid_without_id,
            "invalid_quantity_or_price_rows": int((~valid_sales).sum()),
        },
    }


# Deterministic customer metrics, monthly comparisons, and inactivity analysis
def _customer_analytics_answer(
    df: pd.DataFrame,
    schema: dict[str, Any] | None,
    question: str,
) -> dict[str, Any] | None:
    """Deterministic customer metrics, monthly comparisons, and inactivity analysis."""
    customer_col = _semantic_column(
        df, schema, "customer_id",
        ["customer_id", "customer id", "customerid", "customer number", "customer no"],
    )
    invoice_col = _semantic_column(
        df, schema, "invoice_id",
        ["invoice", "invoice id", "invoice number", "invoice no", "order id", "order number"],
    )
    date_col = _semantic_column(
        df, schema, "date",
        ["invoice_date", "invoice date", "date", "order date", "orderdate"],
    )
    quantity_col, price_col, quantity, price, valid_revenue = _revenue_components(df, schema)
    # Check condition
    if not customer_col:
        return None
    # Set up values
    customer_ids = _clean_identifier_values(df[customer_col])
    dates = _parse_date_values(df[date_col]) if date_col else None
    month_pattern = (
        r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
        r"nov(?:ember)?|dec(?:ember)?)\s+(20\d{2})\b"
    )
    month_nums = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    month_matches = re.findall(month_pattern, question.lower())
    periods = []
    # Loop over items
    for month_text, year_text in month_matches:
        key = month_text[:3]
        periods.append(f"{int(year_text):04d}-{month_nums[key]:02d}")
    # Set up values
    periods = list(dict.fromkeys(periods))
    # Check condition
    if dates is None or quantity is None or price is None or valid_revenue is None:
        if any(term in question.lower() for term in ["revenue", "sales", "spending", "spent", "aov", "average order"]):
            return None
    # Set up values
    valid_customer = customer_ids.notna()
    missing_customer_rows = int((~valid_customer).sum())
    valid_txn = valid_customer.copy()
    # Check condition
    if dates is not None:
        valid_txn &= dates.notna()
    # Check condition
    if valid_revenue is not None:
        valid_txn &= valid_revenue
    # Full monthly trend when the user asks for customer counts or AOV by month.
    asks_customer_count_by_month = (
        "customer" in question.lower()
        and any(term in question.lower() for term in ["by month", "each month", "per month", "monthly"])
        and any(term in question.lower() for term in ["unique", "distinct", "count", "how many"])
    )
    asks_aov_by_month = (
        any(term in question.lower() for term in ["aov", "average order value", "average order"])
        and any(term in question.lower() for term in ["by month", "each month", "per month", "monthly"])
    )
    # Check condition
    if (asks_customer_count_by_month or asks_aov_by_month) and dates is not None:
        month_values = dates.dt.strftime("%Y-%m")
        usable = valid_txn & month_values.notna()
        rows = []
        for period in sorted(month_values[usable].unique()):
            mask = usable & month_values.eq(period)
            customer_count = int(customer_ids[mask].nunique())
            revenue = float((quantity[mask] * price[mask]).sum()) if quantity is not None and price is not None else None
            orders = int(_clean_identifier_values(df.loc[mask, invoice_col]).nunique()) if invoice_col else None
            aov = revenue / orders if revenue is not None and orders else None
            rows.append({"month": period, "unique_customers": customer_count,
                        "net_revenue": round(revenue, 2) if revenue is not None else None,
                        "distinct_orders": orders, "net_aov": round(aov, 2) if aov is not None else None,
                        "transaction_rows": int(mask.sum())})
        if rows:
            if asks_aov_by_month and invoice_col:
                lines = ["Monthly net average order value (AOV):", "", "| Month | Net revenue | Distinct orders | Net AOV |", "|---|---:|---:|---:|"]
                lines.extend(f"| {r['month']} | {r['net_revenue']:,.2f} | {r['distinct_orders']:,} | {r['net_aov']:,.2f} |" for r in rows)
                analysis = "monthly_aov_trend"
            else:
                lines = ["Unique identified customers by month:", "", "| Month | Unique customers |", "|---|---:|"]
                lines.extend(f"| {r['month']} | {r['unique_customers']:,} |" for r in rows)
                analysis = "monthly_unique_customer_trend"
            lines.extend(["", f"Missing customer IDs are excluded ({missing_customer_rows:,} rows across the full dataset).", "AOV uses net revenue (including returns) divided by distinct non-null invoices."])
            return {"answer": "\n".join(lines), "details": {
                "analysis": analysis, "customer_column": customer_col, "date_column": date_col,
                "invoice_column": invoice_col, "quantity_column": quantity_col, "price_column": price_col,
                "monthly_results": rows, "missing_customer_id_rows_excluded": missing_customer_rows,
            }}
    # Monthly customer comparison: customer count, revenue, orders, AOV, new and lost IDs.
    if len(periods) == 2 and dates is not None and quantity is not None and price is not None:
        asks_customer_period_comparison = (
            "customer" in question.lower()
            and any(term in question.lower() for term in [
                "compare", "comparison", "versus", " vs ", "difference", "change",
                "stopped", "stop purchasing", "inactive", "lost customer", "churn",
                "unique", "distinct", "count", "aov", "average order", "revenue", "sales",
            ])
        )
        if asks_customer_period_comparison:
            month_series = dates.dt.strftime("%Y-%m")
            period_stats = {}
            period_customers = {}
            for period in periods:
                mask = valid_txn & month_series.eq(period)
                ids = set(customer_ids[mask].astype(str))
                period_customers[period] = ids
                revenue = float((quantity[mask] * price[mask]).sum()) if quantity is not None and price is not None else 0.0
                orders = int(_clean_identifier_values(df.loc[mask, invoice_col]).nunique()) if invoice_col else None
                aov = revenue / orders if orders else None
                period_stats[period] = {
                    "customer_count": len(ids),
                    "revenue": round(revenue, 2),
                    "orders": orders,
                    "aov": round(aov, 2) if aov is not None else None,
                    "transaction_rows": int(mask.sum()),
                }
            first, second = periods
            new_ids = sorted(period_customers[second] - period_customers[first])
            lost_ids = sorted(period_customers[first] - period_customers[second])
            common_ids = period_customers[first] & period_customers[second]
            rev_change = period_stats[second]["revenue"] - period_stats[first]["revenue"]
            rev_pct = (rev_change / period_stats[first]["revenue"] * 100) if period_stats[first]["revenue"] else None
            lines = [
                f"Customer comparison: **{first} vs {second}**", "",
                "| Metric | " + first + " | " + second + " |",
                "|---|---:|---:|",
                f"| Unique identified customers | {period_stats[first]['customer_count']:,} | {period_stats[second]['customer_count']:,} |",
                f"| Net revenue | {period_stats[first]['revenue']:,.2f} | {period_stats[second]['revenue']:,.2f} |",
            ]
            if invoice_col:
                lines.append(f"| Distinct orders | {period_stats[first]['orders']:,} | {period_stats[second]['orders']:,} |")
                lines.append(f"| Net AOV | {period_stats[first]['aov']:,.2f} | {period_stats[second]['aov']:,.2f} |")
            lines.extend([
                "", f"Revenue change ({second} − {first}): **{rev_change:,.2f}**" + (f" ({rev_pct:+.2f}%)." if rev_pct is not None else "."),
                f"Customers in both months: **{len(common_ids):,}**.",
                f"Newly active in {second}: **{len(new_ids):,}**.",
                f"Active in {first} but not in {second}: **{len(lost_ids):,}**.",
                "", "The last group means customers with transactions in the first selected month and none in the second; it does not prove permanent churn.",
                f"Missing customer IDs are excluded ({missing_customer_rows:,} dataset rows). Returns are included in net revenue.",
            ])
            return {
                "answer": "\n".join(lines),
                "details": {
                    "analysis": "monthly_customer_comparison",
                    "customer_column": customer_col,
                    "date_column": date_col,
                    "quantity_column": quantity_col,
                    "price_column": price_col,
                    "invoice_column": invoice_col,
                    "periods": period_stats,
                    "customers_in_both_periods": len(common_ids),
                    "newly_active_customer_count": len(new_ids),
                    "previously_active_not_in_second_period_count": len(lost_ids),
                    "newly_active_customer_ids": new_ids[:100],
                    "previously_active_not_in_second_period_ids": lost_ids[:100],
                    "missing_customer_id_rows_excluded": missing_customer_rows,
                    "returns_included": True,
                    "churn_caveat": "Absence in the second selected month does not establish permanent churn.",
                },
            }
    # Single month unique customer count / monthly AOV.
    asks_monthly_customer_count = (
        "customer" in question.lower()
        and any(term in question.lower() for term in ["unique", "distinct", "how many", "count"])
        and any(term in question.lower() for term in ["month", "during", "in "])
    )
    asks_monthly_aov = (
        any(term in question.lower() for term in ["aov", "average order value", "average order"])
        and ("month" in question.lower() or bool(periods))
    )
    # Check condition
    if periods and len(periods) == 1 and dates is not None and (asks_monthly_customer_count or asks_monthly_aov):
        period = periods[0]
        mask = valid_txn & dates.dt.strftime("%Y-%m").eq(period)
        customer_count = int(customer_ids[mask].nunique())
        revenue = float((quantity[mask] * price[mask]).sum()) if quantity is not None and price is not None else None
        orders = int(_clean_identifier_values(df.loc[mask, invoice_col]).nunique()) if invoice_col else None
        aov = revenue / orders if revenue is not None and orders else None
        if asks_monthly_aov and invoice_col:
            answer = f"Net average order value for {period}: **{aov:,.2f}**.\n\nNet revenue: {revenue:,.2f}. Distinct orders: {orders:,}. Returns are included in net revenue."
            analysis = "monthly_customer_aov"
        else:
            answer = f"Unique identified customers in {period}: **{customer_count:,}**.\n\nMissing customer IDs are excluded ({missing_customer_rows:,} rows across the full dataset)."
            analysis = "monthly_unique_customers"
        return {
            "answer": answer,
            "details": {
                "analysis": analysis, "period": period,
                "customer_count": customer_count,
                "net_revenue": round(revenue, 2) if revenue is not None else None,
                "distinct_orders": orders,
                "net_aov": round(aov, 2) if aov is not None else None,
                "missing_customer_id_rows_excluded": missing_customer_rows,
            },
        }
    # Customers with no transaction in the latest recorded month, compared with the month before.
    asks_stopped = any(term in question.lower() for term in ["stopped purchasing", "stop purchasing", "inactive customers", "lost customers", "churned customers"])
    # Check condition
    if asks_stopped and dates is not None:
        month_series = dates.dt.strftime("%Y-%m")
        available_months = sorted(month_series.dropna().unique())
        if len(available_months) >= 2:
            previous, latest = available_months[-2], available_months[-1]
            previous_mask = valid_txn & month_series.eq(previous)
            latest_mask = valid_txn & month_series.eq(latest)
            previous_ids = set(customer_ids[previous_mask].astype(str))
            latest_ids = set(customer_ids[latest_mask].astype(str))
            inactive_ids = sorted(previous_ids - latest_ids)
            shown = inactive_ids[:50]
            return {
                "answer": (
                    f"{len(inactive_ids):,} customers purchased in {previous} but had no recorded purchase in {latest}.\n\n"
                    f"Customer IDs (first {len(shown)}): {', '.join(shown) if shown else 'None'}.\n\n"
                    "This is a one-month activity comparison, not proof that these customers permanently churned. "
                    f"Missing customer IDs are excluded ({missing_customer_rows:,} rows across the dataset)."
                ),
                "details": {
                    "analysis": "customers_not_returning_latest_month",
                    "previous_month": previous,
                    "latest_month": latest,
                    "inactive_customer_count": len(inactive_ids),
                    "inactive_customer_ids": shown,
                    "customer_ids_truncated": len(inactive_ids) > len(shown),
                    "missing_customer_id_rows_excluded": missing_customer_rows,
                },
            }
    # Default global customer revenue ranking (top-N helper remains the source of truth).
    if "customer" in question.lower() and any(term in question.lower() for term in ["top", "highest", "most revenue", "highest spending"]):
        return _top_customer_revenue_answer(df, schema, top_n=10)
    # Return result
    return None


# Helper: split compound questions
def _split_compound_questions(question: str) -> list[str]:
    """Split numbered or line-separated multi-question prompts into individual questions."""
    # Check condition
    if not isinstance(question, str):
        return []
    # Set up values
    normalized = re.sub(r"(?m)^\s*(?:\d+[\).]|[-*])\s+", "\n", question.strip())
    pieces = re.split(r"\?\s*|\n+", normalized)
    # Return result
    return [piece.strip(" \t\r\n-•") for piece in pieces if piece.strip(" \t\r\n-•.,;:!?")]


# Rank customers by net revenue (quantity × unit price), excluding missing IDs
def _top_customer_revenue_answer_uncached(
    df: pd.DataFrame, schema: dict[str, Any] | None = None, top_n: int = 10
) -> dict[str, Any] | None:
    """Rank customers by net revenue (quantity × unit price), excluding missing IDs."""
    customer_col = _semantic_column(
        df, schema, "customer_id",
        ["customer_id", "customer id", "customerid", "customer number", "customer no"],
    )
    quantity_col, price_col, quantity, price, valid = _revenue_components(df, schema)
    # Check condition
    if not customer_col or quantity is None or price is None or valid is None:
        return None
    # Set up values
    customer_ids = _clean_identifier_values(df[customer_col])
    valid &= customer_ids.notna()
    # Check condition
    if not valid.any():
        return None
    # Set up values
    work = pd.DataFrame({
        "customer_id": customer_ids[valid],
        "revenue": quantity[valid] * price[valid],
    })
    grouped = (
        work.groupby("customer_id", dropna=True)["revenue"]
        .sum()
        .sort_values(ascending=False, kind="stable")
        .head(max(1, min(int(top_n), 100)))
    )
    # Check condition
    if grouped.empty:
        return None
    # Set up values
    total_customer_revenue = float(grouped.sum())
    lines = [
        f"Top {len(grouped)} customers by net revenue (quantity × unit price):",
        "",
        "| Rank | Customer ID | Net revenue |",
        "|---:|---|---:|",
    ]
    lines.extend(
        f"| {rank} | {customer_id} | {value:,.2f} |"
        for rank, (customer_id, value) in enumerate(grouped.items(), start=1)
    )
    lines.extend([
        "",
        "Missing customer IDs are excluded. Negative quantities are included, so returns reduce net revenue.",
    ])
    # Return result
    return {
        "answer": "\n".join(lines),
        "details": {
            "analysis": "top_customer_revenue",
            "customer_column": customer_col,
            "quantity_column": quantity_col,
            "price_column": price_col,
            "top_customers": [
                {"customer_id": str(customer_id), "revenue": round(float(value), 2)}
                for customer_id, value in grouped.items()
            ],
            "customers_ranked": int(len(grouped)),
            "missing_customer_rows_excluded": int((~_clean_identifier_values(df[customer_col]).notna()).sum()),
            "returns_included": True,
        },
    }


# Helper: top customer revenue answer
def _top_customer_revenue_answer(df, schema=None, top_n=10):
    # Return result
    return _cached_dataframe_answer(
        "top_customer_revenue", df, schema, (int(top_n),),
        lambda: _top_customer_revenue_answer_uncached(df, schema, top_n=top_n),
    )


# Calculate customer-level RFM values, optionally returning one segment
def _rfm_analysis_answer_uncached(
    df: pd.DataFrame,
    schema: dict[str, Any] | None = None,
    segment_filter: str | None = None,
    top_n: int = 10,
) -> dict[str, Any] | None:
    """Calculate customer-level RFM values, optionally returning one segment."""
    customer_col = _semantic_column(
        df, schema, "customer_id",
        ["customer_id", "customer id", "customerid", "customer number", "customer no"],
    )
    invoice_col = _semantic_column(
        df, schema, "invoice_id",
        ["invoice", "invoice id", "invoice number", "invoice no", "order id", "order number"],
    )
    date_col = _semantic_column(
        df, schema, "date",
        ["invoice_date", "invoice date", "date", "order date", "orderdate"],
    )
    quantity_col, price_col, quantity, price, valid_sales = _revenue_components(df, schema)
    # Check condition
    if not all([customer_col, invoice_col, date_col]) or quantity is None or price is None or valid_sales is None:
        return None
    # Set up values
    customer_ids = _clean_identifier_values(df[customer_col])
    invoice_ids = _clean_identifier_values(df[invoice_col])
    dates = _parse_date_values(df[date_col])
    valid = valid_sales & customer_ids.notna() & invoice_ids.notna() & dates.notna()
    # Check condition
    if not valid.any():
        return None
    # Set up values
    work = pd.DataFrame({
        "customer_id": customer_ids[valid],
        "invoice_id": invoice_ids[valid],
        "date": dates[valid],
        "revenue": quantity[valid] * price[valid],
    })
    # Use the day after the latest transaction as the reference date. This makes
    # recency reproducible from the loaded dataset rather than the machine clock.
    reference_date = work["date"].max().normalize() + pd.Timedelta(days=1)
    rfm = work.groupby("customer_id").agg(
        last_purchase=("date", "max"),
        frequency=("invoice_id", "nunique"),
        monetary=("revenue", "sum"),
    )
    rfm["recency"] = (reference_date - rfm["last_purchase"].dt.normalize()).dt.days
    # Function: quintile score
    def quintile_score(values: pd.Series, higher_is_better: bool = True) -> pd.Series:
        # Set up values
        ranked = values.rank(method="first", ascending=higher_is_better)
        scores = pd.qcut(ranked, q=5, labels=[1, 2, 3, 4, 5]).astype(int)
        # Return result
        return scores
    # For recency, fewer days is better; for frequency and monetary, more is better.
    rfm["R"] = quintile_score(rfm["recency"], higher_is_better=False)
    rfm["F"] = quintile_score(rfm["frequency"], higher_is_better=True)
    rfm["M"] = quintile_score(rfm["monetary"], higher_is_better=True)
    rfm["RFM_Score"] = rfm[["R", "F", "M"]].astype(str).agg("".join, axis=1)
    # Function: segment
    def segment(row: pd.Series) -> str:
        # Set up values
        r, f, m = int(row["R"]), int(row["F"]), int(row["M"])
        # Check condition
        if r >= 4 and f >= 4 and m >= 4:
            return "Champions"
        # Check condition
        if r >= 3 and f >= 4:
            return "Loyal Customers"
        # Check condition
        if r >= 4 and f >= 2:
            return "Potential Loyalists"
        # Check condition
        if r == 5 and f == 1:
            return "New Customers"
        # Check condition
        if r <= 2 and f >= 3 and m >= 3:
            return "At Risk"
        # Check condition
        if r <= 2 and f >= 4:
            return "Cannot Lose Them"
        # Check condition
        if r <= 2 and f <= 2:
            return "Hibernating"
        # Return result
        return "Others"
    # Set up values
    rfm["segment"] = rfm.apply(segment, axis=1)
    segment_counts = rfm["segment"].value_counts().sort_values(ascending=False)
    # Segment-specific requests must be filtered before ranking. For At Risk,
    # prioritize customers with the highest historical net value, then longest
    # recency, so the list is useful for retention outreach.
    selected = rfm
    # Check condition
    if segment_filter:
        selected = rfm[rfm["segment"].str.casefold() == segment_filter.casefold()]
        selected = selected.sort_values(
            ["monetary", "recency", "frequency"],
            ascending=[False, False, False],
            kind="stable",
        )
    else:
        selected = selected.sort_values(
            ["R", "F", "M", "monetary"],
            ascending=[False, False, False, False],
            kind="stable",
        )
    # Set up values
    top_customers = selected.head(max(1, min(int(top_n), 100)))
    lines = [
        "RFM customer segmentation is calculated from the loaded transactions.",
        "",
        f"Customers included: **{len(rfm):,}**.",
        f"Reference date: **{reference_date.date().isoformat()}** (day after the latest transaction).",
        "",
        "RFM means Recency (days since last purchase), Frequency (distinct invoices), and Monetary (net revenue). Each score ranges from 1 to 5.",
    ]
    # Check condition
    if segment_filter:
        lines.extend([
            "",
            f"Customers in the **{segment_filter}** segment: **{len(selected):,}**.",
            f"Showing up to **{len(top_customers)}** customers, prioritized by net monetary value and then recency.",
            "",
            "| Rank | Customer ID | Recency (days) | Frequency | Monetary | RFM score | Segment |",
            "|---:|---|---:|---:|---:|---:|---|",
        ])
    else:
        lines.extend([
            "",
            "| Customer segment | Customers |",
            "|---|---:|",
        ])
        lines.extend(f"| {name} | {int(count):,} |" for name, count in segment_counts.items())
        lines.extend([
            "",
            f"Top {len(top_customers)} customers by RFM score:",
            "",
            "| Customer ID | Recency (days) | Frequency | Monetary | RFM | Segment |",
            "|---|---:|---:|---:|---:|---|",
        ])
    # Loop over items
    for rank, (customer_id, row) in enumerate(top_customers.iterrows(), start=1):
        if segment_filter:
            lines.append(
                f"| {rank} | {customer_id} | {int(row['recency'])} | "
                f"{int(row['frequency'])} | {float(row['monetary']):,.2f} | "
                f"{row['RFM_Score']} | {row['segment']} |"
            )
        else:
            lines.append(
                f"| {customer_id} | {int(row['recency'])} | {int(row['frequency'])} | "
                f"{float(row['monetary']):,.2f} | {row['RFM_Score']} | {row['segment']} |"
            )
    lines.extend([
        "",
        "Missing customer IDs, invoice IDs, dates, and non-numeric quantity/price rows are excluded. Returns are included in Monetary value.",
    ])
    # Return result
    return {
        "answer": "\n".join(lines),
        "details": {
            "analysis": "rfm_segmentation",
            "customer_column": customer_col,
            "invoice_column": invoice_col,
            "date_column": date_col,
            "quantity_column": quantity_col,
            "price_column": price_col,
            "reference_date": reference_date.isoformat(),
            "customer_count": int(len(rfm)),
            "segment_counts": {str(k): int(v) for k, v in segment_counts.items()},
            "requested_segment": segment_filter,
            "matching_segment_customer_count": int(len(selected)) if segment_filter else None,
            "requested_top_n": int(top_n),
            "top_customers": [
                {
                    "customer_id": str(customer_id),
                    "recency": int(row["recency"]),
                    "frequency": int(row["frequency"]),
                    "monetary": round(float(row["monetary"]), 2),
                    "rfm_score": str(row["RFM_Score"]),
                    "segment": str(row["segment"]),
                }
                for customer_id, row in top_customers.iterrows()
            ],
            "returns_included_in_monetary": True,
        },
    }


# Helper: rfm analysis answer
def _rfm_analysis_answer(df, schema=None, segment_filter=None, top_n=10):
    # Return result
    return _cached_dataframe_answer(
        "rfm", df, schema, (segment_filter, int(top_n)),
        lambda: _rfm_analysis_answer_uncached(
            df, schema, segment_filter=segment_filter, top_n=top_n
        ),
    )


# Helper: business intelligence answer
def _business_intelligence_answer(
    question: str,
    df: pd.DataFrame,
    schema: dict[str, Any] | None,
    report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a plain-English answer from deterministic metrics and evidence-backed actions."""
    report = report or analyze_business_question(question, df, schema)
    metrics = report.get("analysis", {}).get("metrics", {})
    catalog = report.get("analysis", {}).get("catalog", {}).get("metrics", {})
    recommendations = report.get("evidence_backed_recommendations", [])
    lines = ["## Evidence-based business analysis", ""]
    # Check condition
    if metrics:
        lines.append("### What the data shows")
        labels = {
            "net_revenue": ("Net revenue", "currency"),
            "gross_sales_revenue": ("Gross sales revenue (positive quantities only)", "currency"),
            "returns_value": ("Returns value", "currency"),
            "net_quantity": ("Net quantity", "number"),
            "positive_quantity": ("Positive quantity", "number"),
            "negative_quantity": ("Negative quantity", "number"),
            "distinct_customers": ("Distinct customers", "integer"),
            "distinct_orders": ("Distinct orders", "integer"),
            "aov_net": ("Average order value (net revenue / distinct orders)", "currency"),
            "missing_customer_id_rows": ("Rows missing customer ID", "integer"),
            "rows_negative_quantity": ("Rows with negative quantity", "integer"),
            "invalid_revenue_rows": ("Rows excluded from revenue due to invalid quantity/price", "integer"),
        }
        for key, (label, kind) in labels.items():
            if key not in metrics:
                continue
            value = metrics[key]
            if kind == "currency":
                rendered = f"{float(value):,.2f}"
            elif kind == "integer":
                rendered = f"{int(value):,}"
            else:
                rendered = f"{float(value):,.2f}"
            lines.append(f"- **{label}:** {rendered}")
        lines.append(f"- **Rows analyzed:** {report.get('analysis', {}).get('row_count', len(df)):,}")
    else:
        lines.append("The available columns do not support the standard sales metrics.")
    lines.extend(["", "### Recommended actions"])
    # Check condition
    if recommendations:
        for rec in recommendations:
            lines.extend([
                f"**{rec['title']}**",
                f"- Observation: {rec['observation']}",
                f"- Action: {rec['recommended_action']}",
                f"- Confidence: {rec['confidence']}",
                f"- How to measure: {rec['measurement_plan']}",
                "",
            ])
    else:
        lines.append("No specific data-quality or returns opportunity was detected by the current recommendation rules.")
    lines.extend([
        "",
        "### Important limitations",
        "- These are descriptive findings, not proof of cause and effect.",
        "- Profit or gross margin is not estimated unless usable cost data is present.",
        "- Confirm the business meaning of negative quantities and the semantic column mappings.",
    ])
    # Return result
    return {
        "answer": "\n".join(lines),
        "details": {
            "analysis": "evidence_first_business_intelligence",
            "question": question,
            "classification": report.get("classification"),
            "analysis_results": report.get("analysis"),
            "evidence_backed_recommendations": recommendations,
            "guardrails": report.get("guardrails", []),
        },
    }


# Function: ask
@app.post("/api/ask")
def ask(req: AskRequest):
    # Set up values
    question = (req.question or "").strip()
    # Check condition
    if not question:
        raise HTTPException(400, "Question cannot be empty")
    # Set up values
    provider = str(req.provider or "auto").strip().lower()
    requested_provider = provider
    # Check condition
    if provider not in {"auto", "custom", "gemini", "gemini2", "groq", "openrouter", "ollama"}:
        raise HTTPException(400, "Invalid provider. Choose auto, custom, gemini, gemini2, groq, openrouter, or ollama.")
    # IMPORTANT: keep every explicitly selected provider strict.
    # Gemini 2 must NOT be silently rerouted to Gemini 1. Its own
    # provider entry in ai_analyst.py uses GEMINI_API_KEY_2 and
    # GEMINI_MODEL_2, so a Gemini 2 selection stays Gemini 2.
    #
    # Auto fallback is handled by _call_ai_provider() and is intentionally
    # separate from explicit provider selection.
    if provider == "gemini2":
        print("[AI ROUTER] Gemini 2 selected; keeping explicit Gemini 2 route.", flush=True)
        provider = "gemini2"
    # IMPORTANT: Auto mode is controlled only by the provider value sent by
    # the current request. Do not replace "auto" with a previously saved
    # Custom provider here. A saved Custom setting is used only when the
    # frontend explicitly sends provider="custom".
    #
    # This prevents a stale Gemini custom setting from hijacking Auto mode
    # and stopping the intended Gemini -> Groq -> OpenRouter -> Ollama chain.
    if provider == "auto":
        print("[AI ROUTER] Auto mode requested; using shared Auto fallback chain.", flush=True)
    # FASTEST PATH: solve unambiguous arithmetic before session lookup, intent
    # classification, BI profiling, or any remote AI provider call.
    try:
        from ai.analyst import _try_python_arithmetic
        python_result = _try_python_arithmetic(question)
    except Exception as arithmetic_import_error:
        print(f"[Python arithmetic route unavailable] {arithmetic_import_error}", flush=True)
        python_result = None
    # Check condition
    if python_result is not None:
        print("[AI ROUTER] Arithmetic answered locally by Python", flush=True)
        return {
            "answer": str(python_result.get("answer", "")),
            "details": {
                "analysis": "python_arithmetic",
                "provider": python_result.get("provider", "Python (local calculation)"),
                "provider_result": python_result,
                "fast_path": True,
            },
        }
    # FAST PATH: predefined conversational responses before any AI provider call.
    _predefined_key = question.lower().strip(" .,!?")
    _predefined_responses = {
        "hi": "Hello! How can I help you with your data analysis today?",
        "hello": "Hello! How can I help you with your data analysis today?",
        "hey": "Hey! How can I help you with your data analysis today?",
        "hii": "Hello! How can I help you with your data analysis today?",
        "hiii": "Hello! How can I help you with your data analysis today?",
        "good morning": "Good morning! How can I help you with your data analysis today?",
        "good afternoon": "Good afternoon! How can I help you with your data analysis today?",
        "good evening": "Good evening! How can I help you with your data analysis today?",
        "thanks": "You are welcome!",
        "thank you": "You are welcome!",
    }
    predefined = _predefined_responses.get(_predefined_key)
    # Check condition
    if predefined:
        print(f"[AI ROUTER] Predefined response matched: {_predefined_key}", flush=True)
        return {
            "answer": str(predefined),
            "details": {
                "analysis": "predefined_response",
                "provider": "Local question bank",
            },
        }
    # Without a workbook session, use general chat instead of returning 404.
    # Dataset-specific questions continue through the existing logic below.
    if not req.sessionId:
        try:
            from ai.analyst import answer_general_chat
            result = answer_general_chat(question, req.history, provider=provider)
            if isinstance(result, dict):
                answer = str(result.get("answer") or result.get("interpretation") or "").strip()
                if not answer:
                    answer = "I couldn't generate a response. Please try rephrasing your question."
                details = result
            else:
                answer = str(result)
                details = {"analysis": "general_chat"}
            return {
                "answer": answer,
                "details": {
                    "analysis": "general_chat",
                    "requested_provider": requested_provider,
                    "provider_result": details,
                },
            }
        except Exception as exc:
            return {
                "answer": (
                    "I couldn't answer that message right now. Please check the AI "
                    "provider configuration and backend terminal for the technical error."
                ),
                "details": {"analysis": "general_chat", "error": str(exc)},
            }
    # Set up values
    state = get_session(req.sessionId)
    df = state["workspace"].current
    question_lower = question.lower()
    normalized_question = question_lower.strip(" .,!?")
    # EARLY RFM SEGMENT ROUTER:
    # This must run immediately after loading the workbook and before
    # _customer_analytics_answer(), BI recommendation handling, or generic
    # top-customer revenue ranking. Those broader handlers can otherwise
    # intercept "top 20 customers in the At Risk segment".
    rfm_segment = None
    # Check condition
    if any(term in question_lower for term in [
        "at risk", "at-risk", "risk of becoming inactive",
        "becoming inactive", "at risk of becoming inactive",
    ]):
        rfm_segment = "At Risk"
    elif any(term in question_lower for term in [
        "hibernating", "inactive customers", "customers inactive",
    ]):
        rfm_segment = "Hibernating"
    elif any(term in question_lower for term in [
        "cannot lose them", "can't lose them", "cannot_lose_them",
    ]):
        rfm_segment = "Cannot Lose Them"
    elif "champion" in question_lower:
        rfm_segment = "Champions"
    elif "loyal customer" in question_lower or "loyal customers" in question_lower:
        rfm_segment = "Loyal Customers"
    elif "potential loyalist" in question_lower:
        rfm_segment = "Potential Loyalists"
    elif "new customer" in question_lower or "new customers" in question_lower:
        rfm_segment = "New Customers"
    # Set up values
    asks_rfm_segment = (
        rfm_segment is not None
        and any(term in question_lower for term in [
            "customer", "inactive", "risk", "segment", "rfm", "list", "show", "identify",
        ])
    )
    # Check condition
    if asks_rfm_segment:
        top_match = re.search(r"\btop\s+(\d+)\b", question_lower)
        requested_n = int(top_match.group(1)) if top_match else 20
        try:
            rfm_result = _rfm_analysis_answer(
                df,
                state.get("schema"),
                segment_filter=rfm_segment,
                top_n=requested_n,
            )
            if rfm_result:
                print(
                    f"[AI ROUTER] RFM segment fast path: {rfm_segment}; "
                    f"requested_top_n={requested_n}",
                    flush=True,
                )
                return {
                    "answer": rfm_result.get("answer", ""),
                    "details": {
                        **(rfm_result.get("details") or {}),
                        "analysis": "rfm_segment_customers",
                        "requested_segment": rfm_segment,
                        "requested_top_n": requested_n,
                        "fast_path": True,
                    },
                }
            return {
                "answer": (
                    "I couldn't calculate this RFM segment. Required columns are "
                    "customer ID, invoice ID, transaction date, quantity, and unit price."
                ),
                "details": {
                    "analysis": "rfm_segment_customers",
                    "requested_segment": rfm_segment,
                    "available_columns": [str(column) for column in df.columns],
                    "fast_path": True,
                },
            }
        except Exception as exc:
            print(f"[AI ROUTER] RFM segment calculation failed: {exc}", flush=True)
            return {
                "answer": f"I couldn't calculate the {rfm_segment} customer list: {exc}",
                "details": {
                    "analysis": "rfm_segment_customers",
                    "requested_segment": rfm_segment,
                    "error": str(exc),
                    "fast_path": True,
                },
            }
    # FAST DETERMINISTIC RANKING ROUTES:
    # Common ranking questions should not pay for BI classification, profiling,
    # orchestration, or an LLM call. The helpers calculate from the live workbook.
    requested_top_match = re.search(r"\btop\s+(\d+)\b", question_lower)
    requested_top_n = max(1, min(int(requested_top_match.group(1)), 100)) if requested_top_match else 10
    asks_top_product_revenue_fast = (
        any(term in question_lower for term in ("product", "products", "item", "stock code"))
        and any(term in question_lower for term in ("revenue", "sales value", "sales amount", "total spending"))
        and any(term in question_lower for term in ("top", "highest", "most", "best", "which"))
        and not any(term in question_lower for term in ("return", "returned", "refund"))
    )
    # Check condition
    if asks_top_product_revenue_fast:
        started = time.perf_counter()
        result = _top_product_answer(
            df, state.get("schema"), metric="revenue", top_n=requested_top_n
        )
        if result:
            elapsed = round((time.perf_counter() - started) * 1000, 2)
            print(f"[AI FAST PATH] Top products by revenue: {elapsed} ms", flush=True)
            return {
                "answer": result.get("answer", ""),
                "details": {**(result.get("details") or {}), "fast_path": True,
                            "calculation_ms": elapsed, "provider": "Python (cached deterministic analytics)"},
            }
    # Set up values
    asks_top_customer_revenue_fast = (
        "customer" in question_lower
        and any(term in question_lower for term in ("top", "highest", "most", "rank", "best"))
        and any(term in question_lower for term in ("revenue", "sales", "spending", "spent", "purchase", "total"))
        and not any(term in question_lower for term in ("missing", "without", "empty", "at risk", "at-risk", "rfm"))
    )
    # Check condition
    if asks_top_customer_revenue_fast:
        started = time.perf_counter()
        result = _top_customer_revenue_answer(
            df, state.get("schema"), top_n=requested_top_n
        )
        if result:
            elapsed = round((time.perf_counter() - started) * 1000, 2)
            print(f"[AI FAST PATH] Top customers by net revenue: {elapsed} ms", flush=True)
            return {
                "answer": result.get("answer", ""),
                "details": {**(result.get("details") or {}), "fast_path": True,
                            "calculation_ms": elapsed, "provider": "Python (cached deterministic analytics)"},
            }
    # FAST PATH: handle conversational and year questions before expensive BI classification.
    greeting_messages = {
        "hi": "Hi! I'm your AI Analyst. How can I help?",
        "hello": "Hello! I'm your AI Analyst. How can I help?",
        "hey": "Hey! What would you like to know?",
        "hi there": "Hi! What would you like to know?",
        "hello there": "Hello! What would you like to know?",
        "how are you": "I'm ready to help. What would you like to work on?",
        "good morning": "Good morning! How can I help?",
        "good afternoon": "Good afternoon! How can I help?",
        "good evening": "Good evening! How can I help?",
    }
    # Check condition
    if normalized_question in greeting_messages:
        return {
            "answer": greeting_messages[normalized_question],
            "details": {"analysis": "greeting", "provider": "backend", "fast_path": True},
        }
    # Set up values
    asks_year_context = any(term in question_lower for term in (
        "which year is this", "what year is this", "current year",
        "what year are we in", "which year are we in",
        "what is the year", "what year is it",
    ))
    # Check condition
    if asks_year_context:
        metadata = state.get("date_metadata")
        if not isinstance(metadata, dict):
            # Older persisted sessions predate cached date metadata. Compute once.
            metadata = _build_dataset_date_metadata(df, state.get("schema"))
            state["date_metadata"] = metadata
            persist_session(req.sessionId, state)
        current_year = datetime.datetime.now().year
        if metadata.get("available"):
            years = metadata.get("years") or []
            year_text = ", ".join(str(year) for year in years) if years else "not available"
            answer = (
                f"The current year is **{current_year}**.\n\n"
                f"Your dataset covers **{metadata['min_date']} to {metadata['max_date']}** "
                f"and contains records from these calendar years: **{year_text}**."
            )
        else:
            answer = (
                f"The current year is **{current_year}**. "
                "I couldn't identify a usable date range in the uploaded dataset."
            )
        return {
            "answer": answer,
            "details": {
                "analysis": "current_year_and_dataset_date_range",
                "current_year": current_year,
                "dataset_date_metadata": metadata,
                "fast_path": True,
            },
        }
    # Resolve short follow-ups such as "which are they?" from the previous
    # country-count question, and list country names directly from pandas.
    recent_user_questions = [
        str(item.get("content", "")).strip().lower()
        for item in (req.history or [])[-8:]
        if isinstance(item, dict) and item.get("role") == "user"
    ]
    is_country_follow_up = (
        normalized_question in {"which are they", "what are they", "list them", "name them", "which ones", "what are those"}
        and any(
            ("countr" in prior and any(term in prior for term in ("how many", "number of", "count", "distinct", "unique")))
            for prior in recent_user_questions
        )
    )
    asks_country_list = (
        any(term in question_lower for term in ("list countries", "list the countries", "which countries", "what countries", "name the countries", "show countries", "which are the countries"))
        or is_country_follow_up
    )
    # Check condition
    if asks_country_list:
        country_col = _semantic_column(
            df, state.get("schema"), "country", ["country", "countries", "region", "market"]
        )
        if country_col is not None:
            country_values = df[country_col].astype("string").str.strip()
            country_values = country_values.replace(
                {"": pd.NA, "nan": pd.NA, "none": pd.NA, "null": pd.NA, "<na>": pd.NA}
            ).dropna()
            # Deduplicate case-insensitively while retaining a readable source label.
            unique_by_key = {}
            for value in country_values:
                key = str(value).casefold()
                unique_by_key.setdefault(key, str(value))
            countries = sorted(unique_by_key.values(), key=str.casefold)
            return {
                "answer": f"There are **{len(countries)} distinct countries** in the dataset:\n\n" + ", ".join(countries),
                "details": {
                    "analysis": "distinct_country_list",
                    "column": str(country_col),
                    "country_count": len(countries),
                    "countries": countries,
                    "fast_path": True,
                    "provider": "Python (deterministic dataset calculation)",
                },
            }
        return {
            "answer": "I couldn't find a country or region column in the loaded dataset.",
            "details": {"analysis": "distinct_country_list", "available_columns": [str(c) for c in df.columns]},
        }
    # Fast-route obvious workbook and general questions without a separate
    # LLM intent-classifier request. This saves one full model round-trip.
    # Ambiguous questions retain the existing AI classifier and fallback logic.
    intent_started = time.perf_counter()
    fast_intent = _fast_dataset_question_intent(question)
    # Check condition
    if fast_intent is None:
        fast_intent = _fast_general_question_intent(question)
    # Check condition
    if fast_intent is not None:
        question_intent = fast_intent
        intent_result = {
            "intent": question_intent,
            "reason": "Matched a clear question pattern without an LLM classifier call.",
            "confidence": "high",
            "provider": "backend-fast-route",
            "elapsed_ms": 0.0,
            "routing": "keyword_fast_path",
        }
        intent_fallback_used = False
    else:
        try:
            intent_result = _classify_question_intent(
                question, df, req.history, provider=provider
            )
            if requested_provider != provider:
                intent_result["requested_provider"] = requested_provider
                intent_result["effective_provider"] = provider
            question_intent = intent_result["intent"]
            intent_fallback_used = False
        except Exception as intent_error:
            print(f"AI intent classifier warning: {intent_error}")
            question_intent = _fallback_question_intent(question)
            intent_result = {
                "intent": question_intent,
                "reason": "AI classifier unavailable; used conservative fallback.",
                "confidence": "fallback",
                "provider": None,
                "elapsed_ms": round((time.perf_counter() - intent_started) * 1000, 2),
                "error": str(intent_error)[:300],
                "routing": "fallback",
            }
            intent_fallback_used = True
    # Check condition
    if question_intent == "general_knowledge":
        try:
            from ai.analyst import answer_business_question
            # DATASET-FIRST SAFETY NET:
            # The intent classifier only sees column names and workbook dimensions.
            # It can therefore mistake a question about actual workbook values for
            # general knowledge. Always give the dataset-aware analyst the first
            # opportunity to answer while a workbook is loaded. That helper uses
            # deterministic pandas calculations for dataset questions and routes
            # genuinely unrelated questions to general chat.
            result = answer_business_question(
                question,
                df,
                provider=provider,
                schema=state.get("schema"),
            )
            if isinstance(result, dict):
                answer = str(
                    result.get("answer") or result.get("interpretation") or ""
                ).strip()
            else:
                answer = str(result).strip()
            if not answer:
                answer = "I couldn't generate a direct answer. Please rephrase your question."
            return {
                "answer": answer,
                "details": {
                    "analysis": "dataset_first_general_fallback",
                    "intent": intent_result,
                    "intent_fallback_used": intent_fallback_used,
                    "provider_result": result if isinstance(result, dict) else {},
                    "dataset_was_available": True,
                    "fast_path": True,
                },
            }
        except Exception as exc:
            return {
                "answer": (
                    "I couldn't answer that question from the loaded workbook or "
                    "general knowledge right now. Please check the backend terminal "
                    "for the technical error."
                ),
                "details": {
                    "analysis": "dataset_first_general_fallback",
                    "intent": intent_result,
                    "intent_fallback_used": intent_fallback_used,
                    "dataset_was_available": True,
                    "error": str(exc),
                },
            }
    # Support a numbered, line-separated, or question-mark-separated list of
    # questions in one chat message. Each item uses the same deterministic
    # routing below, and the individual answers are combined into one response.
    compound_questions = _split_compound_questions(req.question)
    # Check condition
    if len(compound_questions) > 1:
        combined_results = []
        for individual_question in compound_questions:
            individual_result = ask(
                AskRequest(sessionId=req.sessionId, question=individual_question, history=req.history, provider=provider)
            )
            combined_results.append({
                "question": individual_question,
                "answer": str(individual_result.get("answer", "")),
                "details": individual_result.get("details", {}),
            })
        combined_answer = "\n\n".join(
            f"**{index}. {item['question']}**\n\n{item['answer']}"
            for index, item in enumerate(combined_results, start=1)
        )
        return {
            "answer": combined_answer,
            "details": {
                "analysis": "multiple_questions",
                "question_count": len(combined_results),
                "results": combined_results,
            },
        }
    # Evidence-first business recommendations: use calculated dataset metrics,
    # not unsupported model-generated business claims.
    try:
        bi_report = analyze_business_question(question, df, state.get("schema"))
        classification = bi_report.get("classification") or {}
        detected_intents = set(classification.get("intents") or [])
        # Specific analytical requests must reach their deterministic handlers
        # before the generic recommendation fallback, even when the classifier
        # also detects a recommendation intent in a compound question.
        specific_analytics = {
            "ranking", "product", "customer", "trend", "comparison",
            "forecast", "anomaly", "segmentation", "aggregation",
        }
        if (
            classification.get("primary_intent") == "recommendation"
            and not (detected_intents & specific_analytics)
        ):
            return _business_intelligence_answer(question, df, state.get("schema"), bi_report)
    except Exception as exc:
        # Do not break existing analytics if the optional BI layer encounters an issue.
        print(f"Business intelligence layer warning: {exc}")
    # Deterministic customer-ID completeness and sales breakdown.
    asks_customer_id_sales = (
        "customer" in question_lower
        and any(term in question_lower for term in ["missing", "empty", "without", "with and without"])
        and any(term in question_lower for term in ["sales", "revenue", "percentage", "percent", "rows", "how many"])
    )
    # Check condition
    if asks_customer_id_sales:
        try:
            result = _customer_id_sales_answer(df, state.get("schema"))
            if result:
                return result
            return {
                "answer": "I need customer_id, quantity, and price columns to calculate this. Please check the column names in your dataset.",
                "details": {"analysis": "customer_id_missing_and_sales", "available_columns": [str(c) for c in df.columns]},
            }
        except Exception as exc:
            return {
                "answer": "I couldn't calculate the missing-customer and sales breakdown.",
                "details": {"analysis": "customer_id_missing_and_sales", "error": str(exc)},
            }
    # Handle simple greetings directly so the dataset-analysis model is not forced
    # to answer a social message using dataset context.
    greeting_messages = {
        "hi": "Hi! I'm your AI Analyst. Ask me a question about your loaded dataset, and I'll help analyze it.",
        "hello": "Hello! I'm your AI Analyst. Ask me a question about your loaded dataset, and I'll help analyze it.",
        "hey": "Hey! I'm your AI Analyst. What would you like to know about your dataset?",
        "hi there": "Hi! I'm your AI Analyst. What would you like to know about your dataset?",
        "hello there": "Hello! I'm your AI Analyst. What would you like to know about your dataset?",
        "how are you": "I'm ready to help analyze your data! What would you like to find out?",
        "hi how are you": "I'm doing well and ready to help analyze your data! What would you like to find out?",
        "hello how are you": "I'm doing well and ready to help analyze your data! What would you like to find out?",
        "good morning": "Good morning! I'm your AI Analyst. What would you like to know about your dataset?",
        "good afternoon": "Good afternoon! I'm your AI Analyst. What would you like to know about your dataset?",
        "good evening": "Good evening! I'm your AI Analyst. What would you like to know about your dataset?",
    }
    # Check condition
    if normalized_question in greeting_messages:
        return {
            "answer": greeting_messages[normalized_question],
            "details": {"analysis": "greeting", "provider": "backend"},
        }
    # Deterministic customer analytics must run before the generic distinct-count
    # handler below. Otherwise month-specific questions such as
    # "How many unique customers purchased in January 2011?" are intercepted
    # and incorrectly answered with the all-time customer count.
    try:
        customer_result = _customer_analytics_answer(
            df, state.get("schema"), question
        )
        if customer_result:
            return customer_result
    except Exception as exc:
        return {
            "answer": "I couldn't calculate the requested customer analytics.",
            "details": {
                "analysis": "customer_analytics",
                "error": str(exc),
            },
        }
    # General-knowledge routing is handled once, above, before BI classification.
    # Detailed product-return requests must be handled before the generic
    # negative-quantity counter below.
    asks_product_return_analysis = (
        any(term in question_lower for term in [
            "return analysis", "returned products", "returned quantity",
            "returned value", "return rate", "return invoice",
            "product returns", "top products by returns",
        ])
        and any(term in question_lower for term in [
            "product", "products", "item", "stock code",
            "returned quantity", "returned value",
        ])
    )
    # Check condition
    if asks_product_return_analysis:
        try:
            result = _product_return_analysis_answer(
                df, state.get("schema"), limit=10
            )
            if result:
                return result
            return {
                "answer": (
                    "I need product code, quantity, and unit price columns "
                    "to perform product return analysis."
                ),
                "details": {
                    "analysis": "product_return_analysis",
                    "available_columns": [
                        str(column) for column in df.columns
                    ],
                },
            }
        except Exception as exc:
            return {
                "answer": "I couldn't calculate the product return analysis.",
                "details": {
                    "analysis": "product_return_analysis",
                    "error": str(exc),
                },
            }
    # Count rows with negative quantity deterministically, without asking the LLM.
    asks_negative_quantity = (
        ("negative quantity" in question_lower)
        or ("quantity less than zero" in question_lower)
        or ("quantity below zero" in question_lower)
        or ("quantity < 0" in question_lower)
    )
    # Check condition
    if asks_negative_quantity:
        quantity_col = _semantic_column(df, state.get("schema"), "quantity", ["Quantity", "Qty", "Units"])
        if quantity_col is not None:
            quantity = pd.to_numeric(df[quantity_col], errors="coerce")
            negative_count = int((quantity < 0).sum())
            return {
                "answer": (
                    f"Rows with negative quantity: {negative_count:,}. "
                    f"Dataset rows: {len(df):,}."
                ),
                "details": {
                    "analysis": "negative_quantity_count",
                    "column": str(quantity_col),
                    "negative_rows": negative_count,
                    "dataset_rows": int(len(df)),
                    "invalid_or_missing_quantity_rows": int(quantity.isna().sum()),
                },
            }
        return {
            "answer": "I couldn't find a quantity column in the loaded dataset.",
            "details": {
                "analysis": "negative_quantity_count",
                "available_columns": [str(column) for column in df.columns],
            },
        }
    # Count rows with negative price deterministically, without asking the LLM.
    asks_negative_price = (
        ("negative price" in question_lower)
        or ("price less than zero" in question_lower)
        or ("price below zero" in question_lower)
        or ("price < 0" in question_lower)
    )
    # Check condition
    if asks_negative_price:
        price_col = _semantic_column(df, state.get("schema"), "unit_price", ["Price", "Unit Price", "UnitPrice", "Item Price"])
        if price_col is not None:
            price = pd.to_numeric(df[price_col], errors="coerce")
            negative_count = int((price < 0).sum())
            return {
                "answer": (
                    f"Rows with negative price: {negative_count:,}. "
                    f"Dataset rows: {len(df):,}."
                ),
                "details": {
                    "analysis": "negative_price_count",
                    "column": str(price_col),
                    "negative_rows": negative_count,
                    "dataset_rows": int(len(df)),
                    "invalid_or_missing_price_rows": int(price.isna().sum()),
                },
            }
        return {
            "answer": "I couldn't find a price column in the loaded dataset.",
            "details": {
                "analysis": "negative_price_count",
                "available_columns": [str(column) for column in df.columns],
            },
        }
    # Deterministic semantic query engine: calculate with pandas, never infer numeric results with the LLM.
    asks_average_order_value = any(term in question_lower for term in ["average order value", "average value per order", "average invoice value", "aov"])
    # Check condition
    if asks_average_order_value:
        result = _average_order_value_answer(df, state.get("schema"))
        if result:
            return result
        return {"answer": "I need invoice ID, quantity, and unit price columns to calculate average order value.", "details": {"analysis": "average_order_value", "available_columns": [str(c) for c in df.columns]}}
    # Set up values
    asks_country_revenue = (
        any(term in question_lower for term in ["country", "countries", "region", "market"])
        and any(term in question_lower for term in ["revenue", "sales", "generates", "generate", "highest", "most"])
        and "customer" not in question_lower
        and not re.search(r"\bcount\b|\bnumber\s+of\b", question_lower)
    )
    # Check condition
    if asks_country_revenue:
        # Run the safe analytics orchestrator for this dataset question.
        # The deterministic country-revenue calculation below remains the
        # source of the displayed answer; orchestration adds execution details.
        try:
            from ai.orchestrator import run_analytics_orchestrator
            tool_execution = run_analytics_orchestrator(req.question, df)
        except Exception as exc:
            # Keep the existing answer available even if an optional tool fails.
            tool_execution = {
                "status": "error",
                "selection_mode": "dynamic",
                "execution_permission": "automatic_safe_tools_only",
                "tools": [],
                "execution_trace": [],
                "results": {},
                "error": str(exc),
            }
        result = _country_revenue_answer(df, state.get("schema"))
        if result:
            result["tool_execution"] = tool_execution
            return result
        return {
            "answer": (
                "I need a country/region column plus quantity and unit price "
                "columns to calculate revenue by country."
            ),
            "details": {
                "analysis": "country_revenue",
                "available_columns": [str(c) for c in df.columns],
            },
            "tool_execution": tool_execution,
        }
    # Handle combined best/least-selling quantity questions before revenue ranking;
    # these questions may also request revenue as an output column.
    asks_product_quantity_extremes = (
        any(term in question_lower for term in ["product", "item", "stock code"])
        and any(term in question_lower for term in ["best-selling", "best selling", "least-selling", "least selling", "bottom", "top"])
        and any(term in question_lower for term in ["net quantity", "quantity sold", "units sold", "least-selling", "least selling"])
    )
    # Check condition
    if asks_product_quantity_extremes:
        result = _product_quantity_extremes_answer(df, state.get("schema"), limit=10)
        if result:
            return result
        return {
            "answer": "I need product ID, quantity, unit price, and ideally invoice columns to compare best- and least-selling products.",
            "details": {"analysis": "product_quantity_extremes", "available_columns": [str(c) for c in df.columns]},
        }
    # Set up values
    asks_top_product_revenue = (
        any(term in question_lower for term in ["product", "item", "stock code"])
        and any(term in question_lower for term in ["revenue", "sales value", "sales amount"])
        and any(term in question_lower for term in ["most", "highest", "top", "best"])
    )
    # Check condition
    if asks_top_product_revenue:
        result = _top_product_answer(df, state.get("schema"), metric="revenue", top_n=10 if re.search(r"\b(?:top|which|show|list)\s*(?:the\s*)?(?:10|ten)\b", question_lower) else 5)
        if result:
            return result
        return {"answer": "I need product ID, quantity, and unit price columns to rank products by revenue.", "details": {"analysis": "top_product_by_revenue", "available_columns": [str(c) for c in df.columns]}}
    # Set up values
    asks_top_product_quantity = (
        any(term in question_lower for term in ["product", "item", "stock code", "best seller", "best-selling", "bestselling"])
        and any(term in question_lower for term in ["most", "highest", "top", "best", "sells", "selling", "sold"])
        and not any(term in question_lower for term in ["revenue", "sales value", "sales amount", "price"])
    )
    # Check condition
    if asks_top_product_quantity:
        positive_only = any(term in question_lower for term in ["excluding returns", "without returns", "gross quantity", "positive quantity", "before returns"])
        result = _top_product_answer(df, state.get("schema"), metric="quantity", top_n=10 if any(t in question_lower for t in ["top 10", "top ten", "list", "show all top"]) else 5, positive_only=positive_only)
        if result:
            return result
        return {"answer": "I need product ID and quantity columns to rank products by quantity sold.", "details": {"analysis": "top_product_by_quantity", "available_columns": [str(c) for c in df.columns]}}
    # Set up values
    asks_total_quantity = (
        any(term in question_lower for term in ["total quantity", "total units", "units sold", "quantity sold", "how many units", "sum of quantity"])
        and not any(term in question_lower for term in ["product", "item", "stock code", "by country", "by month"])
    )
    # Check condition
    if asks_total_quantity:
        result = _total_quantity_answer(df, state.get("schema"))
        if result:
            return result
    # Deterministic RFM segment queries must be routed before generic
    # "top customers" revenue ranking. Otherwise phrases such as
    # "top 20 customers in the At Risk segment" are misclassified as revenue.
    rfm_segment = None
    # Check condition
    if any(term in question_lower for term in [
        "at risk", "at-risk", "risk of becoming inactive", "becoming inactive",
    ]):
        rfm_segment = "At Risk"
    elif any(term in question_lower for term in [
        "hibernating", "inactive customers", "customers inactive",
    ]):
        rfm_segment = "Hibernating"
    elif any(term in question_lower for term in [
        "cannot lose them", "can't lose them", "cannot_lose_them",
    ]):
        rfm_segment = "Cannot Lose Them"
    elif "champion" in question_lower:
        rfm_segment = "Champions"
    elif "loyal customer" in question_lower or "loyal customers" in question_lower:
        rfm_segment = "Loyal Customers"
    elif "potential loyalist" in question_lower:
        rfm_segment = "Potential Loyalists"
    elif "new customer" in question_lower or "new customers" in question_lower:
        rfm_segment = "New Customers"
    # Set up values
    asks_rfm_segment = rfm_segment is not None and any(term in question_lower for term in [
        "customer", "inactive", "risk", "segment", "rfm", "list", "show", "identify",
    ])
    # Check condition
    if asks_rfm_segment:
        top_match = re.search(r"\btop\s+(\d+)\b", question_lower)
        requested_n = int(top_match.group(1)) if top_match else 20
        try:
            result = _rfm_analysis_answer(
                df, state.get("schema"), segment_filter=rfm_segment, top_n=requested_n
            )
            if result:
                return result
            return {
                "answer": "I couldn't calculate the requested RFM segment from the loaded data. Check that customer ID, invoice ID, date, quantity, and price columns are available.",
                "details": {
                    "analysis": "rfm_segment_customers",
                    "requested_segment": rfm_segment,
                    "available_columns": [str(column) for column in df.columns],
                },
            }
        except Exception as exc:
            return {
                "answer": f"I couldn't calculate the {rfm_segment} customer list.",
                "details": {
                    "analysis": "rfm_segment_customers",
                    "requested_segment": rfm_segment,
                    "error": str(exc),
                },
            }
    # Deterministic top-customer revenue ranking.
    asks_top_customer_revenue = (
        "customer" in question_lower
        and any(term in question_lower for term in ["revenue", "sales", "spending", "spent", "highest", "top"])
        and any(term in question_lower for term in ["top", "highest", "most", "rank", "best"])
        and not any(term in question_lower for term in ["missing", "without", "empty"])
    )
    # Check condition
    if asks_top_customer_revenue:
        try:
            result = _top_customer_revenue_answer(df, state.get("schema"), top_n=10)
            if result:
                return result
            return {
                "answer": "I need customer ID, quantity, and unit price columns to rank customers by revenue.",
                "details": {
                    "analysis": "top_customer_revenue",
                    "available_columns": [str(column) for column in df.columns],
                },
            }
        except Exception as exc:
            return {
                "answer": "I couldn't calculate the top customers by revenue.",
                "details": {"analysis": "top_customer_revenue", "error": str(exc)},
            }
    # Deterministic RFM segmentation; the language model must not invent scores.
    asks_rfm = any(term in question_lower for term in [
        "rfm", "recency frequency monetary", "customer segmentation",
        "customer segments", "segment customers", "segment the customers",
        "identify customers at risk", "customers at risk", "at risk of becoming inactive",
        "customers becoming inactive", "identify inactive customers",
    ])
    # Check condition
    if asks_rfm:
        try:
            result = _rfm_analysis_answer(df, state.get("schema"))
            if result:
                return result
            return {
                "answer": "I need customer ID, invoice/order ID, transaction date, quantity, and unit price columns to perform RFM analysis.",
                "details": {
                    "analysis": "rfm_segmentation",
                    "available_columns": [str(column) for column in df.columns],
                },
            }
        except Exception as exc:
            return {
                "answer": "I couldn't calculate RFM segmentation from the loaded data.",
                "details": {"analysis": "rfm_segmentation", "error": str(exc)},
            }
    # Answer distinct-count questions deterministically, without asking the LLM.
    asks_distinct_count = any(
        term in question_lower
        for term in ("distinct", "unique", "different", "count", "how many")
    )
    distinct_target = None
    distinct_candidates = None
    distinct_label = None
    # Check condition
    if asks_distinct_count:
        if any(term in question_lower for term in ("stock code", "stock_code", "stockcode", "item code", "product code")):
            distinct_target = "stock_code"
            distinct_candidates = ["stock_code", "stock code", "stockcode", "item code", "product code"]
            distinct_label = "stock codes"
        elif any(term in question_lower for term in ("customer id", "customer_id", "customerid", "customer number", "customer no", "unique customer", "distinct customer", "customers")):
            distinct_target = "customer_id"
            distinct_candidates = ["customer_id", "customer id", "customerid", "customer number", "customer no"]
            distinct_label = "customer IDs"
        elif "invoice" in question_lower or "order" in question_lower:
            distinct_target = "invoice"
            distinct_candidates = ["invoice", "invoice number", "invoice no", "invoice_number", "invoiceno"]
            distinct_label = "invoice numbers"
    # Check condition
    if distinct_target is not None:
        semantic_key = ("invoice_id" if distinct_target == "invoice" else "product_id" if distinct_target == "stock_code" else distinct_target)
        column = _semantic_column(df, state.get("schema"), semantic_key, distinct_candidates)
        if column is not None:
            values = df[column].astype("string").str.strip()
            # Exclude null, blank, and common textual representations of missing data.
            values = values.replace(
                {"": pd.NA, "nan": pd.NA, "none": pd.NA, "null": pd.NA, "<na>": pd.NA}
            ).dropna()
            # Normalize mixed numeric/text identifiers such as 579440 and 579440.0.
            # Keep other strings (e.g. stock codes with letters) unchanged.
            values = values.str.replace(r"\.0$", "", regex=True)
            distinct_count = int(values.nunique(dropna=True))
            return {
                "answer": (
                    f"Distinct {distinct_label}: {distinct_count:,}. "
                    "Missing and empty values were excluded."
                ),
                "details": {
                    "analysis": "distinct_count",
                    "target": distinct_target,
                    "column": str(column),
                    "distinct_count": distinct_count,
                    "missing_or_empty_excluded": True,
                    "normalization": "trimmed whitespace and removed trailing .0",
                },
            }
        return {
            "answer": f"I couldn't find the {distinct_label} column in the loaded dataset.",
            "details": {
                "analysis": "distinct_count",
                "target": distinct_target,
                "available_columns": [str(column) for column in df.columns],
            },
        }
    # Calculate average revenue directly instead of asking the language model.
    asks_average_revenue = (
        ("average" in question_lower or "mean" in question_lower)
        and any(term in question_lower for term in ["revenue", "sales", "per row", "each row", "transaction"])
        and any(term in question_lower for term in ["row", "transaction", "divide", "divided", "per "])
    )
    # Check condition
    if asks_average_revenue:
        try:
            result = _average_revenue_answer(df, state.get("schema"))
            if result:
                return result
        except Exception as exc:
            return {"answer": "I couldn't calculate average revenue. Check the Quantity and UnitPrice columns.", "details": {"error": str(exc)}}
    # Exact date ranges and explicit two-year comparisons run before generic year filters.
    # Explicit month comparisons and month ranges must run before generic
    # year comparisons, single-month filters, and whole-dataset totals.
    asks_month_period = (
        any(term in question_lower for term in ["revenue", "sales", "turnover"])
        and re.search(
            r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
            r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
            r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(?:19|20)\d{2}\b",
            question_lower,
        ) is not None
        and any(term in question_lower for term in [
            "compare", "comparison", "versus", " vs ", "difference",
            "change", "between", "from", " to ", "through", "until",
        ])
    )
    # Check condition
    if asks_month_period:
        try:
            result = _month_period_revenue_answer(
                df, state.get("schema"), question
            )
            if result:
                return result
        except Exception as exc:
            return {
                "answer": "I couldn't calculate that month range or monthly comparison.",
                "details": {"analysis": "month_period_revenue", "error": str(exc)},
            }
    # Set up values
    asks_date_range_or_comparison = (
        any(term in question_lower for term in ["revenue", "sales", "turnover"])
        and (
            any(term in question_lower for term in ["between", "from", "through", "until", "compare", "comparison", "versus", " vs ", "difference"])
        )
    )
    # Check condition
    if asks_date_range_or_comparison:
        try:
            result = _date_range_or_year_comparison_answer(
                df, state.get("schema"), question
            )
            if result:
                return result
        except Exception as exc:
            return {
                "answer": "I couldn't calculate revenue for that date range or year comparison.",
                "details": {"analysis": "date_range_or_year_comparison", "error": str(exc)},
            }
    # Explicit month/year filters must run before the all-dataset total-revenue route.
    asks_date_specific_revenue = (
        any(term in question_lower for term in ["revenue", "sales", "turnover", "quantity * price", "quantity × price"])
        and re.search(r"\b(19\d{2}|20\d{2})\b", question_lower) is not None
        and not any(term in question_lower for term in ["average", "mean", "per customer"])
    )
    # Check condition
    if asks_date_specific_revenue:
        try:
            result = _date_filtered_revenue_answer(df, state.get("schema"), question)
            if result:
                return result
        except Exception as exc:
            return {"answer": "I couldn't calculate revenue for that date period.",
                    "details": {"analysis": "date_filtered_revenue", "error": str(exc)}}
    # Calculate total-revenue questions directly with pandas instead of the LLM.
    asks_total_revenue = (
        any(term in question_lower for term in [
            "total revenue", "total sales", "sum of revenue", "revenue total",
            "sales total", "calculate revenue", "calculate total", "overall revenue",
            "overall sales", "how much revenue", "revenue for the entire dataset",
            "revenue for the full dataset", "quantity * price", "quantity × price",
        ])
        and not any(
            term in question_lower
            for term in ["monthly", "by month", "per month", "month-by-month", "trend"]
        )
        and not any(term in question_lower for term in ["average", "mean", "per customer"])
    )
    # Check condition
    if asks_total_revenue:
        try:
            result = _total_revenue_answer(df, state.get("schema"))
            if result:
                return result
        except Exception as exc:
            return {
                "answer": "I couldn't calculate total revenue from the quantity and price columns.",
                "details": {"error": str(exc)},
            }
    # Use deterministic calculations for monthly-trend requests so dates and
    # totals are computed from the dataset rather than guessed by the language model.
    excludes_monthly_trend = any(
        phrase in question_lower
        for phrase in [
            "do not show the monthly",
            "don't show the monthly",
            "do not return the monthly",
            "don't return the monthly",
            "not the monthly sales trend",
            "without the monthly sales trend",
        ]
    )
    asks_monthly_trend = not excludes_monthly_trend and (
        (
            ("month" in question_lower or "monthly" in question_lower)
            and any(
                word in question_lower
                for word in ["trend", "sales", "revenue", "turnover"]
            )
        )
        or (
            "convert invoicedate" in question_lower
            and "date" in question_lower
        )
    )
    # Check condition
    if asks_monthly_trend:
        try:
            requested_year_match = re.search(r"\b(19\d{2}|20\d{2})\b", question_lower)
            requested_year = int(requested_year_match.group(1)) if requested_year_match else None
            result = _monthly_sales_answer(df, state.get("schema"), year=requested_year)
            if result:
                return result
        except Exception as exc:
            # Keep the error useful for debugging rather than silently inventing a result.
            return {
                "answer": "I couldn't calculate the monthly trend from these columns. Check that the date, quantity, and price columns contain valid values.",
                "details": {"error": str(exc)},
            }
    # Try, handle errors
    try:
        from ai.analyst import answer_business_question
        simple_language_instruction = (
            "IMPORTANT RESPONSE STYLE: Answer in simple everyday English. "
            "Use short sentences and explain technical words. Be direct. "
            "When the question asks for a calculation, show the numbers and how you calculated them. "
            "Do not claim to have changed or converted the dataset unless you actually changed it. "
            "If a requested result cannot be calculated from the data, say what is missing. "
            "User's question: "
        )
        result = answer_business_question(
            simple_language_instruction + req.question,
            df,
            provider=provider,
            schema=state.get("schema"),
        )
        if isinstance(result, dict):
            answer = str(result.get("answer") or "").strip()
            # Never return an empty chat bubble. If the model leaves answer blank,
            # use its interpretation as a fallback; otherwise return a clear message.
            if not answer:
                answer = str(result.get("interpretation") or "").strip()
            if not answer:
                answer = (
                    "I couldn't generate a direct answer. Please rephrase your question "
                    "or ask for a specific calculation from the loaded dataset."
                )
            details = result
        else:
            answer = str(result)
            details = {"result": result}
        return {"answer": answer, "details": details}
    except Exception as exc:
        return {
            "answer": "I couldn't answer that question right now. The dataset is loaded, but the AI service had a problem. Please check the backend terminal for the technical error.",
            "details": {
                "error": str(exc),
                "rows": len(df),
                "columns": list(map(str, df.columns)),
                "missing_cells": int(df.isna().sum().sum()),
                "hint": "Check AI provider configuration and backend logs.",
            },
        }


# Function: business intelligence report
@app.get("/api/business-intelligence/{sid}")
def business_intelligence_report(sid: str):
    """Return the metric catalog, computed metrics, classification defaults and recommendations."""
    state = get_session(sid)
    df = state["workspace"].current
    # Return result
    return analyze_business_question(
        "Provide an evidence-based business overview and identify improvement opportunities.",
        df,
        state.get("schema"),
    )


# Return available metric definitions and deterministic metric values
@app.get("/api/business-intelligence/{sid}/metrics")
def business_intelligence_metrics(sid: str):
    """Return available metric definitions and deterministic metric values."""
    state = get_session(sid)
    df = state["workspace"].current
    schema = state.get("schema")
    analysis = calculate_core_metrics(df, schema)
    # Return result
    return {
        "catalog": analysis["catalog"],
        "analysis": analysis,
    }


# Function: download
@app.get("/api/download/{sid}")
def download(sid: str, format: str = "csv"):
        # Set up values
        state = get_session(sid)
        df = state["workspace"].current
        buffer = io.BytesIO()
        # Check condition
        if format.lower() == "xlsx":
                    try:
                            df.to_excel(buffer, index=False)
                    except Exception as exc:
                            raise HTTPException(
                                        500, f"Could not create Excel file: {exc}"
                            ) from exc
                    buffer.seek(0)
                    return StreamingResponse(
                            buffer,
                            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            headers={"Content-Disposition": "attachment; filename=cleaned_dataset.xlsx"},
                    )
        buffer.write(df.to_csv(index=False).encode("utf-8"))
        buffer.seek(0)
        # Return result
        return StreamingResponse(
                    buffer,
                    media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=cleaned_dataset.csv"},
        )
