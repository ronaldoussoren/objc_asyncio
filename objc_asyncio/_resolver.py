"""Resolver mixin"""
import collections
import itertools
import socket

from ._log import logger


def _interleave_addrinfos(addrinfos, first_address_family_count=1):
    """Interleave list of addrinfo tuples by family."""
    # Group addresses by family
    addrinfos_by_family = collections.OrderedDict()
    for addr in addrinfos:
        family = addr[0]
        if family not in addrinfos_by_family:
            addrinfos_by_family[family] = []
        addrinfos_by_family[family].append(addr)
    addrinfos_lists = list(addrinfos_by_family.values())

    reordered = []
    if first_address_family_count > 1:
        reordered.extend(addrinfos_lists[0][: first_address_family_count - 1])
        del addrinfos_lists[0][: first_address_family_count - 1]
    reordered.extend(
        a
        for a in itertools.chain.from_iterable(itertools.zip_longest(*addrinfos_lists))
        if a is not None
    )
    return reordered


def _ipaddr_info(host, port, family, type, proto, flowinfo=0, scopeid=0):  # noqa: A002
    # Try to skip getaddrinfo if "host" is already an IP. Users might have
    # handled name resolution in their own code and pass in resolved IPs.
    if not hasattr(socket, "inet_pton"):
        return None

    if proto not in {0, socket.IPPROTO_TCP, socket.IPPROTO_UDP} or host is None:
        return None

    if type == socket.SOCK_STREAM:
        proto = socket.IPPROTO_TCP
    elif type == socket.SOCK_DGRAM:
        proto = socket.IPPROTO_UDP
    else:
        return None

    if port is None:
        port = 0
    elif isinstance(port, bytes) and port == b"":
        port = 0
    elif isinstance(port, str) and port == "":
        port = 0
    else:
        # If port's a service name like "http", don't skip getaddrinfo.
        try:
            port = int(port)
        except (TypeError, ValueError):
            return None

    if family == socket.AF_UNSPEC:
        afs = [socket.AF_INET]
        afs.append(socket.AF_INET6)
    else:
        afs = [family]

    if isinstance(host, bytes):
        host = host.decode("idna")
    if "%" in host:
        # Linux's inet_pton doesn't accept an IPv6 zone index after host,
        # like '::1%lo0'.
        return None

    for af in afs:
        try:
            socket.inet_pton(af, host)
            # The host has already been resolved.
            if af == socket.AF_INET6:
                return af, type, proto, "", (host, port, flowinfo, scopeid)
            else:
                return af, type, proto, "", (host, port)
        except OSError:
            pass

    # "host" is not an IP address.
    return None


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
        addrinfo = socket.getaddrinfo(host, port, family, type, proto, flags)
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
