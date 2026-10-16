"""Tests for the property register.

    python3 -m unittest discover -s tests -t .

By default everything runs on SQLite in a temporary folder. Set
TEST_DATABASE_URL to a throwaway Postgres database to run the same tests on
Postgres; it is emptied and reseeded over and over. .env is ignored, so the
live register (local or Supabase) is never touched.
"""

import atexit
import os
import shutil
import tempfile
from urllib.parse import urlparse

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
if "supabase." in (urlparse(TEST_DATABASE_URL).hostname or ""):
    raise SystemExit("TEST_DATABASE_URL points at Supabase. The tests wipe their database: "
                     "use a throwaway Postgres instead.")

DATA_DIR = tempfile.mkdtemp(prefix="register-tests-")
atexit.register(shutil.rmtree, DATA_DIR, True)

# Set before `server` is imported. Its .env loader never overrides a variable
# that is already set, even to "", so these win over anything in .env.
os.environ.update({
    "DATABASE_URL": TEST_DATABASE_URL,
    "SUPABASE_URL": "",
    "SUPABASE_SERVICE_ROLE_KEY": "",
    "REGISTER_DATA_DIR": DATA_DIR,
})
