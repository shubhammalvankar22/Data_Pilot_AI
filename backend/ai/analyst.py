"""AI business analyst: Python-calculated facts + Gemini/Groq/OpenRouter/Ollama."""



# Imports
import json
import ast
import operator
import math

import os
from pathlib import Path

import re

import urllib.parse

import urllib.request
import urllib.error
import time
from datetime import datetime
from zoneinfo import ZoneInfo



import pandas as pd

from dotenv import load_dotenv



from ai.orchestrator import run_analytics_orchestrator

# Module-level setup
try:
    from business import analyze_business_question
except Exception:
    analyze_business_question = None





# Load the project-root .env file so API keys are available when this module is used.

load_dotenv()



# Constants and settings
GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_MODEL_2 = os.environ.get("GEMINI_MODEL_2", "gemini-3.5-flash-lite").strip()

GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# OpenRouter uses an OpenAI-compatible chat completions endpoint.
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = os.environ.get(
    "OPENROUTER_MODEL", "deepseek/deepseek-v4.1-flash-1017"
).strip()

OLLAMA_MODEL = "qwen2.5:3b"

OLLAMA_URL = "http://localhost:11434/api/chat"





WORLD_BANK_GDP_API = (

    "https://api.worldbank.org/v2/country/IND/"

    "indicator/NY.GDP.MKTP.CD"

)

WORLD_BANK_GDP_SOURCE = (

    "https://data.worldbank.org/indicator/NY.GDP.MKTP.CD?locations=IN"

)





# Fetch India's latest non-null nominal GDP observation from the World Bank
def get_india_latest_gdp():

    """Fetch India's latest non-null nominal GDP observation from the World Bank."""

    request_url = WORLD_BANK_GDP_API + "?format=json&mrnev=1"

    request = urllib.request.Request(

        request_url,

        headers={"User-Agent": "AI-Analyst/1.0"},

        method="GET",

    )

    # Try, handle errors
    try:

        with urllib.request.urlopen(request, timeout=15) as response:

            payload = json.loads(response.read().decode("utf-8"))



        if not isinstance(payload, list) or len(payload) < 2:

            return None



        observations = payload[1]

        if not isinstance(observations, list):

            return None



        valid_rows = [

            row for row in observations

            if isinstance(row, dict) and row.get("value") is not None

        ]

        if not valid_rows:

            return None



        latest = max(valid_rows, key=lambda row: int(row["date"]))

        value = float(latest["value"])

        year = str(latest["date"])



        return {

            "answer": (

                f"According to the World Bank, India's nominal GDP was "

                f"${value / 1_000_000_000_000:.2f} trillion in {year} "

                f"(current US dollars)."

            ),

            "interpretation": (

                "This is nominal GDP measured in current US dollars. "

                "National accounts data may be revised by the source."

            ),

            "recommendations": [],

            "follow_up_questions": [],

            "limitations": [],

            "suggested_analyses": [],

            "provider": "World Bank API",

            "analysis_mode": "live_data",

            "year": year,

            "value_usd": value,

            "source": WORLD_BANK_GDP_SOURCE,

        }

    except (

        urllib.error.URLError,

        TimeoutError,

        OSError,

        ValueError,

        TypeError,

        KeyError,

    ):

        return None





# Find a likely column from its name
def find_column(columns, keywords):

    """Find a likely column from its name."""

    # Loop over items
    for column in columns:

        name = str(column).strip().lower().replace("_", " ")

        if any(word in name for word in keywords):

            return column

    # Return result
    return None





# Parse common business date formats without forcing one exact format
def _parse_date_series(series):

    """Parse common business date formats without forcing one exact format."""

    parsed = pd.to_datetime(series, errors="coerce")

    # Check condition
    if parsed.notna().sum() == 0:

        parsed = pd.to_datetime(series, errors="coerce", dayfirst=True)

    # Return result
    return parsed





# Profile a dataset and calculate business metrics using Python
def build_dataset_context(df):

    """Profile a dataset and calculate business metrics using Python."""

    # Check condition
    if not isinstance(df, pd.DataFrame) or df.empty:

        raise ValueError("Upload a dataset containing at least one row.")



    # Set up values
    numeric_columns = df.select_dtypes(include="number").columns.tolist()



    date_col = find_column(

        df.columns,

        ["order date", "invoice date", "transaction date", "timestamp", "date"],

    )

    sales_col = find_column(

        numeric_columns,

        ["sales", "revenue", "turnover", "total amount", "order value"],

    )

    quantity_col = find_column(

        numeric_columns, ["quantity", "qty", "units sold"]

    )

    price_col = find_column(

        numeric_columns,

        ["unit price", "unitprice", "selling price", "item price", "price"],

    )



    data = df.copy()



    # Check condition
    if sales_col is not None:

        data["_ai_metric"] = pd.to_numeric(data[sales_col], errors="coerce")

        metric_name = str(sales_col)

    elif quantity_col is not None and price_col is not None:

        data["_ai_metric"] = (

            pd.to_numeric(data[quantity_col], errors="coerce")

            * pd.to_numeric(data[price_col], errors="coerce")

        )

        metric_name = f"{quantity_col} Ã— {price_col}"

    else:

        data["_ai_metric"] = float("nan")

        metric_name = None



    # Set up values
    context = {

        "dataset": {

            "rows": int(len(df)),

            "columns_count": int(len(df.columns)),

            "missing_cells": int(df.isna().sum().sum()),

            "duplicate_rows": int(df.duplicated().sum()),

            "columns": [],

        },

        "metric": {

            "name": metric_name,

            "date_column": str(date_col) if date_col is not None else None,

        },

        "calculated_facts": [],

        "monthly_totals": {},

        "segment_summaries": {},

        "limitations": [],

    }



    # Loop over items
    for column in df.columns:

        series = df[column]

        context["dataset"]["columns"].append({

            "name": str(column),

            "dtype": str(series.dtype),

            "missing_count": int(series.isna().sum()),

            "unique_count": int(series.nunique()),

            "sample_values": [

                str(value)[:80]

                for value in series.dropna().head(3).tolist()

            ],

        })



    # Set up values
    context["numeric_summary"] = {}

    # Loop over items
    for column in numeric_columns[:30]:

        values = pd.to_numeric(df[column], errors="coerce").dropna()

        if not values.empty:

            context["numeric_summary"][str(column)] = {

                "sum": float(values.sum()),

                "mean": float(values.mean()),

                "median": float(values.median()),

                "min": float(values.min()),

                "max": float(values.max()),

            }



    # Check condition
    if metric_name is None:

        context["limitations"].append(

            "No obvious sales/revenue column or Quantity Ã— UnitPrice "

            "combination was detected. Do not invent sales figures."

        )

    elif date_col is not None:

        dates = _parse_date_series(data[date_col])

        valid = pd.DataFrame({

            "date": dates,

            "metric": data["_ai_metric"],

        }).dropna()



        if not valid.empty:

            valid["month"] = valid["date"].dt.to_period("M")

            monthly = valid.groupby("month")["metric"].sum().sort_index()



            context["monthly_totals"] = {

                str(period): float(value)

                for period, value in monthly.items()

            }

            context["date_coverage"] = {

                "first_date": str(valid["date"].min()),

                "last_date": str(valid["date"].max()),

            }



            if len(monthly) >= 2:

                previous_period = monthly.index[-2]

                latest_period = monthly.index[-1]

                previous = float(monthly.iloc[-2])

                latest = float(monthly.iloc[-1])



                if previous != 0:

                    change = (latest - previous) / abs(previous) * 100

                    context["calculated_facts"].append({

                        "metric": metric_name,

                        "comparison": (

                            "latest recorded month vs previous recorded month"

                        ),

                        "previous_period": str(previous_period),

                        "latest_period": str(latest_period),

                        "previous_value": previous,

                        "latest_value": latest,

                        "absolute_change": latest - previous,

                        "percentage_change": change,

                        "direction": (

                            "decreased" if change < 0

                            else "increased" if change > 0

                            else "unchanged"

                        ),

                    })

                else:

                    context["limitations"].append(

                        "The previous period is zero, so the percentage "

                        "change is undefined."

                    )

            else:

                context["limitations"].append(

                    "At least two months of valid records are needed "

                    "for a monthly comparison."

                )

    elif metric_name is not None:

        total = data["_ai_metric"].sum(min_count=1)

        if pd.notna(total):

            context["calculated_facts"].append({

                "metric": metric_name,

                "total": float(total),

                "note": "Total across available rows; no date-based "

                        "comparison is possible without a date column.",

            })



    # Provide possible segment breakdowns for business investigation.

    if metric_name is not None:

        for column in df.columns:

            if column in (date_col, sales_col):

                continue



            if (

                not pd.api.types.is_numeric_dtype(df[column])

                and 2 <= df[column].nunique(dropna=True) <= 30

            ):

                segment_data = pd.DataFrame({

                    "segment": df[column].astype("string"),

                    "metric": data["_ai_metric"],

                }).dropna()



                grouped = (

                    segment_data.groupby("segment")["metric"]

                    .agg(["sum", "count"])

                    .sort_values("sum", ascending=False)

                    .head(10)

                )



                context["segment_summaries"][str(column)] = [

                    {

                        "segment": str(index),

                        "total": float(row["sum"]),

                        "records": int(row["count"]),

                    }

                    for index, row in grouped.iterrows()

                ]



            if len(context["segment_summaries"]) >= 8:

                break



    # Return result
    return context







# ---------------------------------------------------------------------------
# Safe local Python computation
# ---------------------------------------------------------------------------

_ARITHMETIC_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_ARITHMETIC_UNARYOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


# Evaluate a tiny arithmetic AST; never execute user-supplied Python
def _evaluate_numeric_ast(node, depth=0):
    """Evaluate a tiny arithmetic AST; never execute user-supplied Python."""
    # Check condition
    if depth > 20:
        raise ValueError("Expression is too deeply nested.")
    # Check condition
    if isinstance(node, ast.Expression):
        return _evaluate_numeric_ast(node.body, depth + 1)
    # Check condition
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        value = node.value
    elif isinstance(node, ast.BinOp) and type(node.op) in _ARITHMETIC_BINOPS:
        left = _evaluate_numeric_ast(node.left, depth + 1)
        right = _evaluate_numeric_ast(node.right, depth + 1)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("Exponent is too large.")
        value = _ARITHMETIC_BINOPS[type(node.op)](left, right)
    elif isinstance(node, ast.UnaryOp) and type(node.op) in _ARITHMETIC_UNARYOPS:
        value = _ARITHMETIC_UNARYOPS[type(node.op)](_evaluate_numeric_ast(node.operand, depth + 1))
    else:
        raise ValueError("Only basic numeric arithmetic is supported.")
    # Check condition
    if not math.isfinite(float(value)) or abs(value) > 1e100:
        raise ValueError("Result is outside the supported numeric range.")
    # Return result
    return value


# Route unambiguous arithmetic questions to safe local Python
def _try_python_arithmetic(question):
    """
    Route unambiguous arithmetic questions to safe local Python.
    Returns a standard response dict, or None when the question is not
    clearly a standalone arithmetic request.
    """
    q = str(question or "").strip().lower()
    q = re.sub(r"^\s*(?:what is|calculate|compute|solve|evaluate)\s+", "", q)
    q = q.rstrip(" ?=")
    replacements = [
        (r"\bmultiplied\s+by\b|\btimes\b|\bx\b", "*"),
        (r"\bdivided\s+by\b|\bover\b", "/"),
        (r"\bplus\b|\badded\s+to\b", "+"),
        (r"\bminus\b|\bsubtract(?:ed)?\b", "-"),
    ]
    # Loop over items
    for pattern, symbol in replacements:
        q = re.sub(pattern, symbol, q)
    # Set up values
    q = q.replace(",", "")
    # Require an explicit arithmetic operator and reject any remaining words.
    if not re.search(r"[+*/%]|(?<!^)-", q):
        return None
    # Check condition
    if not re.fullmatch(r"[0-9\s.()+*/%\-]+", q):
        return None
    # Try, handle errors
    try:
        tree = ast.parse(q, mode="eval")
        result = _evaluate_numeric_ast(tree)
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError):
        return None

    # Check condition
    if isinstance(result, float) and result.is_integer():
        display = str(int(result))
    else:
        display = f"{result:.12g}" if isinstance(result, float) else str(result)
    # Return result
    return {
        "answer": display,
        "interpretation": "Calculated locally using Python; no AI provider was called.",
        "recommendations": [],
        "follow_up_questions": [],
        "limitations": [],
        "suggested_analyses": [],
        "provider": "Python (local calculation)",
        "analysis_mode": "python_arithmetic",
    }


# Detect stock/share/market-price questions that need live market data
def _is_market_price_question(question):
    """Detect stock/share/market-price questions that need live market data."""
    q = str(question or "").lower()
    markers = (
        "stock price", "share price", "stock value", "share value",
        "market price", "share rate", "stock rate", "current price",
        "current stock", "current share", "trading price",
        "stock quote", "share quote", "stock quotation",
    )
    # Return result
    return any(marker in q for marker in markers)


# Extract the company/security phrase from a natural-language price question
def _extract_market_query(question):
    """Extract the company/security phrase from a natural-language price question."""
    q = re.sub(r"\s+", " ", str(question or "").strip())
    q = re.sub(
        r"\b(what is|what's|tell me|show me|give me|please|the|current|latest|today|"
        r"right now|now|price|stock price|share price|stock|shares|share|market price|"
        r"market|quote|quotation|trading price|value|rate|of|for)\b",
        " ",
        q,
        flags=re.I,
    )
    q = re.sub(r"[^A-Za-z0-9&.\- ]+", " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    # Return result
    return q


# Provider-independent live/latest market quote retrieval
def _get_live_market_data(question):
    """
    Provider-independent live/latest market quote retrieval.

    The result is added to the shared AI context before Gemini/Groq/OpenRouter/
    Ollama are called. If the market source is unavailable, return None so the
    existing provider routing continues unchanged.
    """
    # Check condition
    if not _is_market_price_question(question):
        return None

    # Set up values
    query = _extract_market_query(question)
    # Check condition
    if not query:
        return None

    # Set up values
    known_symbols = {
        "reliance": "RELIANCE.NS",
        "reliance industries": "RELIANCE.NS",
        "reliance industries limited": "RELIANCE.NS",
        "tcs": "TCS.NS",
        "tata consultancy services": "TCS.NS",
        "infosys": "INFY.NS",
        "infy": "INFY.NS",
        "hdfc bank": "HDFCBANK.NS",
        "hdfc": "HDFCBANK.NS",
        "icici bank": "ICICIBANK.NS",
        "sbi": "SBIN.NS",
        "state bank of india": "SBIN.NS",
        "itc": "ITC.NS",
        "bharti airtel": "BHARTIARTL.NS",
        "airtel": "BHARTIARTL.NS",
        "tata motors": "TATAMOTORS.NS",
        "tata steel": "TATASTEEL.NS",
        "adani enterprises": "ADANIENT.NS",
        "adani ports": "ADANIPORTS.NS",
        "wipro": "WIPRO.NS",
        "axis bank": "AXISBANK.NS",
        "kotak mahindra bank": "KOTAKBANK.NS",
        "larsen and toubro": "LT.NS",
        "l&t": "LT.NS",
        "hdfc life": "HDFCLIFE.NS",
        "maruti": "MARUTI.NS",
        "maruti suzuki": "MARUTI.NS",
        "sun pharma": "SUNPHARMA.NS",
        "asian paints": "ASIANPAINT.NS",
        "nestle india": "NESTLEIND.NS",
        "bajaj finance": "BAJFINANCE.NS",
        "bajaj finserv": "BAJAJFINSV.NS",
        "amazon": "AMZN",
        "apple": "AAPL",
        "microsoft": "MSFT",
        "google": "GOOGL",
        "alphabet": "GOOGL",
        "tesla": "TSLA",
        "nvidia": "NVDA",
        "meta": "META",
    }

    symbol = known_symbols.get(query.lower().strip())
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
    }

    # Helper: get json
    def _get_json(url, timeout=8):
        # Set up values
        request = urllib.request.Request(url, headers=headers, method="GET")
        # Open resource safely
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    # Try, handle errors
    try:
        if symbol is None:
            search_url = (
                "https://query1.finance.yahoo.com/v1/finance/search?"
                + urllib.parse.urlencode({
                    "q": query,
                    "quotesCount": 8,
                    "newsCount": 0,
                    "enableFuzzyQuery": "true",
                })
            )
            search_payload = _get_json(search_url)
            quotes = search_payload.get("quotes") or []
            candidates = [
                item for item in quotes
                if isinstance(item, dict)
                and item.get("symbol")
                and item.get("quoteType") in {"EQUITY", "ETF", "INDEX"}
            ]
            nse_candidates = [
                item for item in candidates
                if str(item.get("exchange") or "").upper() in {"NSI", "NSE"}
                or str(item.get("symbol") or "").upper().endswith(".NS")
            ]
            selected = nse_candidates or candidates
            if not selected:
                return None
            symbol = str(selected[0]["symbol"]).strip()

        chart_url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            + urllib.parse.quote(symbol, safe="")
            + "?"
            + urllib.parse.urlencode({
                "range": "1d",
                "interval": "1m",
                "includePrePost": "true",
                "events": "div,splits",
            })
        )
        payload = _get_json(chart_url)
        result = ((payload.get("chart") or {}).get("result") or [None])[0]
        if not isinstance(result, dict):
            return None

        meta = result.get("meta") or {}
        price = meta.get("regularMarketPrice")
        previous_close = meta.get("previousClose") or meta.get("chartPreviousClose")

        if price is None:
            indicators = result.get("indicators") or {}
            quote_rows = (indicators.get("quote") or [{}])[0]
            closes = quote_rows.get("close") or []
            valid_closes = [value for value in closes if value is not None]
            if valid_closes:
                price = valid_closes[-1]

        if price is None:
            return None

        price_float = float(price)
        previous_float = float(previous_close) if previous_close is not None else None
        change = price_float - previous_float if previous_float is not None else None
        change_pct = (
            change / previous_float * 100
            if previous_float not in (None, 0)
            else None
        )

        quote_time_text = ""
        quote_time = meta.get("regularMarketTime")
        if quote_time:
            try:
                quote_dt = datetime.fromtimestamp(
                    float(quote_time), tz=ZoneInfo("Asia/Kolkata")
                )
                quote_time_text = quote_dt.strftime("%d %B %Y, %I:%M:%S %p IST")
            except Exception:
                pass

        source_url = (
            "https://finance.yahoo.com/quote/"
            + urllib.parse.quote(symbol, safe="")
        )

        return {
            "symbol": symbol,
            "query": query,
            "price": price_float,
            "currency": str(meta.get("currency") or "").upper(),
            "exchange": str(
                meta.get("exchangeName") or meta.get("fullExchangeName") or ""
            ).strip(),
            "market_state": str(meta.get("marketState") or "").strip(),
            "previous_close": previous_float,
            "change": change,
            "change_percent": change_pct,
            "quote_time": quote_time_text,
            "source": "Yahoo Finance market data",
            "source_url": source_url,
            "retrieved_at": datetime.now(
                ZoneInfo("Asia/Kolkata")
            ).strftime("%d %B %Y, %I:%M:%S %p IST"),
        }

    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        json.JSONDecodeError,
    ) as exc:
        print(
            f"[LIVE MARKET DATA] unavailable for {query!r}: {str(exc)[:250]}",
            flush=True,
        )
        return None


# Identify questions where an answer based only on model memory is unsafe
def _requires_live_search(question):
    """Identify questions where an answer based only on model memory is unsafe."""
    q = str(question or "").lower()
    time_markers = (
        "current ", "currently ", "latest ", "today", "right now",
        "as of now", "this week", "this month", "this year",
        "yesterday", "recent ", "recently", "breaking ",
        "stock price", "share price", "market price", "exchange rate",
        "weather", "news ", "news about", "who is ", "pm of ",
        "prime minister", "president of", "chief minister",
        "ceo of", "governor of", "chairperson of",
    )
    # Return result
    return any(marker in q for marker in time_markers)



# Make Gemini requests with a single reliable urllib timeout
def _gemini_urlopen_with_retry(
    request, connection_timeout=90, response_timeout=90, max_attempts=2
):
    """Make Gemini requests with a single reliable urllib timeout.

    urllib uses one timeout for both connection establishment and response
    reads, so use the longer response timeout rather than changing the socket
    after urlopen() has already returned.
    """
    last_error = None

    # Loop over items
    for attempt in range(max_attempts):
        try:
            return urllib.request.urlopen(request, timeout=response_timeout)

        except urllib.error.HTTPError as error:
            last_error = error
            if error.code not in (500, 502, 503, 504) or attempt == max_attempts - 1:
                raise
            time.sleep(1)

    raise last_error


# Tell the selected AI the application's authoritative current IST date/time
def _append_runtime_datetime_instruction(system_prompt, context):
    """Tell the selected AI the application's authoritative current IST date/time."""
    current_datetime = str(context.get("current_datetime") or "").strip()
    # Check condition
    if not current_datetime:
        return system_prompt
    # Return result
    return (
        system_prompt
        + "\n\nAPPLICATION CURRENT DATE/TIME (authoritative runtime context):\n"
        + current_datetime
        + "\nFor questions asking today's date, current day, current time, or current year, "
        "use this application-provided value. Do not claim you lack access to a clock when "
        "this value is supplied. Do not invent a different date or time.\n"
    )


# Call Gemini 1 with model fallback; explicit secondary-key calls stay strict
def call_gemini(question, context, api_key_override=None, model_override=None):
    """Call Gemini 1 with model fallback; explicit secondary-key calls stay strict."""
    # Check condition
    if model_override is not None or api_key_override is not None:
        return _call_gemini_single_model(
            question, context,
            api_key_override=api_key_override,
            model_override=model_override,
        )

    # Set up values
    models = []
    # Loop over items
    for model in (
        GEMINI_MODEL,
    ):
        if model and model not in models:
            models.append(model)

    # Set up values
    errors = []
    # Loop over items
    for model in models:
        try:
            response = _call_gemini_single_model(
                question, context, model_override=model
            )
            response["model_used"] = model
            return response
        except Exception as exc:
            detail = str(exc).replace("\n", " ")[:250]
            print(f"[GEMINI MODEL FALLBACK] {model}: {detail}", flush=True)
            errors.append(f"{model}: {detail}")

    raise RuntimeError(
        "All configured Gemini 1 models failed. " + " | ".join(errors)
    )


# Helper: call gemini single model
def _call_gemini_single_model(question, context, api_key_override=None, model_override=None):

    """Ask Gemini to interpret the calculated evidence. An optional key enables a secondary project key."""

    # If a secondary key was explicitly requested, never fall back to the
    # primary key. This prevents Gemini 2 from retrying Gemini 1's key.
    if api_key_override is not None:
        api_key = str(api_key_override).strip()
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY_2 is not configured.")
    else:
        api_key = os.environ.get("GEMINI_API_KEY")
        if api_key:
            api_key = str(api_key).strip()

    # Check condition
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured.")



    # Check condition
    if context.get("mode") == "general_knowledge":

        system_prompt = """

You are a helpful general-knowledge assistant.

Answer the user's actual question directly using your general knowledge.

Do NOT analyze, refer to, or require an uploaded dataset.

Do NOT claim that an answer needs a sales or revenue column.

For any current, recent, or time-sensitive question, you MUST use the
Google Search tool before answering. Do not answer these questions from model
memory alone. This includes current officeholders, government roles, company
leaders, prices, market data, news, weather, schedules, and recent events.

Prefer official government, company, regulator, exchange, or primary sources.
Check the date of the source and distinguish the date of publication from the
date the fact applies. If reliable search evidence is unavailable or conflicting,
say that you could not verify the current answer. Never fall back to an old
training-memory answer or invent a current fact.

Return the answer and let the application attach the verified source links.
Do not invent source URLs.

Return valid JSON only with keys:

{

"answer": "Direct answer to the question",

"interpretation": "Brief explanation or context",

"recommendations": [],

"follow_up_questions": [],

"limitations": ["Mention uncertainty only when relevant"],

"suggested_analyses": []

}

"""

    else:

        system_prompt = """

You are an expert business analyst, data analyst, and statistician.



Answer the user's actual question first, in clear natural language.

Use the supplied dataset profile, Python-calculated facts, and tool_execution results.

Treat successful tool outputs as evidence; never claim a failed or unrun tool succeeded.

Never invent numbers, column names, calculations, findings, or causes.

Identify the periods and values being compared.

Distinguish verified facts from hypotheses about causes.

Do not claim correlation proves causation.

If data is insufficient, explain why and ask a useful question.

Recommend concrete next investigations using available columns.

Do not claim to have run an analysis that was not actually run.



Return valid JSON only with these keys:

{

"answer": "Direct answer to the question",

"interpretation": "What the result means",

"recommendations": ["Practical business recommendation"],

"follow_up_questions": ["Useful follow-up question"],

"limitations": ["Important limitation"],

"suggested_analyses": ["Useful next analysis"]

}

"""



    # Set up values
    system_prompt = _append_runtime_datetime_instruction(system_prompt, context)

    body = {

        "systemInstruction": {

            "parts": [{"text": system_prompt}]

        },

        "contents": [{

            "role": "user",

            "parts": [{

                "text": json.dumps({

                    "question": question,

                    "dataset_context": context,

                }, ensure_ascii=False),

            }],

        }],

        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
            "maxOutputTokens": 1024,
        },

    }



    # Google Search grounding has its own quota. Use it only for questions that
    # genuinely require current or time-sensitive information.
    use_google_search = (
        context.get("mode") == "general_knowledge"
        and _requires_live_search(question)
    )
    # Keep the normal Gemini grounded request unchanged. If a free-tier
    # project has generateContent quota but Google Search grounding is
    # temporarily quota-limited, the narrow 429 retry below will reuse the
    # same Gemini model without the grounding tool.
    grounding_quota_fallback = False
    # Check condition
    if use_google_search:
        body["tools"] = [{"google_search": {}}]



    # Set up values
    url = (

        "https://generativelanguage.googleapis.com/v1beta/models/"

        f"{model_override or GEMINI_MODEL}:generateContent?key="

        + urllib.parse.quote(api_key, safe="")

    )

    request = urllib.request.Request(

        url,

        data=json.dumps(body).encode("utf-8"),

        headers={"Content-Type": "application/json"},

        method="POST",

    )



    # Try, handle errors
    try:
        with _gemini_urlopen_with_retry(
            request, connection_timeout=90, response_timeout=90
        ) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        # Preserve Google's structured quota details in logs, without exposing keys.
        raw_error = error.read().decode("utf-8", errors="replace")
        try:
            error_payload = json.loads(raw_error)
            google_error = error_payload.get("error", {})
            details = google_error.get("details", [])
            message = google_error.get("message", str(error))
            detail_text = json.dumps(details, ensure_ascii=False) if details else raw_error[:2000]
        except Exception:
            message, detail_text = str(error), raw_error[:2000]

        # A 429 on a live-search request can be specific to Search grounding.
        # Retry the same Gemini model without the grounding tool. The response
        # is marked unverified below; it is never presented as live-search
        # verified.
        if error.code == 429 and use_google_search:
            print(
                "[GEMINI] Google Search grounding returned HTTP 429; "
                "retrying the same Gemini model without grounding.",
                flush=True,
            )
            fallback_body = dict(body)
            fallback_body.pop("tools", None)
            fallback_request = urllib.request.Request(
                url,
                data=json.dumps(fallback_body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with _gemini_urlopen_with_retry(
                    fallback_request, connection_timeout=90, response_timeout=90
                ) as response:
                    result = json.loads(response.read().decode("utf-8"))
                    grounding_quota_fallback = True
            except urllib.error.HTTPError as fallback_error:
                fallback_raw = fallback_error.read().decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"HTTP {fallback_error.code}: {fallback_raw[:2000]}. "
                    f"Original Google Search quota error: {message}. "
                    f"Google quota details: {detail_text}"
                ) from fallback_error
        else:
            raise RuntimeError(
                f"HTTP {error.code}: {message}. Google quota details: {detail_text}"
            ) from error



    # Set up values
    candidates = result.get("candidates", [])

    # Check condition
    if not candidates:
        raise RuntimeError(
            "Gemini returned no candidates. "
            f"Feedback: {result.get('promptFeedback', {})}"
        )

    # Set up values
    candidate = candidates[0]
    candidate_content = candidate.get("content") or {}
    parts = candidate_content.get("parts") or []

    content = "".join(
        part.get("text", "")
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    )

    # Check condition
    if not content.strip():
        raise RuntimeError(
            "Gemini returned no text. "
            f"Finish reason: {candidate.get('finishReason', 'unknown')}"
        )

    # Try, handle errors
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Gemini returned invalid JSON: {exc}"
        ) from exc

    # Check condition
    if not isinstance(parsed, dict):
        raise RuntimeError("Gemini returned an invalid JSON object.")

    # Gemini's REST generateContent response places Search grounding data
    # beside candidate.content. Preserve the actual source URLs for the UI.
    grounding = candidate.get("groundingMetadata") or candidate.get("grounding_metadata") or {}
    chunks = grounding.get("groundingChunks") or grounding.get("grounding_chunks") or []
    sources = []
    seen_urls = set()
    # Loop over items
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        web_source = chunk.get("web") or {}
        uri = web_source.get("uri") or web_source.get("url")
        title = web_source.get("title") or uri
        if isinstance(uri, str) and uri.startswith(("https://", "http://")) and uri not in seen_urls:
            seen_urls.add(uri)
            sources.append({"title": str(title or uri), "url": uri})

    # Check condition
    if sources:
        parsed["sources"] = sources
        answer_text = str(parsed.get("answer") or "").strip()
        if answer_text and "Sources:" not in answer_text:
            source_lines = ["", "Sources:"]
            source_lines.extend(
                f"- [{source['title']}]({source['url']})"
                for source in sources[:6]
            )
            parsed["answer"] = answer_text + "\\n" + "\\n".join(source_lines)

    # Check condition
    if (
        context.get("mode") == "general_knowledge"
        and _requires_live_search(question)
        and not sources
    ):
        if grounding_quota_fallback:
            parsed.setdefault("limitations", [])
            limitations = parsed.get("limitations")
            if not isinstance(limitations, list):
                limitations = [limitations] if limitations else []
            limitations.append(
                "Gemini answered without Google Search because the Search "
                "grounding request returned HTTP 429. This response is not "
                "live-search verified."
            )
            parsed["limitations"] = limitations
            parsed["verification_status"] = "unverified_grounding_quota_fallback"
        else:
            raise RuntimeError(
                "Gemini did not return Google Search grounding sources for this "
                "current-information question. The answer was not accepted because "
                "it could not be verified against live sources."
            )

    # Return result
    return parsed






# Normalize JSON or plain-text model output into the analyst response shape
def _normalize_provider_response(content, provider_name="AI provider"):
    """Normalize JSON or plain-text model output into the analyst response shape.

    Some OpenAI-compatible models occasionally return JSON with markdown fences,
    partial JSON, or plain text despite a JSON instruction. Recover the answer
    field when possible; never silently invent missing facts.
    """
    # Check condition
    if isinstance(content, list):
        content = "".join(
            str(part.get("text", ""))
            for part in content if isinstance(part, dict)
        )
    # Set up values
    raw = str(content or "").strip()
    # Check condition
    if not raw:
        raise RuntimeError(f"{provider_name} returned an empty response.")

    # Set up values
    cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", raw, flags=re.I)
    parsed = None
    # Try, handle errors
    try:
        candidate = json.loads(cleaned)
        if isinstance(candidate, dict):
            parsed = candidate
    except (json.JSONDecodeError, TypeError):
        # Try a complete JSON object embedded in surrounding prose.
        start = cleaned.find("{")
        if start >= 0:
            try:
                candidate, _ = json.JSONDecoder().raw_decode(cleaned[start:])
                if isinstance(candidate, dict):
                    parsed = candidate
            except (json.JSONDecodeError, TypeError):
                parsed = None

    # Check condition
    if parsed is None:
        # Salvage a complete answer string from otherwise truncated JSON.
        match = re.search(
            r'"answer"\s*:\s*("(?:\\.|[^"\\])*")',
            cleaned,
            flags=re.S,
        )
        if match:
            try:
                answer = json.loads(match.group(1))
            except json.JSONDecodeError:
                answer = ""
            parsed = {"answer": answer}
        else:
            # Plain text is still a usable answer; malformed JSON is not.
            # Let the provider chain try the next model instead of displaying
            # a broken JSON payload as if it were a natural-language answer.
            if cleaned.lstrip().startswith("{") or '"answer"' in cleaned:
                raise RuntimeError(
                    f"{provider_name} returned malformed JSON and no recoverable answer."
                )
            parsed = {"answer": cleaned}

    # Set up values
    answer = str(parsed.get("answer") or parsed.get("interpretation") or "").strip()
    # Check condition
    if not answer:
        raise RuntimeError(f"{provider_name} returned no usable answer.")

    # Set up values
    parsed["answer"] = answer
    parsed.setdefault("interpretation", "")
    # Loop over items
    for key in ("recommendations", "follow_up_questions", "limitations", "suggested_analyses"):
        value = parsed.get(key, [])
        if not isinstance(value, list):
            value = [value] if value else []
        parsed[key] = [str(item) for item in value if str(item).strip()]
    # Return result
    return parsed


# Ask Groq using a plain OpenAI-compatible chat completion
def call_groq(question, context, api_key_override=None, model_override=None):
    """Ask Groq using a plain OpenAI-compatible chat completion.

    Groq is a fallback provider, so this path deliberately avoids forcing
    JSON mode or tool calls.  GPT-OSS can support tools, but a normal fallback
    answer must not depend on a tool being registered or executed.
    """
    api_key = str(api_key_override or os.environ.get("GROQ_API_KEY") or "").strip()
    # Check condition
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not configured.")

    # Set up values
    model = str(
        model_override or os.environ.get("GROQ_MODEL", GROQ_MODEL) or ""
    ).strip()
    # Check condition
    if not model:
        raise RuntimeError("GROQ_MODEL is not configured.")

    # Check condition
    if context.get("mode") == "general_knowledge":
        system_prompt = """
You are a helpful general-knowledge assistant.
Answer the user's actual question directly using your general knowledge.
Do not analyze, refer to, or require an uploaded dataset.
Do not invent exact current figures.
If dataset_context.live_market_data_verified is true, use the supplied live_market_data
as the authoritative current market evidence and answer the market-price question directly.
Do not say you lack real-time market data when live_market_data is supplied.
If the information may have changed recently, clearly say that it may need live verification.
Do not claim that you searched the web or cite sources you did not receive.
If dataset_context.current_information_unverified is true, treat current facts as unverified.
Return a concise natural-language answer. Do not return JSON and do not call tools.
"""
    else:
        system_prompt = """
You are an expert business analyst, data analyst, and statistician.
Answer the user's actual question first, in clear natural language.
Use the supplied dataset profile, Python-calculated facts, and tool_execution results.
Treat successful tool outputs as evidence; never claim a failed or unrun tool succeeded.
Never invent numbers, column names, calculations, findings, or causes.
Distinguish verified facts from hypotheses about causes.
Do not claim correlation proves causation.
If data is insufficient, explain why and ask a useful question.
Recommend concrete next investigations using available columns.
Do not claim to have run an analysis that was not actually run.
Return a concise natural-language answer. Do not return JSON and do not call tools.
"""

    # Check condition
    if context.get("current_information_unverified"):
        system_prompt += (
            "\nCurrent-information verification was unavailable upstream. "
            "Do not present time-sensitive facts as live-verified."
        )

    # Set up values
    system_prompt = _append_runtime_datetime_instruction(system_prompt, context)

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt.strip()},
            {
                "role": "user",
                "content": json.dumps(
                    {"question": question, "dataset_context": context},
                    ensure_ascii=False,
                ),
            },
        ],
        "temperature": 0.2,
        "max_tokens": 4096,
    }

    request = urllib.request.Request(
        GROQ_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "AI-Analyst/1.0",
        },
        method="POST",
    )

    # Try, handle errors
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        try:
            error_payload = json.loads(error_body)
            api_error = error_payload.get("error", {})
            detail = api_error.get("message") or error_body[:1000]
        except Exception:
            detail = error_body[:1000]
        raise RuntimeError(f"HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Groq connection error: {error.reason}") from error

    # Set up values
    choices = result.get("choices") or []
    # Check condition
    if not choices:
        raise RuntimeError("Groq returned no choices.")

    # Set up values
    message = choices[0].get("message") or {}
    content = message.get("content")

    # Some OpenAI-compatible responses can put the text in a list of content
    # parts. Convert those parts into one normal string before parsing.
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                text_part = part.get("text") or part.get("content")
                if text_part:
                    parts.append(str(text_part))
            elif part:
                parts.append(str(part))
        content = "\n".join(parts).strip()

    # Check condition
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Groq returned an empty response.")

    # Return result
    return _normalize_provider_response(content, "Groq")

# Ask OpenRouter through its OpenAI-compatible chat completions API
def call_openrouter(question, context, api_key_override=None, model_override=None):
    """Ask OpenRouter through its OpenAI-compatible chat completions API."""
    api_key = str(
        api_key_override or os.environ.get("OPENROUTER_API_KEY") or ""
    ).strip()
    # Check condition
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured.")

    # Set up values
    model = str(
        model_override
        or os.environ.get("OPENROUTER_MODEL", OPENROUTER_MODEL)
        or ""
    ).strip()
    # Check condition
    if not model:
        raise RuntimeError("OPENROUTER_MODEL is not configured.")

    # Check condition
    if context.get("mode") == "general_knowledge":
        system_prompt = """
You are a helpful general-knowledge assistant.
Answer the user's actual question directly using your general knowledge.
Do not analyze, refer to, or require an uploaded dataset.
Do not invent exact current figures or claim that you searched the web.
If dataset_context.live_market_data_verified is true, use the supplied live_market_data
as the authoritative current market evidence and answer the market-price question directly.
Do not say you lack real-time market data when live_market_data is supplied.
If current information is not live-verified, clearly state that it may be outdated.
Return a concise natural-language answer. Do not return JSON.
"""
    else:
        system_prompt = """
You are an expert business analyst, data analyst, and statistician.
Answer the user's actual question first, in clear natural language.
Use the supplied dataset profile, Python-calculated facts, and tool_execution results.
Treat successful tool outputs as evidence; never claim a failed or unrun tool succeeded.
Never invent numbers, column names, calculations, findings, or causes.
Distinguish verified facts from hypotheses about causes.
Do not claim correlation proves causation.
If data is insufficient, explain why and ask a useful question.
Recommend concrete next investigations using available columns.
Do not claim to have run an analysis that was not actually run.
Return a concise natural-language answer. Do not return JSON.
"""

    # Check condition
    if context.get("current_information_unverified"):
        system_prompt += (
            "\nCurrent-information verification was unavailable upstream. "
            "Do not present time-sensitive facts as live-verified."
        )

    # Set up values
    system_prompt = _append_runtime_datetime_instruction(system_prompt, context)

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt.strip()},
            {
                "role": "user",
                "content": json.dumps(
                    {"question": question, "dataset_context": context},
                    ensure_ascii=False,
                ),
            },
        ],
        "temperature": 0.2,
        "max_tokens": 4096,
    }

    request = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:5173",
            "X-Title": "AI Analyst",
        },
        method="POST",
    )

    # Try, handle errors
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        try:
            error_payload = json.loads(error_body)
            api_error = error_payload.get("error", {})
            detail = api_error.get("message") or error_body[:1000]
        except Exception:
            detail = error_body[:1000]
        raise RuntimeError(f"HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"OpenRouter connection error: {error.reason}") from error

    # Set up values
    choices = result.get("choices") or []
    # Check condition
    if not choices:
        raise RuntimeError("OpenRouter returned no choices.")

    # Set up values
    choice = choices[0] or {}
    message = choice.get("message") or {}
    content = message.get("content")

    # Check condition
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                text_part = part.get("text") or part.get("content")
                if text_part:
                    parts.append(str(text_part))
            elif part:
                parts.append(str(part))
        content = "\n".join(parts).strip()

    # A few OpenRouter routes expose the generated text in an alternate field.
    # Accept those fields before treating the response as empty.
    if not content:
        content = message.get("reasoning_content") or message.get("refusal")

    # Check condition
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("OpenRouter returned no usable answer.")

    # Set up values
    parsed = _normalize_provider_response(content, "OpenRouter")
    # Check condition
    if choice.get("finish_reason") == "length":
        parsed.setdefault("limitations", []).append(
            "The model response reached its output-token limit; the answer may be incomplete."
        )
    # Return result
    return parsed

# Use the local Qwen model if Gemini is unavailable
def call_ollama(question, context):

    """Use the local Qwen model if Gemini is unavailable."""

    # Check condition
    if context.get("mode") == "general_knowledge":

        system_prompt = """

You are a helpful general-knowledge assistant.

Answer the user's actual question directly using your general knowledge.

Do NOT analyze, refer to, or require an uploaded dataset.

Do NOT claim that an answer needs a sales or revenue column.

For current or time-sensitive facts, state uncertainty when you cannot verify them.
If dataset_context.live_market_data_verified is true, use the supplied live_market_data
as the authoritative current market evidence. Do not say you lack real-time market data.

Do not invent exact current figures. If dataset_context.current_information_unverified is true,
clearly state that the answer is not live-verified and may be outdated. Never claim web search
or cite sources that were not supplied.

Return valid JSON only with keys:

answer, interpretation, recommendations, follow_up_questions,

limitations, suggested_analyses.

The last four keys must be arrays of strings.

"""

    else:

        system_prompt = """

You are an expert business analyst and data scientist.

Answer the user's actual question first.

Use only the supplied dataset context, calculated facts, and tool_execution results.

Treat successful tool outputs as evidence; never claim a failed or unrun tool succeeded.

Never invent numerical results or claim an unperformed analysis.

Separate facts from possible explanations.

Mention limitations and recommend practical next steps.



Return valid JSON only with keys:

answer, interpretation, recommendations, follow_up_questions,

limitations, suggested_analyses.

The last four keys must be arrays of strings.

"""



    # Set up values
    system_prompt = _append_runtime_datetime_instruction(system_prompt, context)

    body = {

        "model": OLLAMA_MODEL,

        "messages": [

            {"role": "system", "content": system_prompt},

            {

                "role": "user",

                "content": json.dumps({

                    "question": question,

                    "dataset_context": context,

                }, ensure_ascii=False),

            },

        ],

        "stream": False,

        "format": "json",

        "options": {"temperature": 0.1},

    }



    request = urllib.request.Request(

        OLLAMA_URL,

        data=json.dumps(body).encode("utf-8"),

        headers={"Content-Type": "application/json"},

        method="POST",

    )



    # Open resource safely
    with urllib.request.urlopen(request, timeout=180) as response:

        result = json.loads(response.read().decode("utf-8"))



    # Set up values
    message = result.get("message") or {}
    content = message.get("content")

    # Check condition
    if not isinstance(content, str) or not content.strip():
        # Qwen2.5:3b can occasionally return an empty JSON-constrained message.
        # Retry once with a short plain-text prompt; do not fail the whole chain.
        retry_body = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": "Answer the user's question directly and concisely. Do not return JSON."},
                {"role": "user", "content": str(question)},
            ],
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 384},
        }
        retry_request = urllib.request.Request(
            OLLAMA_URL,
            data=json.dumps(retry_body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(retry_request, timeout=90) as retry_response:
            retry_result = json.loads(retry_response.read().decode("utf-8"))
        retry_message = retry_result.get("message") or {}
        retry_content = retry_message.get("content")
        if isinstance(retry_content, str) and retry_content.strip():
            return {
                "answer": retry_content.strip(),
                "interpretation": "",
                "recommendations": [],
                "follow_up_questions": [],
                "limitations": [],
                "suggested_analyses": [],
            }
        raise RuntimeError(
            "Ollama returned an empty response after one plain-text retry "
            f"(done_reason={retry_result.get('done_reason')!r})."
        )

    # Try, handle errors
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Ollama returned invalid JSON: {exc}"
        ) from exc

    # Check condition
    if not isinstance(parsed, dict):
        raise RuntimeError("Ollama returned an invalid JSON object.")

    # Some local models incorrectly return the answer as an array.
    # Normalize it to the string expected by the rest of AI Analyst.
    answer = parsed.get("answer")
    # Check condition
    if isinstance(answer, list):
        parsed["answer"] = "\n".join(
            str(item) for item in answer if item is not None
        )
    elif answer is not None and not isinstance(answer, str):
        parsed["answer"] = str(answer)

    # Return result
    return parsed







# Choose a relevant column without relying on LLM guesses
def _column_by_exact_or_keyword(df, exact_names, keywords):

    """Choose a relevant column without relying on LLM guesses."""

    normalized = {

        str(column).strip().lower().replace("_", " ").replace("-", " "): column

        for column in df.columns

    }

    # Loop over items
    for name in exact_names:

        if name in normalized:

            return normalized[name]

    # Loop over items
    for column in df.columns:

        name = str(column).strip().lower().replace("_", " ").replace("-", " ")

        if any(keyword in name for keyword in keywords):

            return column

    # Return result
    return None





# Return per-row sales and a transparent description of its calculation
def _sales_metric(df):

    """Return per-row sales and a transparent description of its calculation."""

    sales_col = _column_by_exact_or_keyword(

        df,

        ["sales", "revenue", "total sales", "total revenue", "line total",

        "total amount", "order value"],

        ["sales", "revenue", "turnover", "line total", "total amount", "order value"],

    )

    quantity_col = _column_by_exact_or_keyword(

        df, ["quantity", "qty"], ["quantity", "qty", "units sold"]

    )

    price_col = _column_by_exact_or_keyword(

        df, ["unit price", "unitprice", "selling price", "item price", "price"],

        ["unit price", "unitprice", "selling price", "item price", "price"],

    )



    # Check condition
    if sales_col is not None:

        metric = pd.to_numeric(df[sales_col], errors="coerce")

        return metric, f"sum of {sales_col}"

    # Check condition
    if quantity_col is not None and price_col is not None:

        quantity = pd.to_numeric(df[quantity_col], errors="coerce")

        price = pd.to_numeric(df[price_col], errors="coerce")

        return quantity * price, f"{quantity_col} Ã— {price_col}"

    # Return result
    return None, None





# Helper: format number
def _format_number(value):

    # Return result
    return f"{float(value):,.2f}"





# Answer row-level max/min/ranking questions directly from the live DataFrame
def _deterministic_row_lookup_answer(question, df):
    """Answer row-level max/min/ranking questions directly from the live DataFrame."""
    # Check condition
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None

    # The frontend can temporarily replace underscores/backticks with `*` while
    # preparing inline-code text. Normalize those markers here so dataset column
    # names such as `Monthly_Sales` and `Employee_ID` still match the live DataFrame.
    q = str(question or "").lower()
    q = re.sub(r"[*`]+", " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    ranking_terms = ("highest", "lowest", "maximum", "minimum", "max", "min", "top", "bottom")
    # Check condition
    if not any(re.search(r"\b" + re.escape(term) + r"\b", q) for term in ranking_terms):
        return None

    # Prefer an exact/normalized column name mentioned by the user.
    normalized_q = re.sub(r"[_\-]+", " ", q)
    target_col = None
    # Loop over items
    for column in df.columns:
        normalized_column = re.sub(r"[_\-]+", " ", str(column).strip().lower())
        if normalized_column and re.search(
            r"(?<![a-z0-9])" + re.escape(normalized_column) + r"(?![a-z0-9])",
            normalized_q,
        ):
            target_col = column
            break

    # Common business-language aliases when the physical column name is not used.
    aliases = (
        (("monthly sales", "monthly sale", "sales", "sale"), ("monthly sales", "sales", "revenue", "turnover")),
        (("salary", "pay", "compensation"), ("salary", "pay", "compensation")),
        (("experience", "experience years", "years of experience"), ("experience years", "experience", "years experience")),
        (("performance", "performance score", "score"), ("performance score", "performance", "score")),
        (("age",), ("age",)),
        (("quantity", "qty", "units sold"), ("quantity", "qty", "units sold")),
        (("price", "unit price", "selling price"), ("price", "unit price", "selling price")),
    )
    # Check condition
    if target_col is None:
        for phrases, column_names in aliases:
            if any(re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", q) for phrase in phrases):
                target_col = _column_by_exact_or_keyword(df, column_names, column_names)
                if target_col is not None:
                    break

    # Check condition
    if target_col is None:
        return None

    # Set up values
    numeric_values = pd.to_numeric(df[target_col], errors="coerce")
    valid = numeric_values.dropna()
    # Check condition
    if valid.empty:
        return None

    # Set up values
    is_low = any(re.search(r"\b" + re.escape(term) + r"\b", q) for term in ("lowest", "minimum", "min", "bottom"))
    top_match = re.search(r"\btop\s+(\d+)\b", q)
    n = min(max(int(top_match.group(1)), 1), 20) if top_match else 1

    ranked = numeric_values.sort_values(ascending=is_low, kind="stable")
    ranked = ranked.dropna().head(n)
    # Check condition
    if ranked.empty:
        return None

    # For a single highest/lowest record, expose the useful row-level fields
    # instead of only returning the aggregate maximum/minimum.
    entity_words = ("employee", "person", "record", "row", "customer", "product", "batsman", "player", "invoice")
    asks_entity = any(word in q for word in entity_words)
    # Check condition
    if n == 1 and asks_entity:
        row_index = ranked.index[0]
        row = df.loc[row_index]
        preferred = [
            "employee_id", "customer_id", "invoice", "stock_code", "batter", "player",
            "city", "state", "department", "country", "salary", "monthly_sales", target_col,
        ]
        selected = []
        for name in preferred:
            for column in df.columns:
                if str(column).strip().lower() == name and column not in selected:
                    selected.append(column)
        for column in df.columns:
            if column not in selected and len(selected) < 12:
                selected.append(column)
        lines = []
        for column in selected:
            value = row[column]
            if pd.isna(value):
                display = "Missing"
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                display = f"{float(value):,.2f}" if isinstance(value, float) and not float(value).is_integer() else f"{int(value):,}"
            else:
                display = str(value)
            lines.append(f"- **{column}:** {display}")
        direction = "lowest" if is_low else "highest"
        response = {
            "answer": f"The {direction} {target_col} record is:\n" + "\n".join(lines),
            "interpretation": f"Selected the {direction} non-missing {target_col} value directly from the uploaded DataFrame and returned fields from the same row.",
            "recommendations": [],
            "follow_up_questions": [],
            "limitations": [],
            "suggested_analyses": [],
            "provider": "Python (verified row-level calculation)",
            "analysis_mode": "row_level_lookup",
        }
        return response

    # Set up values
    lines = []
    # Loop over items
    for rank, (idx, value) in enumerate(ranked.items(), 1):
        lines.append(f"{rank}. {value:,.2f}" if float(value) % 1 else f"{rank}. {int(value):,}")
    # Set up values
    direction = "lowest" if is_low else "highest"
    # Return result
    return {
        "answer": f"{direction.title()} {target_col} value(s):\n" + "\n".join(lines),
        "interpretation": f"Calculated directly from the uploaded DataFrame using the non-missing numeric values in {target_col}.",
        "recommendations": [],
        "follow_up_questions": [],
        "limitations": [],
        "suggested_analyses": [],
        "provider": "Python (verified calculation)",
        "analysis_mode": "row_level_lookup",
    }


# Handle common numeric questions directly with pandas, not an LLM
def _deterministic_answer(question, df):

    """Handle common numeric questions directly with pandas, not an LLM."""

    q = question.lower()

    response = {

        "answer": "",

        "interpretation": "",

        "recommendations": [],

        "follow_up_questions": [],

        "limitations": [],

        "suggested_analyses": [],

        "provider": "Python (verified calculation)",

    }



    # Check condition
    if not isinstance(df, pd.DataFrame) or df.empty:

        return None



    # Per-column missing-value questions must be handled before the broader

    # dataset-quality matcher (the word "column" can otherwise match that branch).

    asks_missing_by_column = (

        "missing" in q

        and any(term in q for term in (

            "per column", "each column", "every column", "by column",

            "column-wise", "column wise", "breakdown", "percentage", "percent",

        ))

    )

    # Check condition
    if asks_missing_by_column:

        missing_count = df.isna().sum()

        missing_percent = (missing_count / len(df) * 100).round(2)

        summary = pd.DataFrame({

            "Column": [str(column) for column in df.columns],

            "Missing Count": [int(missing_count[column]) for column in df.columns],

            "Missing %": [float(missing_percent[column]) for column in df.columns],

        }).sort_values("Missing Count", ascending=False, kind="stable")

        total_missing = int(missing_count.sum())

        total_cells = int(df.shape[0] * df.shape[1])

        total_percent = (total_missing / total_cells * 100) if total_cells else 0.0

        response["answer"] = (

            "Missing values by column (percentage is of rows in each column):\n"

            + summary.to_string(index=False)

            + f"\n\nTotal missing cells: {total_missing:,} ({total_percent:.2f}% of all cells)"

        )

        response["interpretation"] = (

            "Counts are calculated directly from the loaded DataFrame using pandas isna(). "

            "Every column is included, including columns with zero missing values. "

            "Per-column percentages use the total number of dataset rows as the denominator."

        )

        return response



    # Combined dataset-quality questions must return every requested metric in one answer.

    asks_rows = any(term in q for term in ("how many rows", "number of rows", "row count", "how many records"))

    asks_columns = any(term in q for term in ("how many columns", "number of columns", "column count", "columns"))

    asks_missing = "missing" in q and any(term in q for term in ("how many", "count", "values", "cells"))

    asks_duplicates = "duplicate" in q and any(term in q for term in ("how many", "count", "rows"))



    requested_quality_metrics = sum((asks_rows, asks_columns, asks_missing, asks_duplicates))

    # Check condition
    if requested_quality_metrics >= 2:

        answer_lines = []

        if asks_rows:

            answer_lines.append(f"Rows: {len(df):,}")

        if asks_columns:

            answer_lines.append(f"Columns: {len(df.columns):,}")

        if asks_missing:

            missing = int(df.isna().sum().sum())

            answer_lines.append(f"Missing cells: {missing:,}")

        if asks_duplicates:

            duplicates = int(df.duplicated().sum())

            answer_lines.append(f"Duplicate rows: {duplicates:,}")

        response["answer"] = "Dataset quality summary\n" + "\n".join(answer_lines)

        response["interpretation"] = (

            "Calculated directly from the loaded pandas DataFrame. Missing cells count null/NaN values; "

            "duplicate rows are rows whose values match an earlier row across all columns."

        )

        return response



    # Simple dataset-quality questions.

    if any(term in q for term in ("how many rows", "number of rows", "row count", "how many records")):

        response["answer"] = f"The dataset contains {len(df):,} rows."

        response["interpretation"] = "This is the number of rows currently loaded in the dataset."

        return response

    # Check condition
    if any(term in q for term in ("how many columns", "number of columns", "column count", "count columns")):

        response["answer"] = f"The dataset contains {len(df.columns):,} columns."

        response["interpretation"] = "This is the number of columns in the currently loaded dataset."

        return response

    # Check condition
    if "missing" in q and any(term in q for term in ("how many", "count", "values", "cells")):

        missing = int(df.isna().sum().sum())

        response["answer"] = f"The dataset contains {missing:,} missing cells."

        response["interpretation"] = f"Missing cells across all columns: {missing:,}."

        return response

    # Check condition
    if "duplicate" in q and any(term in q for term in ("how many", "count", "rows")):

        duplicates = int(df.duplicated().sum())

        response["answer"] = f"The dataset contains {duplicates:,} duplicate rows."

        response["interpretation"] = "Rows are counted as duplicates when all column values match a previous row."

        return response



    # Distinct-count and distinct-value questions must be answered from pandas,
    # not delegated to an LLM with only a small dataset profile/sample.
    asks_distinct_count = (
        any(term in q for term in (
            "how many unique", "number of unique", "unique count",
            "count unique", "count of unique", "how many distinct",
            "number of distinct", "distinct count", "count distinct",
        ))
        or (
            any(term in q for term in ("unique", "distinct"))
            and any(term in q for term in ("how many", "number of", "count"))
        )
    )
    asks_distinct_list = (
        any(term in q for term in (
            "name all", "list all", "show all", "what are all",
            "which are all", "list the", "show the", "name the",
            "distinct values", "unique values", "all values",
        ))
        or (
            any(term in q for term in ("unique", "distinct"))
            and any(term in q for term in ("list", "show", "name", "what are", "which are"))
        )
    )

    # Check condition
    if asks_distinct_count or asks_distinct_list:
        # First resolve an explicitly named dataset column.
        target_col = None
        normalized_question = re.sub(r"[_\-]+", " ", q)
        for column in df.columns:
            normalized_column = re.sub(r"[_\-]+", " ", str(column).strip().lower())
            if normalized_column and re.search(
                r"(?<![a-z0-9])" + re.escape(normalized_column) + r"(?![a-z0-9])",
                normalized_question,
            ):
                target_col = column
                break

        # Then use common business-language aliases when the column name
        # is not repeated literally in the question.
        if target_col is None:
            column_aliases = (
                (("country", "countries", "nation", "nations"), ("country",)),
                (("customer", "customers", "client", "clients"), ("customer id", "customer", "client id")),
                (("product", "products", "item", "items"), ("description", "product", "product name", "item")),
                (("region", "regions", "market", "markets"), ("region", "market", "country")),
                (("category", "categories"), ("category", "product category")),
                (("city", "cities"), ("city",)),
                (("state", "states"), ("state",)),
            )
            for aliases, exact_names in column_aliases:
                if any(re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", q) for alias in aliases):
                    target_col = _column_by_exact_or_keyword(df, exact_names, exact_names)
                    if target_col is not None:
                        break

        if target_col is not None:
            values = df[target_col].dropna().drop_duplicates()
            if asks_distinct_count and not asks_distinct_list:
                response["answer"] = (
                    f"There are {len(values):,} unique non-missing values in the "
                    f"{target_col} column."
                )
                response["interpretation"] = (
                    f"Calculated directly using pandas nunique(dropna=True) on {target_col}. "
                    "Missing values are excluded."
                )
                return response

            # Convert values to display strings and sort consistently for readability.
            display_values = sorted(
                (str(value) for value in values.tolist()),
                key=lambda value: value.casefold(),
            )
            response["answer"] = (
                f"Unique values in {target_col} ({len(display_values):,} total):\n"
                + "\n".join(f"{index}. {value}" for index, value in enumerate(display_values, 1))
            )
            response["interpretation"] = (
                f"Distinct non-missing values were calculated directly from the loaded "
                f"{target_col} column using pandas. No AI-generated values were added."
            )
            return response

    # Set up values
    metric, metric_description = _sales_metric(df)

    # Check condition
    if metric is None:

        price_col_for_average = _column_by_exact_or_keyword(

            df, ["unit price", "unitprice", "selling price", "item price"],

            ["unit price", "unitprice", "selling price", "item price"],

        )

        normalized_question = q.replace("unitprice", "unit price")

        if price_col_for_average is not None and any(

            term in normalized_question

            for term in ("average unit price", "average price", "mean unit price", "mean price")

        ):

            values = pd.to_numeric(df[price_col_for_average], errors="coerce").dropna()

            if not values.empty:

                response["answer"] = (

                    f"The average {price_col_for_average} is {_format_number(values.mean())}, "

                    f"calculated from {len(values):,} non-missing numeric rows."

                )

                response["interpretation"] = (

                    f"Calculation: sum of valid {price_col_for_average} values divided by their count."

                )

                return response

        return None



    # Set up values
    product_col = _column_by_exact_or_keyword(

        df,

        ["description", "product", "product name", "item", "item name"],

        ["product name", "description", "product", "item name"],

    )

    country_col = _column_by_exact_or_keyword(

        df, ["country"], ["country", "market", "region"]

    )

    quantity_col = _column_by_exact_or_keyword(

        df, ["quantity", "qty"], ["quantity", "qty", "units sold"]

    )

    price_col = _column_by_exact_or_keyword(

        df, ["unit price", "unitprice", "selling price", "item price", "price"],

        ["unit price", "unitprice", "selling price", "item price", "price"],

    )

    invoice_col = _column_by_exact_or_keyword(

        df, ["invoice", "invoice number", "invoice no", "order id", "order number"],

        ["invoice", "order id", "order number"],

    )

    date_col = _column_by_exact_or_keyword(

        df, ["invoice date", "order date", "transaction date", "date"],

        ["invoice date", "order date", "transaction date", "date"],

    )

    customer_col = _column_by_exact_or_keyword(

        df, ["customer id", "customer", "client id", "account id"],

        ["customer id", "client id", "account id"],

    )



    # Customer order-count rankings must be handled separately from revenue.

    asks_order_count = (

        any(term in q for term in ("order", "orders", "invoice", "invoices", "purchase"))

        and any(term in q for term in ("most", "highest", "top", "number", "count"))

        and any(term in q for term in ("customer", "client"))

    )

    # Check condition
    if asks_order_count and customer_col is not None and invoice_col is not None:

        customer_orders = df[[customer_col, invoice_col]].dropna()

        grouped_orders = (

            customer_orders.groupby(customer_col)[invoice_col]

            .nunique()

            .sort_values(ascending=False, kind="stable")

        )

        if grouped_orders.empty:

            return None

        top_match = re.search(r"\btop\s+(\d+)\b", q)

        n = min(int(top_match.group(1)), 50) if top_match else 10

        top = grouped_orders.head(n)

        lines = []

        for i, (customer, count) in enumerate(top.items(), 1):

            customer_label = (

                str(int(customer))

                if isinstance(customer, (int, float)) and float(customer).is_integer()

                else str(customer)

            )

            lines.append(f"{i}. {customer_label}: {int(count):,} orders")

        response["answer"] = (

            f"Top {len(top)} customers by distinct order/invoice count:\n"

            + "\n".join(lines)

        )

        response["interpretation"] = (

            f"Counted distinct {invoice_col} values for each non-missing {customer_col}. "

            "Customers with missing IDs and rows with missing invoice IDs are excluded."

        )

        return response



    # Returns/negative-quantity analysis reports both row and invoice rates.

    asks_negative_quantity = (

        quantity_col is not None

        and any(term in q for term in ("negative", "return", "returns"))

        and any(term in q for term in ("quantity", "quantities", "transaction", "transactions", "percentage", "percent", "how many", "count"))

    )

    # Check condition
    if asks_negative_quantity:

        quantities = pd.to_numeric(df[quantity_col], errors="coerce")

        valid_quantities = quantities.notna()

        negative_rows = quantities < 0

        valid_count = int(valid_quantities.sum())

        negative_count = int((negative_rows & valid_quantities).sum())

        row_pct = (negative_count / valid_count * 100) if valid_count else 0.0

        answer_lines = [

            f"Rows with negative quantities: {negative_count:,} of {valid_count:,} valid quantity rows ({row_pct:.2f}%)."

        ]

        if invoice_col is not None:

            invoice_rows = df.loc[valid_quantities, [invoice_col]].copy()

            invoice_rows["_negative"] = negative_rows.loc[valid_quantities].to_numpy()

            invoice_rows = invoice_rows.dropna(subset=[invoice_col])

            invoice_flags = invoice_rows.groupby(invoice_col)["_negative"].any()

            invoice_total = int(invoice_flags.size)

            negative_invoices = int(invoice_flags.sum())

            invoice_pct = (negative_invoices / invoice_total * 100) if invoice_total else 0.0

            answer_lines.append(

                f"Invoices containing at least one negative-quantity row: "

                f"{negative_invoices:,} of {invoice_total:,} invoices ({invoice_pct:.2f}%)."

            )

        response["answer"] = "\n".join(answer_lines)

        response["interpretation"] = (

            "Negative quantity rows are treated as return/credit line items. "

            "The row percentage uses valid numeric quantities as its denominator; "

            "the invoice percentage counts an invoice once if any of its rows has a negative quantity."

        )

        return response



    # Year-over-year revenue growth, calculated directly from the dataset.

    asks_yoy = any(term in q for term in (

        "year over year", "year-over-year", "year on year", "year-on-year",

        "yoy", "annual growth", "yearly growth", "revenue growth by year",

    ))

    # Check condition
    if asks_yoy and date_col is not None:

        dates = _parse_date_series(df[date_col])

        annual_data = pd.DataFrame({

            "year": dates.dt.year,

            "metric": metric,

        }).dropna(subset=["year", "metric"])

        if annual_data.empty:

            return None

        annual = annual_data.groupby("year")["metric"].sum().sort_index()

        lines = []

        previous = None

        for year, value in annual.items():

            if previous is None:

                growth_text = "â€” (base year)"

            elif previous == 0:

                growth_text = "undefined (previous year revenue was zero)"

            else:

                growth = (float(value) - previous) / abs(previous) * 100

                growth_text = f"{growth:+.2f}%"

            lines.append(

                f"{int(year)}: {_format_number(value)} revenue; YoY growth: {growth_text}"

            )

            previous = float(value)

        response["answer"] = (

            "Annual net revenue and year-over-year growth:\n" + "\n".join(lines)

        )

        response["interpretation"] = (

            f"Revenue is calculated as {metric_description}. Annual totals use valid dates "

            "and numeric revenue rows. Negative quantities remain included, so returns reduce net revenue."

        )

        return response



    # Monthly AOV = monthly net revenue divided by distinct monthly invoices.

    asks_monthly_aov = (

        any(term in q for term in ("average order value", "average order", "aov"))

        and any(term in q for term in ("month", "monthly", "months", "highest", "lowest", "which"))

    )

    # Check condition
    if asks_monthly_aov and date_col is not None and invoice_col is not None:

        dates = _parse_date_series(df[date_col])

        monthly_data = pd.DataFrame({

            "month": dates.dt.to_period("M"),

            "invoice": df[invoice_col],

            "metric": metric,

        }).dropna(subset=["month", "invoice", "metric"])

        if monthly_data.empty:

            return None

        monthly = monthly_data.groupby("month").agg(

            revenue=("metric", "sum"),

            invoices=("invoice", "nunique"),

        )

        monthly = monthly[monthly["invoices"] > 0].copy()

        monthly["aov"] = monthly["revenue"] / monthly["invoices"]

        if monthly.empty:

            return None

        top = monthly.sort_values("aov", ascending=False, kind="stable").head(10)

        low_month = monthly["aov"].idxmin()

        lines = [

            f"{period}: {_format_number(row['aov'])} "

            f"(revenue {_format_number(row['revenue'])}; {int(row['invoices']):,} invoices)"

            for period, row in top.iterrows()

        ]

        response["answer"] = (

            "Top months by average order value (AOV):\n" + "\n".join(lines)

            + f"\n\nLowest AOV month: {low_month}: {_format_number(monthly.loc[low_month, 'aov'])}."

        )

        response["interpretation"] = (

            "Monthly AOV is calculated as monthly net revenue divided by distinct invoice IDs "

            "within each month. Negative quantities remain included in net revenue."

        )

        return response



    # Product sales rankings. "Description" is intentionally allowed to have

    # many unique values; do not apply the low-cardinality segment-summary limit.

    asks_sales = any(term in q for term in ("sales", "revenue", "turnover"))

    asks_top = any(term in q for term in ("top", "highest", "most", "best-selling", "best selling", "largest", "rank"))

    # Check condition
    if product_col is not None and asks_sales and asks_top and not any(term in q for term in ("country", "region", "market")):

        table = pd.DataFrame({

            "label": df[product_col].astype("string"),

            "metric": metric,

        }).dropna(subset=["label", "metric"])

        grouped = table.groupby("label", dropna=True)["metric"].sum().sort_values(ascending=False)

        if grouped.empty:

            return None

        top_match = re.search(r"\btop\s+(\d+)\b", q)

        n = min(int(top_match.group(1)), 50) if top_match else 5

        top = grouped.head(n)

        lines = [f"{i}. {label}: {_format_number(value)}" for i, (label, value) in enumerate(top.items(), 1)]

        response["answer"] = (

            f"Top {len(top)} products by total sales (calculated as {metric_description}):\n"

            + "\n".join(lines)

        )

        response["interpretation"] = (

            f"Totals are grouped by {product_col} across all {len(df):,} loaded rows. "

            "Negative quantities, such as returns, reduce net sales."

        )

        response["limitations"] = [

            f"Rows with missing product labels or nonnumeric {metric_description} values were excluded from the ranking."

        ]

        return response



    # Country/region sales rankings.

    if country_col is not None and asks_sales and asks_top and any(term in q for term in ("country", "region", "market")):

        table = pd.DataFrame({

            "label": df[country_col].astype("string"),

            "metric": metric,

        }).dropna(subset=["label", "metric"])

        grouped = table.groupby("label")["metric"].sum().sort_values(ascending=False)

        if grouped.empty:

            return None

        top_match = re.search(r"\btop\s+(\d+)\b", q)

        n = min(int(top_match.group(1)), 50) if top_match else 5

        top = grouped.head(n)

        lines = [f"{i}. {label}: {_format_number(value)}" for i, (label, value) in enumerate(top.items(), 1)]

        response["answer"] = f"Top {len(top)} countries/regions by total sales:\n" + "\n".join(lines)

        response["interpretation"] = f"Totals use {metric_description} grouped by {country_col} across the loaded rows."

        return response



    # Average unit price.

    normalized_question = q.replace("unitprice", "unit price")

    # Check condition
    if price_col is not None and any(term in normalized_question for term in ("average unit price", "average price", "mean unit price", "mean price")):

        values = pd.to_numeric(df[price_col], errors="coerce").dropna()

        if values.empty:

            return None

        response["answer"] = f"The average {price_col} is {_format_number(values.mean())}, calculated from {len(values):,} non-missing numeric rows."

        response["interpretation"] = f"Calculation: sum of valid {price_col} values divided by their count."

        return response



    # Overall sales/revenue.

    if asks_sales and any(term in q for term in ("total", "overall", "sum", "how much")) and not asks_top:

        total = metric.sum(min_count=1)

        if pd.isna(total):

            return None

        valid_count = int(metric.notna().sum())

        response["answer"] = f"Total sales are {_format_number(total)}, calculated as {metric_description} across {valid_count:,} valid rows."

        response["interpretation"] = "This is net sales if negative quantities/returns are present."

        return response



    # Quantity rankings.

    if quantity_col is not None and product_col is not None and any(term in q for term in ("quantity", "units sold", "units")) and asks_top:

        quantities = pd.to_numeric(df[quantity_col], errors="coerce")

        table = pd.DataFrame({"label": df[product_col].astype("string"), "quantity": quantities}).dropna()

        grouped = table.groupby("label")["quantity"].sum().sort_values(ascending=False)

        if grouped.empty:

            return None

        top_match = re.search(r"\btop\s+(\d+)\b", q)

        n = min(int(top_match.group(1)), 50) if top_match else 5

        top = grouped.head(n)

        lines = [f"{i}. {label}: {_format_number(value)} units" for i, (label, value) in enumerate(top.items(), 1)]

        response["answer"] = f"Top {len(top)} products by total quantity:\n" + "\n".join(lines)

        response["interpretation"] = f"Quantities are summed by {product_col}; negative quantities remain included and reduce the total."

        return response



    # Return result
    return None





# Return True when a request explicitly combines multiple analytical tasks
def _is_multi_analysis_question(question):

    """Return True when a request explicitly combines multiple analytical tasks."""

    q = question.lower()

    task_groups = {

        "time_trend": ("monthly", "month", "trend", "over time", "by year", "yearly"),

        "country_breakdown": ("country", "region", "market"),

        "product_breakdown": ("product", "products", "item", "stock code", "best-selling"),

        "customer_breakdown": ("customer", "customers", "client"),

        "statistics": ("correlation", "correlations", "relationship", "outlier", "distribution"),

        "data_quality": ("data quality", "missing", "duplicate", "clean", "negative quantity", "returns"),

    }

    matched = 0

    # Loop over items
    for terms in task_groups.values():

        if any(term in q for term in terms):

            matched += 1

    # Return result
    return matched >= 2





# Load backend-only custom AI settings without exposing the stored API key
def _load_saved_ai_settings():
    """Load backend-only custom AI settings without exposing the stored API key."""
    candidates = []
    # Check condition
    if os.environ.get("AI_ANALYST_ROOT"):
        candidates.append(Path(os.environ["AI_ANALYST_ROOT"]) / ".ai_analyst_settings.json")

    # Set up values
    module_path = Path(__file__).resolve()
    candidates.extend(parent / ".ai_analyst_settings.json" for parent in module_path.parents)

    # Loop over items
    for settings_path in candidates:
        try:
            if settings_path.is_file():
                payload = json.loads(settings_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    return payload
        except Exception:
            continue
    # Return result
    return {}



# Call only the provider/model saved by the user's Custom AI settings
def _call_custom_ai_provider(question, context):
    """Call only the provider/model saved by the user's Custom AI settings."""
    settings = _load_saved_ai_settings()
    provider = str(settings.get("provider") or "").strip().lower()
    model = str(settings.get("model") or "").strip()
    api_key = str(settings.get("api_key") or "").strip()

    # Check condition
    if provider not in {"gemini", "groq", "openrouter"}:
        raise RuntimeError("Custom AI provider is not configured. Choose Gemini, Groq, or OpenRouter in Settings.")
    # Check condition
    if not model:
        raise RuntimeError("Custom AI model is not configured. Choose or enter a model ID in Settings.")
    # Check condition
    if not api_key:
        raise RuntimeError("Custom AI API key is not configured. Add an API key in Settings.")

    # Check condition
    if provider == "gemini":
        return call_gemini(question, context, api_key_override=api_key, model_override=model)
    # Check condition
    if provider == "groq":
        return call_groq(question, context, api_key_override=api_key, model_override=model)
    # Return result
    return call_openrouter(question, context, api_key_override=api_key, model_override=model)



# Try providers in priority order, or use the saved custom provider strictly
def _call_ai_provider(question, context, provider="auto"):
    """Try providers in priority order, or use the saved custom provider strictly."""
    provider = str(provider or "auto").strip().lower()

    # Check condition
    if provider == "custom":
        # Custom mode is intentionally strict: one saved provider/model only, no fallback.
        # _call_custom_ai_provider() returns the response dict only, while callers
        # of _call_ai_provider() expect (response, provider_name).
        response = _call_custom_ai_provider(question, context)
        saved_settings = _load_saved_ai_settings()
        custom_provider = str(saved_settings.get("provider") or "custom").strip().lower()
        custom_model = str(saved_settings.get("model") or "").strip()

        provider_labels = {
            "gemini": "Gemini",
            "groq": "Groq",
            "openrouter": "OpenRouter",
        }
        provider_label = provider_labels.get(custom_provider, custom_provider.title())

        if custom_model:
            provider_name = f"{provider_label} ({custom_model})"
        else:
            provider_name = provider_label

        return response, provider_name

    # Set up values
    gemini_1 = ("Gemini 1", call_gemini)
    gemini_2_key = os.environ.get("GEMINI_API_KEY_2")
    gemini_2 = (
        "Gemini 2",
        lambda q, ctx: call_gemini(
            q, ctx,
            api_key_override=gemini_2_key,
            model_override=GEMINI_MODEL_2,
        ),
    )
    groq_provider = (f"Groq ({GROQ_MODEL})", call_groq)
    openrouter_provider = (f"OpenRouter ({OPENROUTER_MODEL})", call_openrouter)
    ollama_provider = ("Ollama (local)", call_ollama)

    provider_map = {
        "gemini": (gemini_1,),
        "gemini2": (gemini_2,),
        "groq": (groq_provider,),
        "openrouter": (openrouter_provider,),
        "ollama": (ollama_provider,),
    }
    allowed = ", ".join(("auto", *provider_map.keys()))
    # Check condition
    if provider != "auto" and provider not in provider_map:
        raise ValueError(f"Invalid AI provider. Choose {allowed}.")

    # Set up values
    requires_live_search = (
        context.get("mode") == "general_knowledge"
        and _requires_live_search(question)
    )

    # Check condition
    if provider == "auto":
        # Auto fallback order matches the Current Project settings shown
        # in the UI: Gemini 1 -> Gemini 2 -> Groq -> OpenRouter -> Ollama.
        # Gemini 2 is also independently selectable; when Auto is used it
        # gets a chance only after Gemini 1 fails.
        providers = [
            gemini_1,
            gemini_2,
            groq_provider,
            openrouter_provider,
            ollama_provider,
        ]
    else:
        # Explicit selection remains strict; only Auto mode uses the full chain.
        providers = list(provider_map[provider])

    # Set up values
    errors = []
    # Loop over items
    for provider_name, provider_call in providers:
        try:
            provider_context = context
            # Fallback providers should receive the original context. Gemini's live-search failure must not prevent Groq/OpenRouter/Ollama from answering.
            provider_context = context

            response = provider_call(question, provider_context)
            if not isinstance(response, dict):
                raise RuntimeError("The AI returned an invalid response.")
            answer = str(response.get("answer") or "").strip()
            if not answer:
                raise RuntimeError("The AI returned an empty answer.")

            if requires_live_search and provider_name.startswith("Gemini"):
                response["verification_status"] = "live_search_grounded"
            elif requires_live_search and provider_name.startswith("Groq"):
                response["verification_status"] = "groq_fallback"
            elif requires_live_search and provider_name.startswith("OpenRouter"):
                response["verification_status"] = "openrouter_fallback"
            elif requires_live_search and provider_name.startswith("Ollama"):
                response["verification_status"] = "ollama_fallback"

            return response, provider_name

        except Exception as exc:
            # Log provider errors without exposing API keys or request URLs.
            detail = str(exc)
            if isinstance(exc, urllib.error.HTTPError):
                try:
                    error_body = exc.read().decode("utf-8", errors="replace")
                    try:
                        error_json = json.loads(error_body)
                        api_error = error_json.get("error", {})
                        detail = (
                            f"HTTP {exc.code}: "
                            f"{api_error.get('status', '')} "
                            f"{api_error.get('message', error_body)}"
                        ).strip()
                    except Exception:
                        detail = f"HTTP {exc.code}: {error_body[:500]}"
                except Exception:
                    detail = f"HTTP {exc.code}: {exc.reason}"
            detail = str(detail).replace("\n", " ")[:500]
            print(f"[AI PROVIDER ERROR] {provider_name}: {detail}", flush=True)
            errors.append(f"{provider_name}: {detail[:200]}")

    # Check condition
    if requires_live_search:
        raise RuntimeError(
            "Gemini live search failed and the Groq/OpenRouter/Ollama fallbacks "
            "could not generate an answer. "
            + " | ".join(errors)
        )
    raise RuntimeError("All permitted AI providers failed. " + " | ".join(errors))


# Return a verified, vectorized data-quality profile without calling an LLM
def _data_quality_fast_answer(question, df):
    """Return a verified, vectorized data-quality profile without calling an LLM."""
    # Check condition
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None

    # Set up values
    q = str(question or "").lower()
    quality_intent = any(term in q for term in (
        "data quality", "quality issues", "quality problems",
        "check data quality", "check the data", "profile this data",
        "profile the dataset", "inspect the data", "data problems",
    ))
    # Check condition
    if not quality_intent:
        return None

    # Set up values
    row_count, column_count = df.shape
    missing_by_column = df.isna().sum()
    missing_total = int(missing_by_column.sum())
    duplicate_count = int(df.duplicated().sum())

    lines = [
        f"Dataset size: {row_count:,} rows Ã— {column_count:,} columns",
        f"Missing cells: {missing_total:,} ({missing_total / max(row_count * column_count, 1) * 100:.2f}% of all cells)",
        f"Exact duplicate rows: {duplicate_count:,}",
        "",
        "Missing values by column:",
    ]

    missing_columns = [
        (str(col), int(count), float(count / max(row_count, 1) * 100))
        for col, count in missing_by_column.items() if int(count) > 0
    ]
    # Check condition
    if missing_columns:
        for col, count, pct in sorted(missing_columns, key=lambda x: x[1], reverse=True):
            lines.append(f"- {col}: {count:,} ({pct:.2f}% of rows)")
    else:
        lines.append("- None detected")

    # Set up values
    qty_col = _column_by_exact_or_keyword(
        df, ["quantity", "qty"], ["quantity", "qty", "units sold"]
    )
    price_col = _column_by_exact_or_keyword(
        df, ["unit price", "unitprice", "selling price", "item price", "price"],
        ["unit price", "unitprice", "selling price", "item price", "price"]
    )

    negative_qty = 0
    # Check condition
    if qty_col is not None:
        qty = pd.to_numeric(df[qty_col], errors="coerce")
        negative_qty = int(qty.lt(0).sum())
        lines.extend(["", "Potential value issues:"])
        lines.append(f"- Negative {qty_col} rows: {negative_qty:,}")
    else:
        lines.extend(["", "Potential value issues:", "- No quantity column identified"])

    # Check condition
    if price_col is not None:
        price = pd.to_numeric(df[price_col], errors="coerce")
        negative_price = int(price.lt(0).sum())
        lines.append(f"- Negative {price_col} rows: {negative_price:,}")

    # Set up values
    date_col = _column_by_exact_or_keyword(
        df, ["invoice date", "order date", "transaction date", "date"],
        ["invoice date", "order date", "transaction date", "timestamp", "date"]
    )
    # Check condition
    if date_col is not None:
        lines.extend(["", "Date field:"])
        lines.append(f"- {date_col} is stored as {df[date_col].dtype}")
        if not pd.api.types.is_datetime64_any_dtype(df[date_col]):
            lines.append("- The column is not currently a pandas datetime type; validate parsing before time-series analysis.")

    # Apply IQR screening only to business measures, not identifiers or codes.
    measure_terms = ("quantity", "qty", "price", "sales", "revenue", "amount",
                     "discount", "profit", "cost", "duration", "age")
    outlier_lines = []
    # Loop over items
    for col in df.select_dtypes(include="number").columns:
        name = str(col).lower().replace("_", " ")
        if not any(term in name for term in measure_terms):
            continue
        values = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(values) < 4:
            continue
        q1, q3 = values.quantile([0.25, 0.75])
        iqr = q3 - q1
        if not pd.notna(iqr) or iqr == 0:
            continue
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        count = int(((values < lower) | (values > upper)).sum())
        outlier_lines.append(
            f"- {col}: {count:,} values outside IQR fences ({lower:,.2f} to {upper:,.2f})"
        )
    lines.extend(["", "Potential statistical outliers (1.5 Ã— IQR rule):"])
    lines.extend(outlier_lines or ["- No eligible numeric measure columns found"])

    # Weighted quality score. Only assess dimensions for which the dataset
    # contains evidence; do not penalize legitimate returns or statistical outliers.
    score_dimensions = []
    total_cells = max(row_count * column_count, 1)
    completeness_ratio = min(max(missing_total / total_cells, 0.0), 1.0)
    score_dimensions.append(("Completeness", 30.0, 30.0 * (1.0 - completeness_ratio)))

    duplicate_ratio = min(max(duplicate_count / max(row_count, 1), 0.0), 1.0)
    score_dimensions.append(("Uniqueness", 20.0, 20.0 * (1.0 - duplicate_ratio)))

    invalid_value_mask = pd.Series(False, index=df.index)
    numeric_checks = []
    # Loop over items
    for numeric_col in (qty_col, price_col):
        if numeric_col is None:
            continue
        raw = df[numeric_col]
        converted = pd.to_numeric(raw, errors="coerce")
        invalid_value_mask |= raw.notna() & converted.isna()
        if numeric_col == price_col:
            invalid_value_mask |= converted.lt(0).fillna(False)
        numeric_checks.append(numeric_col)

    # Check condition
    if numeric_checks:
        invalid_value_rows = int(invalid_value_mask.sum())
        invalid_value_ratio = min(invalid_value_rows / max(row_count, 1), 1.0)
        score_dimensions.append(("Value validity", 30.0, 30.0 * (1.0 - invalid_value_ratio)))
    else:
        invalid_value_rows = 0

    # Set up values
    date_parse_failures = 0
    # Check condition
    if date_col is not None:
        parsed_dates = _parse_date_series(df[date_col])
        date_parse_failures = int((df[date_col].notna() & parsed_dates.isna()).sum())
        date_failure_ratio = min(date_parse_failures / max(row_count, 1), 1.0)
        score_dimensions.append(("Date consistency", 20.0, 20.0 * (1.0 - date_failure_ratio)))

    # Set up values
    assessed_weight = sum(weight for _, weight, _ in score_dimensions)
    quality_score = round(
        sum(points for _, _, points in score_dimensions) / max(assessed_weight, 1.0) * 100
    )
    # Check condition
    if quality_score >= 90:
        quality_label = "Excellent"
    elif quality_score >= 80:
        quality_label = "Good"
    elif quality_score >= 65:
        quality_label = "Fair"
    elif quality_score >= 50:
        quality_label = "Poor"
    else:
        quality_label = "Critical"

    lines.extend([
        "",
        "DATA QUALITY SCORE:",
        f"- Overall score: {quality_score}/100 ({quality_label})",
        "- Scoring breakdown:",
    ])
    # Loop over items
    for dimension, weight, points in score_dimensions:
        lines.append(f"  - {dimension}: {points:.1f}/{weight:.0f} points")
    lines.extend([
        f"- Rows with invalid numeric values or negative prices: {invalid_value_rows:,}",
        f"- Non-empty dates that failed parsing: {date_parse_failures:,}",
        "- Negative quantities and IQR outliers are reported but not penalized automatically because they may be legitimate.",
        "- Score uses only dimensions that could be assessed from the available columns; assessed weights are normalized to 100.",
    ])

    recommendations = [
        "Investigate missing customer or product identifiers before excluding those records; some transactions may still be usable.",
        "Check whether negative quantities represent legitimate returns or credit notes before removing them.",
        "Validate negative prices and unusually large values against source records.",
        "Convert date fields to datetime only after checking day/month ordering and parse failures.",
    ]
    limitations = [
        "IQR flags are screening indicators, not proof of incorrect data.",
        "Duplicate rows are exact full-row duplicates; repeated invoice/product lines are not automatically duplicates.",
        "Negative quantities may be legitimate returns.",
    ]
    # Return result
    return {
        "answer": "Data quality assessment (calculated directly from the loaded DataFrame):\n" + "\n".join(lines),
        "interpretation": "The counts above are computed from the currently loaded dataset. Review flagged records in context rather than deleting them automatically.",
        "recommendations": recommendations,
        "follow_up_questions": ["Would you like a row-level list of the flagged records?"],
        "limitations": limitations,
        "suggested_analyses": ["Inspect missing customer IDs", "Review negative prices and quantities", "Validate date parsing", "Review IQR outliers"],
        "provider": "Python (fast data-quality profile)",
        "analysis_mode": "deterministic_data_quality",
        "dataset_rows": int(row_count),
        "dataset_columns": int(column_count),
        "data_quality_score": int(quality_score),
        "data_quality_grade": quality_label,
        "data_quality_breakdown": [
            {"dimension": name, "weight": weight, "score": round(points, 2)}
            for name, weight, points in score_dimensions
        ],
    }



# Helper: is dataset summary question
def _is_dataset_summary_question(question):
    # Set up values
    q = re.sub(r"\s+", " ", str(question or "").lower()).strip()
    # Return result
    return any(term in q for term in (
        "summarize this dataset", "summarise this dataset",
        "summarize the dataset", "summarise the dataset",
        "dataset summary", "give me a dataset summary",
        "overall summary", "overview of this dataset",
        "summarize my data", "summarise my data",
        "analyze this dataset", "analyse this dataset",
        "profile this dataset",
    ))


# Build a factual dataset overview locally; this path never needs an API
def _deterministic_dataset_summary_answer(df, context):
    """Build a factual dataset overview locally; this path never needs an API."""
    row_count, column_count = df.shape
    dataset = context.get("dataset", {})
    metric = context.get("metric", {})
    metric_name = metric.get("name")
    lines = [
        "## Dataset overview",
        f"- **Rows:** {row_count:,}",
        f"- **Columns:** {column_count:,}",
        f"- **Missing cells:** {int(dataset.get('missing_cells', int(df.isna().sum().sum()))):,}",
        f"- **Duplicate rows:** {int(dataset.get('duplicate_rows', int(df.duplicated().sum()))):,}",
        "",
        "## Columns",
    ]
    # Loop over items
    for column in df.columns:
        series = df[column]
        lines.append(
            f"- **{column}** â€” {series.dtype}; "
            f"{int(series.nunique(dropna=True)):,} distinct non-null values; "
            f"{int(series.isna().sum()):,} missing"
        )

    # Check condition
    if metric_name:
        numeric_metric = None
        if metric_name in df.columns:
            numeric_metric = pd.to_numeric(df[metric_name], errors="coerce")
        elif "Ã—" in str(metric_name):
            parts = [part.strip() for part in str(metric_name).split("Ã—", 1)]
            if len(parts) == 2 and all(part in df.columns for part in parts):
                numeric_metric = (
                    pd.to_numeric(df[parts[0]], errors="coerce")
                    * pd.to_numeric(df[parts[1]], errors="coerce")
                )
        if numeric_metric is not None:
            valid_metric = numeric_metric.dropna()
            if not valid_metric.empty:
                lines.extend([
                    "",
                    "## Calculated metric",
                    f"- **Metric:** {metric_name}",
                    f"- **Net total:** {float(valid_metric.sum()):,.2f}",
                    f"- **Average per valid row:** {float(valid_metric.mean()):,.2f}",
                    f"- **Valid rows:** {len(valid_metric):,}",
                ])

    # Set up values
    date_col = metric.get("date_column")
    # Check condition
    if date_col and date_col in df.columns:
        parsed_dates = _parse_date_series(df[date_col]).dropna()
        if not parsed_dates.empty:
            lines.extend([
                "",
                "## Date coverage",
                f"- **Date column:** {date_col}",
                f"- **From:** {parsed_dates.min().date().isoformat()}",
                f"- **To:** {parsed_dates.max().date().isoformat()}",
                f"- **Valid date rows:** {len(parsed_dates):,}",
            ])

    # Set up values
    monthly = context.get("monthly_totals") or {}
    # Check condition
    if monthly:
        ordered = sorted(monthly.items())
        lines.extend(["", "## Monthly metric highlights"])
        for period, value in ordered[-6:]:
            lines.append(f"- **{period}:** {float(value):,.2f}")

    lines.extend([
        "",
        "## Notes",
        "- This overview is calculated directly from the uploaded data; no AI provider was needed.",
        "- The metric total is a net sum when the source contains negative quantities or values.",
        "- Descriptive statistics do not establish causes or business performance drivers.",
    ])
    # Return result
    return {
        "answer": "\n".join(lines),
        "interpretation": "Deterministic dataset profile calculated locally with pandas.",
        "recommendations": [],
        "follow_up_questions": [
            "Which products or customers contribute the most revenue?",
            "How do sales change month by month?",
            "What data-quality issues should I investigate?",
        ],
        "limitations": list(context.get("limitations", [])),
        "suggested_analyses": ["product ranking", "customer analysis", "monthly trend", "data quality"],
        "provider": "Python (local deterministic summary)",
        "analysis_mode": "dataset_summary",
    }


# Calculate common numeric answers with Python; use an LLM for interpretation
def answer_business_question(question, df, provider="auto", schema=None):

    """Calculate common numeric answers with Python; use an LLM for interpretation."""

    question = question.strip()



    # Remove the API's response-style wrapper before routing the question.

    question_match = re.search(

        r"User's question:\s*(.*)",

        question,

        flags=re.IGNORECASE | re.DOTALL,

    )

    # Check condition
    if question_match:

        question = question_match.group(1).strip().strip('"').strip("'")



    print("AI ANALYST QUESTION RECEIVED:", repr(question))



    # Check condition
    if not question:

        raise ValueError("Enter a business or data analysis question.")

    # Simple arithmetic is deterministic: solve it locally without an LLM.
    python_result = _try_python_arithmetic(question)
    # Check condition
    if python_result is not None:
        print("AI ANALYST ROUTED TO:", python_result["provider"])
        return python_result

    # Set up values
    question_lower = question.lower()



    # LIVE WORLD BANK DATA: India nominal GDP.

    # Keep dataset-specific questions on the existing dataset-analysis path.

    dataset_context_markers = (

        "dataset", "spreadsheet", "workbook", "uploaded data",

        "in my data", "in this data", "in the data", "in this table",

        "in these records", "in the file", "in this file", "column",

        "transactions", "invoice", "customer", "stock code",

    )

    asks_india_gdp = (

        "gdp" in question_lower

        and ("india" in question_lower or "indian" in question_lower)

        and not any(marker in question_lower for marker in dataset_context_markers)

    )

    # Check condition
    if asks_india_gdp:

        live_result = get_india_latest_gdp()

        if live_result is not None:

            return live_result

        # If the official API is unavailable, continue to the existing

        # general-knowledge AI route rather than failing the whole request.



    general_knowledge_markers = (

        "gdp of ", "gross domestic product", "what is gdp",

        "population of ", "capital of ", "president of ",

        "prime minister of ", "who is ", "who was ", "when was ",

        "where is ", "define ", "meaning of ", "explain ",

        "what does ", "how does ", "how do ", "why does ", "why do ",

    )

    dataset_context_markers = (

        "dataset", "spreadsheet", "workbook", "uploaded data",

        "in my data", "in this data", "in the data", "in this table",

        "in these records", "in the file", "in this file", "column",

        "transactions", "invoice", "customer", "stock code",

        "total revenue", "total sales", "monthly sales",

    )

    asks_general_knowledge = (

        any(marker in question_lower for marker in general_knowledge_markers)

        and not any(marker in question_lower for marker in dataset_context_markers)

    )



    # Check condition
    if asks_general_knowledge:

        context = {

            "mode": "general_knowledge",

            "limitations": [],

        }

        response, provider = _call_ai_provider(
            question,
            context,
            provider,
        )

        if not isinstance(response, dict):

            raise RuntimeError("The AI returned an invalid response.")

        response["answer"] = str(

            response.get("answer", "No direct answer was returned.")

        )

        response["interpretation"] = str(response.get("interpretation", ""))

        for key in (

            "recommendations", "follow_up_questions",

            "limitations", "suggested_analyses",

        ):

            value = response.get(key, [])

            if not isinstance(value, list):

                value = [str(value)]

            response[key] = [str(item) for item in value]

        response["provider"] = provider

        response["analysis_mode"] = "general_knowledge"

        return response



    # Row-level max/min questions must use the live DataFrame, not only the dataset summary.
    row_lookup_response = _deterministic_row_lookup_answer(question, df)
    # Check condition
    if row_lookup_response is not None:
        return row_lookup_response

    # Fast path for broad data-quality requests: calculate from pandas and return
    # before the BI profiler, orchestrator, and remote LLM calls.
    quality_response = _data_quality_fast_answer(question, df)
    # Check condition
    if quality_response is not None:
        return quality_response

    # Set up values
    context = build_dataset_context(df)

    # Local 100K question bank improves example retrieval for complex questions.
    # Its examples are guidance only; all factual answers still use the live DataFrame.
    try:
        from ai.question_bank import retrieve_question_examples
        context["question_bank_examples"] = retrieve_question_examples(question, limit=5)
        context["question_bank_note"] = (
            "Examples are intent references only. Never copy their results. "
            "Use the actual uploaded DataFrame and executed tool evidence for every value, "
            "filter, grouping, ranking, and count. If evidence is insufficient, say so."
        )
    except Exception as question_bank_error:
        print(f"[QUESTION BANK] Retrieval unavailable: {question_bank_error}", flush=True)
        context["question_bank_examples"] = []

    # Add evidence-first business intelligence context without replacing
    # the existing deterministic calculations or provider fallback.
    bi_context = None
    # Check condition
    if analyze_business_question is not None:
        try:
            bi_context = analyze_business_question(question, df, schema)
            context["business_intelligence"] = bi_context
        except Exception as exc:
            context["business_intelligence"] = {
                "error": f"Business intelligence context unavailable: {exc}"
            }

    # Dynamic tool orchestration: safe Python/SQL tools run before AI interpretation.

    # Existing deterministic answers still return immediately when Python can answer exactly.

    tool_execution = run_analytics_orchestrator(question, df)

    context["tool_execution"] = tool_execution

    # Broad dataset summaries are factual profiling tasks. Return the pandas-
    # calculated overview directly so provider quota, malformed JSON, or local
    # Ollama availability can never prevent this common request from working.
    if _is_dataset_summary_question(question):
        summary = _deterministic_dataset_summary_answer(df, context)
        summary["dataset_context"] = context
        summary["tool_execution"] = tool_execution
        return summary



    # Exact single-task questions can still use the fast deterministic path.

    # Compound requests must reach the AI with all orchestrator evidence so one

    # deterministic handler (for example country_revenue) cannot swallow the rest.

    multi_analysis_request = _is_multi_analysis_question(question)

    # A validated structured query may contain a HAVING/filter condition that
    # older deterministic handlers do not understand. Do not let a broader
    # legacy answer (for example, top customers) swallow the filtered result.
    structured_query_ran = any(
        item.get("tool") == "validated_structured_query"
        and item.get("status") == "success"
        for item in tool_execution.get("execution_trace", [])
        if isinstance(item, dict)
    )

    deterministic = (
        None if (multi_analysis_request or structured_query_ran)
        else _deterministic_answer(question, df)
    )

    # Check condition
    if deterministic is not None:

        deterministic["recommendations"] = deterministic.get("recommendations", [])

        deterministic["follow_up_questions"] = deterministic.get("follow_up_questions", [])

        deterministic["limitations"] = list(dict.fromkeys(

            deterministic.get("limitations", []) + context["limitations"]

        ))

        deterministic["suggested_analyses"] = deterministic.get("suggested_analyses", [])

        deterministic["dataset_context"] = context

        deterministic["tool_execution"] = tool_execution

        if isinstance(bi_context, dict):
            evidence_recs = bi_context.get("evidence_backed_recommendations", [])
            if isinstance(evidence_recs, list):
                existing = deterministic.get("recommendations", [])
                if not isinstance(existing, list):
                    existing = [str(existing)]
                deterministic["recommendations"] = existing + evidence_recs

        return deterministic



    # Set up values
    response, provider = _call_ai_provider(
        question,
        context,
        provider,
    )

    # Check condition
    if not isinstance(response, dict):

        raise RuntimeError("The AI returned an invalid response.")



    # Set up values
    response["answer"] = str(

        response.get("answer", "No direct answer was returned.")

    )

    response["interpretation"] = str(response.get("interpretation", ""))



    # Loop over items
    for key in (

        "recommendations",

        "follow_up_questions",

        "limitations",

        "suggested_analyses",

    ):

        value = response.get(key, [])

        if not isinstance(value, list):

            value = [str(value)]

        response[key] = [str(item) for item in value]



    # Set up values
    response["limitations"] = list(dict.fromkeys(

        response["limitations"] + context["limitations"]

    ))

    response["provider"] = provider

    response["dataset_context"] = context

    response["tool_execution"] = tool_execution

    # Check condition
    if isinstance(bi_context, dict):
        evidence_recs = bi_context.get("evidence_backed_recommendations", [])
        if isinstance(evidence_recs, list):
            existing = response.get("recommendations", [])
            if not isinstance(existing, list):
                existing = [str(existing)]
            response["recommendations"] = existing + evidence_recs

    # Return result
    return response

# Prevent internal inline-code markers from leaking into user-visible answers
def _clean_internal_response_placeholders(value):
    """Prevent internal inline-code markers from leaking into user-visible answers."""
    # Check condition
    if isinstance(value, str):
        value = re.sub(r"@@INLINE\*CODE\*\d+@@", "", value)
        return value
    # Check condition
    if isinstance(value, list):
        return [_clean_internal_response_placeholders(item) for item in value]
    # Check condition
    if isinstance(value, dict):
        return {key: _clean_internal_response_placeholders(item) for key, item in value.items()}
    # Return result
    return value


# Answer a general question using the shared provider/fallback policy
def answer_general_chat(question, history=None, provider="auto"):
    """Answer a general question using the shared provider/fallback policy."""
    question = str(question or "").strip()
    # Check condition
    if not question:
        raise ValueError("Enter a question.")

    # Let Python handle clear arithmetic instead of waiting for a language model.
    python_result = _try_python_arithmetic(question)
    # Check condition
    if python_result is not None:
        return python_result

    # Set up values
    safe_history = []
    # Check condition
    if isinstance(history, list):
        for item in history[-12:]:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = str(item.get("content", "")).strip()
            if role in ("user", "assistant") and content:
                safe_history.append({"role": role, "content": content[:4000]})

    # Try, handle errors
    try:
        now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
        context_current_datetime = (
            f"Current date: {now_ist.strftime('%d %B %Y')}\\n"
            f"Current time: {now_ist.strftime('%I:%M:%S %p')}\\n"
            "Timezone: Asia/Kolkata (IST)"
        )
    except Exception:
        # Keep the application usable if the timezone database is unavailable.
        now_local = datetime.now()
        context_current_datetime = (
            f"Current date: {now_local.strftime('%d %B %Y')}\\n"
            f"Current time: {now_local.strftime('%I:%M:%S %p')}\\n"
            "Timezone: local application runtime"
        )

    # Set up values
    context = {
        "mode": "general_knowledge",
        "conversation_history": safe_history,
        "current_datetime": context_current_datetime,
        "limitations": [],
    }

    # Provider-independent live market evidence. This is additive: if the
    # market source is unavailable, the existing provider routing continues.
    if _is_market_price_question(question):
        live_market_data = _get_live_market_data(question)
        if live_market_data is not None:
            context["live_market_data"] = live_market_data
            context["live_market_data_verified"] = True
        else:
            context["live_market_data_verified"] = False
            context["current_information_unverified"] = True

    # Set up values
    response, provider_name = _call_ai_provider(question, context, provider)
    response["answer"] = str(response.get("answer") or "").strip()
    response["interpretation"] = str(response.get("interpretation", ""))
    # Loop over items
    for key in (
        "recommendations", "follow_up_questions", "limitations", "suggested_analyses"
    ):
        value = response.get(key, [])
        if not isinstance(value, list):
            value = [str(value)]
        response[key] = [str(item) for item in value]
    # Set up values
    response["provider"] = provider_name
    response["analysis_mode"] = "general_chat"
    response = _clean_internal_response_placeholders(response)
    # Return result
    return response


