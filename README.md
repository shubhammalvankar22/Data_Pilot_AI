# Data Pilot AI

🔗 **Live demo:** [https://data-pilot-ai-w3iu.vercel.app/](https://data-pilot-ai-w3iu.vercel.app/)

An AI-powered data analysis workspace: upload a spreadsheet, edit it in a grid, check data quality, and ask questions in plain English.

## Tech stack
- **Backend:** Python (FastAPI), SQL (DuckDB, Postgres, BigQuery, Snowflake dialects)
- **Frontend:** React + Vite (JavaScript/JSX), CSS
- **AI providers:** Gemini, Groq, OpenRouter, Ollama

## Run
    cd backend  && pip install -r requirements.txt && uvicorn main:app --reload --port 8000
    cd frontend && npm install && npm run dev        # http://localhost:5173
AI keys: GEMINI_API_KEY / GROQ_API_KEY / OPENROUTER_API_KEY in backend/.env, or Settings in the UI.

## backend/
    main.py                 the API: every /api/... route and the question-answering logic
    ai/                     analyst.py (talks to Gemini/Groq/OpenRouter/Ollama), orchestrator.py, question bank
    spreadsheet/            workspace.py - table editing engine (edit, undo, clean)
    sql/                    policy.py (SQL safety) + dialects/ (DuckDB, Postgres, BigQuery, Snowflake)
    profiling/              detects what each column means (revenue, date, customer...)
    business/               metrics and recommendations

## frontend/src/
    main.jsx                entry point
    App.jsx                 main screen: upload, AI chat, settings, state
    components/OpenSheetsView.jsx   the spreadsheet grid
    pages/                  DataPilotHome.jsx, DataQualityPage.jsx (+ .css)
    styles/global.css       global styles
    (frontend/vendor/opensheets-2.1.0.tgz = third-party spreadsheet library used by OpenSheetsView)
