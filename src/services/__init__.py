"""
Mirt-AI Service Layer.
======================

This directory contains the core business logic and infrastructure services
of the application.

Services Breakdown:
-------------------

1.  **Infrastructure (Foundation):**
    - `common`: Exception definitions (Error Contract).
    - `storage`: PostgreSQL connection pool & DAL interfaces.
    - `observability`: Tracing, Metrics, Cost Calculation (Billing).
    - `notifications`: Telegram alerts for managers (Escalations).

2.  **Product & Commerce:**
    - `catalog`: Product search, Price validation (SSOT).
    - `orders`: Order models & Validation logic.

3.  **Conversation Management:**
    - `conversation`: Orchestrator for chat flows.
    - `session`: Session state management (The "Librarian").
    - `memory`: Long-term user memory (Facts, Summarization).
    - `parser`: Adapters for LLM outputs.
    - `guardrails`: Safety mechanisms (Loop detection).
    - `moderation`: PII & Injection protection.
    - `summarization`: Background conversation compression.

4.  **Integration:**
    - `webhook`: ManyChat integration entry point (The "Bouncer").

Usage:
------
Import services directly from their submodules to avoid circular dependencies:
>>> from src.services.catalog import CatalogService
>>> from src.services.session import SessionManager
"""
