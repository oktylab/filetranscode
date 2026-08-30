#############################################################
#############################################################
class NodeNotFound(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"no node registered as {name!r}")
        self.name = name


#############################################################
#############################################################
class NoBranchMatched(Exception):
    def __init__(self, key: str, available: tuple[str, ...]) -> None:
        super().__init__(f"no branch for {key!r}; available: {available}")
        self.key = key
        self.available = available
