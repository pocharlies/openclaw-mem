#!/usr/bin/env python3
"""LLM synthesis pipeline for openclaw-mem.

Uses any OpenAI-compatible API to generate summaries and digests
from stored observations.

Usage:
    python -m openclaw_mem.synthesizer --daily-sync
    python -m openclaw_mem.synthesizer --synthesize-date 2026-03-14

Environment variables:
    OPENCLAW_MEM_LLM_BASE_URL  — API endpoint (default: http://127.0.0.1:4000/v1)
    OPENCLAW_MEM_LLM_API_KEY   — API key (default: empty)
    OPENCLAW_MEM_LLM_MODEL     — Model name (default: qwen35-35b)
    OPENCLAW_WORKSPACE         — OpenClaw workspace (default: ~/.openclaw/workspace)
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx

from openclaw_mem.db import get_connection, init_db, insert_observation
from openclaw_mem.importer import import_daily_files, import_rules, import_memory_md

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="[%(levelname)s] %(message)s",
)
logger = logging.getLogger("openclaw-mem-synth")

DEFAULT_BASE_URL = "http://127.0.0.1:4000/v1"
DEFAULT_MODEL = "qwen35-35b"
RATE_LIMIT_SECONDS = 5


def _get_llm_config() -> dict:
    return {
        "base_url": os.environ.get("OPENCLAW_MEM_LLM_BASE_URL", DEFAULT_BASE_URL),
        "api_key": os.environ.get("OPENCLAW_MEM_LLM_API_KEY", ""),
        "model": os.environ.get("OPENCLAW_MEM_LLM_MODEL", DEFAULT_MODEL),
    }


def _llm_call(prompt: str, system: str = "") -> str:
    """Call the LLM API and return the response text."""
    config = _get_llm_config()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    headers = {"Content-Type": "application/json"}
    if config["api_key"]:
        headers["Authorization"] = f"Bearer {config['api_key']}"

    body = {
        "model": config["model"],
        "messages": messages,
        "max_tokens": 2048,
        "temperature": 0.3,
    }

    with httpx.Client(timeout=120.0) as client:
        resp = client.post(
            f"{config['base_url']}/chat/completions",
            headers=headers,
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()


def synthesize_date(date_str: str) -> int:
    """Generate a daily digest for a specific date.

    Args:
        date_str: Date in YYYY-MM-DD format

    Returns:
        Number of synthesis observations created (0 or 1)
    """
    conn = get_connection()

    # Check if synthesis already exists for this date
    existing = conn.execute(
        """SELECT 1 FROM synthesis_runs
           WHERE run_type = 'daily' AND input_date = ? AND status = 'done'""",
        (date_str,),
    ).fetchone()
    if existing:
        logger.info("Daily synthesis already exists for %s, skipping.", date_str)
        conn.close()
        return 0

    # Get all observations from this date
    rows = conn.execute(
        """SELECT id, type, title, content, created_at
           FROM observations
           WHERE is_active = 1
             AND created_at >= ? AND created_at < ?
             AND source != 'synthesis'
           ORDER BY created_at ASC""",
        (f"{date_str} 00:00:00", f"{date_str} 23:59:59"),
    ).fetchall()

    if not rows:
        logger.info("No observations for %s, skipping synthesis.", date_str)
        conn.close()
        return 0

    # Record synthesis run start
    conn.execute(
        """INSERT INTO synthesis_runs (run_type, input_date, status, started_at)
           VALUES ('daily', ?, 'running', datetime('now'))""",
        (date_str,),
    )
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()

    # Build prompt
    obs_text = "\n".join(
        f"[{r['id']}] {r['created_at']} | {r['type']} | {r['title']}\n{r['content'][:300]}"
        for r in rows
    )

    system_prompt = (
        "You are a memory synthesis agent. Your job is to create concise daily digests "
        "from a list of observations. Focus on: key events, decisions made, important "
        "discoveries, and action items. Be factual and specific. Output a structured "
        "summary with bullet points grouped by theme."
    )
    user_prompt = (
        f"Summarize the following {len(rows)} observations from {date_str} into a "
        f"concise daily digest:\n\n{obs_text}"
    )

    try:
        summary = _llm_call(user_prompt, system_prompt)

        obs_id = insert_observation(
            conn,
            title=f"Daily digest: {date_str}",
            content=summary,
            type="observation",
            source="synthesis",
            tags="daily-digest",
        )

        conn.execute(
            """UPDATE synthesis_runs
               SET status = 'done', completed_at = datetime('now'),
                   output_observation_ids = ?
               WHERE id = ?""",
            (json.dumps([obs_id]), run_id),
        )
        conn.commit()
        logger.info("Synthesized daily digest for %s -> observation #%d", date_str, obs_id)
        conn.close()
        return 1

    except Exception as e:
        logger.error("Synthesis failed for %s: %s", date_str, e)
        conn.execute(
            """UPDATE synthesis_runs
               SET status = 'error', error = ?, completed_at = datetime('now')
               WHERE id = ?""",
            (str(e), run_id),
        )
        conn.commit()
        conn.close()
        return 0


def daily_sync(workspace: str) -> None:
    """Run a full daily sync: import new files + synthesize recent days."""
    logger.info("Starting daily sync...")

    # Phase 1: Import
    logger.info("Phase 1: Importing new files")
    total_imported = 0
    total_imported += import_daily_files(workspace)
    total_imported += import_rules(workspace)
    total_imported += import_memory_md(workspace)
    logger.info("Imported %d new observations", total_imported)

    # Phase 2: Synthesize recent days (last 3 days)
    logger.info("Phase 2: Synthesizing recent days")
    today = datetime.now(timezone.utc).date()
    total_synth = 0
    for days_ago in range(1, 4):  # yesterday, day before, etc.
        date = today - timedelta(days=days_ago)
        date_str = date.strftime("%Y-%m-%d")
        total_synth += synthesize_date(date_str)
        time.sleep(RATE_LIMIT_SECONDS)

    logger.info("Daily sync complete. Imported: %d, Synthesized: %d", total_imported, total_synth)


def main():
    parser = argparse.ArgumentParser(description="openclaw-mem synthesis pipeline")
    parser.add_argument(
        "--workspace",
        default=os.environ.get("OPENCLAW_WORKSPACE", os.path.expanduser("~/.openclaw/workspace")),
        help="OpenClaw workspace path",
    )
    parser.add_argument(
        "--daily-sync",
        action="store_true",
        help="Run full daily sync (import + synthesize)",
    )
    parser.add_argument(
        "--synthesize-date",
        metavar="YYYY-MM-DD",
        help="Synthesize a specific date",
    )
    args = parser.parse_args()

    init_db()

    if args.daily_sync:
        daily_sync(args.workspace)
    elif args.synthesize_date:
        synthesize_date(args.synthesize_date)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
