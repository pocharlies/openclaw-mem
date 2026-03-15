# openclaw-mem

Persistent memory plugin for [OpenClaw](https://openclaw.com). Gives your agents searchable, synthesized memory across all sessions using SQLite + FTS5 full-text search.

Inspired by [claude-mem](https://github.com/thedotmack/claude-mem).

## What it does

- **Stores** observations, rules, contacts, events, decisions, and lessons in a local SQLite database
- **Searches** memories using FTS5 full-text search with BM25 ranking
- **Imports** existing OpenClaw workspace memory files (daily logs, rules, MEMORY.md)
- **Synthesizes** daily digests using any OpenAI-compatible LLM API
- **Integrates** as an MCP server + skill — agents can search and save memories via tool calls

## Requirements

- Python 3.10+
- OpenClaw (any version with MCP support)
- `mcp` Python package (>= 1.0.0)

## Quick Install

```bash
git clone https://github.com/pocharlies/openclaw-mem.git
cd openclaw-mem
./install.sh
```

The install script will:

1. Create a Python virtual environment and install dependencies
2. Initialize the SQLite database at `~/.openclaw-mem/memory.db`
3. Register the MCP server in OpenClaw (`~/.openclaw/mcp/openclaw-mem.yaml`)
4. Add an entry to mcporter config (if available)
5. Install the `memory` skill for agents

Then restart OpenClaw:

```bash
systemctl --user restart openclaw-gateway
```

## Import Existing Memories

Import your workspace memory files into the database:

```bash
# Import everything
.venv/bin/python3 -m openclaw_mem.importer --all

# Or selectively
.venv/bin/python3 -m openclaw_mem.importer --daily    # Daily YYYY-MM-DD*.md logs
.venv/bin/python3 -m openclaw_mem.importer --rules    # Rule/policy files
.venv/bin/python3 -m openclaw_mem.importer --memory   # MEMORY.md

# Custom workspace path
.venv/bin/python3 -m openclaw_mem.importer --all --workspace /path/to/workspace
```

All imports are idempotent — safe to re-run.

## Usage

### For Agents (via skill)

Agents automatically learn how to use memory via the installed `memory` skill. The skill teaches the **3-layer token-efficient workflow**:

1. **`memory_search`** — Search the index (compact results, ~60 tokens each)
2. **`memory_timeline`** — Get chronological context around a result (~100 tokens each)
3. **`memory_get`** — Fetch full content only for what you need (~300 tokens each)

### Tool Reference

| Tool | Description |
| --- | --- |
| `memory_search` | FTS5 full-text search with filters (type, date range, tags) |
| `memory_timeline` | Chronological context window around an observation |
| `memory_get` | Batch fetch full content by IDs |
| `memory_save` | Create a new memory observation |
| `memory_update` | Update existing (supersedes old version, preserving history) |
| `memory_stats` | Database summary statistics |

### Example Tool Calls

```bash
# Search
mcporter call openclaw-mem.memory_search --args '{"query": "email triage rules"}'
mcporter call openclaw-mem.memory_search --args '{"query": "Wesley", "type": "contact"}'

# Save
mcporter call openclaw-mem.memory_save --args '{"title": "New triage rule", "content": "Always flag invoices over 500 EUR", "type": "rule", "tags": "email,invoicing"}'

# Get full details
mcporter call openclaw-mem.memory_get --args '{"ids": [1, 2, 3]}'

# Stats
mcporter call openclaw-mem.memory_stats
```

### Observation Types

| Type | Use for |
| --- | --- |
| `observation` | General facts, notes, context |
| `rule` | Policies, triage rules, operational rules |
| `contact` | People, phone numbers, preferences |
| `event` | Things that happened (triages, incidents, config changes) |
| `decision` | Choices made by the user or team |
| `lesson` | Things learned from mistakes or experience |
| `state` | Current state of ongoing processes |

## LLM Synthesis (Optional)

Generate daily digest summaries from stored observations using any OpenAI-compatible API:

```bash
# Synthesize a specific date
.venv/bin/python3 -m openclaw_mem.synthesizer --synthesize-date 2026-03-14

# Full daily sync (import new files + synthesize last 3 days)
.venv/bin/python3 -m openclaw_mem.synthesizer --daily-sync
```

### Automated Daily Sync

Install the systemd timer for automatic daily synthesis at 03:00:

```bash
cp config/systemd/openclaw-mem-sync.* ~/.config/systemd/user/
# Edit the service file to set LLM env vars if needed
systemctl --user daemon-reload
systemctl --user enable --now openclaw-mem-sync.timer
```

## Configuration

All configuration is via environment variables:

| Variable | Default | Description |
| --- | --- | --- |
| `OPENCLAW_MEM_DB` | `~/.openclaw-mem/memory.db` | Database file path |
| `OPENCLAW_MEM_LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `OPENCLAW_WORKSPACE` | `~/.openclaw/workspace` | OpenClaw workspace path for imports |
| `OPENCLAW_MEM_LLM_BASE_URL` | `http://127.0.0.1:4000/v1` | OpenAI-compatible API endpoint |
| `OPENCLAW_MEM_LLM_API_KEY` | (empty) | API key for LLM |
| `OPENCLAW_MEM_LLM_MODEL` | `qwen35-35b` | Model name for synthesis |

## Architecture

```
OpenClaw Agent
    │
    ▼ (MCP tool call via stdio)
┌──────────────────┐
│  server.py       │  FastMCP server — 6 tools
│  (MCP stdio)     │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  db.py           │  SQLite + FTS5 full-text search
│  (memory.db)     │  WAL mode, porter stemmer
└──────────────────┘
         │
    ┌────┴────┐
    ▼         ▼
importer   synthesizer
(.md →DB)  (LLM → digests)
```

The 3-layer search workflow saves ~10x tokens compared to fetching all content:

1. **Search layer** returns only IDs + titles (50-80 tokens per result)
2. **Timeline layer** adds chronological context (100 tokens per result)
3. **Detail layer** fetches full content only for selected IDs (300+ tokens per result)

## Uninstall

```bash
./uninstall.sh
systemctl --user restart openclaw-gateway
```

This removes the MCP config, mcporter entry, skill, and virtual environment. Your database at `~/.openclaw-mem/` is preserved — delete it manually if you want a clean removal.

## License

MIT
