#!/bin/sh
# Start the property register. No dependencies beyond Python 3.7+.
cd "$(dirname "$0")" || exit 1
exec python3 -m server.app --port "${PORT:-8000}" --host "${HOST:-127.0.0.1}"
