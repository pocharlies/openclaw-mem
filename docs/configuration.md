# Configuration

## Environment Variables

All openclaw-mem configuration is via environment variables. No config files needed.

### Core

| Variable | Default | Description |
| --- | --- | --- |
| `OPENCLAW_MEM_DB` | `~/.openclaw-mem/memory.db` | Path to SQLite database file |
| `OPENCLAW_MEM_LOG_LEVEL` | `INFO` | Log level: DEBUG, INFO, WARNING, ERROR |

### Importer

| Variable | Default | Description |
| --- | --- | --- |
| `OPENCLAW_WORKSPACE` | `~/.openclaw/workspace` | OpenClaw workspace directory |

### Synthesizer (LLM)

| Variable | Default | Description |
| --- | --- | --- |
| `OPENCLAW_MEM_LLM_BASE_URL` | `http://127.0.0.1:4000/v1` | OpenAI-compatible API endpoint |
| `OPENCLAW_MEM_LLM_API_KEY` | (empty) | API key for the LLM provider |
| `OPENCLAW_MEM_LLM_MODEL` | `qwen35-35b` | Model name to use for synthesis |

### Install Paths

| Variable | Default | Description |
| --- | --- | --- |
| `OPENCLAW_HOME` | `~/.openclaw` | OpenClaw installation directory |
| `OPENCLAW_MEM_DATA_DIR` | `~/.openclaw-mem` | Data directory for database and logs |

## Custom Workspace Path

If your OpenClaw workspace is not at the default location:

```bash
# For imports
OPENCLAW_WORKSPACE=/custom/path .venv/bin/python3 -m openclaw_mem.importer --all

# For synthesis
OPENCLAW_WORKSPACE=/custom/path .venv/bin/python3 -m openclaw_mem.synthesizer --daily-sync
```

## LLM Provider Examples

### Local vLLM via LiteLLM

```bash
export OPENCLAW_MEM_LLM_BASE_URL=http://127.0.0.1:4000/v1
export OPENCLAW_MEM_LLM_API_KEY=sk-your-litellm-key
export OPENCLAW_MEM_LLM_MODEL=qwen35-35b
```

### OpenAI

```bash
export OPENCLAW_MEM_LLM_BASE_URL=https://api.openai.com/v1
export OPENCLAW_MEM_LLM_API_KEY=sk-your-openai-key
export OPENCLAW_MEM_LLM_MODEL=gpt-4o-mini
```

### Ollama

```bash
export OPENCLAW_MEM_LLM_BASE_URL=http://127.0.0.1:11434/v1
export OPENCLAW_MEM_LLM_API_KEY=ollama
export OPENCLAW_MEM_LLM_MODEL=llama3.2
```

## Systemd Timer

For automated daily sync, copy the service files and configure LLM environment:

```bash
cp config/systemd/openclaw-mem-sync.* ~/.config/systemd/user/

# Edit the service to set your LLM config
nano ~/.config/systemd/user/openclaw-mem-sync.service
# Uncomment and set the OPENCLAW_MEM_LLM_* variables

systemctl --user daemon-reload
systemctl --user enable --now openclaw-mem-sync.timer

# Check status
systemctl --user list-timers | grep openclaw-mem
```
