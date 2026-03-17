#!/bin/bash
# openclaw-mem web dashboard launcher

echo "🚀 Starting OpenClaw Memory Dashboard..."

# Start dashboard app
cd /Users/usuario/openclaw-mem
.venv/bin/python3 web_app.py > /tmp/web_app.log 2>&1 &
DASHBOARD_PID=$!

# Start history app
.venv/bin/python3 history_app.py > /tmp/history_app.log 2>&1 &
HISTORY_PID=$!

echo "✅ Dashboard: http://localhost:5001"
echo "✅ History:   http://localhost:5002"
echo "🔒 Local access only"
echo "👉 Use 'kill $DASHBOARD_PID $HISTORY_PID' to stop"
echo "👉 Or run: pkill -f 'web_app.py\|history_app.py'"
