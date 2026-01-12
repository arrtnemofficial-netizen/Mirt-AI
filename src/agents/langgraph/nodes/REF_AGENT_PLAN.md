# 🏗️ ZB_ENGINE_V6: Refactoring Plan for `agent.py` (REFINED)

**Task Type**: ARCHITECTURE (Refactoring God Object)
**Status**: PLANNING
**Target**: `src/agents/langgraph/nodes/agent.py`
**Auditor**: ARCHITECT OPUS

## 🧠 Internal Analysis (Why this needs to be Ironclad)
The `agent.py` node is the "Central Nervous System" of the conversation. Refactoring it is like open-heart surgery.
*   **Risk**: Breaking the logic where cart deduplication happens, or breaking the "Payment Agent" handover.
*   **Approach**: "Functional Core, Imperative Shell". Move logic into pure functions (handlers) that take data and return data, without side effects. `agent.py` just calls them.

## 1. 📐 The Handlers Architecture (The Solution)

We will create `src/agents/langgraph/nodes/handlers/` and split responsibilities:

### A. `snippet_handler.py` (The Gatekeeper)
*   **Responsibility**: Checks if we should bypass LLM (Policy Snippets).
*   **Contract**: `check_snippet_policy(state: dict, user_msg: str) -> dict | None`
*   **Logic**: Encapsulates `maybe_apply_snippet_policy` + `determine_response_policy` (the "Optimization" check).

### B. `color_handler.py` (The Visualizer)
*   **Responsibility**: Handles "Show me colors" requests.
*   **Contract**: `handle_color_request(state: dict, msg: str) -> dict | None`
*   **Logic**: Moves `_handle_color_show_request` entirely.

### C. `dispatch_handler.py` (The Brain Caller)
*   **Responsibility**: Decides *which* Pydantic agent to call (Support vs Payment) and executes it.
*   **Contract**: `async execute_llm(state: dict, user_msg: str, deps: AgentDeps) -> SupportResponse`
*   **Logic**:
    *   Handles the `if STATE_5: run_payment else: run_support` switch.
    *   Handles normalizaton of `PaymentResponse` -> `SupportResponse`.
    *   **Crucial**: Returns strict `SupportResponse`.

### D. `cart_handler.py` (The Cart Manager)
*   **Responsibility**: Merges new products from LLM into existing cart.
*   **Contract**: `merge_cart(current: list[dict], new: list[dict], strictly_additive: bool) -> list[dict]`
*   **Logic**: The complex deduplication loop + the logic "In STATE_5 only add if explicit intent".

### E. `transition_handler.py` (The State Referee)
*   **Responsibility**: Finalizes the state transition using SSOT Reducer.
*   **Contract**: `finalize_transition(state: dict, llm_response: SupportResponse, user_msg: str) -> dict`
*   **Logic**: Applies `compute_transition`, handles `preserve_state` overrides, updates `step_number`.

## 2. 🛡️ Verification Strategy (Ironclad)

### Unit Tests (`tests/unit/nodes/handlers/`)
1.  **`test_cart_handler.py`**:
    *   Test: Add duplicate -> No change.
    *   Test: Add unique -> Appended.
    *   Test: `strictly_additive=True` (Payment Phase) -> Ignores implicit adds.
2.  **`test_dispatch_handler.py`**:
    *   Test: Mock `STATE_5` state -> verify `run_payment` called.
    *   Test: Mock `STATE_1` state -> verify `run_support` called.

### Integration
*   **Regression**: Run `tests/unit/test_agent_edge_cases.py` (existing suite) to ensure the refactored `agent_node` behaves identically.

## 3. 📝 Execution Steps (The Runbook)

1.  **[CREATE]** `src/agents/langgraph/nodes/handlers/__init__.py`.
2.  **[MOVE]** Extract logic to `snippet_handler.py`, `color_handler.py`, `cart_handler.py`, `dispatch_handler.py`, `transition_handler.py`.
3.  **[TEST]** Run quick unit verification on handlers (inline or separate file).
4.  **[REWIRE]** Rewrite `agent.py` to import and compose these handlers.
5.  **[VERIFY]** Run full regression suite.

## 4. 🚫 Safety Rules
*   **NO** direct imports of `agent.py` inside handlers (Cyclic Import Risk).
*   **NO** global state mutation inside handlers. They must return new state/dict.
*   **NO** `try...except pass` in handlers. Fail loudly or return structured error.

---
**Approvals**:
- [ ] User Approval (Implicit in "Go ahead")
