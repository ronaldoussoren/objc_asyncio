import asyncio
import os
import select
import socket
import subprocess
import typing
import warnings
from asyncio.base_subprocess import BaseSubprocessTransport

from ._log import logger

_ProtocolFactory = typing.Callable[[], asyncio.BaseProtocol]


def _format_pipe(fd):
    if fd == subprocess.PIPE:
        return "<pipe>"
    elif fd == subprocess.STDOUT:
        return "<stdout>"
    elif fd == subprocess.DEVNULL:
        return "<devnull>"
    else:
        return repr(fd)


class SubprocessMixin(asyncio.AbstractEventLoop):
    def _log_subprocess(
        self, msg: str, stdin: typing.Any, stdout: typing.Any, stderr: typing.Any
    ) -> None:
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
        protocol_factory: _ProtocolFactory,
        cmd: typing.Union[bytes, str],
        *,
        stdin: typing.Any = subprocess.PIPE,
        stdout: typing.Any = subprocess.PIPE,
        stderr: typing.Any = subprocess.PIPE,
        **kwargs,
    ) -> typing.Tuple[asyncio.BaseTransport, asyncio.BaseProtocol]:

        if not isinstance(cmd, (bytes, str)):
            raise ValueError("cmd must be a string")
        for key in (
            "bufsize",
            "universal_newlines",
            "shell",
            "text",
            "encoding",
            "errors",
        ):
            if key in kwargs:
                raise ValueError(f"{key} should not be specified")

        protocol = protocol_factory()
        debug_log = None
        if self._debug:
            debug_log = f"run shell command {cmd!r}"
            self._log_subprocess(debug_log, stdin, stdout, stderr)
        transport = await self._make_subprocess_transport(
            protocol, cmd, True, stdin, stdout, stderr, **kwargs
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
        **kwargs,
    ):
        if not isinstance(program, (bytes, str)):
            raise ValueError("program must be a string")
        if not all(isinstance(x, type(program)) for x in args):
            raise ValueError("program arguments must be same type as program")
        for key in (
            "bufsize",
            "universal_newlines",
            "shell",
            "text",
            "encoding",
            "errors",
        ):
            if key in kwargs:
                raise ValueError(f"{key} should not be specified")

        popen_args = (program,) + args
        protocol = protocol_factory()
        debug_log = None
        if self._debug:
            # don't log parameters: they may contain sensitive information
            # (password) and may be too long
            debug_log = f"run shell command {program!r}"
            self._log_subprocess(debug_log, stdin, stdout, stderr)
        transport = await self._make_subprocess_transport(
            protocol, popen_args, False, stdin, stdout, stderr, **kwargs
        )
        if self._debug and debug_log is not None:
            logger.info("%s: %r", debug_log, transport)
        return transport, protocol

    async def _make_subprocess_transport(
        self, protocol, args, shell, stdin, stdout, stderr, extra=None, **kwargs
    ):
        assert extra is None
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
            transp = PyObjCSubprocessTransport(
                self,
                protocol,
                args,
                shell,
                stdin,
                stdout,
                stderr,
                0,
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


class KQueueChildWatcher(asyncio.AbstractChildWatcher):
    """Monitor child processes

    This watcher uses kqueue to monitor (child) processes.  This watcher
    does not require signals or threads and does not interact with
    other process management APIs.

    It is save to have multiple instances of this watcher, and those can
    be attached to different loops.
    """

    def __init__(self) -> None:
        self._loop: typing.Optional[asyncio.AbstractEventLoop] = None
        self._kqueue = select.kqueue()
        self._callbacks: typing.Dict[
            int, typing.Tuple[typing.Callable[..., None], typing.Tuple[typing.Any, ...]]
        ] = {}

    def __enter__(self) -> "KQueueChildWatcher":
        return self

    def __exit__(
        self, exc_type: typing.Any, exc_value: typing.Any, exc_traceback: typing.Any
    ) -> None:
        pass

    def is_active(self) -> bool:
        return self._loop is not None and self._loop.is_running()

    def close(self):
        self.attach_loop(None)

    def attach_loop(self, loop: typing.Optional[asyncio.AbstractEventLoop]):
        if self._loop is not None and loop is None and self._callbacks:
            warnings.warn(
                "A loop is being detached "
                "from a child watcher with pending handlers",
                RuntimeWarning,
            )

            self._kqueue.control(
                [
                    select.kevent(
                        ident=pid,
                        filter=select.KQ_FILTER_PROC,
                        flags=select.KQ_EV_DELETE,
                        fflags=select.KQ_NOTE_EXIT,
                        data=0,
                        udata=0,
                    )
                    for pid in self._callbacks
                ],
                0,
                0,
            )

            self._callbacks.clear()

        if self._loop is not None:
            self._loop.remove_reader(self._kqueue.fileno())

        self._loop = loop

        if self._loop is not None:
            self._loop.add_reader(self._kqueue.fileno(), self._handle_process_events)

    def add_child_handler(
        self, pid: int, callback: typing.Callable[..., None], *args: typing.Any
    ):
        try:
            self._kqueue.control(
                [
                    select.kevent(
                        ident=pid,
                        filter=select.KQ_FILTER_PROC,
                        flags=select.KQ_EV_ADD,
                        fflags=select.KQ_NOTE_EXIT,
                        data=0,
                        udata=0,
                    )
                ],
                0,
                0,
            )
            self._callbacks[pid] = (callback, args)

        except ProcessLookupError:
            # The process filter cannot be added when the
            # process exitted before we got here. This can
            # happen when the child proces exits quickly and
            # we do some work (such as logging).
            self._callbacks[pid] = (callback, args)
            self._do_wait(pid)

    def _do_wait(self, pid: int) -> None:
        callback, args = self._callbacks.pop(pid)
        try:
            _, status = os.waitpid(pid, 0)
        except ChildProcessError:
            # The child process is already reaped
            # (may happen if waitpid() is called elsewhere).
            returncode = 255
            logger.warning(
                "child process pid %d exit status already read: "
                " will report returncode 255",
                pid,
            )
        else:
            returncode = _compute_returncode(status)

        try:
            self._kqueue.control(
                [
                    select.kevent(
                        ident=pid,
                        filter=select.KQ_FILTER_PROC,
                        flags=select.KQ_EV_DELETE,
                        fflags=select.KQ_NOTE_EXIT,
                        data=0,
                        udata=0,
                    )
                ],
                0,
                0,
            )
        except FileNotFoundError:
            # Not sure why this happens
            pass

        callback(pid, returncode, *args)

    def _handle_process_events(self) -> None:
        events = self._kqueue.control(None, len(self._callbacks), 0)
        for evt in events:
            self._do_wait(evt.ident)

    def remove_child_handler(self, pid: int) -> bool:
        try:
            del self._callbacks[pid]
        except KeyError:
            return False

        self._kqueue.control(
            [
                select.kevent(
                    ident=pid,
                    filter=select.KQ_FILTER_PROC,
                    flags=select.KQ_EV_DELETE,
                    fflags=select.KQ_NOTE_EXIT,
                    data=0,
                    udata=0,
                )
            ],
            0,
            0,
        )
        return True


def _compute_returncode(status: int):
    if os.WIFSIGNALED(status):
        # The child process died because of a signal.
        return -os.WTERMSIG(status)
    elif os.WIFEXITED(status):
        # The child process exited (e.g sys.exit()).
        return os.WEXITSTATUS(status)
    else:
        # The child exited, but we don't understand its status.
        # This shouldn't happen, but if it does, let's just
        # return that status; perhaps that helps debug it.
        return status


class PyObjCSubprocessTransport(BaseSubprocessTransport):
    def _start(
        self,
        args: typing.Tuple[typing.Any],
        shell: bool,
        stdin: typing.Any,
        stdout: typing.Any,
        stderr: typing.Any,
        bufsize: int,
        **kwargs,
    ) -> None:
        stdin_w = None
        if stdin == asyncio.subprocess.PIPE:
            stdin, stdin_w = socket.socketpair()

        try:
            self._proc = subprocess.Popen(
                args,
                shell=shell,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                universal_newlines=False,
                bufsize=bufsize,
                **kwargs,
            )
            if stdin_w is not None:
                stdin.close()
                self._proc.stdin = open(stdin_w.detach(), "wb", buffering=bufsize)
                stdin_w = None
        finally:
            if stdin_w is not None:
                stdin.close()
                stdin_w.close()
