__all__ = "EventLoop"

import asyncio
import collections
import heapq
import os
import sys
import warnings
import weakref

from Cocoa import (
    CFAbsoluteTimeGetCurrent,
    CFRunLoopAddObserver,
    CFRunLoopAddTimer,
    CFRunLoopGetCurrent,
    CFRunLoopObserverCreateWithHandler,
    CFRunLoopRemoveObserver,
    CFRunLoopRemoveTimer,
    CFRunLoopRun,
    CFRunLoopStop,
    CFRunLoopTimerCreateWithHandler,
    CFRunLoopTimerGetNextFireDate,
    CFRunLoopTimerInvalidate,
    CFRunLoopTimerSetNextFireDate,
    CFRunLoopWakeUp,
    kCFRunLoopBeforeTimers,
    kCFRunLoopCommonModes,
    kCFRunLoopEntry,
    kCFRunLoopExit,
)

from ._exceptionhandler import ExceptionHandlerMixin
from ._executor import ExecutorMixin
from ._log import logger
from ._resolver import ResolverMixin
from ._signals import SignalMixin
from ._sockets import SocketMixin
from ._subprocess import SubprocessMixin

_unset = object()
_POSIX_TO_CFTIME = 978307200
_EPSILON = 1e-6


def posix2cftime(posixtime):
    """ Convert a POSIX timestamp to a CFAbsoluteTime timestamp """
    return posixtime - _POSIX_TO_CFTIME


def cftime2posix(cftime):
    """ Convert a CFAbsoluteTime timestamp to a POSIX timestamp """
    return cftime + _POSIX_TO_CFTIME


def _format_handle(handle):
    cb = handle._callback
    if isinstance(getattr(cb, "__self__", None), asyncio.Task):
        # format the task
        return repr(cb.__self__)
    else:
        return str(handle)


class PyObjCEventLoop(
    SocketMixin,
    ExecutorMixin,
    ResolverMixin,
    ExceptionHandlerMixin,
    SubprocessMixin,
    SignalMixin,
    asyncio.AbstractEventLoop,
):
    """
    An asyncio eventloop that uses a Cocoa eventloop

    There are two ways of running the loop:

    1) Use the standard asyncio eventloop API
    2) Implicitly run the loop by running the Cocoa
       eventloop in the default mode.
    """

    def __init__(self):
        self._loop = CFRunLoopGetCurrent()

        # Add a runloop observer to detect if the loop is active to ensure
        # the EventLoop is running when the CFRunLoop is active, even if
        # it is started by other code.
        self._observer = CFRunLoopObserverCreateWithHandler(
            None,
            kCFRunLoopEntry | kCFRunLoopExit | kCFRunLoopBeforeTimers,
            True,
            0,
            self._observer_loop,
        )
        CFRunLoopAddObserver(self._loop, self._observer, kCFRunLoopCommonModes)

        self._thread = None
        self._running = False
        self._closed = False
        self._timer = None
        self._timer_q = []
        self._transports = weakref.WeakValueDictionary()
        self._asyncgens = weakref.WeakSet()
        self._asyncgens_shutdown_called = False
        self._ready = collections.deque()
        self._current_handle = None

        self._task_factory = None
        self._exception_handler = None

        # This mirrors how asyncio detects debug mode
        self._debug = sys.flags.dev_mode or (
            not sys.flags.ignore_environment
            and bool(os.environ.get("PYTHONASYNCIODEBUG"))
        )

        self._internal_fds = 0
        # self._make_self_pipe()

        ExceptionHandlerMixin.__init__(self)
        ExecutorMixin.__init__(self)
        SocketMixin.__init__(self)
        SignalMixin.__init__(self)

    def __del__(self, _warn=warnings.warn):
        if self._observer is not None:
            CFRunLoopRemoveObserver(self._loop, self._observer, kCFRunLoopCommonModes)

        if not self.is_closed():
            _warn(f"unclosed event loop {self!r}", ResourceWarning, source=self)
            if not self.is_running():
                self.close()

    def get_debug(self):
        return self._debug

    def set_debug(self, enabled):
        self._debug = bool(enabled)

    def _observer_loop(self, observer, activity):
        if activity == kCFRunLoopEntry:
            self._running = True
            asyncio._set_running_loop(self)

        elif activity == kCFRunLoopExit:
            self._running = False
            asyncio._set_running_loop(None)

        elif activity == kCFRunLoopBeforeTimers:
            # This is the only place where callbacks are actually *called*.
            # All other places just add them to ready.
            # Note: We run all currently scheduled callbacks, but not any
            # callbacks scheduled by callbacks run this time around --
            # they will be run the next time (after another I/O poll).
            # Use an idiom that is thread-safe without using locks.
            ntodo = len(self._ready)
            for _ in range(ntodo):
                handle = self._ready.popleft()
                if handle._cancelled:
                    continue
                if self._debug:
                    try:
                        self._current_handle = handle
                        t0 = self.time()
                        handle._run()
                        dt = self.time() - t0
                        if dt >= self.slow_callback_duration:
                            logger.warning(
                                "Executing %s took %.3f seconds",
                                _format_handle(handle),
                                dt,
                            )
                    finally:
                        self._current_handle = None
                else:
                    handle._run()
            handle = None  # Needed to break cycles when an exception occurs.

    def _add_callback(self, handle):
        """Add a Handle to _scheduled (TimerHandle) or _ready."""
        assert isinstance(handle, asyncio.Handle), "A Handle is required here"
        if handle._cancelled:
            return
        assert not isinstance(handle, asyncio.TimerHandle)
        self._ready.append(handle)

    # Running and stopping the loop

    def run_until_complete(self, future):
        future.add_done_callback(lambda _: self.stop())
        self.run_forever()

        return future.result()

    def _asyncgen_firstiter_hook(self, agen):
        if self._asyncgens_shutdown_called:
            warnings.warn(
                f"asynchronous generator {agen!r} was scheduled after "
                f"loop.shutdown_asyncgens() call",
                ResourceWarning,
                source=self,
            )

        self._asyncgens.add(agen)

    def _asyncgen_finalizer_hook(self, agen):
        self._asyncgens.discard(agen)
        if not self.is_closed():
            self.call_soon_threadsafe(self.create_task, agen.aclose())

    def run_forever(self):
        old_agen_hooks = sys.get_asyncgen_hooks()
        sys.set_asyncgen_hooks(
            firstiter=self._asyncgen_firstiter_hook,
            finalizer=self._asyncgen_finalizer_hook,
        )
        try:
            CFRunLoopRun()
        finally:
            sys.set_asyncgen_hooks(*old_agen_hooks)

    def stop(self):
        CFRunLoopStop(self._loop)

    def is_running(self):
        # XXX: This should also return true if the Cocoa
        # runloop is active due to some other reason.
        #
        return self._running

    def _check_closed(self):
        if self._closed:
            raise RuntimeError("Event loop is closed")

    def is_closed(self):
        return self._closed

    def close(self):
        if self._running:
            raise RuntimeError

        if self._closed:
            return

        if self._timer_q:
            # Cancel timers?
            ...

        if self._timer is not None:
            CFRunLoopRemoveTimer(self._loop, self._timer, kCFRunLoopCommonModes)
            CFRunLoopTimerInvalidate(self._timer)
            self._timer = None

        self._closed = True

        ExecutorMixin.close(self)
        SocketMixin.close(self)

    async def shutdown_asyncgens(self):
        """Shutdown all active asynchronous generators."""
        self._asyncgens_shutdown_called = True

        if not len(self._asyncgens):
            # If Python version is <3.6 or we don't have any asynchronous
            # generators alive.
            return

        closing_agens = list(self._asyncgens)
        self._asyncgens.clear()

        results = await asyncio.gather(
            *[ag.aclose() for ag in closing_agens], return_exceptions=True, loop=self
        )

        for result, agen in zip(results, closing_agens):
            if isinstance(result, Exception):
                self.call_exception_handler(
                    {
                        "message": f"an error occurred during closing of "
                        f"asynchronous generator {agen!r}",
                        "exception": result,
                        "asyncgen": agen,
                    }
                )

    # Scheduling callbacks

    def call_soon(self, callback, *args, context=None):
        handle = asyncio.Handle(callback, args, self, context)
        self._ready.append(handle)
        CFRunLoopWakeUp(self._loop)
        return handle

    def call_soon_threadsafe(self, callback, *args, context=None):
        handle = asyncio.Handle(callback, args, self, context)
        self._ready.append(handle)
        CFRunLoopWakeUp(self._loop)
        return handle

    # Scheduling delayed callbacks

    def call_later(self, delay, callback, *args, context=None):
        return self.call_at(self.time() + delay, callback, *args, context=context)

    def _process_timer(self):
        while self._timer_q and self._timer_q[0].when() <= self.time() + _EPSILON:
            handle = heapq.heappop(self._timer_q)
            if handle.cancelled():
                return

            handle._run()

        if self._timer_q:
            CFRunLoopTimerSetNextFireDate(
                self._timer, posix2cftime(self._timer_q[0].when())
            )

    def call_at(self, when, callback, *args, context=None):
        cfwhen = posix2cftime(when)
        if self._timer is None:
            self._timer = CFRunLoopTimerCreateWithHandler(
                None, cfwhen, 1000.0, 0, 0, lambda timer: self._process_timer()
            )
            CFRunLoopAddTimer(self._loop, self._timer, kCFRunLoopCommonModes)

        handle = asyncio.TimerHandle(when, callback, args, self, context=context)
        heapq.heappush(self._timer_q, handle)

        if CFRunLoopTimerGetNextFireDate(self._timer) > posix2cftime(
            self._timer_q[0].when()
        ):
            CFRunLoopTimerSetNextFireDate(
                self._timer, posix2cftime(self._timer_q[0].when())
            )

        return handle

    def time(self):
        return cftime2posix(CFAbsoluteTimeGetCurrent())

    # Creating Futures and Tasks
    def create_future(self):
        return asyncio.Future(loop=self)

    def create_task(self, coro, *, name=None):
        if self._task_factory is not None:
            task = self._task_factory(self, coro)
            if name is not None:
                task.set_name(name)
            return task

        else:
            return asyncio.Task(coro, loop=self, name=name)

    def set_task_factory(self, factory):
        if factory is not None and not callable(factory):
            raise TypeError("task factory must be a callable or None")
        self._task_factory = factory

    def get_task_factory(self):
        return self._task_factory

    # Working with pipes

    async def connect_read_pipe(self, protocol_factory, pipe):
        raise NotImplementedError(22)

    async def connect_write_pipe(self, protocol_factory, pipe):
        raise NotImplementedError(23)

    # Executing code in thread or process pools

    def _timer_handle_cancelled(self, handle):
        if handle._scheduled:
            self._timer_cancelled_count += 1

    def _check_callback(self, callback, method):
        if asyncio.iscoroutine(callback) or asyncio.iscoroutinefunction(callback):
            raise TypeError(f"coroutines cannot be used with {method}()")
        if not callable(callback):
            raise TypeError(
                f"a callable object was expected by {method}(), " f"got {callback!r}"
            )
