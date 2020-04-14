"""Mixin for socket handling"""

import asyncio
import collections
import functools
import itertools
import os
import socket
import ssl
import stat
import sys
import warnings
from asyncio import constants  # XXX
from asyncio import staggered  # XXX
from asyncio.base_events import Server, _SendfileFallbackProtocol  # XXX

from Cocoa import kCFSocketReadCallBack, kCFSocketWriteCallBack

from ._log import logger
from ._resolver import _interleave_addrinfos, _ipaddr_info
from ._selector import RunLoopSelector, _fileobj_to_fd

_unset = object()


def _set_reuseport(sock):
    if not hasattr(socket, "SO_REUSEPORT"):
        raise ValueError("reuse_port not supported by socket module")
    else:
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            raise ValueError(
                "reuse_port not supported by socket module, "
                "SO_REUSEPORT defined but not implemented."
            )


def _check_ssl_socket(sock):
    if ssl is not None and isinstance(sock, ssl.SSLSocket):
        raise TypeError("Socket cannot be of type SSLSocket")


class SocketMixin:
    def __init__(self):
        self._selector = RunLoopSelector(self)

    def close(self):
        if self._selector is not None:
            self._selector.close()
            self._selector = None

    async def sock_sendfile(self, sock, file, offset=0, count=None, *, fallback=True):
        if self._debug and sock.gettimeout() != 0:
            raise ValueError("the socket must be non-blocking")
        self._check_sendfile_params(sock, file, offset, count)
        try:
            return await self._sock_sendfile_native(sock, file, offset, count)
        except asyncio.SendfileNotAvailableError:
            if not fallback:
                raise
        return await self._sock_sendfile_fallback(sock, file, offset, count)

    async def _sock_sendfile_fallback(self, sock, file, offset, count):
        if offset:
            file.seek(offset)
        blocksize = (
            min(count, constants.SENDFILE_FALLBACK_READBUFFER_SIZE)
            if count
            else constants.SENDFILE_FALLBACK_READBUFFER_SIZE
        )
        buf = bytearray(blocksize)
        total_sent = 0
        try:
            while True:
                if count:
                    blocksize = min(count - total_sent, blocksize)
                    if blocksize <= 0:
                        break
                view = memoryview(buf)[:blocksize]
                read = await self.run_in_executor(None, file.readinto, view)
                if not read:
                    break  # EOF
                await self.sock_sendall(sock, view[:read])
                total_sent += read
            return total_sent
        finally:
            if total_sent > 0 and hasattr(file, "seek"):
                file.seek(offset + total_sent)

    def _check_sendfile_params(self, sock, file, offset, count):
        if "b" not in getattr(file, "mode", "b"):
            raise ValueError("file should be opened in binary mode")
        if not sock.type == socket.SOCK_STREAM:
            raise ValueError("only SOCK_STREAM type sockets are supported")
        if count is not None:
            if not isinstance(count, int):
                raise TypeError(
                    "count must be a positive integer (got {!r})".format(count)
                )
            if count <= 0:
                raise ValueError(
                    "count must be a positive integer (got {!r})".format(count)
                )
        if not isinstance(offset, int):
            raise TypeError(
                "offset must be a non-negative integer (got {!r})".format(offset)
            )
        if offset < 0:
            raise ValueError(
                "offset must be a non-negative integer (got {!r})".format(offset)
            )

    async def _connect_sock(self, exceptions, addr_info, local_addr_infos=None):
        """Create, bind and connect one socket."""
        my_exceptions = []
        exceptions.append(my_exceptions)
        family, type_, proto, _, address = addr_info
        sock = None
        try:
            sock = socket.socket(family=family, type=type_, proto=proto)
            sock.setblocking(False)
            if local_addr_infos is not None:
                for _, _, _, _, laddr in local_addr_infos:
                    try:
                        sock.bind(laddr)
                        break
                    except OSError as exc:
                        msg = (
                            f"error while attempting to bind on "
                            f"address {laddr!r}: "
                            f"{exc.strerror.lower()}"
                        )
                        exc = OSError(exc.errno, msg)
                        my_exceptions.append(exc)
                else:  # all bind attempts failed
                    raise my_exceptions.pop()
            await self.sock_connect(sock, address)
            return sock
        except OSError as exc:
            my_exceptions.append(exc)
            if sock is not None:
                sock.close()
            raise
        except:  # noqa: E722, B001
            if sock is not None:
                sock.close()
            raise

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
        """Connect to a TCP server.

        Create a streaming transport connection to a given Internet host and
        port: socket family AF_INET or socket.AF_INET6 depending on host (or
        family if specified), socket type SOCK_STREAM. protocol_factory must be
        a callable returning a protocol instance.

        This method is a coroutine which will try to establish the connection
        in the background.  When successful, the coroutine returns a
        (transport, protocol) pair.
        """
        if server_hostname is not None and not ssl:
            raise ValueError("server_hostname is only meaningful with ssl")

        if server_hostname is None and ssl:
            # Use host as default for server_hostname.  It is an error
            # if host is empty or not set, e.g. when an
            # already-connected socket was passed or when only a port
            # is given.  To avoid this error, you can pass
            # server_hostname='' -- this will bypass the hostname
            # check.  (This also means that if host is a numeric
            # IP/IPv6 address, we will attempt to verify that exact
            # address; this will probably fail, but it is possible to
            # create a certificate for a specific IP address, so we
            # don't judge it here.)
            if not host:
                raise ValueError(
                    "You must set server_hostname " "when using ssl without a host"
                )
            server_hostname = host

        if ssl_handshake_timeout is not None and not ssl:
            raise ValueError("ssl_handshake_timeout is only meaningful with ssl")

        if happy_eyeballs_delay is not None and interleave is None:
            # If using happy eyeballs, default to interleave addresses by family
            interleave = 1

        if host is not None or port is not None:
            if sock is not None:
                raise ValueError(
                    "host/port and sock can not be specified at the same time"
                )

            infos = await self._ensure_resolved(
                (host, port),
                family=family,
                type=socket.SOCK_STREAM,
                proto=proto,
                flags=flags,
                loop=self,
            )
            if not infos:
                raise OSError("getaddrinfo() returned empty list")

            if local_addr is not None:
                laddr_infos = await self._ensure_resolved(
                    local_addr,
                    family=family,
                    type=socket.SOCK_STREAM,
                    proto=proto,
                    flags=flags,
                    loop=self,
                )
                if not laddr_infos:
                    raise OSError("getaddrinfo() returned empty list")
            else:
                laddr_infos = None

            if interleave:
                infos = _interleave_addrinfos(infos, interleave)

            exceptions = []
            if happy_eyeballs_delay is None:
                # not using happy eyeballs
                for addrinfo in infos:
                    try:
                        sock = await self._connect_sock(
                            exceptions, addrinfo, laddr_infos
                        )
                        break
                    except OSError:
                        continue
            else:  # using happy eyeballs
                sock, _, _ = await staggered.staggered_race(
                    (
                        functools.partial(
                            self._connect_sock, exceptions, addrinfo, laddr_infos
                        )
                        for addrinfo in infos
                    ),
                    happy_eyeballs_delay,
                    loop=self,
                )

            if sock is None:
                exceptions = [exc for sub in exceptions for exc in sub]
                if len(exceptions) == 1:
                    raise exceptions[0]
                else:
                    # If they all have the same str(), raise one.
                    model = str(exceptions[0])
                    if all(str(exc) == model for exc in exceptions):
                        raise exceptions[0]
                    # Raise a combined exception so the user can see all
                    # the various error messages.
                    raise OSError(
                        "Multiple exceptions: {}".format(
                            ", ".join(str(exc) for exc in exceptions)
                        )
                    )

        else:
            if sock is None:
                raise ValueError(
                    "host and port was not specified and no sock specified"
                )
            if sock.type != socket.SOCK_STREAM:
                # We allow AF_INET, AF_INET6, AF_UNIX as long as they
                # are SOCK_STREAM.
                # We support passing AF_UNIX sockets even though we have
                # a dedicated API for that: create_unix_connection.
                # Disallowing AF_UNIX in this method, breaks backwards
                # compatibility.
                raise ValueError(f"A Stream Socket was expected, got {sock!r}")

        transport, protocol = await self._create_connection_transport(
            sock,
            protocol_factory,
            ssl,
            server_hostname,
            ssl_handshake_timeout=ssl_handshake_timeout,
        )
        if self._debug:
            # Get the socket from the transport because SSL transport closes
            # the old socket and creates a new SSL socket
            sock = transport.get_extra_info("socket")
            logger.debug(
                "%r connected to %s:%r: (%r, %r)", sock, host, port, transport, protocol
            )
        return transport, protocol

    async def _create_connection_transport(
        self,
        sock,
        protocol_factory,
        ssl,
        server_hostname,
        server_side=False,
        ssl_handshake_timeout=None,
    ):

        sock.setblocking(False)

        protocol = protocol_factory()
        waiter = self.create_future()
        if ssl:
            sslcontext = None if isinstance(ssl, bool) else ssl
            transport = self._make_ssl_transport(
                sock,
                protocol,
                sslcontext,
                waiter,
                server_side=server_side,
                server_hostname=server_hostname,
                ssl_handshake_timeout=ssl_handshake_timeout,
            )
        else:
            transport = self._make_socket_transport(sock, protocol, waiter)

        try:
            await waiter
        except:  # noqa: F722, B001
            transport.close()
            raise

        return transport, protocol

    async def sendfile(self, transport, file, offset=0, count=None, *, fallback=True):
        """Send a file to transport.

        Return the total number of bytes which were sent.

        The method uses high-performance os.sendfile if available.

        file must be a regular file object opened in binary mode.

        offset tells from where to start reading the file. If specified,
        count is the total number of bytes to transmit as opposed to
        sending the file until EOF is reached. File position is updated on
        return or also in case of error in which case file.tell()
        can be used to figure out the number of bytes
        which were sent.

        fallback set to True makes asyncio to manually read and send
        the file when the platform does not support the sendfile syscall
        (e.g. Windows or SSL socket on Unix).

        Raise SendfileNotAvailableError if the system does not support
        sendfile syscall and fallback is False.
        """
        if transport.is_closing():
            raise RuntimeError("Transport is closing")
        mode = getattr(
            transport, "_sendfile_compatible", constants._SendfileMode.UNSUPPORTED
        )
        if mode is constants._SendfileMode.UNSUPPORTED:
            raise RuntimeError(f"sendfile is not supported for transport {transport!r}")
        if mode is constants._SendfileMode.TRY_NATIVE:
            try:
                return await self._sendfile_native(transport, file, offset, count)
            except asyncio.SendfileNotAvailableError:
                if not fallback:
                    raise

        if not fallback:
            raise RuntimeError(
                f"fallback is disabled and native sendfile is not "
                f"supported for transport {transport!r}"
            )

        return await self._sendfile_fallback(transport, file, offset, count)

    async def _sendfile_fallback(self, transp, file, offset, count):
        if offset:
            file.seek(offset)
        blocksize = min(count, 16384) if count else 16384
        buf = bytearray(blocksize)
        total_sent = 0
        proto = _SendfileFallbackProtocol(transp)
        try:
            while True:
                if count:
                    blocksize = min(count - total_sent, blocksize)
                    if blocksize <= 0:
                        return total_sent
                view = memoryview(buf)[:blocksize]
                read = await self.run_in_executor(None, file.readinto, view)
                if not read:
                    return total_sent  # EOF
                await proto.drain()
                transp.write(view[:read])
                total_sent += read
        finally:
            if total_sent > 0 and hasattr(file, "seek"):
                file.seek(offset + total_sent)
            await proto.restore()

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
        """Upgrade transport to TLS.

        Return a new transport that *protocol* should start using
        immediately.
        """
        if ssl is None:
            raise RuntimeError("Python ssl module is not available")

        if not isinstance(sslcontext, ssl.SSLContext):
            raise TypeError(
                f"sslcontext is expected to be an instance of ssl.SSLContext, "
                f"got {sslcontext!r}"
            )

        if not getattr(transport, "_start_tls_compatible", False):
            raise TypeError(f"transport {transport!r} is not supported by start_tls()")

        waiter = self.create_future()
        ssl_protocol = asyncio.SSLProtocol(
            self,
            protocol,
            sslcontext,
            waiter,
            server_side,
            server_hostname,
            ssl_handshake_timeout=ssl_handshake_timeout,
            call_connection_made=False,
        )

        # Pause early so that "ssl_protocol.data_received()" doesn't
        # have a chance to get called before "ssl_protocol.connection_made()".
        transport.pause_reading()

        transport.set_protocol(ssl_protocol)
        conmade_cb = self.call_soon(ssl_protocol.connection_made, transport)
        resume_cb = self.call_soon(transport.resume_reading)

        try:
            await waiter
        except BaseException:
            transport.close()
            conmade_cb.cancel()
            resume_cb.cancel()
            raise

        return ssl_protocol._app_transport

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
        """Create datagram connection."""
        if sock is not None:
            if sock.type != socket.SOCK_DGRAM:
                raise ValueError(f"A UDP Socket was expected, got {sock!r}")
            if (
                local_addr
                or remote_addr
                or family
                or proto
                or flags
                or reuse_port
                or allow_broadcast
            ):
                # show the problematic kwargs in exception msg
                opts = {
                    "local_addr": local_addr,
                    "remote_addr": remote_addr,
                    "family": family,
                    "proto": proto,
                    "flags": flags,
                    "reuse_address": reuse_address,
                    "reuse_port": reuse_port,
                    "allow_broadcast": allow_broadcast,
                }
                problems = ", ".join(f"{k}={v}" for k, v in opts.items() if v)
                raise ValueError(
                    f"socket modifier keyword arguments can not be used "
                    f"when sock is specified. ({problems})"
                )
            sock.setblocking(False)
            r_addr = None
        else:
            if not (local_addr or remote_addr):
                if family == 0:
                    raise ValueError("unexpected address family")
                addr_pairs_info = (((family, proto), (None, None)),)
            elif hasattr(socket, "AF_UNIX") and family == socket.AF_UNIX:
                for addr in (local_addr, remote_addr):
                    if addr is not None and not isinstance(addr, str):
                        raise TypeError("string is expected")

                if local_addr and local_addr[0] not in (0, "\x00"):
                    try:
                        if stat.S_ISSOCK(os.stat(local_addr).st_mode):
                            os.remove(local_addr)
                    except FileNotFoundError:
                        pass
                    except OSError as err:
                        # Directory may have permissions only to create socket.
                        logger.error(
                            "Unable to check or remove stale UNIX " "socket %r: %r",
                            local_addr,
                            err,
                        )

                addr_pairs_info = (((family, proto), (local_addr, remote_addr)),)
            else:
                # join address by (family, protocol)
                addr_infos = {}  # Using order preserving dict
                for idx, addr in ((0, local_addr), (1, remote_addr)):
                    if addr is not None:
                        assert (
                            isinstance(addr, tuple) and len(addr) == 2
                        ), "2-tuple is expected"

                        infos = await self._ensure_resolved(
                            addr,
                            family=family,
                            type=socket.SOCK_DGRAM,
                            proto=proto,
                            flags=flags,
                            loop=self,
                        )
                        if not infos:
                            raise OSError("getaddrinfo() returned empty list")

                        for fam, _, pro, _, address in infos:
                            key = (fam, pro)
                            if key not in addr_infos:
                                addr_infos[key] = [None, None]
                            addr_infos[key][idx] = address

                # each addr has to have info for each (family, proto) pair
                addr_pairs_info = [
                    (key, addr_pair)
                    for key, addr_pair in addr_infos.items()
                    if not (
                        (local_addr and addr_pair[0] is None)
                        or (remote_addr and addr_pair[1] is None)
                    )
                ]

                if not addr_pairs_info:
                    raise ValueError("can not get address information")

            exceptions = []

            # bpo-37228
            if reuse_address is not _unset:
                if reuse_address:
                    raise ValueError(
                        "Passing `reuse_address=True` is no "
                        "longer supported, as the usage of "
                        "SO_REUSEPORT in UDP poses a significant "
                        "security concern."
                    )
                else:
                    warnings.warn(
                        "The *reuse_address* parameter has been "
                        "deprecated as of 3.5.10 and is scheduled "
                        "for removal in 3.11.",
                        DeprecationWarning,
                        stacklevel=2,
                    )

            for ((family, proto), (local_address, remote_address)) in addr_pairs_info:
                sock = None
                r_addr = None
                try:
                    sock = socket.socket(
                        family=family, type=socket.SOCK_DGRAM, proto=proto
                    )
                    if reuse_port:
                        _set_reuseport(sock)
                    if allow_broadcast:
                        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                    sock.setblocking(False)

                    if local_addr:
                        sock.bind(local_address)
                    if remote_addr:
                        if not allow_broadcast:
                            await self.sock_connect(sock, remote_address)
                        r_addr = remote_address
                except OSError as exc:
                    if sock is not None:
                        sock.close()
                    exceptions.append(exc)
                except:  # noqa: F722, B001
                    if sock is not None:
                        sock.close()
                    raise
                else:
                    break
            else:
                raise exceptions[0]

        protocol = protocol_factory()
        waiter = self.create_future()
        transport = self._make_datagram_transport(sock, protocol, r_addr, waiter)
        if self._debug:
            if local_addr:
                logger.info(
                    "Datagram endpoint local_addr=%r remote_addr=%r "
                    "created: (%r, %r)",
                    local_addr,
                    remote_addr,
                    transport,
                    protocol,
                )
            else:
                logger.debug(
                    "Datagram endpoint remote_addr=%r created: " "(%r, %r)",
                    remote_addr,
                    transport,
                    protocol,
                )

        try:
            await waiter
        except:  # noqa: F722, B001
            transport.close()
            raise

        return transport, protocol

    async def _ensure_resolved(
        self,
        address,
        *,
        family=0,
        type=socket.SOCK_STREAM,  # noqa: A002
        proto=0,
        flags=0,
        loop,
    ):
        host, port = address[:2]
        info = _ipaddr_info(host, port, family, type, proto, *address[2:])
        if info is not None:
            # "host" is already a resolved IP.
            return [info]
        else:
            return await loop.getaddrinfo(
                host, port, family=family, type=type, proto=proto, flags=flags
            )

    async def _create_server_getaddrinfo(self, host, port, family, flags):
        infos = await self._ensure_resolved(
            (host, port), family=family, type=socket.SOCK_STREAM, flags=flags, loop=self
        )
        if not infos:
            raise OSError(f"getaddrinfo({host!r}) returned empty list")
        return infos

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
        """Create a TCP server.

        The host parameter can be a string, in that case the TCP server is
        bound to host and port.

        The host parameter can also be a sequence of strings and in that case
        the TCP server is bound to all hosts of the sequence. If a host
        appears multiple times (possibly indirectly e.g. when hostnames
        resolve to the same IP address), the server is only bound once to that
        host.

        Return a Server object which can be used to stop the service.

        This method is a coroutine.
        """
        if isinstance(ssl, bool):
            raise TypeError("ssl argument must be an SSLContext or None")

        if ssl_handshake_timeout is not None and ssl is None:
            raise ValueError("ssl_handshake_timeout is only meaningful with ssl")

        if host is not None or port is not None:
            if sock is not None:
                raise ValueError(
                    "host/port and sock can not be specified at the same time"
                )

            if reuse_address is None:
                reuse_address = os.name == "posix" and sys.platform != "cygwin"
            sockets = []
            if host == "":
                hosts = [None]
            elif isinstance(host, str) or not isinstance(
                host, collections.abc.Iterable
            ):
                hosts = [host]
            else:
                hosts = host

            fs = [
                self._create_server_getaddrinfo(host, port, family=family, flags=flags)
                for host in hosts
            ]
            infos = await asyncio.gather(*fs, loop=self)
            infos = set(itertools.chain.from_iterable(infos))

            completed = False
            try:
                for res in infos:
                    af, socktype, proto, canonname, sa = res
                    try:
                        sock = socket.socket(af, socktype, proto)
                    except socket.error:
                        # Assume it's a bad family/type/protocol combination.
                        if self._debug:
                            logger.warning(
                                "create_server() failed to create "
                                "socket.socket(%r, %r, %r)",
                                af,
                                socktype,
                                proto,
                                exc_info=True,
                            )
                        continue
                    sockets.append(sock)
                    if reuse_address:
                        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
                    if reuse_port:
                        _set_reuseport(sock)
                    # Disable IPv4/IPv6 dual stack support (enabled by
                    # default on Linux) which makes a single socket
                    # listen on both address families.
                    if af == socket.AF_INET6:
                        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, True)
                    try:
                        sock.bind(sa)
                    except OSError as err:
                        raise OSError(
                            err.errno,
                            "error while attempting "
                            "to bind on address %r: %s" % (sa, err.strerror.lower()),
                        ) from None
                completed = True
            finally:
                if not completed:
                    for sock in sockets:
                        sock.close()
        else:
            if sock is None:
                raise ValueError("Neither host/port nor sock were specified")
            if sock.type != socket.SOCK_STREAM:
                raise ValueError(f"A Stream Socket was expected, got {sock!r}")
            sockets = [sock]

        for sock in sockets:
            sock.setblocking(False)

        server = Server(
            self, sockets, protocol_factory, ssl, backlog, ssl_handshake_timeout
        )
        if start_serving:
            server._start_serving()
            # Skip one loop iteration so that all 'loop.add_reader'
            # go through.
            await asyncio.sleep(0, loop=self)

        if self._debug:
            logger.info("%r is serving", server)
        return server

    async def connect_accepted_socket(
        self, protocol_factory, sock, *, ssl=None, ssl_handshake_timeout=None
    ):
        """Handle an accepted connection.

        This is used by servers that accept connections outside of
        asyncio but that use asyncio to handle connections.

        This method is a coroutine.  When completed, the coroutine
        returns a (transport, protocol) pair.
        """
        if sock.type != socket.SOCK_STREAM:
            raise ValueError(f"A Stream Socket was expected, got {sock!r}")

        if ssl_handshake_timeout is not None and not ssl:
            raise ValueError("ssl_handshake_timeout is only meaningful with ssl")

        transport, protocol = await self._create_connection_transport(
            sock,
            protocol_factory,
            ssl,
            "",
            server_side=True,
            ssl_handshake_timeout=ssl_handshake_timeout,
        )
        if self._debug:
            # Get the socket from the transport because SSL transport closes
            # the old socket and creates a new SSL socket
            sock = transport.get_extra_info("socket")
            logger.debug("%r handled: (%r, %r)", sock, transport, protocol)
        return transport, protocol

    def _ensure_fd_no_transport(self, fd):
        fileno = _fileobj_to_fd(fd)

        try:
            transport = self._transports[fileno]
        except KeyError:
            pass
        else:
            if not transport.is_closing():
                raise RuntimeError(
                    f"File descriptor {fd!r} is used by transport " f"{transport!r}"
                )

    def _add_reader(self, fd, callback, *args):
        self._check_closed()
        handle = asyncio.Handle(callback, args, self, None)
        try:
            key = self._selector.get_key(fd)
        except KeyError:
            self._selector.register(fd, kCFSocketReadCallBack, (handle, None))
        else:
            mask, (reader, writer) = key.events, key.data
            self._selector.modify(fd, mask | kCFSocketReadCallBack, (handle, writer))
            if reader is not None:
                reader.cancel()

    def _remove_reader(self, fd):
        if self.is_closed():
            return False
        try:
            key = self._selector.get_key(fd)
        except KeyError:
            return False
        else:
            mask, (reader, writer) = key.events, key.data
            mask &= ~kCFSocketReadCallBack
            if not mask:
                self._selector.unregister(fd)
            else:
                self._selector.modify(fd, mask, (None, writer))

            if reader is not None:
                reader.cancel()
                return True
            else:
                return False

    def _add_writer(self, fd, callback, *args):
        self._check_closed()
        handle = asyncio.Handle(callback, args, self, None)
        try:
            key = self._selector.get_key(fd)
        except KeyError:
            self._selector.register(fd, kCFSocketWriteCallBack, (None, handle))
        else:
            mask, (reader, writer) = key.events, key.data
            self._selector.modify(fd, mask | kCFSocketWriteCallBack, (reader, handle))
            if writer is not None:
                writer.cancel()

    def _remove_writer(self, fd):
        """Remove a writer callback."""
        if self.is_closed():
            return False
        try:
            key = self._selector.get_key(fd)
        except KeyError:
            return False
        else:
            mask, (reader, writer) = key.events, key.data
            # Remove both writer and connector.
            mask &= ~kCFSocketWriteCallBack
            if not mask:
                self._selector.unregister(fd)
            else:
                self._selector.modify(fd, mask, (reader, None))

            if writer is not None:
                writer.cancel()
                return True
            else:
                return False

    def add_reader(self, fd, callback, *args):
        """Add a reader callback."""
        self._ensure_fd_no_transport(fd)
        return self._add_reader(fd, callback, *args)

    def remove_reader(self, fd):
        """Remove a reader callback."""
        self._ensure_fd_no_transport(fd)
        return self._remove_reader(fd)

    def add_writer(self, fd, callback, *args):
        """Add a writer callback.."""
        self._ensure_fd_no_transport(fd)
        return self._add_writer(fd, callback, *args)

    def remove_writer(self, fd):
        """Remove a writer callback."""
        self._ensure_fd_no_transport(fd)
        return self._remove_writer(fd)

    # Working with socket objects directly

    async def sock_recv(self, sock, n):
        """Receive data from the socket.

        The return value is a bytes object representing the data received.
        The maximum amount of data to be received at once is specified by
        nbytes.
        """
        _check_ssl_socket(sock)
        if self._debug and sock.gettimeout() != 0:
            raise ValueError("the socket must be non-blocking")
        try:
            return sock.recv(n)
        except (BlockingIOError, InterruptedError):
            pass
        fut = self.create_future()
        fd = sock.fileno()
        self.add_reader(fd, self._sock_recv, fut, sock, n)
        fut.add_done_callback(functools.partial(self._sock_read_done, fd))
        return await fut

    def _sock_read_done(self, fd, fut):
        self.remove_reader(fd)

    def _sock_recv(self, fut, sock, n):
        # _sock_recv() can add itself as an I/O callback if the operation can't
        # be done immediately. Don't use it directly, call sock_recv().
        if fut.done():
            return
        try:
            data = sock.recv(n)
        except (BlockingIOError, InterruptedError):
            return  # try again next time
        except (SystemExit, KeyboardInterrupt):
            raise
        except BaseException as exc:
            fut.set_exception(exc)
        else:
            fut.set_result(data)

    async def sock_recv_into(self, sock, buf):
        """Receive data from the socket.

        The received data is written into *buf* (a writable buffer).
        The return value is the number of bytes written.
        """
        _check_ssl_socket(sock)
        if self._debug and sock.gettimeout() != 0:
            raise ValueError("the socket must be non-blocking")
        try:
            return sock.recv_into(buf)
        except (BlockingIOError, InterruptedError):
            pass
        fut = self.create_future()
        fd = sock.fileno()
        self.add_reader(fd, self._sock_recv_into, fut, sock, buf)
        fut.add_done_callback(functools.partial(self._sock_read_done, fd))
        return await fut

    def _sock_recv_into(self, fut, sock, buf):
        # _sock_recv_into() can add itself as an I/O callback if the operation
        # can't be done immediately. Don't use it directly, call
        # sock_recv_into().
        if fut.done():
            return
        try:
            nbytes = sock.recv_into(buf)
        except (BlockingIOError, InterruptedError):
            return  # try again next time
        except (SystemExit, KeyboardInterrupt):
            raise
        except BaseException as exc:
            fut.set_exception(exc)
        else:
            fut.set_result(nbytes)

    async def sock_sendall(self, sock, data):
        """Send data to the socket.

        The socket must be connected to a remote socket. This method continues
        to send data from data until either all data has been sent or an
        error occurs. None is returned on success. On error, an exception is
        raised, and there is no way to determine how much data, if any, was
        successfully processed by the receiving end of the connection.
        """
        _check_ssl_socket(sock)
        if self._debug and sock.gettimeout() != 0:
            raise ValueError("the socket must be non-blocking")
        try:
            n = sock.send(data)
        except (BlockingIOError, InterruptedError):
            n = 0

        if n == len(data):
            # all data sent
            return

        fut = self.create_future()
        fd = sock.fileno()
        fut.add_done_callback(functools.partial(self._sock_write_done, fd))
        # use a trick with a list in closure to store a mutable state
        self.add_writer(fd, self._sock_sendall, fut, sock, memoryview(data), [n])
        return await fut

    def _sock_sendall(self, fut, sock, view, pos):
        if fut.done():
            # Future cancellation can be scheduled on previous loop iteration
            return
        start = pos[0]
        try:
            n = sock.send(view[start:])
        except (BlockingIOError, InterruptedError):
            return
        except (SystemExit, KeyboardInterrupt):
            raise
        except BaseException as exc:
            fut.set_exception(exc)
            return

        start += n

        if start == len(view):
            fut.set_result(None)
        else:
            pos[0] = start

    async def sock_connect(self, sock, address):
        """Connect to a remote socket at address.

        This method is a coroutine.
        """
        _check_ssl_socket(sock)
        if self._debug and sock.gettimeout() != 0:
            raise ValueError("the socket must be non-blocking")

        if not hasattr(socket, "AF_UNIX") or sock.family != socket.AF_UNIX:
            resolved = await self._ensure_resolved(
                address, family=sock.family, proto=sock.proto, loop=self
            )
            _, _, _, _, address = resolved[0]

        fut = self.create_future()
        self._sock_connect(fut, sock, address)
        return await fut

    def _sock_connect(self, fut, sock, address):
        fd = sock.fileno()
        try:
            sock.connect(address)
        except (BlockingIOError, InterruptedError):
            # Issue #23618: When the C function connect() fails with EINTR, the
            # connection runs in background. We have to wait until the socket
            # becomes writable to be notified when the connection succeed or
            # fails.
            fut.add_done_callback(functools.partial(self._sock_write_done, fd))
            self.add_writer(fd, self._sock_connect_cb, fut, sock, address)
        except (SystemExit, KeyboardInterrupt):
            raise
        except BaseException as exc:
            fut.set_exception(exc)
        else:
            fut.set_result(None)

    def _sock_write_done(self, fd, fut):
        self.remove_writer(fd)

    def _sock_connect_cb(self, fut, sock, address):
        if fut.done():
            return

        try:
            err = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            if err != 0:
                # Jump to any except clause below.
                raise OSError(err, f"Connect call failed {address}")
        except (BlockingIOError, InterruptedError):
            # socket is still registered, the callback will be retried later
            pass
        except (SystemExit, KeyboardInterrupt):
            raise
        except BaseException as exc:
            fut.set_exception(exc)
        else:
            fut.set_result(None)

    async def sock_accept(self, sock):
        """Accept a connection.

        The socket must be bound to an address and listening for connections.
        The return value is a pair (conn, address) where conn is a new socket
        object usable to send and receive data on the connection, and address
        is the address bound to the socket on the other end of the connection.
        """
        _check_ssl_socket(sock)
        if self._debug and sock.gettimeout() != 0:
            raise ValueError("the socket must be non-blocking")
        fut = self.create_future()
        self._sock_accept(fut, False, sock)
        return await fut

    def _sock_accept(self, fut, registered, sock):
        fd = sock.fileno()
        if registered:
            self.remove_reader(fd)
        if fut.done():
            return
        try:
            conn, address = sock.accept()
            conn.setblocking(False)
        except (BlockingIOError, InterruptedError):
            self.add_reader(fd, self._sock_accept, fut, True, sock)
        except (SystemExit, KeyboardInterrupt):
            raise
        except BaseException as exc:
            fut.set_exception(exc)
        else:
            fut.set_result((conn, address))

    async def _sendfile_native(self, transp, file, offset, count):
        del self._transports[transp._sock_fd]
        resume_reading = transp.is_reading()
        transp.pause_reading()
        await transp._make_empty_waiter()
        try:
            return await self.sock_sendfile(
                transp._sock, file, offset, count, fallback=False
            )
        finally:
            transp._reset_empty_waiter()
            if resume_reading:
                transp.resume_reading()
            self._transports[transp._sock_fd] = transp
