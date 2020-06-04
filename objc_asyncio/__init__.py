"""
Main library
"""

__all__ = ("EventLoop",)
__version__ = "0.1"

from ._helpers import IBAction  # noqa: F401
from ._loop import PyObjCEventLoop  # noqa: F401
from ._loop_policy import PyObjCEventLoopPolicy  # noqa: F401
from ._subprocess import KQueueChildWatcher  # noqa: F401
