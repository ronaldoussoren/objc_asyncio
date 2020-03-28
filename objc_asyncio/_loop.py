__all__ = "EventLoop"

import asyncio
import heapq
import os
import socket
import subprocess
import sys

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

from ._selector import RunLoopSelector

_unset = object()
_POSIX_TO_CFTIME = 978307200


def posix2cftime(posixtime):
    """ Convert a POSIX timestamp to a CFAbsoluteTime timestamp """
    return posixtime - _POSIX_TO_CFTIME


def cftime2posix(cftime):
    """ Convert a CFAbsoluteTime timestamp to a POSIX timestamp """
    return cftime + _POSIX_TO_CFTIME


def handle_callback(handle):
    if handle.cancelled():
        return

    handle._run()


class EventLoop(asyncio.AbstractEventLoop):
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

        self._selector = RunLoopSelector(self)

        self._thread = None
        self._running = False
        self._closed = False
        self._timer = None
        self._timer_q = []

        self._task_factory = None
        self._executor = None
        self._exception_handler = None

        # This mirrors how asyncio detects debug mode
        self._debug = sys.flags.dev_mode or (
            not sys.flags.ignore_environment
            and bool(os.environ.get("PYTHONASYNCIODEBUG"))
        )

    def __del__(self):
        if self._observer is not None:
            CFRunLoopRemoveObserver(self._loop, self._observer, kCFRunLoopCommonModes)

    def _observer_loop(self, observer, activity):
        if activity == kCFRunLoopEntry:
            self._running = True
            asyncio._set_running_loop(self)

        elif activity == kCFRunLoopExit:
            self._running = False
            asyncio._set_running_loop(None)

    # Running and stopping the loop

    def run_until_complete(self, future):
        future.add_done_callback(lambda: self.stop())
        self.run_forever()

        return future.result()

    def _asyncgen_firstiter_hook(self, agen):
        ...

    def _asyncgen_finalizer_hook(self, agen):
        ...

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

        self._selector.close()
        self._selector = None
        self._closed = True

    def shutdown_asyncgens(self):
        raise NotImplementedError(1)

    # Scheduling callbacks

    def call_soon(self, callback, *args, context=None):
        handle = asyncio.Handle(callback, args, self, context)
        CFRunLoopPerformBlock(
            self._loop, kCFRunLoopCommonModes, lambda: handle_callback(handle)
        )
        CFRunLoopWakeUp(self._loop)

        return handle

    def call_soon_thread_safe(self, callback, *args, context=None):
        handle = asyncio.Handle(callback, args, self, context)
        CFRunLoopPerformBlock(
            self._loop, kCFRunLoopCommonModes, lambda: handle_callback(handle)
        )
        CFRunLoopWakeUp(self._loop)
        return handle

    # Scheduling delayed callbacks

    def call_later(self, delay, callback, *args, context=None):
        return self.call_at(self.time() + delay, callback, *args, context=context)

    def _process_timer(self):
        while self._timer_q and self._timer_q[0].when() <= self.time():
            handle = heapq.heappop(self._timer_q)
            handle_callback(handle)

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
            task = self._task_factory(coro)
            if name is not None:
                task.set_name(name)
            return task

        else:
            return asyncio.Task(coro, loop=self, name=name)

    def set_task_factory(self, factory):
        self._task_factory = factory

    def get_task_factory(self):
        return self._task_factory

    # Opening network connections

    async def create_connection(
        self,
        protocol_factory,
        host=None,
        port=None,
        *,
        ssl=None,
        family=0,
        proto=0,
        flags=0,
        sock=None,
        local_addr=None,
        server_hostname=None,
        ssl_handshake_timeout=None,
        happy_eyeballs_delay=None,
        interleave=None,
    ):
        raise NotImplementedError(2)

    async def create_datagram_endpoint(
        self,
        protocol_factory,
        local_addr=None,
        remote_addr=None,
        *,
        family=0,
        proto=0,
        flags=0,
        reuse_address=_unset,
        reuse_port=None,
        allow_broadcast=None,
        sock=None,
    ):
        raise NotImplementedError(3)

    async def create_unix_connection(
        sefl,
        protocol_factory,
        path=None,
        *,
        ssl=None,
        sock=None,
        server_hostname=None,
        ssl_handshake_timeout=None,
    ):
        raise NotImplementedError(4)

    # Creating network servers
    async def create_server(
        self,
        protocol_factory,
        host=None,
        port=None,
        *,
        family=socket.AF_UNSPEC,
        flags=socket.AI_PASSIVE,
        sock=None,
        backlog=100,
        ssl=None,
        reuse_address=None,
        reuse_port=None,
        ssl_handshake_timeout=None,
        start_serving=True,
    ):
        raise NotImplementedError(5)

    async def create_unix_server(
        self,
        protocol_factory,
        path=None,
        *,
        sock=None,
        backlog=100,
        ssl=None,
        ssl_handshake_timeout=None,
        start_serving=True,
    ):
        raise NotImplementedError(6)

    async def connect_accepted_socket(
        self, protocol_factory, sock, *, ssl=None, ssl_handshake_timeout=None
    ):
        raise NotImplementedError(7)

    # Transfering files
    async def sendfile(transport, file, offset=0, count=None, *, fallback=True):
        raise NotImplementedError(8)

    # TLS Upgrade
    async def start_tls(
        self,
        transport,
        protocol,
        sslcontext,
        *,
        server_side=False,
        server_hostname=None,
        ssl_handshake_timeout=None,
    ):
        raise NotImplementedError(9)

    # Watching file descriptors
    async def add_reader(self, fd, callback, *args):
        raise NotImplementedError(10)

    async def remove_reader(self, fd):
        raise NotImplementedError(11)

    async def add_writer(self, fd, *args):
        raise NotImplementedError(12)

    async def remove_writer(self, fd):
        raise NotImplementedError(13)

    # Working with socket objects directly

    async def sock_recv(self, sock, nbytes):
        raise NotImplementedError(14)

    async def sock_recv_into(self, sock, buf):
        raise NotImplementedError(15)

    async def sock_sendall(self, sock, data):
        raise NotImplementedError(16)

    async def sock_connect(self, sock, address):
        raise NotImplementedError(17)

    async def sock_accept(self, sock):
        raise NotImplementedError(18)

    async def sock_sendfile(self, file, offset=0, count=None, *, fallback=True):
        raise NotImplementedError(19)

    # DNS

    async def getaddrinfo(
        self, host, port, *, family=0, type=0, proto=0, flags=0  # noqa: A002
    ):
        raise NotImplementedError(20)

    async def getnameinfo(self, sockaddr, flags=0):
        raise NotImplementedError(21)

    # Working with pipes

    async def connect_read_pipe(self, protocol_factory, pipe):
        raise NotImplementedError(22)

    async def connect_write_pipe(self, protocol_factory, pipe):
        raise NotImplementedError(23)

    # Unix signals

    def add_signal_handler(self, signum, callback, *args):
        raise NotImplementedError(24)

    def remove_singal_handler(self, signum):
        raise NotImplementedError(25)

    # Executing code in thread or process pools

    async def run_in_executor(self, executor, func, *args):
        raise NotImplementedError(26)

    def set_default_executor(self, executor):
        self._executor = executor

    # Error handling API

    def set_exception_handler(self, handler):
        self._exeception_handler = handler

    def get_exception_handler(self):
        return self._exeception_handler

    def default_exception_handler(self, context):
        print("Exception", context)

    def call_exception_handler(self, context):
        print("call_exception_handler", context)

    # Enabling debug mode

    def get_debug(self):
        return self._debug

    def set_debug(self, enabled):
        self._debug = bool(enabled)

    # Running subprocesses

    async def subprocess_exec(
        self,
        protocol_factory,
        *args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **kwargs,
    ):
        raise NotImplementedError(27)

    async def subprocess_shell(
        self,
        protocol_factory,
        cmd,
        *,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **kwargs,
    ):
        raise NotImplementedError(28)

    #
    #

    def _timer_handle_cancelled(self, handle):
        if handle._scheduled:
            self._timer_cancelled_count += 1

    def _io_event(self, event, key):
        raise NotImplementedError(29)
