__all__ = "EventLoop"

import asyncio
import collections
import contextlib
import heapq
import os
import sys
import warnings
import weakref
from asyncio.unix_events import _UnixReadPipeTransport as PyObjCReadPipeTransport
from asyncio.unix_events import _UnixWritePipeTransport as PyObjCWritePipeTransport

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

# Minimum number of _scheduled timer handles before cleanup of
# cancelled handles is performed.
_MIN_SCHEDULED_TIMER_HANDLES = 100

# Minimum fraction of _scheduled timer handles that are cancelled
# before cleanup of cancelled handles is performed.
_MIN_CANCELLED_TIMER_HANDLES_FRACTION = 0.5


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


def _run_until_complete_cb(fut):
    if not fut.cancelled():
        exc = fut.exception()
        if isinstance(exc, (SystemExit, KeyboardInterrupt)):
            # Issue #22429: run_forever() already finished, no need to
            # stop it.
            return

    fut.get_loop().stop()


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
       eventloop in the default mode (when using a
       helper function).
    """

    def __init__(self):
        self._loop = CFRunLoopGetCurrent()

        self._observer = CFRunLoopObserverCreateWithHandler(
            None, kCFRunLoopBeforeTimers, True, 0, self._observer_loop
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
        self._timer_cancelled_count = 0
        self._exception = None

        self._task_factory = None
        self._exception_handler = None

        # This mirrors how asyncio detects debug mode
        self._debug = sys.flags.dev_mode or (
            not sys.flags.ignore_environment
            and bool(os.environ.get("PYTHONASYNCIODEBUG"))
        )

        self._internal_fds = 0
        # self._make_self_pipe()

        # In debug mode, if the execution of a callback or a step of a task
        # exceed this duration in seconds, the slow callback/task is logged.
        self.slow_callback_duration = 0.1

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
        try:

            if activity == kCFRunLoopBeforeTimers:
                timer_count = len(self._timer_q)
                if (
                    timer_count > _MIN_SCHEDULED_TIMER_HANDLES
                    and self._timer_cancelled_count / timer_count
                    > _MIN_CANCELLED_TIMER_HANDLES_FRACTION
                ):
                    # Remove delayed calls that were cancelled if their number
                    # is too high
                    new_timer_q = []
                    for handle in self._timer_q:
                        if handle._cancelled:
                            handle._scheduled = False
                        else:
                            new_timer_q.append(handle)

                    heapq.heapify(new_timer_q)
                    self._new_timer_q = new_timer_q
                    self._timer_cancelled_count = 0
                else:
                    # Remove delayed calls that were cancelled from head of queue.
                    while self._timer_q and self._timer_q[0]._cancelled:
                        self._timer_cancelled_count -= 1
                        handle = heapq.heappop(self._timer_q)
                        handle._scheduled = False

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

        except (KeyboardInterrupt, SystemExit) as exc:
            CFRunLoopStop(self._loop)
            self._exception = exc

        except:  # noqa: E722, B001
            logger.info("Unexpected exception", exc_info=True)

    def _add_callback(self, handle):
        """Add a Handle to _scheduled (TimerHandle) or _ready."""
        assert isinstance(handle, asyncio.Handle), "A Handle is required here"
        if handle._cancelled:
            return
        assert not isinstance(handle, asyncio.TimerHandle)
        self._ready.append(handle)

    # Running and stopping the loop

    def run_until_complete(self, future):
        self._check_closed()
        # self._check_running()

        new_task = not asyncio.isfuture(future)
        future = asyncio.ensure_future(future, loop=self)
        if new_task:
            # An exception is raised if the future didn't complete, so there
            # is no need to log the "destroy pending task" message
            future._log_destroy_pending = False
        future.add_done_callback(_run_until_complete_cb)

        try:
            self.run_forever()
        except:  # noqa: E722, B001
            if new_task and future.done() and not future.cancelled():
                # The coroutine raised a BaseException. Consume the exception
                # to not log a warning, the caller doesn't have access to the
                # local task.
                future.exception()
            raise

        finally:
            future.remove_done_callback(_run_until_complete_cb)

        if not future.done():
            raise RuntimeError("Event loop stopped before Future completed")

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

    @contextlib.contextmanager
    def _running_loop(self):
        # The setup and teardown code for run_forever
        # is split off into a contextmanager to be
        # able to reuse this code in GUI applications
        # (see the running_loop context manager
        # in ._helpers.
        old_agen_hooks = sys.get_asyncgen_hooks()
        sys.set_asyncgen_hooks(
            firstiter=self._asyncgen_firstiter_hook,
            finalizer=self._asyncgen_finalizer_hook,
        )
        self._running = True
        asyncio._set_running_loop(self)

        try:
            yield

        finally:
            self._running = False
            asyncio._set_running_loop(None)
            sys.set_asyncgen_hooks(*old_agen_hooks)

        if self._exception is not None:
            exc = self._exception
            self._exception = None
            raise exc

    def run_forever(self):
        with self._running_loop():
            CFRunLoopRun()

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

        SignalMixin.close(self)
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
                continue

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
        protocol = protocol_factory()
        waiter = self.create_future()
        transport = PyObjCReadPipeTransport(self, pipe, protocol, waiter, None)

        try:
            await waiter
        except:  # noqa: E722, B001
            transport.close()
            raise

        if self._debug:
            logger.debug(
                "Read pipe %r connected: (%r, %r)", pipe.fileno(), transport, protocol
            )
        return transport, protocol

    async def connect_write_pipe(self, protocol_factory, pipe):
        protocol = protocol_factory()
        waiter = self.create_future()
        transport = PyObjCWritePipeTransport(self, pipe, protocol, waiter, None)

        try:
            await waiter
        except:  # noqa: E722, B001
            transport.close()
            raise

        if self._debug:
            logger.debug(
                "Write pipe %r connected: (%r, %r)", pipe.fileno(), transport, protocol
            )
        return transport, protocol

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
