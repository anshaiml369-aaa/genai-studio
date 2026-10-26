#!/bin/bash
# Start Kalpana · GenAI Studio  ->  http://localhost:8000
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "First run: installing libraries..."
  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
fi

(sleep 2 && open http://localhost:8000) &
.venv/bin/uvicorn main:app --app-dir backend --port 8000 --no-access-log
