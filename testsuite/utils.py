import asyncio
import signal
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
