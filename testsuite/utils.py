import asyncio
import contextlib
import io
import logging
import signal
import socket
import threading
import unittest

import objc_asyncio
from objc_asyncio._log import logger

MAX_TEST_TIME = 30


@contextlib.contextmanager
def captured_log():
    try:
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter(fmt="%(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        yield stream

    finally:
        logger.removeHandler(handler)
        logger.setLevel(logging.NOTSET)


class TestCase(unittest.TestCase):
    def setUp(self):
        # Ensure the process is killed when a test takes
        # too much time.
        signal.alarm(MAX_TEST_TIME)

        self._old_policy = asyncio.get_event_loop_policy()
        asyncio.set_event_loop_policy(objc_asyncio.PyObjCEventLoopPolicy())
        self.loop = objc_asyncio.PyObjCEventLoop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        if self.loop._default_executor is not None:
            if self.loop.is_closed():
                self.loop._default_executor.shutdown(wait=True)
            else:
                self.loop.run_until_complete(self.loop.shutdown_default_executor())

        self.loop.close()
        asyncio.set_event_loop(None)
        asyncio.set_event_loop_policy(self._old_policy)
        signal.alarm(0)

    def make_socketpair(
        self, family=socket.AF_UNIX, type=socket.SOCK_STREAM, proto=0  # noqa: A002
    ):
        def close_socket(sd):
            try:
                sd.close()
            except socket.error:
                pass

        sd1, sd2 = socket.socketpair(family, type, proto)
        self.addCleanup(close_socket, sd1)
        self.addCleanup(close_socket, sd2)

        sd1.setblocking(False)
        sd2.setblocking(False)

        return sd1, sd2

    def make_echoserver(self, family=socket.AF_INET):
        sd_serv = socket.socket(family, socket.SOCK_STREAM, 0)
        sd_serv.listen(5)
        self.addCleanup(sd_serv.close)

        def runloop():
            try:
                while True:
                    sd, addr = sd_serv.accept()

                    data = sd.recv(100)
                    data = data.upper()
                    sd.sendall(data)
                    sd.close()

            except socket.error:
                pass

        thr = threading.Thread(target=runloop)
        thr.start()

        return sd_serv.getsockname()


class EchoServerProtocol(asyncio.Protocol):
    def connection_made(self, transport):
        self.transport = transport

    def data_received(self, data):
        self.transport.write(data)
        self.transport.close()
