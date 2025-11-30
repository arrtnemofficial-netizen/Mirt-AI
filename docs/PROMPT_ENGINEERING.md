# Prompt Engineering Guide

## Overview

MIRT AI uses a **single source of truth** for system prompts, defined in YAML and loaded dynamically. This ensures consistency between the codebase and the LLM's behavior.

---

## 📄 Prompt Structure

### 1. Master Prompt (`data/system_prompt_full.yaml`)
This is the definitive prompt file. It contains:
- **Identity**: Persona (Kind, professional stylist).
- **Tools**: Definitions of available tools (Catalog, CRM).
- **Output Contract**: Strict JSON schema for responses.
- **Catalog**: Embedded product list (top bestsellers).
- **Domain Knowledge**: Sizing charts, return policies, delivery info.

### 2. Prompt Loader (`src/core/prompt_loader.py`)
Responsible for loading and formatting the prompt.
- Reads `system_prompt_full.yaml`.
- Converts YAML sections into a unified Markdown string.
- Injects dynamic context (if any).

---

## 🛠️ Editing Prompts

**DO NOT hardcode prompts in Python files.**

To change the bot's behavior:
1. Open `data/system_prompt_full.yaml`.
2. Edit the relevant section (e.g., `IDENTITY` or `POLICIES`).
3. Restart the server (prompt is loaded on agent initialization).

### Example: Changing Tone
```yaml
IDENTITY: |
  You are Mirt, a helpful and stylish assistant.
  Tone: Warm, encouraging, using emojis (🤍, ✨).
  Language: Ukrainian (always).
```

---

## 📦 Embedded Catalog

For speed and reliability, we embed the core product catalog directly into the system prompt.
This avoids RAG latency and database dependencies for common queries.

**Location**: `data/catalog.json` (source) -> `system_prompt_full.yaml` (runtime)

---

## 🧪 Testing Prompts

Use the `scripts/test_real_llm.py` (legacy) or manual testing via Telegram to verify prompt changes.
Always check that the LLM adheres to the `OUTPUT_CONTRACT` defined in the Pydantic models.
