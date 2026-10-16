#!/bin/sh
# Wait for a register to answer, then check it serves the expected number of
# properties.   Usage: wait-for-register.sh BASE_URL EXPECTED_PROPERTIES
set -eu
base=$1
expected=$2

i=0
until curl -fsS "$base/api/reference" > /dev/null 2>&1; do
    i=$((i + 1))
    if [ "$i" -ge 30 ]; then
        echo "No answer from $base after 30 seconds." >&2
        exit 1
    fi
    sleep 1
done

count=$(curl -fsS "$base/api/properties" | python3 -c 'import json, sys; print(len(json.load(sys.stdin)))')
if [ "$count" != "$expected" ]; then
    echo "Expected $expected properties at $base, got $count." >&2
    exit 1
fi
echo "$base serves $count properties."
