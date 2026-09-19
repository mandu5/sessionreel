"""sessionreel: turn a coding-agent session log into a short recap video."""
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("sessionreel")
except PackageNotFoundError:  # running from a source checkout
    __version__ = "0.0.0+dev"
