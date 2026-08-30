import re
from urllib.parse import urlsplit, urlunsplit

_URL_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s'\"]+")
_TRAILING_PUNCTUATION = ".,;:)]}"


def _scrub(text: str) -> str:
    """Strips the query/fragment off any URL embedded in text, so a resolver-provided
    credential (e.g. a presigned S3 GET signature) never lands in an error message,
    a log line, or a trace. Applies to any URL scheme, not just S3."""

    def strip(match: re.Match) -> str:
        raw = match.group(0)
        trail = ""
        while raw and raw[-1] in _TRAILING_PUNCTUATION:
            trail = raw[-1] + trail
            raw = raw[:-1]
        parts = urlsplit(raw)
        if not (parts.query or parts.fragment):
            return match.group(0)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")) + trail

    return _URL_PATTERN.sub(strip, text)


class ProbeError(Exception):
    def __init__(self, path: str, reason: str) -> None:
        path, reason = _scrub(path), _scrub(reason)
        super().__init__(f"cannot probe {path!r}: {reason}")
        self.path = path
        self.reason = reason


class UnsatisfiableError(Exception):
    pass


class EngineError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(_scrub(message))
