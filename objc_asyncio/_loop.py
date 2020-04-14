__all__ = "EventLoop"

import asyncio
import heapq
import os
import signal
import ssl
import subprocess
import sys
import warnings
import weakref
from asyncio.unix_events import _UnixSubprocessTransport

from Cocoa import (
    CFAbsoluteTimeGetCurrent,
    CFRunLoopAddObserver,
    CFRunLoopAddTimer,
    CFRunLoopGetCurrent,
    CFRunLoopObserverCreateWithHandler,
    CFRunLoopPerformBlock,
    CFRunLoopRemoveObserver,
    CFRunLoopRemoveTimer,
    CFRunLoopRun,
    CFRunLoopStop,
    CFRunLoopTimerCreateWithHandler,
    CFRunLoopTimerGetNextFireDate,
    CFRunLoopTimerInvalidate,
    CFRunLoopTimerSetNextFireDate,
    CFRunLoopWakeUp,
    kCFRunLoopCommonModes,
    kCFRunLoopEntry,
    kCFRunLoopExit,
)

from ._debug import traceexceptions
from ._exceptionhandler import ExceptionHandlerMixin
from ._executor import ExecutorMixin
from ._log import logger
from ._resolver import ResolverMixin
from ._sockets import SocketMixin

_unset = object()
_POSIX_TO_CFTIME = 978307200
_EPSILON = 1e-6


def _check_ssl_socket(sock):
    if isinstance(sock, ssl.SSLSocket):
        raise TypeError("Socket cannot be of type SSLSocket")


def posix2cftime(posixtime):
    """ Convert a POSIX timestamp to a CFAbsoluteTime timestamp """
    return posixtime - _POSIX_TO_CFTIME


def cftime2posix(cftime):
    """ Convert a CFAbsoluteTime timestamp to a POSIX timestamp """
    return cftime + _POSIX_TO_CFTIME


@traceexceptions
def handle_callback(handle):
    if handle.cancelled():
        return

    handle._run()


def _sighandler_noop(signum, frame):
    """Dummy signal handler."""
    pass


def _format_pipe(fd):
    if fd == subprocess.PIPE:
        return "<pipe>"
    elif fd == subprocess.STDOUT:
        return "<stdout>"
    else:
        return repr(fd)


class PyObjCEventLoop(
    SocketMixin,
    ExecutorMixin,
    ResolverMixin,
    ExceptionHandlerMixin,
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
            None, kCFRunLoopEntry | kCFRunLoopExit, True, 0, self._observer_loop
        )
        CFRunLoopAddObserver(self._loop, self._observer, kCFRunLoopCommonModes)

        self._thread = None
        self._running = False
        self._closed = False
        self._timer = None
        self._timer_q = []
        self._signal_handlers = {}
        self._transports = weakref.WeakValueDictionary()

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

    def __del__(self, _warn=warnings.warn):
        if self._observer is not None:
            CFRunLoopRemoveObserver(self._loop, self._observer, kCFRunLoopCommonModes)

        if not self.is_closed():
            _warn(f"unclosed event loop {self!r}", ResourceWarning, source=self)
            if not self.is_running():
                self.close()

    def _observer_loop(self, observer, activity):
        if activity == kCFRunLoopEntry:
            self._running = True
            asyncio._set_running_loop(self)

        elif activity == kCFRunLoopExit:
            self._running = False
            asyncio._set_running_loop(None)

    # Running and stopping the loop

    @traceexceptions
    def run_until_complete(self, future):
        future.add_done_callback(lambda: self.stop())
        self.run_forever()

        return future.result()

    @traceexceptions
    def _asyncgen_firstiter_hook(self, agen):
        ...

    @traceexceptions
    def _asyncgen_finalizer_hook(self, agen):
        ...

    @traceexceptions
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

    @traceexceptions
    def stop(self):
        CFRunLoopStop(self._loop)

    @traceexceptions
    def is_running(self):
        # XXX: This should also return true if the Cocoa
        # runloop is active due to some other reason.
        #
        return self._running

    @traceexceptions
    def _check_closed(self):
        if self._closed:
            raise RuntimeError("Event loop is closed")

    @traceexceptions
    def is_closed(self):
        return self._closed

    @traceexceptions
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

    @traceexceptions
    def shutdown_asyncgens(self):
        raise NotImplementedError(1)

    # Scheduling callbacks

    @traceexceptions
    def call_soon(self, callback, *args, context=None):
        handle = asyncio.Handle(callback, args, self, context)
        CFRunLoopPerformBlock(
            self._loop, kCFRunLoopCommonModes, lambda: handle_callback(handle)
        )
        CFRunLoopWakeUp(self._loop)
        return handle

    @traceexceptions
    def call_soon_threadsafe(self, callback, *args, context=None):
        handle = asyncio.Handle(callback, args, self, context)
        CFRunLoopPerformBlock(
            self._loop, kCFRunLoopCommonModes, lambda: handle_callback(handle)
        )
        CFRunLoopWakeUp(self._loop)
        return handle

    # Scheduling delayed callbacks

    @traceexceptions
    def call_later(self, delay, callback, *args, context=None):
        return self.call_at(self.time() + delay, callback, *args, context=context)

    @traceexceptions
    def _process_timer(self):
        while self._timer_q and self._timer_q[0].when() <= self.time() + _EPSILON:
            handle = heapq.heappop(self._timer_q)
            handle_callback(handle)

        if self._timer_q:
            CFRunLoopTimerSetNextFireDate(
                self._timer, posix2cftime(self._timer_q[0].when())
            )

    @traceexceptions
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

    @traceexceptions
    def time(self):
        return cftime2posix(CFAbsoluteTimeGetCurrent())

    # Creating Futures and Tasks
    @traceexceptions
    def create_future(self):
        return asyncio.Future(loop=self)

    @traceexceptions
    def create_task(self, coro, *, name=None):
        if self._task_factory is not None:
            task = self._task_factory(coro)
            if name is not None:
                task.set_name(name)
            return task

        else:
            return asyncio.Task(coro, loop=self, name=name)

    @traceexceptions
    def set_task_factory(self, factory):
        self._task_factory = factory

    @traceexceptions
    def get_task_factory(self):
        return self._task_factory

    # Working with pipes

    async def connect_read_pipe(self, protocol_factory, pipe):
        raise NotImplementedError(22)

    async def connect_write_pipe(self, protocol_factory, pipe):
        raise NotImplementedError(23)

    # Unix signals

    @traceexceptions
    def add_signal_handler(self, sig, callback, *args):
        """Add a handler for a signal.  UNIX only.

        Raise ValueError if the signal number is invalid or uncatchable.
        Raise RuntimeError if there is a problem setting up the handler.
        """
        raise NotImplementedError(24)

    @traceexceptions
    def remove_signal_handler(self, sig):
        """Remove a handler for a signal.  UNIX only.

        Return True if a signal handler was removed, False if not.
        """
        raise NotImplementedError(25)

    @traceexceptions
    def _check_signal(self, sig):
        """Internal helper to validate a signal.

        Raise ValueError if the signal number is invalid or uncatchable.
        Raise RuntimeError if there is a problem setting up the handler.
        """
        if not isinstance(sig, int):
            raise TypeError(f"sig must be an int, not {sig!r}")

        if sig not in signal.valid_signals():
            raise ValueError(f"invalid signal number {sig}")

    # Executing code in thread or process pools

    # Enabling debug mode

    @traceexceptions
    def get_debug(self):
        return self._debug

    @traceexceptions
    def set_debug(self, enabled):
        self._debug = bool(enabled)

    # Running subprocesses

    @traceexceptions
    def _log_subprocess(self, msg, stdin, stdout, stderr):
        info = [msg]
        if stdin is not None:
            info.append(f"stdin={_format_pipe(stdin)}")
        if stdout is not None and stderr == subprocess.STDOUT:
            info.append(f"stdout=stderr={_format_pipe(stdout)}")
        else:
            if stdout is not None:
                info.append(f"stdout={_format_pipe(stdout)}")
            if stderr is not None:
                info.append(f"stderr={_format_pipe(stderr)}")
        logger.debug(" ".join(info))

    async def subprocess_shell(
        self,
        protocol_factory,
        cmd,
        *,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=False,
        shell=True,
        bufsize=0,
        encoding=None,
        errors=None,
        text=None,
        **kwargs,
    ):
        if not isinstance(cmd, (bytes, str)):
            raise ValueError("cmd must be a string")
        if universal_newlines:
            raise ValueError("universal_newlines must be False")
        if not shell:
            raise ValueError("shell must be True")
        if bufsize != 0:
            raise ValueError("bufsize must be 0")
        if text:
            raise ValueError("text must be False")
        if encoding is not None:
            raise ValueError("encoding must be None")
        if errors is not None:
            raise ValueError("errors must be None")

        protocol = protocol_factory()
        debug_log = None
        if self._debug:
            # don't log parameters: they may contain sensitive information
            # (password) and may be too long
            debug_log = "run shell command %r" % cmd
            self._log_subprocess(debug_log, stdin, stdout, stderr)
        transport = await self._make_subprocess_transport(
            protocol, cmd, True, stdin, stdout, stderr, bufsize, **kwargs
        )
        if self._debug and debug_log is not None:
            logger.info("%s: %r", debug_log, transport)
        return transport, protocol

    async def subprocess_exec(
        self,
        protocol_factory,
        program,
        *args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=False,
        shell=False,
        bufsize=0,
        encoding=None,
        errors=None,
        text=None,
        **kwargs,
    ):
        if universal_newlines:
            raise ValueError("universal_newlines must be False")
        if shell:
            raise ValueError("shell must be False")
        if bufsize != 0:
            raise ValueError("bufsize must be 0")
        if text:
            raise ValueError("text must be False")
        if encoding is not None:
            raise ValueError("encoding must be None")
        if errors is not None:
            raise ValueError("errors must be None")

        popen_args = (program,) + args
        protocol = protocol_factory()
        debug_log = None
        if self._debug:
            # don't log parameters: they may contain sensitive information
            # (password) and may be too long
            debug_log = f"execute program {program!r}"
            self._log_subprocess(debug_log, stdin, stdout, stderr)
        transport = await self._make_subprocess_transport(
            protocol, popen_args, False, stdin, stdout, stderr, bufsize, **kwargs
        )
        if self._debug and debug_log is not None:
            logger.info("%s: %r", debug_log, transport)
        return transport, protocol

    async def _make_subprocess_transport(
        self,
        protocol,
        args,
        shell,
        stdin,
        stdout,
        stderr,
        bufsize,
        extra=None,
        **kwargs,
    ):
        with asyncio.get_child_watcher() as watcher:
            if not watcher.is_active():
                # Check early.
                # Raising exception before process creation
                # prevents subprocess execution if the watcher
                # is not ready to handle it.
                raise RuntimeError(
                    "asyncio.get_child_watcher() is not activated, "
                    "subprocess support is not installed."
                )
            waiter = self.create_future()
            transp = _UnixSubprocessTransport(
                self,
                protocol,
                args,
                shell,
                stdin,
                stdout,
                stderr,
                bufsize,
                waiter=waiter,
                extra=extra,
                **kwargs,
            )

            watcher.add_child_handler(
                transp.get_pid(), self._child_watcher_callback, transp
            )
            try:
                await waiter
            except (SystemExit, KeyboardInterrupt):
                raise
            except BaseException:
                transp.close()
                await transp._wait()
                raise

        return transp

    def _child_watcher_callback(self, pid, returncode, transp):
        self.call_soon_threadsafe(transp._process_exited, returncode)

    #
    #

    @traceexceptions
    def _timer_handle_cancelled(self, handle):
        if handle._scheduled:
            self._timer_cancelled_count += 1

    @traceexceptions
    def _io_event(self, event, key):
        print("handle event", event, key)
        raise NotImplementedError(29)

    def _check_callback(self, callback, method):
        if asyncio.iscoroutine(callback) or asyncio.iscoroutinefunction(callback):
            raise TypeError(f"coroutines cannot be used with {method}()")
        if not callable(callback):
            raise TypeError(
                f"a callable object was expected by {method}(), " f"got {callback!r}"
            )
