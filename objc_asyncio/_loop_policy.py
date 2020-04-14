import asyncio
import threading

from ._loop import PyObjCEventLoop


class PyObjCEventLoopPolicy(asyncio.AbstractEventLoopPolicy):
    _loop_factory = PyObjCEventLoop

    class _Local(threading.local):
        _loop = None
        _set_called = False

    def __init__(self):
        self._local = self._Local()
        self._watcher = None

    def get_event_loop(self):
        """Get the event loop for the current context.

        Returns an instance of EventLoop or raises an exception.
        """
        if (
            self._local._loop is None
            and not self._local._set_called
            and threading.current_thread() is threading.main_thread()
        ):
            self.set_event_loop(self.new_event_loop())

        if self._local._loop is None:
            raise RuntimeError(
                "There is no current event loop in thread %r."
                % threading.current_thread().name
            )

        return self._local._loop

    def set_event_loop(self, loop):
        """Set the event loop.

        As a side effect, if a child watcher was set before, then calling
        .set_event_loop() from the main thread will call .attach_loop(loop) on
        the child watcher.
        """
        self._local._set_called = True
        assert loop is None or isinstance(loop, asyncio.AbstractEventLoop)
        self._local._loop = loop

        if (
            self._watcher is not None
            and threading.current_thread() is threading.main_thread()
        ):
            self._watcher.attach_loop(loop)

    def new_event_loop(self):
        """Create a new event loop.

        You must call set_event_loop() to make this the current event
        loop.
        """
        return self._loop_factory()

    def _init_watcher(self):
        # with asyncio._lock: # XXX
        if self._watcher is None:  # pragma: no branch
            self._watcher = asyncio.ThreadedChildWatcher()
            if threading.current_thread() is threading.main_thread():
                self._watcher.attach_loop(self._local._loop)

    def get_child_watcher(self):
        """Get the watcher for child processes.

        If not yet set, a ThreadedChildWatcher object is automatically created.
        """
        if self._watcher is None:
            self._init_watcher()

        return self._watcher

    def set_child_watcher(self, watcher):
        """Set the watcher for child processes."""

        assert watcher is None or isinstance(watcher, asyncio.AbstractChildWatcher)

        if self._watcher is not None:
            self._watcher.close()

        self._watcher = watcher
