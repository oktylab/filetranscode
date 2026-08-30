from importlib.metadata import entry_points

from .core.core import Registry

registry: Registry = Registry()


def load_plugins() -> None:
    for ep in entry_points(group="filetranscode.plugins"):
        ep.load()
