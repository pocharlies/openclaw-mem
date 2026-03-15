#!/usr/bin/env bash
set -euo pipefail

# openclaw-mem uninstaller

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
DATA_DIR="${OPENCLAW_MEM_DATA_DIR:-$HOME/.openclaw-mem}"

echo "=== openclaw-mem uninstaller ==="
echo ""

# ── 1. Remove MCP yaml ─────────────────────────────────────────────────

MCP_YAML="$OPENCLAW_HOME/mcp/openclaw-mem.yaml"
if [ -f "$MCP_YAML" ]; then
    rm "$MCP_YAML"
    echo "[1/5] Removed MCP config: $MCP_YAML"
else
    echo "[1/5] MCP config not found (already removed)."
fi

# ── 2. Remove mcporter entry ───────────────────────────────────────────

MCPORTER_JSON="$OPENCLAW_HOME/workspace/config/mcporter.json"
if [ -f "$MCPORTER_JSON" ]; then
    python3 -c "
import json
with open('$MCPORTER_JSON') as f:
    data = json.load(f)
if 'openclaw-mem' in data.get('mcpServers', {}):
    del data['mcpServers']['openclaw-mem']
    with open('$MCPORTER_JSON', 'w') as f:
        json.dump(data, f, indent=2)
        f.write('\n')
    print('[2/5] Removed mcporter entry.')
else:
    print('[2/5] mcporter entry not found (already removed).')
" 2>/dev/null || echo "[2/5] mcporter config not found."
else
    echo "[2/5] mcporter config not found."
fi

# ── 3. Remove skill ────────────────────────────────────────────────────

SKILL_DIR="$OPENCLAW_HOME/skills/memory"
if [ -d "$SKILL_DIR" ]; then
    rm -rf "$SKILL_DIR"
    echo "[3/5] Removed skill: $SKILL_DIR"
else
    echo "[3/5] Skill not found (already removed)."
fi

# ── 4. Remove systemd timer ────────────────────────────────────────────

if systemctl --user is-active openclaw-mem-sync.timer &>/dev/null; then
    systemctl --user stop openclaw-mem-sync.timer
    systemctl --user disable openclaw-mem-sync.timer
    echo "[4/5] Stopped and disabled systemd timer."
else
    echo "[4/5] Systemd timer not active."
fi

for f in openclaw-mem-sync.service openclaw-mem-sync.timer; do
    fp="$HOME/.config/systemd/user/$f"
    [ -f "$fp" ] && rm "$fp"
done
systemctl --user daemon-reload 2>/dev/null || true

# ── 5. Remove venv ─────────────────────────────────────────────────────

VENV_DIR="$SCRIPT_DIR/.venv"
if [ -d "$VENV_DIR" ]; then
    rm -rf "$VENV_DIR"
    echo "[5/5] Removed virtual environment."
else
    echo "[5/5] Virtual environment not found."
fi

echo ""
echo "=== Uninstall complete ==="
echo ""
echo "Data preserved at: $DATA_DIR"
echo "To also remove the database: rm -rf $DATA_DIR"
echo ""
echo "Restart OpenClaw: systemctl --user restart openclaw-gateway"
