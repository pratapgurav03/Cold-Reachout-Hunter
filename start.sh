#!/bin/bash
# ─────────────────────────────────────────────
#  Cold Reachout Hunter — Start Web Server
#  Double-click this file or run: bash start.sh
# ─────────────────────────────────────────────

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║       COLD REACHOUT HUNTER — Starting...         ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# Check .env exists
if [ ! -f ".env" ]; then
  echo "⚠️  No .env file found. Copying from .env.example..."
  cp .env.example .env
  echo "   → Open .env and add your API keys before using the app."
  echo ""
fi

# Check Python
if ! command -v python3 &>/dev/null; then
  echo "❌ Python3 not found. Install it from https://python3.org"
  exit 1
fi

# Install dependencies if needed
if ! python3 -c "import flask" 2>/dev/null; then
  echo "📦 Installing dependencies..."
  pip3 install -r requirements.txt --quiet
  echo "✅ Dependencies installed."
  echo ""
fi

# Kill any existing instance on port 5050
lsof -ti:5050 | xargs kill -9 2>/dev/null

echo "🚀 Starting server on http://localhost:5050"
echo "   Press Ctrl+C to stop."
echo ""

# Open browser after 2 seconds
(sleep 2 && open "http://localhost:5050") &

# Start Flask
python3 app.py
