"""The property register.

Settings come from the environment. A `.env` file beside run.sh (KEY=value per
line; never committed) is read first, so the server, `server.reset` and
`server.import_sqlite` all see the same database. A variable already set in
the environment wins over the file.
"""

import os

_ENV_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")

if os.path.isfile(_ENV_FILE):
    with open(_ENV_FILE, encoding="utf-8") as _fh:
        for _line in _fh:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _key, _value = _line.split("=", 1)
            _value = _value.strip()
            if len(_value) >= 2 and _value[0] == _value[-1] and _value[0] in "\"'":
                _value = _value[1:-1]
            os.environ.setdefault(_key.strip(), _value)
