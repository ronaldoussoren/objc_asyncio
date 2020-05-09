import concurrent.futures
import unittest

from objc_asyncio import _executor as mod


class ExecLoop(mod.ExecutorMixin):
    """Minimal loop to facilitate testing"""

    def __init__(self, debug=False):
        self._debug = debug
        self._call_soon = []

        mod.ExecutorMixin.__init__(self)

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
        pass

    def test_run_in_executor_explicit_default(self):
        pass

    def test_run_in_executor_default_after_shutdown(self):
        pass

    def test_run_in_executor_non_default(self):
        pass

    def test_shutdown_default_executor_not_running(self):
        pass

    def test_shutdown_default_executor_running(self):
        pass

    def test_closing(self):
        pass
