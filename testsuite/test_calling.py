import asyncio
import time

from . import utils


class TestFutureCalling(utils.TestCase):
    def test_time(self):
        self.assertAlmostEqual(self.loop.time(), time.time(), 2)

    def test_call_later(self):
        end_time = None
        arg_tuple = None

        def callback(*args):
            nonlocal end_time, arg_tuple
            arg_tuple = args
            end_time = time.time()

        async def wait(seconds):
            await asyncio.sleep(seconds)

        start_time = time.time()

        handle = self.loop.call_later(0.5, callback, 1, 2)
        self.assertIsInstance(handle, asyncio.Handle)

        self.loop.run_until_complete(wait(2))

        self.assertAlmostEqual(end_time - start_time, 0.5, 1)
        self.assertEqual(arg_tuple, (1, 2))

    def test_call_at(self):
        end_time = None
        arg_tuple = None

        def callback(*args):
            nonlocal end_time, arg_tuple
            arg_tuple = args
            end_time = time.time()

        async def wait(seconds):
            await asyncio.sleep(seconds)

        start_time = time.time()
        scheduled_time = start_time + 0.5

        handle = self.loop.call_at(scheduled_time, callback, 1, 2)
        self.assertIsInstance(handle, asyncio.Handle)

        self.loop.run_until_complete(wait(2))

        self.assertAlmostEqual(end_time, scheduled_time, 1)
        self.assertEqual(arg_tuple, (1, 2))

    def test_call_soon(self):
        arg_tuple = None

        def callback(*args):
            nonlocal arg_tuple
            arg_tuple = args

        async def wait1():
            await asyncio.sleep(0.5)

        async def wait2():
            self.loop.call_soon(callback, 3, 4)
            await asyncio.sleep(0.5)

        handle = self.loop.call_soon(callback, 1, 2)
        self.assertIsInstance(handle, asyncio.Handle)

        self.loop.run_until_complete(wait1())
        self.assertEqual(arg_tuple, (1, 2))

        self.loop.run_until_complete(wait2())
        self.assertEqual(arg_tuple, (3, 4))

    def test_call_soon_threadsafe(self):
        arg_tuple = None

        def callback(*args):
            nonlocal arg_tuple
            arg_tuple = args

        async def wait1():
            await asyncio.sleep(0.5)

        async def wait2():
            self.loop.call_soon_threadsafe(callback, 3, 4)
            await asyncio.sleep(0.5)

        handle = self.loop.call_soon(callback, 1, 2)
        self.assertIsInstance(handle, asyncio.Handle)

        self.loop.run_until_complete(wait1())
        self.assertEqual(arg_tuple, (1, 2))

        self.loop.run_until_complete(wait2())
        self.assertEqual(arg_tuple, (3, 4))

    def test_calling_with_cancel(self):
        arg_tuple = None

        def callback(*args):
            nonlocal arg_tuple
            arg_tuple = args

        async def wait():
            await asyncio.sleep(1.0)

        with self.subTest("call_soon"):
            handle = self.loop.call_soon(callback, 1, 2)
            handle.cancel()

            self.loop.run_until_complete(wait())
            self.assertEqual(arg_tuple, None)
            arg_tuple = None

        with self.subTest("call_soon_threadsafe"):
            handle = self.loop.call_soon_threadsafe(callback, 1, 2)
            handle.cancel()

            self.loop.run_until_complete(wait())
            self.assertEqual(arg_tuple, None)
            arg_tuple = None

        with self.subTest("call_later"):
            handle = self.loop.call_later(0.5, callback, 1, 2)
            handle.cancel()
            self.loop.run_until_complete(wait())
            self.assertEqual(arg_tuple, None)
            arg_tuple = None

        with self.subTest("call_at"):
            handle = self.loop.call_at(time.time() + 0.8, callback, 1, 2)
            handle.cancel()

            self.loop.run_until_complete(wait())
            self.assertEqual(arg_tuple, None)
            arg_tuple = None

        with self.subTest("call_later with multiple jobs"):
            self.loop.call_later(0.3, callback, 1, 2)
            self.loop.call_later(0.3, callback, 3, 4)

            # XXX: This is a crude hack to hit some code for testing...
            self.loop._timer_q[1].cancel()

            self.loop.run_until_complete(wait())
            self.assertIsNot(arg_tuple, None)
            arg_tuple = None
