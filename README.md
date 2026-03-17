# OpenClaw-Mem Web Dashboard

A web interface for [openclaw-mem](https://github.com/pocharlies/openclaw-mem) - persistent memory for OpenClaw AI assistant.

## Features

### 📊 Main Dashboard (Port 5000)
- **Statistics**: Total observations, session count, date range
- **Full-text search**: Search across all memories with BM25 ranking
- **Filters**: Filter by type (rule, decision, event, lesson, contact, state, observation)
- **Chronological timeline**: View memories in chronological order
- **Click to expand**: See full content of each memory

### 💬 Conversation History (Port 5001)
- **All messages**: View every message from all conversations
- **User vs Assistant**: Distinguish between user and assistant messages
- **Channel filter**: Filter by channel (whatsapp, telegram, discord)
- **Search**: Search through conversation content
- **Timestamps**: View when each message was sent

## Installation

### Prerequisites
- Python 3.10+
- SQLite database at `~/.openclaw-mem/memory.db`
- Flask installed

```bash
cd /Users/usuario/openclaw-mem
.venv/bin/pip install flask
```

## Usage

### Start the Dashboard

```bash
./start.sh
```

This will start both web apps:
- Dashboard: http://localhost:5001
- History: http://localhost:5002

### Stop the Dashboard

```bash
./stop.sh
```

### Run Tests

```bash
./test.sh
```

## API Endpoints

### Dashboard API

```
GET /api/stats        - Get statistics
GET /api/session-summaries - Get session summaries
```

### History API

```
GET /api/messages     - Get all messages
GET /api/messages?channel=whatsapp - Filter by channel
```

## Database Schema

The dashboard connects to SQLite database at `~/.openclaw-mem/memory.db` with tables:
- `observations` - All memory entries
- `session_summaries` - Session summary records
- `synthesis_runs` - Synthesis run records
- `import_log` - Import tracking

## Features Compared to claude-mem

| Feature | claude-mem | OpenClaw-Mem Dashboard |
|---------|-----------|------------------------|
| Web interface | ✅ | ✅ |
| Full-text search | ✅ | ✅ |
| Chronological timeline | ✅ | ✅ |
| Type filtering | ✅ | ✅ |
| Statistics | ✅ | ✅ |
| Session summaries | ✅ | ✅ |
| Conversation history | ✅ | ✅ |
| Local only | ✅ | ✅ |

## Tech Stack

- **Backend**: Flask (Python)
- **Database**: SQLite with FTS5 full-text search
- **Frontend**: HTML5, CSS3, Vanilla JavaScript
- **Search**: FTS5 with BM25 ranking

## Security

- **Local access only**: Binds to `127.0.0.1` - not accessible externally
- **No authentication**: Intended for local development use only
- **Read-only**: Dashboard can only read data, not modify it

## Current Status

- ✅ Dashboard web app: Running on port 5000
- ✅ History web app: Running on port 5001
- ✅ 172 observations loaded and searchable
- ✅ Full search functionality working
- ✅ All tests passing

## License

MIT
