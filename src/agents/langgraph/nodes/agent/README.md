# Generic Agent Node 🤖

**Directory:** `src/agents/langgraph/nodes/agent/`

## 📖 Overview
The Agent Layer (`agent_node`) is the central orchestrator for most conversation turns. It handles:
- **Phase Management**: Deciding when to move from Discovery -> Size/Color -> Offer.
- **Product Upsell**: Suggesting additional items.
- **Data Gathering**: Collecting size/height/color details.
- **LLM Interaction**: Generating the final response text.

Refactored from a monolithic `agent.py`, it now uses a modular architecture.

## 📂 File Structure

| File | Responsibility | Key Functions |
|------|----------------|---------------|
| **`node.py`** | **Orchestrator**. Wiring user input -> logic -> LLM -> output. | `agent_node` |
| **`logic.py`** | **Business Rules**. State machine transitions, upsell triggers. | `determine_phase`, `should_trigger_upsell` |
| **`tools.py`** | **Pure Logic**. Regex parsing (size/height), math, data merging. | `extract_height_from_text`, `merge_products` |
| **`catalog.py`** | **Data Access**. Interface for DB checks (currently state wrappers). | `check_color_availability` |
| **`__init__.py`** | **Public API**. Exports `agent_node` for the graph. | - |

## 🛠️ How to Extend (Scenarios)

### Scenario A: "Updates to Price Calculation"
**Target:** `tools.py`
Modify `get_size_and_price_for_height` (imported) or `merge_products` logic.

### Scenario B: "New Size Pattern (e.g. US sizes)"
**Target:** `tools.py`
Add regex to `SIZE_PATTERNS` list.

### Scenario C: "Change upsell keywords"
**Target:** `logic.py`
Edit `UPSELL_KEYWORDS` list.

### Scenario D: "Change State Transitions"
**Target:** `logic.py` -> `determine_phase`
This function wraps `state_prompts.py` logic but adds safeguards.

## 🧪 Verification
Run unit tests checking regex and logic flows:
```bash
python tests/verify_agent_refactor.py
```
