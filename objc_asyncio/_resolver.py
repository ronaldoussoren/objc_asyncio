"""Resolver mixin"""
import socket
from asyncio.base_events import _interleave_addrinfos, _ipaddr_info  # noqa: F401

from ._log import logger


class ResolverMixin:
    # XXX: This mixin uses run_in_executor to resolve async, investigate
    # using framework APIs for that (CFNetwork probably has something
    # usefull.
    def _getaddrinfo_debug(self, host, port, family, type, proto, flags):  # noqa: A002
        msg = [f"{host}:{port!r}"]
        if family:
            msg.append(f"family={family!r}")
        if type:
            msg.append(f"type={type!r}")
        if proto:
            msg.append(f"proto={proto!r}")
        if flags:
            msg.append(f"flags={flags!r}")
        msg = ", ".join(msg)
        logger.debug("Get address info %s", msg)

        t0 = self.time()
        try:
            addrinfo = socket.getaddrinfo(host, port, family, type, proto, flags)

        except socket.error as exc:
            dt = self.time() - t0

            msg = f"Getting address info {msg} failed in {dt * 1e3:.3f}ms: {exc!r}"

            if dt >= self.slow_callback_duration:
                logger.info(msg)
            else:
                logger.debug(msg)

            raise

        else:
            dt = self.time() - t0

            msg = f"Getting address info {msg} took {dt * 1e3:.3f}ms: {addrinfo!r}"

            if dt >= self.slow_callback_duration:
                logger.info(msg)
            else:
                logger.debug(msg)
        return addrinfo

    async def getaddrinfo(
        self, host, port, *, family=0, type=0, proto=0, flags=0  # noqa: A002
    ):
        if self._debug:
            getaddr_func = self._getaddrinfo_debug
        else:
            getaddr_func = socket.getaddrinfo

        return await self.run_in_executor(
            None, getaddr_func, host, port, family, type, proto, flags
        )

    async def getnameinfo(self, sockaddr, flags=0):
        return await self.run_in_executor(None, socket.getnameinfo, sockaddr, flags)
