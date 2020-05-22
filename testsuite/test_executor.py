import concurrent.futures
import time
import unittest
import unittest.mock

import objc_asyncio

from . import utils


class TestExecutor(utils.TestCase):
    def test_setting_default_executor(self):
        self.assertIs(self.loop._default_executor, None)

        executor = concurrent.futures.ThreadPoolExecutor()

        self.loop.set_default_executor(executor)

        self.assertIs(self.loop._default_executor, executor)

        with self.assertRaises(TypeError):
            self.loop.set_default_executor(42)

    def test_run_in_executor_implied_default(self):
        self.assertIs(self.loop._default_executor, None)

        awaitable = self.loop.run_in_executor(None, lambda: 42)

        self.assertIsNot(self.loop._default_executor, None)
        self.assertIsInstance(
            self.loop._default_executor, concurrent.futures.ThreadPoolExecutor
        )

        result = self.loop.run_until_complete(awaitable)
        self.assertEqual(result, 42)

    def test_run_in_executor_explicit_default(self):
        executor = concurrent.futures.ThreadPoolExecutor()
        self.loop.set_default_executor(executor)

        awaitable = self.loop.run_in_executor(None, lambda: 42)

        self.assertIsNot(self.loop._default_executor, None)
        self.assertIsInstance(
            self.loop._default_executor, concurrent.futures.ThreadPoolExecutor
        )

        result = self.loop.run_until_complete(awaitable)
        self.assertEqual(result, 42)

    def test_run_in_executor_default_after_shutdown(self):
        awaitable = self.loop.run_in_executor(None, lambda: 42)
        result = self.loop.run_until_complete(awaitable)
        self.assertEqual(result, 42)

        self.loop.run_until_complete(self.loop.shutdown_default_executor())

        with self.assertRaises(RuntimeError):
            awaitable = self.loop.run_in_executor(None, lambda: 21)

    def test_run_in_executor_non_default(self):
        executor = concurrent.futures.ThreadPoolExecutor()
        self.addCleanup(executor.shutdown, wait=True)

        awaitable = self.loop.run_in_executor(executor, lambda: 42)

        self.assertIs(self.loop._default_executor, None)

        result = self.loop.run_until_complete(awaitable)
        self.assertEqual(result, 42)

    def test_shutdown_default_executor_not_running(self):
        self.assertFalse(self.loop._executor_shutdown_called)
        value = self.loop.run_until_complete(self.loop.shutdown_default_executor())
        self.assertTrue(self.loop._executor_shutdown_called)
        self.assertIs(value, None)

    def test_shutdown_default_executor_running(self):
        start = time.time()
        self.assertFalse(self.loop._executor_shutdown_called)
        awaitable = self.loop.run_in_executor(None, lambda: time.sleep(1))
        self.loop.run_until_complete(self.loop.shutdown_default_executor())
        self.assertTrue(self.loop._executor_shutdown_called)
        stop = time.time()

        self.assertGreater(stop - start, 0.5)

        result = self.loop.run_until_complete(awaitable)
        self.assertEqual(result, None)

    def test_closing(self):
        with self.subTest("not running"):
            loop = objc_asyncio.PyObjCEventLoop()
            loop.close()

        with self.subTest("running mock"):
            loop = objc_asyncio.PyObjCEventLoop()
            executor = loop._default_executor = unittest.mock.Mock()
            loop.close()

            self.assertIs(loop._default_executor, None)
            executor.shutdown.assert_called_once_with(wait=False)

        with self.subTest("running real"):
            loop = objc_asyncio.PyObjCEventLoop()
            executor = concurrent.futures.ThreadPoolExecutor()

            loop.set_default_executor(executor)

            self.assertIs(loop._default_executor, executor)

            loop.close()
            self.assertIs(loop._default_executor, None)
