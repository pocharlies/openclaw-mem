#!/usr/bin/env python3
"""Web interface to view full conversation history from OpenClaw sessions."""

import sqlite3
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)

DB_PATH = "/Users/usuario/.openclaw-mem/memory.db"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Conversaciones - OpenClaw Memory</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; color: #333; line-height: 1.6; }
        .container { max-width: 1000px; margin: 0 auto; padding: 20px; }
        header { background: #3498db; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
        h1 { margin: 0; font-size: 24px; }
        .search-box { background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .search-box input { width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 4px; font-size: 16px; }
        .filters { display: flex; gap: 10px; margin-top: 10px; flex-wrap: wrap; }
        .filters select { padding: 8px 12px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px; }
        .conversation-list { list-style: none; padding: 0; }
        .conversation-item { background: white; padding: 20px; border-radius: 8px; margin-bottom: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .conversation-item h3 { margin: 0 0 10px 0; font-size: 18px; color: #2c3e50; }
        .conversation-meta { display: flex; gap: 15px; font-size: 12px; color: #666; margin-bottom: 15px; flex-wrap: wrap; }
        .conversation-meta span { background: #f0f0f0; padding: 4px 8px; border-radius: 4px; }
        .messages { margin-top: 15px; }
        .message { padding: 10px 15px; margin: 10px 0; border-radius: 4px; }
        .message.assistant { background: #e3f2fd; border-left: 4px solid #2196f3; }
        .message.user { background: #f3e5f5; border-left: 4px solid #9c27b0; }
        .message-content { white-space: pre-wrap; font-size: 14px; }
        .message-header { font-size: 11px; color: #666; margin-bottom: 5px; }
        .no-results { text-align: center; padding: 40px; color: #666; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>💬 Historial de Conversaciones</h1>
            <p style="margin-top: 10px; opacity: 0.8;">Todas las conversaciones entre tú y yo</p>
        </header>

        <div class="search-box">
            <input type="text" id="search-input" placeholder="🔍 Buscar en conversaciones...">
            <div class="filters">
                <select id="channel-filter">
                    <option value="">Todos los canales</option>
                    <option value="whatsapp">WhatsApp</option>
                    <option value="telegram">Telegram</option>
                    <option value="discord">Discord</option>
                </select>
                <select id="agent-filter">
                    <option value="">Todos los agentes</option>
                </select>
            </div>
        </div>

        <ul class="conversation-list" id="conversation-list">
            {% for msg in messages %}
            <li class="conversation-item">
                <h3>{{ msg.content[:100] }}...</h3>
                <div class="conversation-meta">
                    <span>{{ msg.channel }}</span>
                    <span>{{ msg.agent_id or 'Unknown' }}</span>
                    <span>{{ msg.created_at }}</span>
                </div>
            </li>
            {% endfor %}
        </ul>
    </div>

    <script>
        document.getElementById('search-input').addEventListener('input', function(e) {
            const query = e.target.value.toLowerCase();
            document.querySelectorAll('.conversation-item').forEach(item => {
                const text = item.textContent.toLowerCase();
                item.style.display = text.includes(query) ? 'block' : 'none';
            });
        });
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    """Show all messages from conversations."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # Get all observations (messages stored as observations)
    messages = conn.execute("""
        SELECT id, type, title, content, channel, agent_id, created_at
        FROM observations
        WHERE is_active = 1 AND type = 'observation'
        ORDER BY created_at DESC
        LIMIT 100
    """).fetchall()
    
    conn.close()
    
    return render_template_string(HTML_TEMPLATE, messages=[dict(m) for m in messages])

@app.route('/api/messages')
def api_messages():
    """API endpoint for messages."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    channel = request.args.get('channel', '')
    agent = request.args.get('agent', '')
    
    query = """
        SELECT id, type, title, content, channel, agent_id, created_at
        FROM observations
        WHERE is_active = 1
    """
    params = []
    
    if channel:
        query += " AND channel = ?"
        params.append(channel)
    if agent:
        query += " AND agent_id = ?"
        params.append(agent)
    
    query += " ORDER BY created_at DESC LIMIT 100"
    
    messages = conn.execute(query, params).fetchall()
    conn.close()
    
    return jsonify([dict(m) for m in messages])

if __name__ == '__main__':
    print("🚀 OpenClaw Conversation History starting...")
    print("📍 URL: http://localhost:5001")
    print("🔒 Local access only")
    app.run(host='127.0.0.1', port=5001, debug=False)
