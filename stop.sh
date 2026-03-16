#!/bin/bash
# Stop openclaw-mem web dashboards

echo "🛑 Stopping OpenClaw Memory Dashboard..."
pkill -f 'web_app.py'
pkill -f 'history_app.py'
echo "✅ Done"
