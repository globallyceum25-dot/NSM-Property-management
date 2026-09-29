"""A small multipart/form-data parser.

The stdlib `cgi.FieldStorage` would do this, but it is deprecated and removed in
Python 3.13, so we parse the handful of parts we need ourselves.
"""

import re

_DISPOSITION_NAME = re.compile(r'name="([^"]*)"')
_DISPOSITION_FILENAME = re.compile(r'filename="([^"]*)"')


class Part(object):
    __slots__ = ("name", "filename", "content_type", "data")

    def __init__(self, name, filename, content_type, data):
        self.name = name
        self.filename = filename
        self.content_type = content_type
        self.data = data

    @property
    def text(self):
        return self.data.decode("utf-8", "replace")

    @property
    def is_file(self):
        return self.filename is not None and self.filename != ""


def boundary_from_content_type(content_type):
    if not content_type:
        return None
    for chunk in content_type.split(";"):
        chunk = chunk.strip()
        if chunk.lower().startswith("boundary="):
            value = chunk[len("boundary="):].strip()
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            return value.encode("ascii")
    return None


def parse(body, content_type):
    """Return {field_name: Part}.  Raises ValueError on malformed input."""
    boundary = boundary_from_content_type(content_type)
    if not boundary:
        raise ValueError("missing multipart boundary")

    delimiter = b"--" + boundary
    segments = body.split(delimiter)
    # segments[0] is the preamble, the last one is the "--\r\n" epilogue.
    parts = {}
    for segment in segments[1:]:
        if segment[:2] == b"--":          # closing delimiter
            break
        if segment[:2] == b"\r\n":
            segment = segment[2:]
        head, sep, data = segment.partition(b"\r\n\r\n")
        if not sep:
            continue
        if data.endswith(b"\r\n"):
            data = data[:-2]

        name = None
        filename = None
        ctype = "application/octet-stream"
        for line in head.decode("utf-8", "replace").split("\r\n"):
            lowered = line.lower()
            if lowered.startswith("content-disposition:"):
                m = _DISPOSITION_NAME.search(line)
                if m:
                    name = m.group(1)
                m = _DISPOSITION_FILENAME.search(line)
                if m:
                    filename = m.group(1)
            elif lowered.startswith("content-type:"):
                ctype = line.split(":", 1)[1].strip()
        if name is None:
            continue
        parts[name] = Part(name, filename, ctype, data)
    return parts
