#!/usr/bin/env bash
set -euo pipefail

# openclaw-mem installer
# Registers MCP server, mcporter entry, and skill in OpenClaw

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
DATA_DIR="${OPENCLAW_MEM_DATA_DIR:-$HOME/.openclaw-mem}"

echo "=== openclaw-mem installer ==="
echo "  Install dir:  $SCRIPT_DIR"
echo "  OpenClaw:     $OPENCLAW_HOME"
echo "  Data dir:     $DATA_DIR"
echo ""

# ── 1. Check prerequisites ──────────────────────────────────────────────

if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.10+ first."
    exit 1
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    echo "ERROR: Python 3.10+ required, found $PY_VERSION"
    exit 1
fi

if [ ! -d "$OPENCLAW_HOME" ]; then
    echo "ERROR: OpenClaw home not found at $OPENCLAW_HOME"
    echo "  Set OPENCLAW_HOME env var if using a custom location."
    exit 1
fi

# ── 2. Create data directory ────────────────────────────────────────────

mkdir -p "$DATA_DIR"
echo "[1/7] Data directory: $DATA_DIR"

# ── 3. Create virtual environment + install deps ────────────────────────

VENV_DIR="$SCRIPT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "[2/7] Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
else
    echo "[2/7] Virtual environment exists."
fi

echo "[3/7] Installing dependencies..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r "$SCRIPT_DIR/requirements.txt"

VENV_PYTHON="$VENV_DIR/bin/python3"

# ── 4. Initialize database ─────────────────────────────────────────────

echo "[4/7] Initializing database..."
OPENCLAW_MEM_DB="$DATA_DIR/memory.db" "$VENV_PYTHON" -c "from openclaw_mem.db import init_db; init_db()"

# ── 5. Register MCP server in OpenClaw ──────────────────────────────────

MCP_DIR="$OPENCLAW_HOME/mcp"
mkdir -p "$MCP_DIR"

MCP_YAML="$MCP_DIR/openclaw-mem.yaml"
cat > "$MCP_YAML" << EOF
name: openclaw-mem
title: OpenClaw Persistent Memory
description: Search, store, and retrieve memories across all sessions. Use the 3-layer workflow - memory_search (index) then memory_timeline (context) then memory_get (full details).
command: $VENV_PYTHON
args:
  - $SCRIPT_DIR/openclaw_mem/server.py
env:
  OPENCLAW_MEM_DB: $DATA_DIR/memory.db
EOF
echo "[5/7] MCP server registered: $MCP_YAML"

# ── 6. Register in mcporter (if config exists) ─────────────────────────

MCPORTER_JSON="$OPENCLAW_HOME/workspace/config/mcporter.json"
if [ -f "$MCPORTER_JSON" ]; then
    # Check if already registered
    if python3 -c "
import json, sys
with open('$MCPORTER_JSON') as f:
    data = json.load(f)
if 'openclaw-mem' in data.get('mcpServers', {}):
    sys.exit(0)
sys.exit(1)
" 2>/dev/null; then
        echo "[6/7] mcporter entry already exists."
    else
        # Add entry using python for safe JSON manipulation
        python3 -c "
import json
with open('$MCPORTER_JSON') as f:
    data = json.load(f)
data.setdefault('mcpServers', {})['openclaw-mem'] = {
    'command': '$VENV_PYTHON',
    'args': ['$SCRIPT_DIR/openclaw_mem/server.py'],
    'env': {
        'OPENCLAW_MEM_DB': '$DATA_DIR/memory.db'
    }
}
with open('$MCPORTER_JSON', 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
"
        echo "[6/7] mcporter entry added: $MCPORTER_JSON"
    fi
else
    echo "[6/7] mcporter config not found, skipping. (Create $MCPORTER_JSON if needed)"
fi

# ── 7. Install skill ───────────────────────────────────────────────────

SKILL_DIR="$OPENCLAW_HOME/skills/memory"
mkdir -p "$SKILL_DIR"
cp "$SCRIPT_DIR/skill/SKILL.md" "$SKILL_DIR/SKILL.md"
echo "[7/7] Skill installed: $SKILL_DIR/SKILL.md"

# ── Done ────────────────────────────────────────────────────────────────

echo ""
echo "=== Installation complete ==="
echo ""
echo "Next steps:"
echo "  1. Restart OpenClaw gateway:  systemctl --user restart openclaw-gateway"
echo "  2. Import existing memories:  OPENCLAW_MEM_DB=$DATA_DIR/memory.db $VENV_PYTHON -m openclaw_mem.importer --all"
echo "  3. (Optional) Install systemd timer for daily sync:"
echo "     cp $SCRIPT_DIR/config/systemd/openclaw-mem-sync.* ~/.config/systemd/user/"
echo "     systemctl --user daemon-reload"
echo "     systemctl --user enable --now openclaw-mem-sync.timer"
echo ""
echo "Test with:  mcporter call openclaw-mem.memory_stats"
