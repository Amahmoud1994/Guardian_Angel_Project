#!/bin/bash
# Guardian Angel — POC Launcher
cd "$(dirname "$0")"
echo ""
echo "  🛡  GUARDIAN ANGEL — Proof of Concept"
echo "  ────────────────────────────────────────"
echo "  Server starting at http://localhost:8000"
echo "  API docs at     http://localhost:8000/docs"
echo ""
python3 -m uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload
