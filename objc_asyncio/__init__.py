"""
Main library
"""

__all__ = ("EventLoop",)
__version__ = "0.1"

from ._helpers import IBAction, install  # noqa: F401
from ._loop import EventLoop  # noqa: F401
