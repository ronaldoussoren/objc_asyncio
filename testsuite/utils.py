import asyncio
import signal
import socket
import unittest

import objc_asyncio

MAX_TEST_TIME = 30


class TestCase(unittest.TestCase):
    def setUp(self):
        # Ensure the process is killed when a test takes
        # too much time.
        signal.alarm(MAX_TEST_TIME)

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
