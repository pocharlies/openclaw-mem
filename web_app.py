#!/usr/bin/env python3
"""Simple web interface for openclaw-mem - displays session summaries and history."""

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
    <title>OpenClaw Memory Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; color: #333; line-height: 1.6; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        header { background: #2c3e50; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
        h1 { margin: 0; font-size: 24px; }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }
        .stat-card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .stat-card h3 { margin: 0 0 10px 0; font-size: 14px; color: #666; text-transform: uppercase; }
        .stat-card .number { font-size: 32px; font-weight: bold; color: #2c3e50; }
        .search-box { background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .search-box input { width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 4px; font-size: 16px; }
        .filters { display: flex; gap: 10px; margin-top: 10px; flex-wrap: wrap; }
        .filters select { padding: 8px 12px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px; }
        .history-list { list-style: none; padding: 0; }
        .history-item { background: white; padding: 20px; border-radius: 8px; margin-bottom: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); cursor: pointer; transition: transform 0.2s; }
        .history-item:hover { transform: translateY(-2px); }
        .history-item h3 { margin: 0 0 10px 0; font-size: 18px; color: #2c3e50; }
        .history-meta { display: flex; gap: 15px; font-size: 12px; color: #666; margin-bottom: 15px; flex-wrap: wrap; }
        .history-meta span { background: #f0f0f0; padding: 4px 8px; border-radius: 4px; }
        .history-content { white-space: pre-wrap; background: #f9f9f9; padding: 15px; border-radius: 4px; font-size: 14px; }
        .badge { display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; margin-right: 5px; }
        .badge-observation { background: #e3f2fd; color: #1976d2; }
        .badge-rule { background: #fff3e0; color: #e65100; }
        .badge-decision { background: #e8f5e9; color: #388e3c; }
        .badge-lesson { background: #fce4ec; color: #880e4f; }
        .badge-contact { background: #f3e5f5; color: #7b1fa2; }
        .badge-event { background: #eceff1; color: #455a64; }
        .no-results { text-align: center; padding: 40px; color: #666; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🧠 OpenClaw Memory Dashboard</h1>
            <p style="margin-top: 10px; opacity: 0.8;">Historial completo de sesiones y memorias</p>
        </header>

        <div class="stats">
            <div class="stat-card">
                <h3>Total Observaciones</h3>
                <div class="number">{{ stats.total_observations }}</div>
            </div>
            <div class="stat-card">
                <h3>Resúmenes Sesiones</h3>
                <div class="number">{{ stats.session_summaries }}</div>
            </div>
            <div class="stat-card">
                <h3>Desde {{ stats.earliest or 'N/A' }}</h3>
                <div class="number">{{ stats.latest or 'N/A' }}</div>
            </div>
        </div>

        <div class="search-box">
            <input type="text" id="search-input" placeholder="🔍 Buscar en todas las memorias...">
            <div class="filters">
                <select id="type-filter">
                    <option value="">Todos los tipos</option>
                    <option value="observation">Observación</option>
                    <option value="rule">Regla</option>
                    <option value="decision">Decisión</option>
                    <option value="lesson">Lección</option>
                    <option value="contact">Contacto</option>
                    <option value="event">Evento</option>
                </select>
            </div>
        </div>

        <ul class="history-list" id="history-list">
            {% for summary in summaries %}
            <li class="history-item" onclick="showDetails({{ summary.id }})">
                <h3>{{ summary.session_id[:50] }}...</h3>
                <div class="history-meta">
                    <span class="badge badge-{{ summary.agent_id or 'observation' }}">{{ summary.agent_id or 'Manual' }}</span>
                    <span>{{ summary.started_at or 'N/A' }}</span>
                    <span>{{ summary.ended_at or 'N/A' }}</span>
                </div>
                <div class="history-content">
                    <strong>Resumen:</strong><br>
                    {{ summary.summary[:500] }}{% if summary.summary|length > 500 %}...{% endif %}
                </div>
            </li>
            {% endfor %}
        </ul>
    </div>

    <script>
        document.getElementById('search-input').addEventListener('input', function(e) {
            const query = e.target.value.toLowerCase();
            document.querySelectorAll('.history-item').forEach(item => {
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
    """Main dashboard showing session summaries."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # Get stats
    stats = conn.execute("""
        SELECT 
            COUNT(*) as total_observations,
            (SELECT COUNT(*) FROM session_summaries) as session_summaries,
            MIN(created_at) as earliest,
            MAX(created_at) as latest
        FROM observations
        WHERE is_active = 1
    """).fetchone()
    
    # Get session summaries (last 50)
    summaries = conn.execute("""
        SELECT id, session_id, agent_id, channel, peer, summary, 
               started_at, ended_at, created_at
        FROM session_summaries
        ORDER BY created_at DESC
        LIMIT 50
    """).fetchall()
    
    conn.close()
    
    return render_template_string(HTML_TEMPLATE, 
                                   stats=dict(stats),
                                   summaries=[dict(s) for s in summaries])

@app.route('/api/stats')
def api_stats():
    """API endpoint for stats."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    stats = conn.execute("""
        SELECT 
            COUNT(*) as total_observations,
            (SELECT COUNT(*) FROM session_summaries) as session_summaries,
            MIN(created_at) as earliest,
            MAX(created_at) as latest
        FROM observations
        WHERE is_active = 1
    """).fetchone()
    
    conn.close()
    return jsonify(dict(stats))

@app.route('/api/session-summaries')
def api_summaries():
    """API endpoint for session summaries."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    summaries = conn.execute("""
        SELECT id, session_id, agent_id, channel, peer, summary, 
               started_at, ended_at, created_at
        FROM session_summaries
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """, (per_page, (page-1)*per_page)).fetchall()
    
    conn.close()
    return jsonify([dict(s) for s in summaries])

if __name__ == '__main__':
    print("🚀 OpenClaw Memory Dashboard starting...")
    print("📍 URL: http://localhost:5000")
    print("🔒 Local access only")
    app.run(host='127.0.0.1', port=5000, debug=False)
