#!/usr/bin/env python3
"""Enhanced web interface for openclaw-mem — modern dashboard with search, editor, and export."""

import io
import csv
import json
import sqlite3
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify, Response

app = Flask(__name__)

DB_PATH = "/Users/usuario/.openclaw-mem/memory.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


# ── API Endpoints ──────────────────────────────────────────────────────


@app.route("/api/stats")
def api_stats():
    conn = get_db()
    try:
        total = conn.execute(
            "SELECT COUNT(*) as c FROM observations WHERE is_active = 1"
        ).fetchone()["c"]

        by_type = conn.execute(
            """SELECT type, COUNT(*) as c FROM observations
               WHERE is_active = 1 GROUP BY type ORDER BY c DESC"""
        ).fetchall()

        by_source = conn.execute(
            """SELECT source, COUNT(*) as c FROM observations
               WHERE is_active = 1 GROUP BY source ORDER BY c DESC"""
        ).fetchall()

        date_range = conn.execute(
            """SELECT MIN(created_at) as earliest, MAX(created_at) as latest
               FROM observations WHERE is_active = 1"""
        ).fetchone()

        # Activity by day (last 30 days)
        daily_activity = conn.execute(
            """SELECT DATE(created_at) as day, COUNT(*) as c
               FROM observations WHERE is_active = 1
               AND created_at >= DATE('now', '-30 days')
               GROUP BY DATE(created_at) ORDER BY day"""
        ).fetchall()

        # Activity by month
        monthly_activity = conn.execute(
            """SELECT strftime('%Y-%m', created_at) as month, COUNT(*) as c
               FROM observations WHERE is_active = 1
               GROUP BY strftime('%Y-%m', created_at) ORDER BY month"""
        ).fetchall()

        summaries_count = conn.execute(
            "SELECT COUNT(*) as c FROM session_summaries"
        ).fetchone()["c"]

        # Top tags
        all_tags = conn.execute(
            "SELECT tags FROM observations WHERE is_active = 1 AND tags IS NOT NULL AND tags != ''"
        ).fetchall()
        tag_counts = {}
        for row in all_tags:
            for tag in row["tags"].split(","):
                tag = tag.strip()
                if tag:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
        top_tags = sorted(tag_counts.items(), key=lambda x: -x[1])[:20]

        return jsonify({
            "total_observations": total,
            "session_summaries": summaries_count,
            "by_type": {r["type"]: r["c"] for r in by_type},
            "by_source": {r["source"]: r["c"] for r in by_source},
            "earliest": date_range["earliest"] if date_range else None,
            "latest": date_range["latest"] if date_range else None,
            "daily_activity": [{"day": r["day"], "count": r["c"]} for r in daily_activity],
            "monthly_activity": [{"month": r["month"], "count": r["c"]} for r in monthly_activity],
            "top_tags": [{"tag": t, "count": c} for t, c in top_tags],
        })
    finally:
        conn.close()


@app.route("/api/observations")
def api_observations():
    conn = get_db()
    try:
        query = request.args.get("q", "").strip()
        obs_type = request.args.get("type", "").strip()
        source = request.args.get("source", "").strip()
        date_start = request.args.get("date_start", "").strip()
        date_end = request.args.get("date_end", "").strip()
        tags = request.args.get("tags", "").strip()
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 50, type=int)
        per_page = min(per_page, 200)
        sort = request.args.get("sort", "created_at")
        order = request.args.get("order", "desc").upper()
        if order not in ("ASC", "DESC"):
            order = "DESC"

        if query:
            # FTS search
            conditions = ["o.is_active = 1"]
            params = [query]

            if obs_type:
                conditions.append("o.type = ?")
                params.append(obs_type)
            if source:
                conditions.append("o.source = ?")
                params.append(source)
            if date_start:
                conditions.append("o.created_at >= ?")
                params.append(date_start)
            if date_end:
                conditions.append("o.created_at <= ?")
                params.append(date_end + " 23:59:59")
            if tags:
                for tag in tags.split(","):
                    tag = tag.strip()
                    if tag:
                        conditions.append("o.tags LIKE ?")
                        params.append(f"%{tag}%")

            where = " AND ".join(conditions)

            count_sql = f"""
                SELECT COUNT(*) as c
                FROM observations_fts fts
                JOIN observations o ON o.id = fts.rowid
                WHERE fts.observations_fts MATCH ? AND {where}
            """
            total = conn.execute(count_sql, params).fetchone()["c"]

            sql = f"""
                SELECT o.id, o.type, o.title, substr(o.content, 1, 300) as content_preview,
                       o.source, o.agent_id, o.channel, o.tags,
                       o.created_at, o.updated_at
                FROM observations_fts fts
                JOIN observations o ON o.id = fts.rowid
                WHERE fts.observations_fts MATCH ? AND {where}
                ORDER BY rank
                LIMIT ? OFFSET ?
            """
            params.extend([per_page, (page - 1) * per_page])
            rows = conn.execute(sql, params).fetchall()
        else:
            # Regular listing
            conditions = ["is_active = 1"]
            params = []

            if obs_type:
                conditions.append("type = ?")
                params.append(obs_type)
            if source:
                conditions.append("source = ?")
                params.append(source)
            if date_start:
                conditions.append("created_at >= ?")
                params.append(date_start)
            if date_end:
                conditions.append("created_at <= ?")
                params.append(date_end + " 23:59:59")
            if tags:
                for tag in tags.split(","):
                    tag = tag.strip()
                    if tag:
                        conditions.append("tags LIKE ?")
                        params.append(f"%{tag}%")

            where = " AND ".join(conditions)

            total = conn.execute(
                f"SELECT COUNT(*) as c FROM observations WHERE {where}", params
            ).fetchone()["c"]

            allowed_sorts = {"created_at", "updated_at", "title", "type", "id"}
            if sort not in allowed_sorts:
                sort = "created_at"

            sql = f"""
                SELECT id, type, title, substr(content, 1, 300) as content_preview,
                       source, agent_id, channel, tags,
                       created_at, updated_at
                FROM observations WHERE {where}
                ORDER BY {sort} {order}
                LIMIT ? OFFSET ?
            """
            params.extend([per_page, (page - 1) * per_page])
            rows = conn.execute(sql, params).fetchall()

        return jsonify({
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
        })
    finally:
        conn.close()


@app.route("/api/observations/<int:obs_id>")
def api_observation_detail(obs_id):
    conn = get_db()
    try:
        row = conn.execute(
            """SELECT id, type, title, content, source, source_file,
                      agent_id, channel, tags, created_at, updated_at,
                      superseded_by, is_active
               FROM observations WHERE id = ?""",
            (obs_id,),
        ).fetchone()
        if not row:
            return jsonify({"error": "Not found"}), 404

        result = dict(row)

        # Get version history
        versions = []
        current_id = obs_id
        # Check if this observation superseded another
        prev = conn.execute(
            "SELECT id, title, created_at FROM observations WHERE superseded_by = ?",
            (obs_id,),
        ).fetchone()
        if prev:
            versions.append({"id": prev["id"], "title": prev["title"], "created_at": prev["created_at"], "status": "superseded"})

        if row["superseded_by"]:
            newer = conn.execute(
                "SELECT id, title, created_at FROM observations WHERE id = ?",
                (row["superseded_by"],),
            ).fetchone()
            if newer:
                versions.append({"id": newer["id"], "title": newer["title"], "created_at": newer["created_at"], "status": "current"})

        result["versions"] = versions

        # Get timeline context
        timeline = []
        before_rows = conn.execute(
            """SELECT id, type, title, created_at FROM observations
               WHERE is_active = 1 AND created_at < ? AND id != ?
               ORDER BY created_at DESC LIMIT 3""",
            (row["created_at"], obs_id),
        ).fetchall()
        after_rows = conn.execute(
            """SELECT id, type, title, created_at FROM observations
               WHERE is_active = 1 AND created_at > ? AND id != ?
               ORDER BY created_at ASC LIMIT 3""",
            (row["created_at"], obs_id),
        ).fetchall()
        timeline = [dict(r) for r in reversed(before_rows)]
        timeline.append({"id": obs_id, "type": row["type"], "title": row["title"], "created_at": row["created_at"], "current": True})
        timeline.extend(dict(r) for r in after_rows)
        result["timeline"] = timeline

        return jsonify(result)
    finally:
        conn.close()


@app.route("/api/observations/<int:obs_id>", methods=["PUT"])
def api_observation_update(obs_id):
    conn = get_db()
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        row = conn.execute("SELECT * FROM observations WHERE id = ?", (obs_id,)).fetchone()
        if not row:
            return jsonify({"error": "Not found"}), 404

        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        content = data.get("content")
        title = data.get("title")
        tags = data.get("tags")
        obs_type = data.get("type")

        # If content changed, create new version
        if content is not None and content != row["content"]:
            cur = conn.execute(
                """INSERT INTO observations
                   (type, title, content, source, source_file, agent_id, channel, tags, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    obs_type or row["type"],
                    title or row["title"],
                    content,
                    row["source"],
                    row["source_file"],
                    row["agent_id"],
                    row["channel"],
                    tags if tags is not None else row["tags"],
                    now,
                    now,
                ),
            )
            new_id = cur.lastrowid
            conn.execute(
                "UPDATE observations SET superseded_by = ?, is_active = 0, updated_at = ? WHERE id = ?",
                (new_id, now, obs_id),
            )
            conn.commit()
            return jsonify({"id": new_id, "message": "New version created", "superseded": obs_id})
        else:
            # In-place update
            updates = []
            params = []
            if title is not None:
                updates.append("title = ?")
                params.append(title)
            if tags is not None:
                updates.append("tags = ?")
                params.append(tags)
            if obs_type is not None:
                updates.append("type = ?")
                params.append(obs_type)
            if updates:
                updates.append("updated_at = ?")
                params.append(now)
                params.append(obs_id)
                conn.execute(
                    f"UPDATE observations SET {', '.join(updates)} WHERE id = ?",
                    params,
                )
                conn.commit()
            return jsonify({"id": obs_id, "message": "Updated"})
    finally:
        conn.close()


@app.route("/api/observations", methods=["POST"])
def api_observation_create():
    conn = get_db()
    try:
        data = request.get_json()
        if not data or not data.get("title") or not data.get("content"):
            return jsonify({"error": "title and content are required"}), 400

        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        cur = conn.execute(
            """INSERT INTO observations
               (type, title, content, source, tags, created_at, updated_at)
               VALUES (?, ?, ?, 'manual', ?, ?, ?)""",
            (
                data.get("type", "observation"),
                data["title"],
                data["content"],
                data.get("tags", ""),
                now,
                now,
            ),
        )
        conn.commit()
        return jsonify({"id": cur.lastrowid, "message": "Created"}), 201
    finally:
        conn.close()


@app.route("/api/observations/<int:obs_id>", methods=["DELETE"])
def api_observation_delete(obs_id):
    conn = get_db()
    try:
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE observations SET is_active = 0, updated_at = ? WHERE id = ?",
            (now, obs_id),
        )
        conn.commit()
        return jsonify({"message": "Soft-deleted"})
    finally:
        conn.close()


@app.route("/api/export")
def api_export():
    fmt = request.args.get("format", "json")
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT id, type, title, content, source, source_file,
                      agent_id, channel, tags, created_at, updated_at
               FROM observations WHERE is_active = 1
               ORDER BY created_at DESC"""
        ).fetchall()
        data = [dict(r) for r in rows]

        if fmt == "csv":
            output = io.StringIO()
            if data:
                writer = csv.DictWriter(output, fieldnames=data[0].keys())
                writer.writeheader()
                writer.writerows(data)
            return Response(
                output.getvalue(),
                mimetype="text/csv",
                headers={"Content-Disposition": "attachment; filename=openclaw-mem-export.csv"},
            )
        else:
            return Response(
                json.dumps(data, indent=2, ensure_ascii=False),
                mimetype="application/json",
                headers={"Content-Disposition": "attachment; filename=openclaw-mem-export.json"},
            )
    finally:
        conn.close()


@app.route("/api/import", methods=["POST"])
def api_import():
    conn = get_db()
    try:
        data = request.get_json()
        if not data or not isinstance(data, list):
            return jsonify({"error": "Expected a JSON array of observations"}), 400

        imported = 0
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        for item in data:
            if not item.get("title") or not item.get("content"):
                continue
            conn.execute(
                """INSERT INTO observations
                   (type, title, content, source, agent_id, channel, tags, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item.get("type", "observation"),
                    item["title"],
                    item["content"],
                    item.get("source", "import"),
                    item.get("agent_id"),
                    item.get("channel"),
                    item.get("tags", ""),
                    item.get("created_at", now),
                    now,
                ),
            )
            imported += 1
        conn.commit()
        return jsonify({"imported": imported, "message": f"{imported} observations imported"})
    finally:
        conn.close()


@app.route("/api/session-summaries")
def api_summaries():
    conn = get_db()
    try:
        page = request.args.get("page", 1, type=int)
        per_page = 20
        summaries = conn.execute(
            """SELECT id, session_id, agent_id, channel, peer, summary,
                      key_decisions, key_actions, started_at, ended_at, created_at
               FROM session_summaries
               ORDER BY created_at DESC
               LIMIT ? OFFSET ?""",
            (per_page, (page - 1) * per_page),
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) as c FROM session_summaries").fetchone()["c"]
        return jsonify({
            "items": [dict(s) for s in summaries],
            "total": total,
            "page": page,
            "pages": (total + per_page - 1) // per_page,
        })
    finally:
        conn.close()


# ── Frontend ───────────────────────────────────────────────────────────


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OpenClaw Memory</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
    <style>
        :root {
            --bg: #0f0f13;
            --bg-card: #1a1a24;
            --bg-card-hover: #22222f;
            --bg-input: #14141d;
            --border: #2a2a3a;
            --border-focus: #6b5ce7;
            --text: #e8e8f0;
            --text-dim: #8888a0;
            --text-muted: #555570;
            --accent: #6b5ce7;
            --accent-light: #8b7df0;
            --accent-bg: rgba(107,92,231,0.12);
            --green: #34d399;
            --green-bg: rgba(52,211,153,0.12);
            --orange: #f59e0b;
            --orange-bg: rgba(245,158,11,0.12);
            --red: #ef4444;
            --red-bg: rgba(239,68,68,0.12);
            --blue: #3b82f6;
            --blue-bg: rgba(59,130,246,0.12);
            --pink: #ec4899;
            --pink-bg: rgba(236,72,153,0.12);
            --cyan: #06b6d4;
            --cyan-bg: rgba(6,182,212,0.12);
            --yellow: #eab308;
            --yellow-bg: rgba(234,179,8,0.12);
            --radius: 12px;
            --radius-sm: 8px;
            --shadow: 0 4px 24px rgba(0,0,0,0.3);
            --transition: 0.2s ease;
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Inter', sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
            min-height: 100vh;
        }

        /* ── Layout ── */
        .app { display: flex; min-height: 100vh; }

        .sidebar {
            width: 240px;
            background: var(--bg-card);
            border-right: 1px solid var(--border);
            padding: 24px 16px;
            position: fixed;
            top: 0; left: 0; bottom: 0;
            overflow-y: auto;
            z-index: 100;
            transition: transform var(--transition);
        }

        .sidebar-brand {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 0 8px 24px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 24px;
        }

        .sidebar-brand .logo {
            width: 32px; height: 32px;
            background: var(--accent);
            border-radius: var(--radius-sm);
            display: flex; align-items: center; justify-content: center;
            font-size: 18px;
        }

        .sidebar-brand span {
            font-weight: 700;
            font-size: 16px;
            letter-spacing: -0.3px;
        }

        .nav-section { margin-bottom: 24px; }
        .nav-section-title {
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-muted);
            padding: 0 12px;
            margin-bottom: 8px;
        }

        .nav-item {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 10px 12px;
            border-radius: var(--radius-sm);
            color: var(--text-dim);
            cursor: pointer;
            transition: all var(--transition);
            font-size: 14px;
            font-weight: 500;
            border: none;
            background: none;
            width: 100%;
            text-align: left;
        }

        .nav-item:hover { background: var(--bg-card-hover); color: var(--text); }
        .nav-item.active { background: var(--accent-bg); color: var(--accent-light); }
        .nav-item svg { width: 18px; height: 18px; flex-shrink: 0; }

        .main {
            margin-left: 240px;
            flex: 1;
            padding: 32px;
            max-width: calc(100% - 240px);
        }

        /* ── Cards ── */
        .card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 24px;
            margin-bottom: 20px;
        }

        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }

        .card-title {
            font-size: 16px;
            font-weight: 600;
            color: var(--text);
        }

        /* ── Stats Grid ── */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }

        .stat-card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 20px;
            transition: border-color var(--transition);
        }

        .stat-card:hover { border-color: var(--accent); }

        .stat-label {
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-muted);
            margin-bottom: 8px;
        }

        .stat-value {
            font-size: 28px;
            font-weight: 700;
            color: var(--text);
            line-height: 1;
        }

        .stat-sub {
            font-size: 12px;
            color: var(--text-dim);
            margin-top: 6px;
        }

        /* ── Charts ── */
        .charts-grid {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 20px;
            margin-bottom: 24px;
        }

        .chart-container {
            position: relative;
            height: 260px;
        }

        /* ── Type Badges ── */
        .badge {
            display: inline-flex;
            align-items: center;
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.3px;
            text-transform: uppercase;
        }

        .badge-observation { background: var(--blue-bg); color: var(--blue); }
        .badge-rule { background: var(--orange-bg); color: var(--orange); }
        .badge-decision { background: var(--green-bg); color: var(--green); }
        .badge-lesson { background: var(--pink-bg); color: var(--pink); }
        .badge-contact { background: var(--cyan-bg); color: var(--cyan); }
        .badge-event { background: var(--yellow-bg); color: var(--yellow); }
        .badge-state { background: var(--red-bg); color: var(--red); }

        /* ── Search & Filters ── */
        .search-bar {
            display: flex;
            gap: 12px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }

        .search-input-wrap {
            flex: 1;
            min-width: 300px;
            position: relative;
        }

        .search-input-wrap svg {
            position: absolute;
            left: 14px;
            top: 50%;
            transform: translateY(-50%);
            width: 16px; height: 16px;
            color: var(--text-muted);
        }

        input, select, textarea {
            background: var(--bg-input);
            border: 1px solid var(--border);
            color: var(--text);
            border-radius: var(--radius-sm);
            padding: 10px 14px;
            font-size: 14px;
            font-family: inherit;
            transition: border-color var(--transition);
            outline: none;
        }

        input:focus, select:focus, textarea:focus {
            border-color: var(--border-focus);
        }

        .search-input-wrap input {
            width: 100%;
            padding-left: 38px;
        }

        .filter-row {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-bottom: 16px;
        }

        .filter-row select, .filter-row input {
            min-width: 140px;
        }

        /* ── Buttons ── */
        .btn {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 9px 16px;
            border-radius: var(--radius-sm);
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            border: 1px solid var(--border);
            background: var(--bg-card);
            color: var(--text);
            transition: all var(--transition);
            white-space: nowrap;
        }

        .btn:hover { background: var(--bg-card-hover); border-color: var(--text-muted); }
        .btn svg { width: 14px; height: 14px; }

        .btn-primary {
            background: var(--accent);
            border-color: var(--accent);
            color: white;
        }
        .btn-primary:hover { background: var(--accent-light); border-color: var(--accent-light); }

        .btn-danger {
            color: var(--red);
            border-color: var(--red);
        }
        .btn-danger:hover { background: var(--red-bg); }

        .btn-sm { padding: 5px 10px; font-size: 12px; }
        .btn-group { display: flex; gap: 8px; }

        /* ── Table ── */
        .obs-table { width: 100%; border-collapse: collapse; }

        .obs-table th {
            text-align: left;
            padding: 10px 14px;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-muted);
            border-bottom: 1px solid var(--border);
            font-weight: 600;
        }

        .obs-table td {
            padding: 12px 14px;
            border-bottom: 1px solid var(--border);
            font-size: 14px;
            vertical-align: top;
        }

        .obs-table tr {
            cursor: pointer;
            transition: background var(--transition);
        }

        .obs-table tbody tr:hover { background: var(--bg-card-hover); }

        .obs-title {
            font-weight: 600;
            color: var(--text);
            display: block;
            margin-bottom: 4px;
        }

        .obs-preview {
            color: var(--text-dim);
            font-size: 13px;
            line-height: 1.4;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }

        .obs-date {
            font-size: 12px;
            color: var(--text-muted);
            white-space: nowrap;
        }

        .obs-tags {
            display: flex;
            gap: 4px;
            flex-wrap: wrap;
            margin-top: 4px;
        }

        .tag {
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 12px;
            background: var(--bg-card-hover);
            color: var(--text-dim);
        }

        /* ── Pagination ── */
        .pagination {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-top: 16px;
            border-top: 1px solid var(--border);
            margin-top: 16px;
        }

        .pagination-info { font-size: 13px; color: var(--text-dim); }

        .pagination-buttons {
            display: flex;
            gap: 4px;
        }

        .page-btn {
            padding: 6px 12px;
            border-radius: 6px;
            border: 1px solid var(--border);
            background: var(--bg-card);
            color: var(--text-dim);
            font-size: 13px;
            cursor: pointer;
            transition: all var(--transition);
        }

        .page-btn:hover { background: var(--bg-card-hover); color: var(--text); }
        .page-btn.active { background: var(--accent); border-color: var(--accent); color: white; }
        .page-btn:disabled { opacity: 0.3; cursor: not-allowed; }

        /* ── Detail Panel ── */
        .detail-overlay {
            display: none;
            position: fixed;
            top: 0; right: 0; bottom: 0;
            width: calc(100% - 240px);
            background: rgba(0,0,0,0.5);
            z-index: 200;
            backdrop-filter: blur(4px);
        }

        .detail-overlay.open { display: block; }

        .detail-panel {
            position: fixed;
            top: 0; right: 0; bottom: 0;
            width: min(720px, calc(100% - 240px));
            background: var(--bg);
            border-left: 1px solid var(--border);
            z-index: 201;
            transform: translateX(100%);
            transition: transform 0.3s ease;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
        }

        .detail-panel.open { transform: translateX(0); }

        .detail-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px 24px;
            border-bottom: 1px solid var(--border);
            flex-shrink: 0;
        }

        .detail-body { padding: 24px; flex: 1; overflow-y: auto; }

        .detail-field { margin-bottom: 20px; }

        .detail-label {
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-muted);
            margin-bottom: 6px;
            font-weight: 600;
        }

        .detail-value {
            font-size: 14px;
            color: var(--text);
        }

        .detail-content {
            background: var(--bg-input);
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            padding: 16px;
            white-space: pre-wrap;
            font-size: 14px;
            line-height: 1.7;
            min-height: 200px;
            color: var(--text);
        }

        textarea.detail-editor {
            width: 100%;
            min-height: 300px;
            resize: vertical;
            line-height: 1.7;
        }

        .detail-meta-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
        }

        .timeline-item {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 8px 12px;
            border-radius: var(--radius-sm);
            font-size: 13px;
            transition: background var(--transition);
            cursor: pointer;
        }

        .timeline-item:hover { background: var(--bg-card-hover); }
        .timeline-item.current { background: var(--accent-bg); border-left: 3px solid var(--accent); }

        .timeline-dot {
            width: 8px; height: 8px;
            border-radius: 50%;
            background: var(--text-muted);
            flex-shrink: 0;
        }

        .timeline-item.current .timeline-dot { background: var(--accent); }

        /* ── Tags Cloud ── */
        .tags-cloud {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }

        .tag-cloud-item {
            padding: 6px 14px;
            border-radius: 20px;
            background: var(--bg-card-hover);
            border: 1px solid var(--border);
            font-size: 13px;
            color: var(--text-dim);
            cursor: pointer;
            transition: all var(--transition);
        }

        .tag-cloud-item:hover {
            background: var(--accent-bg);
            border-color: var(--accent);
            color: var(--accent-light);
        }

        .tag-count {
            font-size: 11px;
            color: var(--text-muted);
            margin-left: 4px;
        }

        /* ── Import/Export ── */
        .import-drop-zone {
            border: 2px dashed var(--border);
            border-radius: var(--radius);
            padding: 48px;
            text-align: center;
            color: var(--text-muted);
            cursor: pointer;
            transition: all var(--transition);
        }

        .import-drop-zone:hover, .import-drop-zone.dragover {
            border-color: var(--accent);
            background: var(--accent-bg);
            color: var(--accent-light);
        }

        /* ── Modal ── */
        .modal-overlay {
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,0.6);
            z-index: 300;
            backdrop-filter: blur(4px);
            justify-content: center;
            align-items: center;
        }

        .modal-overlay.open { display: flex; }

        .modal {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 24px;
            width: min(560px, 90vw);
            max-height: 80vh;
            overflow-y: auto;
        }

        .modal h3 { margin-bottom: 20px; }

        .form-group { margin-bottom: 16px; }
        .form-group label {
            display: block;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-muted);
            margin-bottom: 6px;
            font-weight: 600;
        }

        .form-group input, .form-group select, .form-group textarea {
            width: 100%;
        }

        .form-group textarea { min-height: 120px; resize: vertical; }

        /* ── Toast ── */
        .toast {
            position: fixed;
            bottom: 24px;
            right: 24px;
            padding: 12px 20px;
            border-radius: var(--radius-sm);
            font-size: 14px;
            font-weight: 500;
            z-index: 400;
            opacity: 0;
            transform: translateY(10px);
            transition: all 0.3s ease;
            pointer-events: none;
        }

        .toast.show { opacity: 1; transform: translateY(0); pointer-events: auto; }
        .toast.success { background: var(--green); color: #000; }
        .toast.error { background: var(--red); color: #fff; }

        /* ── Responsive ── */
        .mobile-toggle {
            display: none;
            position: fixed;
            top: 12px; left: 12px;
            z-index: 150;
            padding: 8px;
            border-radius: var(--radius-sm);
            background: var(--bg-card);
            border: 1px solid var(--border);
            color: var(--text);
            cursor: pointer;
        }

        @media (max-width: 768px) {
            .mobile-toggle { display: block; }
            .sidebar { transform: translateX(-100%); }
            .sidebar.open { transform: translateX(0); }
            .main { margin-left: 0; max-width: 100%; padding: 16px; padding-top: 56px; }
            .detail-overlay, .detail-panel { width: 100%; }
            .charts-grid { grid-template-columns: 1fr; }
            .search-input-wrap { min-width: 100%; }
            .detail-meta-grid { grid-template-columns: 1fr; }
            .stats-grid { grid-template-columns: repeat(2, 1fr); }
        }

        /* ── Scrollbar ── */
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }

        /* ── Loading ── */
        .skeleton {
            background: linear-gradient(90deg, var(--bg-card) 25%, var(--bg-card-hover) 50%, var(--bg-card) 75%);
            background-size: 200% 100%;
            animation: shimmer 1.5s infinite;
            border-radius: var(--radius-sm);
        }

        @keyframes shimmer {
            0% { background-position: 200% 0; }
            100% { background-position: -200% 0; }
        }

        .spinner {
            display: inline-block;
            width: 16px; height: 16px;
            border: 2px solid var(--border);
            border-top-color: var(--accent);
            border-radius: 50%;
            animation: spin 0.6s linear infinite;
        }

        @keyframes spin { to { transform: rotate(360deg); } }

        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: var(--text-muted);
        }

        .empty-state svg {
            width: 48px; height: 48px;
            margin-bottom: 16px;
            opacity: 0.4;
        }

        /* ── Page header ── */
        .page-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
        }

        .page-title { font-size: 22px; font-weight: 700; }

        /* ── Hide sections ── */
        .view { display: none; }
        .view.active { display: block; }
    </style>
</head>
<body>
    <!-- Mobile Toggle -->
    <button class="mobile-toggle" onclick="toggleSidebar()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12h18M3 6h18M3 18h18"/></svg>
    </button>

    <div class="app">
        <!-- Sidebar -->
        <nav class="sidebar" id="sidebar">
            <div class="sidebar-brand">
                <div class="logo">O</div>
                <span>OpenClaw Mem</span>
            </div>

            <div class="nav-section">
                <div class="nav-section-title">General</div>
                <button class="nav-item active" onclick="showView('dashboard')">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
                    Dashboard
                </button>
                <button class="nav-item" onclick="showView('memories')">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
                    Memorias
                </button>
                <button class="nav-item" onclick="showView('sessions')">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
                    Sesiones
                </button>
            </div>

            <div class="nav-section">
                <div class="nav-section-title">Herramientas</div>
                <button class="nav-item" onclick="showView('export')">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                    Exportar / Importar
                </button>
                <button class="nav-item" onclick="openCreateModal()">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                    Nueva Memoria
                </button>
            </div>

            <div style="margin-top:auto; padding-top:24px; border-top:1px solid var(--border);">
                <div style="font-size:11px; color:var(--text-muted); padding:0 12px;">
                    openclaw-mem v0.1.0
                </div>
            </div>
        </nav>

        <!-- Main Content -->
        <div class="main">
            <!-- DASHBOARD VIEW -->
            <div class="view active" id="view-dashboard">
                <div class="page-header">
                    <h1 class="page-title">Dashboard</h1>
                    <div class="btn-group">
                        <button class="btn btn-sm" onclick="loadStats()">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/></svg>
                            Actualizar
                        </button>
                    </div>
                </div>

                <div class="stats-grid" id="stats-grid">
                    <div class="stat-card"><div class="stat-label">Total Memorias</div><div class="stat-value" id="stat-total">-</div><div class="stat-sub" id="stat-range"></div></div>
                    <div class="stat-card"><div class="stat-label">Sesiones</div><div class="stat-value" id="stat-sessions">-</div></div>
                    <div class="stat-card"><div class="stat-label">Tipos</div><div class="stat-value" id="stat-types">-</div></div>
                    <div class="stat-card"><div class="stat-label">Tags Distintos</div><div class="stat-value" id="stat-tags">-</div></div>
                </div>

                <div class="charts-grid">
                    <div class="card">
                        <div class="card-header"><div class="card-title">Actividad (30 dias)</div></div>
                        <div class="chart-container"><canvas id="chart-activity"></canvas></div>
                    </div>
                    <div class="card">
                        <div class="card-header"><div class="card-title">Por Tipo</div></div>
                        <div class="chart-container"><canvas id="chart-types"></canvas></div>
                    </div>
                </div>

                <div class="charts-grid">
                    <div class="card">
                        <div class="card-header"><div class="card-title">Actividad Mensual</div></div>
                        <div class="chart-container"><canvas id="chart-monthly"></canvas></div>
                    </div>
                    <div class="card">
                        <div class="card-header"><div class="card-title">Tags Populares</div></div>
                        <div id="tags-cloud" class="tags-cloud" style="padding-top:8px;"></div>
                    </div>
                </div>
            </div>

            <!-- MEMORIES VIEW -->
            <div class="view" id="view-memories">
                <div class="page-header">
                    <h1 class="page-title">Memorias</h1>
                    <button class="btn btn-primary" onclick="openCreateModal()">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                        Nueva
                    </button>
                </div>

                <div class="search-bar">
                    <div class="search-input-wrap">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                        <input type="text" id="search-q" placeholder="Buscar memorias... (soporta AND, OR, NOT)" onkeydown="if(event.key==='Enter')searchObservations()">
                    </div>
                    <button class="btn btn-primary" onclick="searchObservations()">Buscar</button>
                </div>

                <div class="filter-row">
                    <select id="filter-type" onchange="searchObservations()">
                        <option value="">Todos los tipos</option>
                        <option value="observation">Observation</option>
                        <option value="rule">Rule</option>
                        <option value="decision">Decision</option>
                        <option value="lesson">Lesson</option>
                        <option value="contact">Contact</option>
                        <option value="event">Event</option>
                        <option value="state">State</option>
                    </select>
                    <select id="filter-source" onchange="searchObservations()">
                        <option value="">Todas las fuentes</option>
                        <option value="manual">Manual</option>
                        <option value="daily-log">Daily Log</option>
                        <option value="session">Session</option>
                        <option value="import">Import</option>
                        <option value="synthesis">Synthesis</option>
                    </select>
                    <input type="date" id="filter-date-start" onchange="searchObservations()">
                    <input type="date" id="filter-date-end" onchange="searchObservations()">
                    <input type="text" id="filter-tags" placeholder="Tags (comma-sep)" style="width:160px" onkeydown="if(event.key==='Enter')searchObservations()">
                    <button class="btn btn-sm" onclick="clearFilters()">Limpiar</button>
                </div>

                <div class="card" style="padding:0; overflow:hidden;">
                    <table class="obs-table">
                        <thead>
                            <tr>
                                <th style="width:50px">ID</th>
                                <th>Titulo</th>
                                <th style="width:100px">Tipo</th>
                                <th style="width:90px">Fuente</th>
                                <th style="width:140px">Fecha</th>
                            </tr>
                        </thead>
                        <tbody id="obs-tbody"></tbody>
                    </table>
                </div>

                <div class="pagination" id="pagination"></div>
            </div>

            <!-- SESSIONS VIEW -->
            <div class="view" id="view-sessions">
                <div class="page-header">
                    <h1 class="page-title">Sesiones</h1>
                </div>
                <div id="sessions-list"></div>
            </div>

            <!-- EXPORT VIEW -->
            <div class="view" id="view-export">
                <div class="page-header">
                    <h1 class="page-title">Exportar / Importar</h1>
                </div>

                <div class="card">
                    <div class="card-header"><div class="card-title">Exportar Memorias</div></div>
                    <p style="color:var(--text-dim); margin-bottom:16px;">Descarga todas las memorias activas en formato JSON o CSV.</p>
                    <div class="btn-group">
                        <a class="btn btn-primary" id="export-json-link" href="/api/export?format=json" download>
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                            Exportar JSON
                        </a>
                        <a class="btn" id="export-csv-link" href="/api/export?format=csv" download>
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                            Exportar CSV
                        </a>
                    </div>
                </div>

                <div class="card">
                    <div class="card-header"><div class="card-title">Importar Memorias</div></div>
                    <p style="color:var(--text-dim); margin-bottom:16px;">Importa un archivo JSON con un array de observaciones. Cada objeto debe tener al menos <code style="background:var(--bg-input);padding:2px 6px;border-radius:4px;">title</code> y <code style="background:var(--bg-input);padding:2px 6px;border-radius:4px;">content</code>.</p>

                    <div class="import-drop-zone" id="drop-zone" onclick="document.getElementById('import-file').click()">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:40px;height:40px;margin-bottom:12px;display:inline-block;"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                        <div style="font-size:16px;font-weight:600;margin-bottom:4px;">Arrastra un archivo JSON aqui</div>
                        <div>o haz click para seleccionar</div>
                        <input type="file" id="import-file" accept=".json" style="display:none" onchange="handleImportFile(event)">
                    </div>
                    <div id="import-result" style="margin-top:16px;"></div>
                </div>
            </div>
        </div>
    </div>

    <!-- Detail Panel -->
    <div class="detail-overlay" id="detail-overlay" onclick="closeDetail()"></div>
    <div class="detail-panel" id="detail-panel">
        <div class="detail-header">
            <div style="display:flex;align-items:center;gap:12px;">
                <button class="btn btn-sm" onclick="closeDetail()">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </button>
                <span class="card-title" id="detail-title-display">-</span>
            </div>
            <div class="btn-group">
                <button class="btn btn-sm" id="btn-edit" onclick="toggleEdit()">Editar</button>
                <button class="btn btn-sm btn-danger" id="btn-delete" onclick="deleteObservation()">Eliminar</button>
            </div>
        </div>
        <div class="detail-body" id="detail-body">
            <!-- Filled dynamically -->
        </div>
    </div>

    <!-- Create Modal -->
    <div class="modal-overlay" id="create-modal">
        <div class="modal">
            <h3>Nueva Memoria</h3>
            <div class="form-group">
                <label>Titulo</label>
                <input type="text" id="new-title" placeholder="Titulo corto (~10 palabras)">
            </div>
            <div class="form-group">
                <label>Tipo</label>
                <select id="new-type">
                    <option value="observation">Observation</option>
                    <option value="rule">Rule</option>
                    <option value="decision">Decision</option>
                    <option value="lesson">Lesson</option>
                    <option value="contact">Contact</option>
                    <option value="event">Event</option>
                    <option value="state">State</option>
                </select>
            </div>
            <div class="form-group">
                <label>Contenido</label>
                <textarea id="new-content" placeholder="Contenido completo de la memoria..."></textarea>
            </div>
            <div class="form-group">
                <label>Tags (separados por coma)</label>
                <input type="text" id="new-tags" placeholder="tag1, tag2, tag3">
            </div>
            <div class="btn-group" style="justify-content:flex-end;margin-top:20px;">
                <button class="btn" onclick="closeCreateModal()">Cancelar</button>
                <button class="btn btn-primary" onclick="createObservation()">Crear</button>
            </div>
        </div>
    </div>

    <!-- Toast -->
    <div class="toast" id="toast"></div>

    <script>
    // ── Base URL (works behind reverse proxy with prefix like /openclaw-mem/) ──
    const BASE_URL = window.location.pathname.replace(/\/$/, '');
    function apiUrl(path) { return BASE_URL + path; }

    // ── State ──
    let currentView = 'dashboard';
    let currentPage = 1;
    let currentDetail = null;
    let isEditing = false;
    let charts = {};

    // ── Navigation ──
    function showView(view) {
        document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
        document.getElementById('view-' + view).classList.add('active');
        document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
        event.currentTarget.classList.add('active');
        currentView = view;

        if (view === 'dashboard') loadStats();
        else if (view === 'memories') searchObservations();
        else if (view === 'sessions') loadSessions();

        // Close sidebar on mobile
        document.getElementById('sidebar').classList.remove('open');
    }

    function toggleSidebar() {
        document.getElementById('sidebar').classList.toggle('open');
    }

    // ── Toast ──
    function showToast(msg, type = 'success') {
        const t = document.getElementById('toast');
        t.textContent = msg;
        t.className = 'toast ' + type + ' show';
        setTimeout(() => t.classList.remove('show'), 3000);
    }

    // ── Dashboard ──
    async function loadStats() {
        try {
            const res = await fetch(apiUrl('/api/stats'));
            const data = await res.json();

            document.getElementById('stat-total').textContent = data.total_observations.toLocaleString();
            document.getElementById('stat-sessions').textContent = data.session_summaries.toLocaleString();
            document.getElementById('stat-types').textContent = Object.keys(data.by_type).length;
            document.getElementById('stat-tags').textContent = data.top_tags.length;

            if (data.earliest) {
                document.getElementById('stat-range').textContent =
                    data.earliest.split(' ')[0] + ' — ' + (data.latest || '').split(' ')[0];
            }

            renderCharts(data);
        } catch (e) {
            console.error('Error loading stats:', e);
        }
    }

    function renderCharts(data) {
        const typeColors = {
            observation: '#3b82f6', rule: '#f59e0b', decision: '#34d399',
            lesson: '#ec4899', contact: '#06b6d4', event: '#eab308', state: '#ef4444'
        };

        // Activity chart
        if (charts.activity) charts.activity.destroy();
        const actCtx = document.getElementById('chart-activity').getContext('2d');
        charts.activity = new Chart(actCtx, {
            type: 'bar',
            data: {
                labels: data.daily_activity.map(d => d.day.substring(5)),
                datasets: [{
                    data: data.daily_activity.map(d => d.count),
                    backgroundColor: 'rgba(107,92,231,0.5)',
                    borderColor: '#6b5ce7',
                    borderWidth: 1,
                    borderRadius: 4,
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#555570', font: { size: 10 } } },
                    y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#555570' }, beginAtZero: true }
                }
            }
        });

        // Type doughnut
        if (charts.types) charts.types.destroy();
        const typeCtx = document.getElementById('chart-types').getContext('2d');
        const typeLabels = Object.keys(data.by_type);
        charts.types = new Chart(typeCtx, {
            type: 'doughnut',
            data: {
                labels: typeLabels,
                datasets: [{
                    data: Object.values(data.by_type),
                    backgroundColor: typeLabels.map(t => typeColors[t] || '#555570'),
                    borderWidth: 0,
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                cutout: '65%',
                plugins: {
                    legend: { position: 'bottom', labels: { color: '#8888a0', padding: 12, font: { size: 11 } } }
                }
            }
        });

        // Monthly chart
        if (charts.monthly) charts.monthly.destroy();
        const monthCtx = document.getElementById('chart-monthly').getContext('2d');
        charts.monthly = new Chart(monthCtx, {
            type: 'line',
            data: {
                labels: data.monthly_activity.map(d => d.month),
                datasets: [{
                    data: data.monthly_activity.map(d => d.count),
                    borderColor: '#6b5ce7',
                    backgroundColor: 'rgba(107,92,231,0.1)',
                    fill: true,
                    tension: 0.4,
                    pointRadius: 3,
                    pointBackgroundColor: '#6b5ce7',
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#555570', font: { size: 10 } } },
                    y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#555570' }, beginAtZero: true }
                }
            }
        });

        // Tags cloud
        const tagsEl = document.getElementById('tags-cloud');
        if (data.top_tags.length === 0) {
            tagsEl.innerHTML = '<div class="empty-state" style="padding:20px;">Sin tags</div>';
        } else {
            tagsEl.innerHTML = data.top_tags.map(t =>
                `<span class="tag-cloud-item" onclick="searchByTag('${t.tag}')">${t.tag}<span class="tag-count">${t.count}</span></span>`
            ).join('');
        }
    }

    function searchByTag(tag) {
        showViewByName('memories');
        document.getElementById('filter-tags').value = tag;
        searchObservations();
    }

    function showViewByName(view) {
        document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
        document.getElementById('view-' + view).classList.add('active');
        document.querySelectorAll('.nav-item').forEach((n, i) => {
            n.classList.toggle('active', (view === 'dashboard' && i === 0) || (view === 'memories' && i === 1) || (view === 'sessions' && i === 2) || (view === 'export' && i === 3));
        });
        currentView = view;
    }

    // ── Observations List ──
    async function searchObservations(page = 1) {
        currentPage = page;
        const params = new URLSearchParams();
        const q = document.getElementById('search-q').value.trim();
        if (q) params.set('q', q);
        const t = document.getElementById('filter-type').value;
        if (t) params.set('type', t);
        const s = document.getElementById('filter-source').value;
        if (s) params.set('source', s);
        const ds = document.getElementById('filter-date-start').value;
        if (ds) params.set('date_start', ds);
        const de = document.getElementById('filter-date-end').value;
        if (de) params.set('date_end', de);
        const tags = document.getElementById('filter-tags').value.trim();
        if (tags) params.set('tags', tags);
        params.set('page', page);
        params.set('per_page', 50);

        try {
            const res = await fetch(apiUrl('/api/observations?') + params);
            const data = await res.json();
            renderObservations(data);
        } catch (e) {
            console.error('Search error:', e);
        }
    }

    function renderObservations(data) {
        const tbody = document.getElementById('obs-tbody');
        if (data.items.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5"><div class="empty-state">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                <div>Sin resultados</div></div></td></tr>`;
        } else {
            tbody.innerHTML = data.items.map(obs => {
                const tags = obs.tags ? obs.tags.split(',').map(t => t.trim()).filter(Boolean).map(t => `<span class="tag">${t}</span>`).join('') : '';
                return `<tr onclick="openDetail(${obs.id})">
                    <td class="obs-date">#${obs.id}</td>
                    <td>
                        <span class="obs-title">${esc(obs.title)}</span>
                        <span class="obs-preview">${esc(obs.content_preview || '')}</span>
                        ${tags ? '<div class="obs-tags">' + tags + '</div>' : ''}
                    </td>
                    <td><span class="badge badge-${obs.type}">${obs.type}</span></td>
                    <td class="obs-date">${obs.source || '-'}</td>
                    <td class="obs-date">${formatDate(obs.created_at)}</td>
                </tr>`;
            }).join('');
        }

        // Pagination
        const pagEl = document.getElementById('pagination');
        if (data.pages <= 1) {
            pagEl.innerHTML = `<div class="pagination-info">${data.total} memorias</div><div></div>`;
            return;
        }

        let buttons = '';
        buttons += `<button class="page-btn" ${data.page <= 1 ? 'disabled' : ''} onclick="searchObservations(${data.page - 1})">&laquo;</button>`;
        const start = Math.max(1, data.page - 2);
        const end = Math.min(data.pages, data.page + 2);
        for (let i = start; i <= end; i++) {
            buttons += `<button class="page-btn ${i === data.page ? 'active' : ''}" onclick="searchObservations(${i})">${i}</button>`;
        }
        buttons += `<button class="page-btn" ${data.page >= data.pages ? 'disabled' : ''} onclick="searchObservations(${data.page + 1})">&raquo;</button>`;

        pagEl.innerHTML = `
            <div class="pagination-info">Mostrando ${(data.page-1)*data.per_page+1}-${Math.min(data.page*data.per_page, data.total)} de ${data.total}</div>
            <div class="pagination-buttons">${buttons}</div>`;
    }

    function clearFilters() {
        document.getElementById('search-q').value = '';
        document.getElementById('filter-type').value = '';
        document.getElementById('filter-source').value = '';
        document.getElementById('filter-date-start').value = '';
        document.getElementById('filter-date-end').value = '';
        document.getElementById('filter-tags').value = '';
        searchObservations();
    }

    // ── Detail Panel ──
    async function openDetail(id) {
        try {
            const res = await fetch(apiUrl(`/api/observations/${id}`));
            if (!res.ok) { showToast('Error al cargar', 'error'); return; }
            currentDetail = await res.json();
            isEditing = false;
            renderDetail();
            document.getElementById('detail-overlay').classList.add('open');
            document.getElementById('detail-panel').classList.add('open');
        } catch (e) {
            showToast('Error de conexion', 'error');
        }
    }

    function closeDetail() {
        document.getElementById('detail-overlay').classList.remove('open');
        document.getElementById('detail-panel').classList.remove('open');
        currentDetail = null;
        isEditing = false;
    }

    function renderDetail() {
        const d = currentDetail;
        document.getElementById('detail-title-display').textContent = '#' + d.id + ' — ' + d.title;
        document.getElementById('btn-edit').textContent = isEditing ? 'Cancelar' : 'Editar';

        let html = '';

        if (isEditing) {
            html += `
                <div class="detail-field">
                    <div class="detail-label">Titulo</div>
                    <input type="text" id="edit-title" value="${esc(d.title)}" style="width:100%">
                </div>
                <div class="detail-field">
                    <div class="detail-label">Tipo</div>
                    <select id="edit-type" style="width:100%">
                        ${['observation','rule','decision','lesson','contact','event','state'].map(t =>
                            `<option value="${t}" ${d.type === t ? 'selected' : ''}>${t}</option>`
                        ).join('')}
                    </select>
                </div>
                <div class="detail-field">
                    <div class="detail-label">Contenido</div>
                    <textarea class="detail-editor" id="edit-content">${esc(d.content)}</textarea>
                </div>
                <div class="detail-field">
                    <div class="detail-label">Tags</div>
                    <input type="text" id="edit-tags" value="${esc(d.tags || '')}" style="width:100%">
                </div>
                <div class="btn-group" style="margin-top:16px;">
                    <button class="btn btn-primary" onclick="saveEdit()">Guardar</button>
                    <button class="btn" onclick="toggleEdit()">Cancelar</button>
                </div>`;
        } else {
            html += `
                <div class="detail-meta-grid">
                    <div class="detail-field">
                        <div class="detail-label">Tipo</div>
                        <span class="badge badge-${d.type}">${d.type}</span>
                    </div>
                    <div class="detail-field">
                        <div class="detail-label">Fuente</div>
                        <div class="detail-value">${d.source || '-'}</div>
                    </div>
                    <div class="detail-field">
                        <div class="detail-label">Creado</div>
                        <div class="detail-value">${formatDate(d.created_at)}</div>
                    </div>
                    <div class="detail-field">
                        <div class="detail-label">Actualizado</div>
                        <div class="detail-value">${formatDate(d.updated_at)}</div>
                    </div>
                    ${d.agent_id ? `<div class="detail-field"><div class="detail-label">Agente</div><div class="detail-value">${d.agent_id}</div></div>` : ''}
                    ${d.channel ? `<div class="detail-field"><div class="detail-label">Canal</div><div class="detail-value">${d.channel}</div></div>` : ''}
                </div>`;

            if (d.tags) {
                html += `<div class="detail-field" style="margin-top:16px;">
                    <div class="detail-label">Tags</div>
                    <div class="obs-tags">${d.tags.split(',').map(t => `<span class="tag">${t.trim()}</span>`).join('')}</div>
                </div>`;
            }

            html += `<div class="detail-field" style="margin-top:16px;">
                <div class="detail-label">Contenido</div>
                <div class="detail-content">${esc(d.content)}</div>
            </div>`;

            // Versions
            if (d.versions && d.versions.length > 0) {
                html += `<div class="detail-field" style="margin-top:16px;">
                    <div class="detail-label">Versiones</div>`;
                d.versions.forEach(v => {
                    html += `<div class="timeline-item" onclick="openDetail(${v.id})">
                        <div class="timeline-dot"></div>
                        <div><strong>#${v.id}</strong> — ${esc(v.title)} <span class="obs-date">${v.status}</span></div>
                    </div>`;
                });
                html += `</div>`;
            }

            // Timeline
            if (d.timeline && d.timeline.length > 0) {
                html += `<div class="detail-field" style="margin-top:16px;">
                    <div class="detail-label">Contexto Temporal</div>`;
                d.timeline.forEach(t => {
                    html += `<div class="timeline-item ${t.current ? 'current' : ''}" onclick="${t.current ? '' : 'openDetail(' + t.id + ')'}">
                        <div class="timeline-dot"></div>
                        <div>
                            <span class="badge badge-${t.type}" style="margin-right:8px;">${t.type}</span>
                            ${esc(t.title)}
                            <span class="obs-date" style="margin-left:8px;">${formatDate(t.created_at)}</span>
                        </div>
                    </div>`;
                });
                html += `</div>`;
            }
        }

        document.getElementById('detail-body').innerHTML = html;
    }

    function toggleEdit() {
        isEditing = !isEditing;
        renderDetail();
    }

    async function saveEdit() {
        const payload = {
            title: document.getElementById('edit-title').value,
            type: document.getElementById('edit-type').value,
            content: document.getElementById('edit-content').value,
            tags: document.getElementById('edit-tags').value,
        };

        try {
            const res = await fetch(apiUrl(`/api/observations/${currentDetail.id}`), {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await res.json();
            showToast(data.message);
            isEditing = false;
            // Reload detail
            await openDetail(data.id || currentDetail.id);
            // Refresh list
            if (currentView === 'memories') searchObservations(currentPage);
        } catch (e) {
            showToast('Error al guardar', 'error');
        }
    }

    async function deleteObservation() {
        if (!currentDetail) return;
        if (!confirm('Eliminar esta memoria? (soft-delete)')) return;

        try {
            await fetch(apiUrl(`/api/observations/${currentDetail.id}`), { method: 'DELETE' });
            showToast('Memoria eliminada');
            closeDetail();
            if (currentView === 'memories') searchObservations(currentPage);
        } catch (e) {
            showToast('Error al eliminar', 'error');
        }
    }

    // ── Create Modal ──
    function openCreateModal() {
        document.getElementById('create-modal').classList.add('open');
    }

    function closeCreateModal() {
        document.getElementById('create-modal').classList.remove('open');
    }

    async function createObservation() {
        const payload = {
            title: document.getElementById('new-title').value,
            type: document.getElementById('new-type').value,
            content: document.getElementById('new-content').value,
            tags: document.getElementById('new-tags').value,
        };

        if (!payload.title || !payload.content) {
            showToast('Titulo y contenido son requeridos', 'error');
            return;
        }

        try {
            const res = await fetch(apiUrl('/api/observations'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await res.json();
            showToast('Memoria creada: #' + data.id);
            closeCreateModal();
            document.getElementById('new-title').value = '';
            document.getElementById('new-content').value = '';
            document.getElementById('new-tags').value = '';
            if (currentView === 'memories') searchObservations();
        } catch (e) {
            showToast('Error al crear', 'error');
        }
    }

    // ── Sessions ──
    async function loadSessions(page = 1) {
        try {
            const res = await fetch(apiUrl(`/api/session-summaries?page=${page}`));
            const data = await res.json();
            const el = document.getElementById('sessions-list');

            if (data.items.length === 0) {
                el.innerHTML = '<div class="empty-state"><div>Sin sesiones registradas</div></div>';
                return;
            }

            el.innerHTML = data.items.map(s => `
                <div class="card" style="cursor:default;">
                    <div style="display:flex;justify-content:space-between;align-items:start;margin-bottom:12px;">
                        <div>
                            <div style="font-weight:600;margin-bottom:4px;">${esc((s.session_id || '').substring(0, 60))}</div>
                            <div style="display:flex;gap:8px;flex-wrap:wrap;">
                                ${s.agent_id ? `<span class="badge badge-observation">${s.agent_id}</span>` : ''}
                                ${s.channel ? `<span class="badge badge-event">${s.channel}</span>` : ''}
                                ${s.peer ? `<span class="tag">${s.peer}</span>` : ''}
                            </div>
                        </div>
                        <span class="obs-date">${formatDate(s.started_at)}</span>
                    </div>
                    <div class="detail-content" style="min-height:auto;">${esc(s.summary || '')}</div>
                    ${s.key_decisions ? `<div style="margin-top:12px;"><div class="detail-label">Decisiones clave</div><div style="color:var(--text-dim);font-size:13px;">${esc(s.key_decisions)}</div></div>` : ''}
                    ${s.key_actions ? `<div style="margin-top:8px;"><div class="detail-label">Acciones</div><div style="color:var(--text-dim);font-size:13px;">${esc(s.key_actions)}</div></div>` : ''}
                </div>
            `).join('');
        } catch (e) {
            console.error('Sessions error:', e);
        }
    }

    // ── Import ──
    const dropZone = document.getElementById('drop-zone');
    dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
    dropZone.addEventListener('drop', e => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        if (e.dataTransfer.files.length) processImportFile(e.dataTransfer.files[0]);
    });

    function handleImportFile(e) {
        if (e.target.files.length) processImportFile(e.target.files[0]);
    }

    async function processImportFile(file) {
        const resultEl = document.getElementById('import-result');
        resultEl.innerHTML = '<div class="spinner"></div> Importando...';

        try {
            const text = await file.text();
            const data = JSON.parse(text);

            const res = await fetch(apiUrl('/api/import'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            });

            const result = await res.json();
            if (res.ok) {
                resultEl.innerHTML = `<div style="color:var(--green);font-weight:600;">${result.message}</div>`;
                showToast(result.message);
            } else {
                resultEl.innerHTML = `<div style="color:var(--red);">${result.error}</div>`;
                showToast(result.error, 'error');
            }
        } catch (e) {
            resultEl.innerHTML = `<div style="color:var(--red);">Error: archivo JSON invalido</div>`;
            showToast('JSON invalido', 'error');
        }
    }

    // ── Utilities ──
    function esc(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function formatDate(str) {
        if (!str) return '-';
        try {
            const d = new Date(str.replace(' ', 'T') + 'Z');
            return d.toLocaleDateString('es', { year: 'numeric', month: 'short', day: 'numeric' }) +
                   ' ' + d.toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' });
        } catch {
            return str;
        }
    }

    // ── Init ──
    // Fix export links for proxy/prefix support
    document.getElementById('export-json-link').href = apiUrl('/api/export?format=json');
    document.getElementById('export-csv-link').href = apiUrl('/api/export?format=csv');
    loadStats();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    print("OpenClaw Memory Dashboard starting...")
    print("URL: http://localhost:5000")
    print("Local access only")
    app.run(host="127.0.0.1", port=5001, debug=False)
