# Architecture

## Overview

openclaw-mem is a persistent memory system for OpenClaw agents. It stores structured observations in a local SQLite database with FTS5 full-text search, and exposes them as MCP tools that agents can call during conversations.

## Components

### MCP Server (`server.py`)

- FastMCP server using stdio transport
- Launched on-demand by OpenClaw/mcporter when an agent calls a memory tool
- Exposes 6 tools: `memory_search`, `memory_timeline`, `memory_get`, `memory_save`, `memory_update`, `memory_stats`
- Stateless between invocations (reads/writes to SQLite)

### Database (`db.py`)

- SQLite 3 with WAL (Write-Ahead Logging) for concurrent access
- FTS5 virtual table with porter stemmer for full-text search
- Auto-sync triggers keep FTS5 index updated on INSERT/UPDATE/DELETE
- Tables: `observations`, `observations_fts`, `session_summaries`, `synthesis_runs`, `import_log`

### Importer (`importer.py`)

- Parses OpenClaw workspace markdown files into structured observations
- Handles daily logs (`YYYY-MM-DD*.md`), rule files, MEMORY.md, contacts
- Idempotent: tracks imported files by path + SHA256 hash

### Synthesizer (`synthesizer.py`)

- Uses any OpenAI-compatible LLM API to generate daily digest summaries
- Rate-limited (1 call per 5 seconds) to avoid competing with active sessions
- Tracks synthesis runs to prevent duplicate processing

## Database Schema

### observations

The core table. Each row is a memory item.

| Column | Type | Description |
| --- | --- | --- |
| id | INTEGER | Primary key |
| type | TEXT | observation, rule, contact, event, decision, lesson, state |
| title | TEXT | Short title (max ~10 words) |
| content | TEXT | Full text content |
| source | TEXT | manual, daily-log, session, import, synthesis |
| source_file | TEXT | Original file path (for imported observations) |
| agent_id | TEXT | OpenClaw agent ID (main, daily, etc.) |
| channel | TEXT | whatsapp, telegram, web, etc. |
| tags | TEXT | Comma-separated tags |
| created_at | TEXT | ISO timestamp |
| updated_at | TEXT | ISO timestamp |
| superseded_by | INTEGER | FK to newer version (for versioned updates) |
| is_active | INTEGER | 1 = active, 0 = superseded/deleted |

### observations_fts

FTS5 virtual table indexing `title`, `content`, and `tags` with porter stemmer tokenizer.

### import_log

Tracks which files have been imported (path + SHA256 hash) to prevent duplicate imports.

## Token Efficiency

The 3-layer search workflow is inspired by [claude-mem](https://github.com/thedotmack/claude-mem):

1. **Search** (~60 tokens/result): Returns compact index — just IDs, types, titles, dates
2. **Timeline** (~100 tokens/result): Adds chronological context with content previews
3. **Get** (~300 tokens/result): Full content for specific IDs

This progressive disclosure saves ~10x tokens compared to dumping all memories into context. An agent searching 1000 memories only loads ~1,200 tokens for 20 search results, then ~900 tokens for 3 full details = 2,100 tokens total instead of 300,000+.
