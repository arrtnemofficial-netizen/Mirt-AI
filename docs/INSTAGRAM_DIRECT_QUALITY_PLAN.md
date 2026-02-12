# Instagram Direct Quality Plan (Production)

## Goal

Deliver stable, high-quality handling of **all realistic Instagram Direct scenarios** with predictable behavior, measurable quality, and safe fallbacks.

## 1) Scope

### In Scope
- Incoming text messages (single and burst sequence).
- Image message handling (vision branch).
- Product discovery, sizing, payment, delivery, follow-up.
- Out-of-domain and complaint flows.
- Human handoff for ambiguity/high-risk intent.

### Out of Scope (explicit)
- Unsupported media types without parser (voice/video) until dedicated handlers are implemented.
- Fully autonomous handling of legally sensitive cases without manager escalation.

## 2) Data Contract for Instagram Direct Inbound

All inbound events should normalize to one internal model:

```json
{
  "channel": "instagram",
  "user_id": "string",
  "session_id": "string",
  "message_id": "string",
  "timestamp": "iso-8601",
  "message": {
    "type": "text|image|unsupported",
    "text": "string|null",
    "media_url": "https-url|null"
  },
  "metadata": {
    "locale": "uk|ru|en|unknown",
    "source": "manychat|native|other"
  }
}
```

### Invariants
- `session_id`, `message_id`, `user_id` are always present.
- Duplicate `message_id` is idempotent (no duplicated outbound message).
- `message.type` is always one of the allowed enum values.
- `media_url` is required if `message.type=image`.

### Invalid Input Policy
- Missing mandatory IDs -> reject and log structured error.
- Unknown message type -> route to safe fallback text + mark as `unsupported`.
- Too long text (> configured max) -> truncate safely and add metadata flag.

## 3) Target Architecture for Quality

## 3.1 Domain Layer
- Intent detection and state transitions (pure functions).
- Output contract validation (strict schema).
- Escalation policy (risk-based).

## 3.2 Application Layer
- Inbound normalizer.
- Orchestrator (router -> node -> validation -> outbound adapter).
- Retry-safe command processing with idempotency keys.

## 3.3 Infrastructure Layer
- Webhook controller (ManyChat/Instagram adapters).
- Session store + dedupe store.
- Metrics, logs, traces, alerting.

## 4) Reliability Controls (must-have)

1. **Idempotency**
   - Key: `channel:user_id:message_id`.
   - Duplicate inbound events return `already_processed` and do not resend business output.

2. **Timeouts + Retry**
   - LLM call timeout (hard limit).
   - External API retry with exponential backoff and max attempts.
   - Circuit breaker for repeated upstream failures.

3. **Fallbacks**
   - If agent result fails schema validation -> fallback template + escalation flag.
   - If vision fails -> ask for text clarification.

4. **Safe Escalation**
   - Payment/complaint/ambiguous personal data cases route to manager queue.

## 5) Quality Gates before Production

### Gate A: Contract Safety
- 100% outbound messages must pass schema validation.
- 0 unhandled exceptions in webhook path.

### Gate B: Regression Safety
- Golden flow suite must pass for text + image + payment + complaint.
- Snapshot tests for routing decisions on high-risk intents.

### Gate C: Operational Safety
- p95 response latency under target.
- Alerting enabled for error-rate and timeout-rate.

## 6) Test Matrix (minimum)

## 6.1 Normal Scenarios
1. Greeting -> discovery -> product suggestion.
2. Size question -> correct size guidance.
3. Payment + delivery -> valid checkout instruction.

## 6.2 Edge Scenarios
1. Empty text.
2. Burst of 3-5 rapid messages.
3. Duplicate webhook with same `message_id`.
4. Mixed locale input (uk/ru in one thread).

## 6.3 Invalid/Adversarial
1. Unsupported media type.
2. Malformed JSON payload.
3. Prompt injection attempt in user text.
4. External API timeout during product lookup.

## 7) Rollout Strategy

1. Shadow mode (observe only, no user-visible changes).
2. 10% traffic canary.
3. 50% traffic with daily quality review.
4. 100% after 7 days stable SLO.

## 8) KPIs for "quality in any case"

- Intent accuracy on labeled Instagram set.
- Escalation precision (not too low, not too noisy).
- First-response success rate.
- p95 end-to-end latency.
- User re-contact rate within 24h for unresolved issues.

## 9) Practical Definition of Done

System is "ready" only if:
- Critical Instagram flows are covered by automated tests.
- Every failure path has deterministic fallback.
- On-call can diagnose any failed conversation via logs + trace ID in <5 minutes.
