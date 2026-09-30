"""Shared API error type.

Lives in its own module so `masters.py` and `api.py` can both raise it without
importing each other.
"""


class ApiError(Exception):
    def __init__(self, message, status=400, field=None):
        Exception.__init__(self, message)
        self.message = message
        self.status = status
        self.field = field
