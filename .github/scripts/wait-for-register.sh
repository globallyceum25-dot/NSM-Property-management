#!/bin/sh
# Wait for a register to answer, then check it serves the expected number of
# properties.   Usage: wait-for-register.sh BASE_URL EXPECTED_PROPERTIES
# Signs in as REGISTER_ADMIN_EMAIL / REGISTER_ADMIN_PASSWORD, the account the
# container made for itself from the same variables.
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

jar=$(mktemp)
trap 'rm -f "$jar"' EXIT
if [ "$(curl -sS -o /dev/null -w '%{http_code}' "$base/api/properties")" != "401" ]; then
    echo "$base serves the register without signing in." >&2
    exit 1
fi
python3 -c 'import json, os; print(json.dumps({"email": os.environ["REGISTER_ADMIN_EMAIL"],
                                               "password": os.environ["REGISTER_ADMIN_PASSWORD"]}))' |
    curl -fsS -c "$jar" -H 'Content-Type: application/json' --data-binary @- \
        "$base/api/auth/login" > /dev/null

count=$(curl -fsS -b "$jar" "$base/api/properties" | python3 -c 'import json, sys; print(len(json.load(sys.stdin)))')
if [ "$count" != "$expected" ]; then
    echo "Expected $expected properties at $base, got $count." >&2
    exit 1
fi
echo "$base serves $count properties."
