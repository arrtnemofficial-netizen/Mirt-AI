# Architecture Rules

This project follows strict separation of concerns. These rules are required for maintainability and to avoid circular imports.

## Folder Responsibilities
- src/services/domain
  Business logic for a specific feature (payment, vision, memory). No framework or transport code.
- src/services/infra
  External systems (DB clients, HTTP clients, queues, notifications). No business rules.
- src/services/core
  Cross-cutting utilities (observability, moderation, registry, parsing). No feature-specific rules.
- src/services/data
  Data models and storage adapters (schemas, mappers).
- src/agents
  Orchestration and AI agents. Agents can call services, never the other way around.

## Import Rules
- services/* MUST NOT import from agents/*.
- domain/* MAY import core/* and infra/*, but not agents/*.
- infra/* MUST NOT import domain/*.
- data/* MUST NOT import agents/*.

## Prompt Rules
- All user-facing text belongs in data/prompts/system/*.
- Code must use PromptRegistry or load_yaml_from_registry for text.
- No hardcoded user-facing strings in src/*.py.

## Migration Policy
- Legacy compatibility is allowed only with explicit flags (e.g., ENABLE_LEGACY_STATE_ALIASES).
- Remove legacy paths once usage drops to zero.
