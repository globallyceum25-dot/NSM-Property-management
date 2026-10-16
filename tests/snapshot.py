"""Write the answers of every read endpoint, on fresh sample data, to a JSON file.

    python3 -m tests.snapshot OUT.json

Used by test_postgres to run the same requests on SQLite and on Postgres (each
in its own process, since the database is chosen at import) and compare.
"""

import json
import sys

from server import api, db

from .support import load_sample_data

REQUESTS = [
    ("/api/sbus", {}), ("/api/legal-entities", {}), ("/api/locations", {}),
    ("/api/properties", {}), ("/api/properties", {"q": "colombo"}),
    ("/api/properties", {"q": "OUTLET"}), ("/api/properties", {"sbu_id": "1,2,3"}),
    ("/api/properties", {"has_deed": "0"}), ("/api/properties", {"has_deed": "1"}),
    ("/api/properties", {"legal_entity_id": "none"}), ("/api/properties", {"location_id": "3"}),
    ("/api/properties", {"has_renewal": "m3"}), ("/api/properties", {"has_renewal": "later"}),
    ("/api/properties", {"has_doc_type": "DEED"}), ("/api/properties", {"province": "Western"}),
    ("/api/properties", {"district": "Colombo", "status": "ACTIVE"}),
    ("/api/properties", {"ownership_type": "LEASEHOLD", "property_type": "WAREHOUSE"}),
    ("/api/properties/1", {}), ("/api/properties/10", {}), ("/api/properties/1/documents", {}),
    ("/api/documents", {}), ("/api/documents", {"q": "deed"}),
    ("/api/documents", {"doc_status": "expiring"}), ("/api/documents", {"doc_status": "nofile"}),
    ("/api/documents", {"sort": "expiry"}), ("/api/documents", {"sort": "title"}),
    ("/api/documents", {"sort": "sbu"}), ("/api/documents", {"sort": "property"}),
    ("/api/documents", {"doc_type": "LEASE_AGREEMENT", "district": "Gampaha"}),
    ("/api/documents/3", {}), ("/api/stats", {}), ("/api/stats", {"q": "a"}),
    ("/api/stats", {"has_renewal": "m12"}), ("/api/stats", {"legal_entity_id": "none"}),
    ("/api/stats", {"sbu_id": "2,3"}), ("/api/export/properties.csv", {}),
    ("/api/masters", {}), ("/api/masters/location", {}), ("/api/masters/location_code", {}),
    ("/api/masters/sbu", {}), ("/api/masters/legal_entity", {}),
]


class _Context(object):
    def __init__(self, match, query):
        self.match, self.query = match, query


def call(path, query):
    for method, pattern, handler in api.COMPILED_ROUTES:
        match = pattern.match(path)
        if match and method == "GET":
            try:
                status, payload = handler(_Context(match, dict(query)))
            finally:
                db.release()
            if isinstance(payload, dict) and payload.get("__raw__"):
                payload = payload["body"].decode("utf-8-sig")
            return [status, payload]
    raise KeyError(path)


def main():
    db.init_db()
    load_sample_data()
    answers = {path + "?" + json.dumps(query, sort_keys=True): call(path, query)
               for path, query in REQUESTS}
    with open(sys.argv[1], "w", encoding="utf-8") as fh:
        json.dump({"backend": db.describe(), "answers": answers}, fh)


if __name__ == "__main__":
    main()
