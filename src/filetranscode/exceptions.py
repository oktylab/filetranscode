class ProbeError(Exception):
    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"cannot probe {path!r}: {reason}")
        self.path = path
        self.reason = reason


class UnsatisfiableError(Exception):
    pass


class EngineError(Exception):
    pass
