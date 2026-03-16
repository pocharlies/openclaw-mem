#!/bin/bash
# Test script for openclaw-mem web dashboard

echo "🧪 Testing OpenClaw-Mem Web Dashboard..."

# Check if database exists
if [ ! -f ~/.openclaw-mem/memory.db ]; then
    echo "❌ Database not found at ~/.openclaw-mem/memory.db"
    exit 1
fi

echo "✅ Database found"

# Check if web apps are running
echo "🌐 Checking web apps..."

# Test dashboard
RESPONSE=$(curl -s http://127.0.0.1:5000/api/stats)
if echo "$RESPONSE" | grep -q "total_observations"; then
    echo "✅ Dashboard API working"
    echo "   Stats: $RESPONSE"
else
    echo "❌ Dashboard API not responding"
    exit 1
fi

# Test history
RESPONSE=$(curl -s http://127.0.0.1:5001/api/messages | head -c 200)
if echo "$RESPONSE" | grep -q "content"; then
    echo "✅ History API working"
    echo "   Sample: $(echo "$RESPONSE" | head -c 100)..."
else
    echo "❌ History API not responding"
    exit 1
fi

# Test search on dashboard
RESPONSE=$(curl -s "http://127.0.0.1:5000/api/search?q=email" | head -c 100)
if echo "$RESPONSE" | grep -qE "\[|total"; then
    echo "✅ Search working"
else
    echo "⚠️  Search may not be available yet"
fi

# Count observations
COUNT=$(curl -s http://127.0.0.1:5000/api/stats | grep -o '"total_observations":[0-9]*' | grep -o '[0-9]*')
echo "📊 Total observations: $COUNT"

if [ "$COUNT" -gt 0 ]; then
    echo "✅ All tests passed!"
else
    echo "⚠️  Database may be empty"
fi
