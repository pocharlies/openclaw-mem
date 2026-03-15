---
name: memory
description: Search and store persistent memories across sessions. Use when you need to recall past conversations, decisions, rules, contacts, or events. Also use when the user says "remember this" or asks about something from a past session.
metadata:
  openclaw:
    emoji: "\U0001F9E0"
---

# Memory — Persistent Knowledge Store

Search, store, and retrieve information across sessions using the openclaw-mem database.

## When to Use

Activate this skill when:

- Starting a new session (search for relevant context about the user/topic)
- The user references something from a past conversation
- You learn something worth remembering (new rule, contact, decision)
- You need to recall email triage rules, invoice filing rules, or operational procedures
- Checking what happened on a specific date
- Looking up contact info, preferences, or policies
- The user says "remember this", "don't forget", or "save this"

## 3-Layer Workflow (Token-Efficient)

Always follow this pattern — search first, fetch details only for what you need:

### Step 1: Search (compact index)

```
mcporter call openclaw-mem.memory_search --args '{"query": "email triage rules"}'
mcporter call openclaw-mem.memory_search --args '{"query": "skirmshop orders", "type": "event", "limit": 10}'
mcporter call openclaw-mem.memory_search --args '{"query": "Wesley", "type": "contact"}'
mcporter call openclaw-mem.memory_search --args '{"query": "invoice", "date_start": "2026-03-01", "date_end": "2026-03-15"}'
```

### Step 2: Timeline (optional, for context)

```
mcporter call openclaw-mem.memory_timeline --args '{"anchor_id": 42, "before": 3, "after": 3}'
```

### Step 3: Get full details

```
mcporter call openclaw-mem.memory_get --args '{"ids": [42, 43, 45]}'
```

## Save a Memory

```
mcporter call openclaw-mem.memory_save --args '{"title": "Wesley DM rule", "content": "Only reply to Wesley DMs if message contains @openclaw", "type": "rule", "tags": "whatsapp,wesley,dm-policy"}'
```

## Update a Memory

```
mcporter call openclaw-mem.memory_update --args '{"id": 42, "content": "Updated rule: reply to Wesley only if @openclaw or urgent keyword", "tags": "whatsapp,wesley"}'
```

## Check Stats

```
mcporter call openclaw-mem.memory_stats
```

## Types

| Type | Use for |
| --- | --- |
| `observation` | General facts, notes, context |
| `rule` | Policies, triage rules, operational rules |
| `contact` | People, phone numbers, preferences |
| `event` | Things that happened (email triages, incidents, config changes) |
| `decision` | Choices made by the user or team |
| `lesson` | Things learned from mistakes or experience |
| `state` | Current state of ongoing processes |

## Rules

- Search BEFORE asking the user if they already told you something
- Save important new information immediately — don't wait
- Use specific types and tags for better retrieval later
- When updating facts, use `memory_update` — it preserves history
- Don't store sensitive credentials (API keys, tokens) in memory
- Daily logs are automatically imported — no need to manually save routine events
