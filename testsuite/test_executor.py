import asyncio
import concurrent.futures
import time
import unittest
import unittest.mock

from objc_asyncio import _executor as mod


class ExecLoop(mod.ExecutorMixin):
    """Minimal loop to facilitate testing"""

    def __init__(self, debug=False):
        self._debug = debug
        self._call_soon = []

        mod.ExecutorMixin.__init__(self)

    def _check_closed(self):
        pass

    def create_future(self):
        return asyncio.Future()

    def call_soon_threadsafe(self, callback, *args, context=None):
        self._call_soon.append((callback, args, context))


class TestExecutor(unittest.TestCase):
    def test_setting_default_executor(self):
        loop = ExecLoop()

        self.assertIs(loop._default_executor, None)

        executor = concurrent.futures.ThreadPoolExecutor()

        loop.set_default_executor(executor)

        self.assertIs(loop._default_executor, executor)

        with self.assertRaises(TypeError):
            loop.set_default_executor(42)

    def test_run_in_executor_implied_default(self):
        loop = ExecLoop()

        self.assertIs(loop._default_executor, None)

        loop.run_in_executor(None, lambda: 42)

        self.assertIsNot(loop._default_executor, None)
        self.assertIsInstance(
            loop._default_executor, concurrent.futures.ThreadPoolExecutor
        )

        time.sleep(0.5)
        time.sleep(0.5)

        self.assertNotEqual(loop._call_soon, [])

    def test_run_in_executor_explicit_default(self):
        pass

    def test_run_in_executor_default_after_shutdown(self):
        pass

    def test_run_in_executor_non_default(self):
        pass

    def test_shutdown_default_executor_not_running(self):
        loop = ExecLoop()
        self.assertFalse(loop._executor_shutdown_called)
        loop.shutdown_default_executor()  # XXX: Async...
        self.assertTrue(loop._executor_shutdown_called)

    def test_shutdown_default_executor_running(self):
        pass

    def test_closing(self):
        with self.subTest("not running"):
            loop = ExecLoop()
            loop.close()

        with self.subTest("running mock"):
            loop = ExecLoop()
            executor = loop._default_executor = unittest.mock.Mock()
            loop.close()

            self.assertIs(loop._default_executor, None)
            executor.shutdown.assert_called_once_with(wait=False)

        with self.subTest("running real"):
            loop = ExecLoop()
            executor = concurrent.futures.ThreadPoolExecutor()

            loop.set_default_executor(executor)

            self.assertIs(loop._default_executor, None)
