#!/usr/bin/env python3
"""openclaw-mem MCP server — persistent memory for OpenClaw agents.

Exposes 6 tools via FastMCP (stdio transport):
  memory_search   — FTS5 full-text search
  memory_timeline — chronological context around an observation
  memory_get      — batch fetch full content by IDs
  memory_save     — create a new observation
  memory_update   — update an existing observation
  memory_stats    — database summary statistics

Inspired by claude-mem (https://github.com/thedotmack/claude-mem).
"""

import json
import logging
import os
import sys

from mcp.server.fastmcp import FastMCP

from openclaw_mem.db import (
    get_connection,
    get_observations,
    get_stats,
    get_timeline,
    init_db,
    insert_observation,
    search_fts,
    update_observation,
    OBSERVATION_TYPES,
)

# Logging to stderr (stdout is reserved for MCP JSON-RPC)
logging.basicConfig(
    level=getattr(logging, os.environ.get("OPENCLAW_MEM_LOG_LEVEL", "INFO")),
    stream=sys.stderr,
    format="[%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("openclaw-mem")

mcp = FastMCP(
    "openclaw-mem",
    instructions=(
        "Persistent memory system for OpenClaw. "
        "Store, search, and retrieve memories across sessions. "
        "Use the 3-layer workflow for token efficiency: "
        "memory_search (compact index) -> memory_timeline (context) -> memory_get (full details). "
        "Only fetch full details for observations you actually need."
    ),
)

# Ensure database exists on server start
init_db()
_conn = get_connection()


# ── Tools ───────────────────────────────────────────────────────────────


@mcp.tool()
def memory_search(
    query: str,
    type: str = "",
    limit: int = 20,
    date_start: str = "",
    date_end: str = "",
    tags: str = "",
) -> str:
    """Search memories using full-text search.

    Returns a compact table of matching observations (id, type, title, date).
    Use memory_get with specific IDs to fetch full content.

    Args:
        query: Search terms (supports AND, OR, NOT, "exact phrases")
        type: Filter by type: observation, rule, contact, event, decision, lesson, state
        limit: Max results (1-100, default 20)
        date_start: Filter from date (YYYY-MM-DD)
        date_end: Filter to date (YYYY-MM-DD)
        tags: Filter by comma-separated tags
    """
    logger.info("memory_search: query=%r type=%r limit=%d", query, type, limit)
    results = search_fts(
        _conn,
        query=query,
        type=type or None,
        limit=limit,
        date_start=date_start or None,
        date_end=date_end or None,
        tags=tags or None,
    )
    if not results:
        return "No memories found matching your query."

    lines = [f"Found {len(results)} memories:\n"]
    lines.append(f"{'ID':>5} | {'Type':<12} | {'Title':<50} | {'Date':<19}")
    lines.append(f"{'─'*5} | {'─'*12} | {'─'*50} | {'─'*19}")
    for r in results:
        title = r["title"][:50]
        lines.append(f"{r['id']:>5} | {r['type']:<12} | {title:<50} | {r['created_at']:<19}")

    lines.append(f"\nUse memory_get with IDs to fetch full content.")
    return "\n".join(lines)


@mcp.tool()
def memory_timeline(
    anchor_id: int,
    before: int = 3,
    after: int = 3,
) -> str:
    """Get chronological context around a specific observation.

    Shows observations before and after the anchor, helping understand
    what was happening around that time.

    Args:
        anchor_id: Observation ID to center around
        before: Number of observations to show before (1-20, default 3)
        after: Number of observations to show after (1-20, default 3)
    """
    logger.info("memory_timeline: anchor=%d before=%d after=%d", anchor_id, before, after)
    before = max(1, min(before, 20))
    after = max(1, min(after, 20))

    items = get_timeline(_conn, anchor_id, before, after)
    if not items:
        return f"Observation {anchor_id} not found."

    lines = [f"Timeline around observation {anchor_id}:\n"]
    for item in items:
        marker = " >>>" if item["id"] == anchor_id else "    "
        preview = item.get("content_preview", "")[:100]
        lines.append(
            f"{marker} [{item['id']}] {item['created_at']} | {item['type']} | {item['title']}"
        )
        if preview:
            lines.append(f"         {preview}")
    return "\n".join(lines)


@mcp.tool()
def memory_get(ids: list[int]) -> str:
    """Fetch full content for specific observation IDs.

    Use after memory_search or memory_timeline to get detailed content
    for observations you've identified as relevant.

    Args:
        ids: List of observation IDs to fetch (max 50)
    """
    if not ids:
        return "No IDs provided."
    ids = ids[:50]
    logger.info("memory_get: ids=%s", ids)

    observations = get_observations(_conn, ids)
    if not observations:
        return "No observations found for the given IDs."

    lines = []
    for obs in observations:
        lines.append(f"━━━ [{obs['id']}] {obs['type'].upper()} ━━━")
        lines.append(f"Title: {obs['title']}")
        lines.append(f"Date: {obs['created_at']}")
        if obs["tags"]:
            lines.append(f"Tags: {obs['tags']}")
        if obs["source_file"]:
            lines.append(f"Source: {obs['source']} ({obs['source_file']})")
        else:
            lines.append(f"Source: {obs['source']}")
        if obs["agent_id"]:
            lines.append(f"Agent: {obs['agent_id']}")
        if not obs["is_active"]:
            lines.append(f"[SUPERSEDED by #{obs['superseded_by']}]")
        lines.append("")
        lines.append(obs["content"])
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def memory_save(
    title: str,
    content: str,
    type: str = "observation",
    tags: str = "",
) -> str:
    """Save a new memory observation.

    Use to store important information, rules, contacts, events,
    decisions, or lessons learned.

    Args:
        title: Short title (max ~10 words)
        content: Full content of the memory
        type: One of: observation, rule, contact, event, decision, lesson, state
        tags: Comma-separated tags for categorization
    """
    if type not in OBSERVATION_TYPES:
        return f"Invalid type '{type}'. Must be one of: {', '.join(OBSERVATION_TYPES)}"

    logger.info("memory_save: title=%r type=%r", title, type)
    obs_id = insert_observation(
        _conn,
        title=title,
        content=content,
        type=type,
        source="manual",
        tags=tags or None,
    )
    return f"Memory saved with ID {obs_id}."


@mcp.tool()
def memory_update(
    id: int,
    content: str = "",
    title: str = "",
    tags: str = "",
    is_active: bool = True,
) -> str:
    """Update an existing memory observation.

    If content changes, creates a new version and supersedes the old one
    (preserving history). Title/tags/active changes are in-place.

    Args:
        id: Observation ID to update
        content: New content (creates new version if changed)
        title: New title
        tags: New comma-separated tags
        is_active: Set to false to soft-delete
    """
    logger.info("memory_update: id=%d", id)
    new_id = update_observation(
        _conn,
        obs_id=id,
        content=content or None,
        title=title or None,
        tags=tags or None,
        is_active=is_active,
    )
    if new_id:
        return f"Memory updated. Old #{id} superseded by new #{new_id}."
    return f"Memory #{id} updated in place."


@mcp.tool()
def memory_stats() -> str:
    """Get summary statistics about the memory database.

    Shows total count, breakdown by type, date range, and recent entries.
    Useful for understanding what memory is available.
    """
    logger.info("memory_stats")
    stats = get_stats(_conn)

    lines = ["Memory Database Statistics:\n"]
    lines.append(f"Total active observations: {stats['total_observations']}")
    lines.append(f"Session summaries: {stats['session_summaries']}")
    if stats["earliest"]:
        lines.append(f"Date range: {stats['earliest']} to {stats['latest']}")

    if stats["by_type"]:
        lines.append("\nBy type:")
        for t, c in stats["by_type"].items():
            lines.append(f"  {t:<12} {c:>5}")

    if stats["recent"]:
        lines.append("\nMost recent:")
        for r in stats["recent"]:
            lines.append(f"  [{r['id']}] {r['created_at']} | {r['type']} | {r['title']}")

    return "\n".join(lines)


# ── Entry point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="stdio")
