#!/usr/bin/env python3
"""Import OpenClaw workspace memory files into the openclaw-mem database.

Usage:
    python -m openclaw_mem.importer [--daily] [--rules] [--memory] [--all] [--workspace PATH]

All imports are idempotent — tracked by file path + SHA256 hash.
"""

import argparse
import hashlib
import logging
import os
import re
import sys
from glob import glob
from pathlib import Path

from openclaw_mem.db import (
    get_connection,
    init_db,
    insert_observation,
    is_imported,
    log_import,
)

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="[%(levelname)s] %(message)s",
)
logger = logging.getLogger("openclaw-mem-importer")

DEFAULT_WORKSPACE = os.path.expanduser("~/.openclaw/workspace")

# Pattern: "- HH:MM CET — content" or "- HH:MM — content" or just "- content"
DAILY_BULLET_RE = re.compile(
    r"^-\s+(?:(\d{1,2}:\d{2})\s*(?:CET|CEST)?\s*[—–-]\s*)?(.+)",
    re.MULTILINE,
)

# Pattern for daily log filenames: YYYY-MM-DD*.md
DAILY_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _file_hash(path: str) -> str:
    """SHA256 hash of file contents."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _import_file_as_single(
    conn, filepath: str, obs_type: str, source: str, title_prefix: str = ""
) -> int:
    """Import an entire file as a single observation."""
    fhash = _file_hash(filepath)
    if is_imported(conn, filepath, fhash):
        logger.info("  Skipping (already imported): %s", filepath)
        return 0

    content = Path(filepath).read_text(encoding="utf-8", errors="replace").strip()
    if not content:
        return 0

    fname = Path(filepath).stem
    title = f"{title_prefix}{fname}" if title_prefix else fname

    insert_observation(
        conn,
        title=title,
        content=content,
        type=obs_type,
        source=source,
        source_file=filepath,
    )
    log_import(conn, filepath, fhash, 1)
    logger.info("  Imported: %s (1 observation)", filepath)
    return 1


def import_daily_files(workspace: str) -> int:
    """Import daily YYYY-MM-DD*.md files as individual event observations."""
    conn = get_connection()
    memory_dir = os.path.join(workspace, "memory")
    if not os.path.isdir(memory_dir):
        logger.warning("Memory directory not found: %s", memory_dir)
        return 0

    count = 0
    for filepath in sorted(glob(os.path.join(memory_dir, "*.md"))):
        fname = os.path.basename(filepath)
        if not DAILY_FILE_RE.match(fname):
            continue

        fhash = _file_hash(filepath)
        if is_imported(conn, filepath, fhash):
            logger.info("  Skipping (already imported): %s", filepath)
            continue

        content = Path(filepath).read_text(encoding="utf-8", errors="replace")
        date_str = fname[:10]  # YYYY-MM-DD

        # Parse individual bullets
        bullets = DAILY_BULLET_RE.findall(content)
        if not bullets:
            # No structured bullets; import whole file as one observation
            insert_observation(
                conn,
                title=f"Daily log {date_str}",
                content=content.strip(),
                type="event",
                source="daily-log",
                source_file=filepath,
                created_at=f"{date_str} 00:00:00",
            )
            file_count = 1
        else:
            file_count = 0
            for time_str, text in bullets:
                text = text.strip()
                if not text:
                    continue
                # Build title from first ~60 chars
                title = text[:60].rstrip()
                if len(text) > 60:
                    title += "..."

                timestamp = f"{date_str} {time_str}:00" if time_str else f"{date_str} 00:00:00"
                insert_observation(
                    conn,
                    title=title,
                    content=text,
                    type="event",
                    source="daily-log",
                    source_file=filepath,
                    created_at=timestamp,
                )
                file_count += 1

        log_import(conn, filepath, fhash, file_count)
        count += file_count
        logger.info("  Imported: %s (%d observations)", filepath, file_count)

    conn.close()
    return count


def import_rules(workspace: str) -> int:
    """Import rule/policy files as rule observations."""
    conn = get_connection()
    memory_dir = os.path.join(workspace, "memory")
    count = 0

    rule_patterns = [
        ("email-triage-rules*.md", "rule", "import", "Email triage: "),
        ("invoice-filing-rules.md", "rule", "import", "Invoice filing: "),
        ("mcporter-policy.md", "rule", "import", "MCP policy: "),
    ]

    for pattern, obs_type, source, prefix in rule_patterns:
        for filepath in glob(os.path.join(memory_dir, pattern)):
            count += _import_file_as_single(conn, filepath, obs_type, source, prefix)

    # Contacts
    contact_files = ["leila.md"]
    for fname in contact_files:
        filepath = os.path.join(memory_dir, fname)
        if os.path.exists(filepath):
            count += _import_file_as_single(conn, filepath, "contact", "import", "Contact: ")

    # State files
    state_files = ["dgx-watchdog-state.md"]
    for fname in state_files:
        filepath = os.path.join(memory_dir, fname)
        if os.path.exists(filepath):
            count += _import_file_as_single(conn, filepath, "state", "import", "State: ")

    conn.close()
    return count


def import_memory_md(workspace: str) -> int:
    """Import MEMORY.md bullets as decision/rule observations."""
    conn = get_connection()
    filepath = os.path.join(workspace, "MEMORY.md")
    if not os.path.exists(filepath):
        logger.warning("MEMORY.md not found: %s", filepath)
        return 0

    fhash = _file_hash(filepath)
    if is_imported(conn, filepath, fhash):
        logger.info("  Skipping (already imported): %s", filepath)
        return 0

    content = Path(filepath).read_text(encoding="utf-8", errors="replace")
    count = 0

    for match in re.finditer(r"^-\s+(.+?)(?:\n(?!-)|\Z)", content, re.MULTILINE | re.DOTALL):
        text = match.group(1).strip()
        if not text:
            continue
        title = text[:60].rstrip()
        if len(text) > 60:
            title += "..."

        insert_observation(
            conn,
            title=title,
            content=text,
            type="decision",
            source="import",
            source_file=filepath,
            tags="memory-md",
        )
        count += 1

    log_import(conn, filepath, fhash, count)
    logger.info("  Imported: %s (%d observations)", filepath, count)
    conn.close()
    return count


def main():
    parser = argparse.ArgumentParser(
        description="Import OpenClaw workspace files into openclaw-mem database"
    )
    parser.add_argument(
        "--workspace",
        default=os.environ.get("OPENCLAW_WORKSPACE", DEFAULT_WORKSPACE),
        help=f"OpenClaw workspace path (default: {DEFAULT_WORKSPACE})",
    )
    parser.add_argument("--daily", action="store_true", help="Import daily YYYY-MM-DD*.md files")
    parser.add_argument("--rules", action="store_true", help="Import rule/policy files")
    parser.add_argument("--memory", action="store_true", help="Import MEMORY.md")
    parser.add_argument("--all", action="store_true", help="Import all sources")
    args = parser.parse_args()

    if not any([args.daily, args.rules, args.memory, args.all]):
        parser.print_help()
        sys.exit(1)

    init_db()
    total = 0

    if args.daily or args.all:
        logger.info("Importing daily files from %s/memory/", args.workspace)
        total += import_daily_files(args.workspace)

    if args.rules or args.all:
        logger.info("Importing rules from %s/memory/", args.workspace)
        total += import_rules(args.workspace)

    if args.memory or args.all:
        logger.info("Importing MEMORY.md from %s", args.workspace)
        total += import_memory_md(args.workspace)

    logger.info("Import complete. Total observations created: %d", total)


if __name__ == "__main__":
    main()
