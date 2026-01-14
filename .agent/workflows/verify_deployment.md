---
description: Verify System Architecture before Deployment
---

# Verify Architecture

Run this check BEFORE deploying or starting the server to catch "State/Dict" mismatches and missing fields.

1. Run the verifier:
```bash
python tests/verify_architecture.py
```
// turbo

If this passes, your Pydantic Models and LangGraph Dictionaries are in sync.
