# Observability + Runbook (Production)

This runbook lists the key signals and what to do when things go wrong.

## Core signals to watch

- `manychat_time_budget_exceeded`
  - Meaning: request exceeded ManyChat time budget.
  - Action: check checkpointer timings and LLM latency; verify state size caps.

- `[CHECKPOINTER] aget_tuple/aput/aput_writes ... took ...`
  - Meaning: Postgres checkpointer is slow.
  - Action: confirm pooler URL, pool sizes, and state compaction.

- `[CHECKPOINTER] pool opened on demand`
  - Meaning: pool is opening lazily or reopening.
  - Action: verify warmup and pool sizes; check connection limits.

- `vision invalid_image_url` / `Timeout while downloading`
  - Meaning: CDN or image URL is not reachable.
  - Action: verify media proxy, allowlist, CDN health.

- `state_messages_trimmed` (metric)
  - Meaning: state history is being capped.
  - Action: confirm `STATE_MAX_MESSAGES` is set to a safe value.

## Recommended limits (baseline)

- `STATE_MAX_MESSAGES=100`
- `LLM_MAX_HISTORY_MESSAGES=20`
- `CHECKPOINTER_MAX_MESSAGES=200`
- `CHECKPOINTER_MAX_MESSAGE_CHARS=4000`
- `CHECKPOINTER_DROP_BASE64=true`

## Triage steps

1) Check if the issue is LLM latency or checkpointer latency.
2) If checkpointer is slow, lower pool sizes and verify pooler.
3) If state is large, enforce caps and verify compaction.
4) If vision fails, use media proxy and validate image URLs.

## Escalation decision

- If >5% of requests hit budget timeouts: reduce payload size and raise alerts.
- If checkpointer has >2s spikes: reduce pool size and confirm pooler.
- If repeated vision errors: switch to proxy or disable vision for that source.
