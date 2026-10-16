#!/bin/sh
# Start the property register. No dependencies beyond Python 3.7+, unless .env
# points it at Postgres / Supabase: then it uses the driver installed in .venv.
cd "$(dirname "$0")" || exit 1
PYTHON=python3
[ -x .venv/bin/python3 ] && PYTHON=.venv/bin/python3
exec "$PYTHON" -m server.app --port "${PORT:-8000}" --host "${HOST:-127.0.0.1}"
