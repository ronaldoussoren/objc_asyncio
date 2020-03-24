__all__ = "EventLoop"

import asyncio
import socket
import subprocess
import time

from Cocoa import (
    CFRunLoopGetCurrent,
    CFRunLoopRun,
    CFRunLoopStop,
    NSRunLoop,
    NSRunLoopCommonModes,
    NSTimer,
)

_unset = object()


class EventLoop:
    """
    An asyncio eventloop that uses a Cocoa eventloop

    There are two ways of running the loop:

    1) Use the standard asyncio eventloop API
    2) Implicitly run the loop by running the Cocoa
       eventloop in the default mode.
    """

    def __init__(self):
        self._loop = CFRunLoopGetCurrent()
        self._thread = None
        self._running = False
        self._closed = False

        self._task_factory = None
        self._executor = None
        self._exception_handler = None
        self._debug = False  # XXX

    # Running and stopping the loop

    def run_until_complete(self, future):
        future.add_done_callback(lambda: self.stop())
        self.run_forever()

        return future.result()

    def run_forever(self):
        def function():
            print("hello")

        def function2(a):
            print("timer", a)

        timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            1.0, True, function2
        )
        NSRunLoop.currentRunLoop().performBlock_(function)
        NSRunLoop.currentRunLoop().addTimer_forMode_(timer, NSRunLoopCommonModes)
        try:
            self._running = True
            CFRunLoopRun()
        finally:
            self._running = False

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

        if self._executor is not None:
            self._executor.shutdown()

        ...

    def shutdown_asyncgens(self):
        ...

    # Scheduling callbacks

    def call_soon(self, callback, *args, context=None):
        ...

    def call_soon_thread_safe(self):
        ...

    # Scheduling delayed callbacks

    def call_later(self, delay, callback, *args, context=None):
        ...

    def call_at(self, when, callback, *args, context=None):
        ...

    def time(self):
        return time.monotonic()

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
        interleave=None
    ):

        ...

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
        sock=None
    ):
        ...

    async def create_unix_connection(
        sefl,
        protocol_factory,
        path=None,
        *,
        ssl=None,
        sock=None,
        server_hostname=None,
        ssl_handshake_timeout=None
    ):
        ...

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
        start_serving=True
    ):
        ...

    async def create_unix_server(
        self,
        protocol_factory,
        path=None,
        *,
        sock=None,
        backlog=100,
        ssl=None,
        ssl_handshake_timeout=None,
        start_serving=True
    ):
        ...

    async def connect_accepted_socket(
        self, protocol_factory, sock, *, ssl=None, ssl_handshake_timeout=None
    ):
        ...

    # Transfering files
    async def sendfile(transport, file, offset=0, count=None, *, fallback=True):
        ...

    # TLS Upgrade
    async def start_tls(
        self,
        transport,
        protocol,
        sslcontext,
        *,
        server_side=False,
        server_hostname=None,
        ssl_handshake_timeout=None
    ):
        ...

    # Watching file descriptors
    async def add_reader(self, fd, callback, *args):
        ...

    async def remove_reader(self, fd):
        ...

    async def add_writer(self, fd, *args):
        ...

    async def remove_writer(self, fd):
        ...

    # Working with socket objects directly

    async def sock_recv(self, sock, nbytes):
        ...

    async def sock_recv_into(self, sock, buf):
        ...

    async def sock_sendall(self, sock, data):
        ...

    async def sock_connect(self, sock, address):
        ...

    async def sock_accept(self, sock):
        ...

    async def sock_sendfile(self, file, offset=0, count=None, *, fallback=True):
        ...

    # DNS

    async def getaddrinfo(
        self, host, port, *, family=0, type=0, proto=0, flags=0  # noqa: A002
    ):
        ...

    async def getnameinfo(self, sockaddr, flags=0):
        ...

    # Working with pipes

    async def connect_read_pipe(self, protocol_factory, pipe):
        ...

    async def connect_write_pipe(self, protocol_factory, pipe):
        ...

    # Unix signals

    def add_signal_handler(self, signum, callback, *args):
        ...

    def remove_singal_handler(self, signum):
        ...

    # Executing code in thread or process pools

    async def run_in_executor(self, executor, func, *args):
        ...

    def set_default_executor(self, executor):
        self._executor = executor

    # Error handling API

    def set_exception_handler(self, handler):
        self._exeception_handler = handler

    def get_exception_handler(self):
        return self._exeception_handler

    def default_exception_handler(self, context):
        ...

    def call_exception_handler(self, context):
        ...

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
        **kwargs
    ):
        ...

    async def subprocess_shell(
        self,
        protocol_factory,
        cmd,
        *,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **kwargs
    ):
        ...
