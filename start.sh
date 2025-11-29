#!/bin/sh
exec uvicorn src.server.main:app --host 0.0.0.0 --port ${PORT:-8000}
