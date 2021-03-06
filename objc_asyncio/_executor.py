__all__ = "ExecutorMixin"

import asyncio
import concurrent.futures
import threading
import typing


class ExecutorMixin:
    def __init__(self):
        self._default_executor = None
        self._executor_shutdown_called = False

    def close(self) -> None:
        self._executor_shutdown_called = True
        executor = self._default_executor
        if executor is not None:
            self._default_executor = None
            executor.shutdown(wait=False)

    def run_in_executor(
        self,
        executor: concurrent.futures.ThreadPoolExecutor,
        func: typing.Callable[..., typing.Any],
        *args: typing.Any,
    ) -> asyncio.Future:
        self._check_closed()
        if self._debug:
            self._check_callback(func, "run_in_executor")

        if executor is None:
            self._check_default_executor()
            executor = self._default_executor
            if executor is None:
                executor = concurrent.futures.ThreadPoolExecutor(
                    thread_name_prefix="objc_asyncio"
                )
                self._default_executor = executor
        return asyncio.wrap_future(executor.submit(func, *args), loop=self)

    def set_default_executor(
        self, executor: concurrent.futures.ThreadPoolExecutor
    ) -> None:
        if not isinstance(executor, concurrent.futures.ThreadPoolExecutor):
            # NOTE: This is legal in Python 3.8 an earlier, but will be an error
            # in Python 3.9.
            raise TypeError(f"{executor} is not a ThreadPoolExecutor")

        self._default_executor = executor

    async def shutdown_default_executor(self) -> None:
        """Schedule the shutdown of the default executor."""
        self._executor_shutdown_called = True
        if self._default_executor is None:
            return
        future = self.create_future()
        thread = threading.Thread(target=self._do_shutdown, args=(future,))
        thread.start()
        try:
            await future
        finally:
            thread.join()

    def _do_shutdown(self, future: asyncio.Future) -> None:
        try:
            self._default_executor.shutdown(wait=True)
            self.call_soon_threadsafe(future.set_result, None)
        except Exception as ex:
            self.call_soon_threadsafe(future.set_exception, ex)

    def _check_default_executor(self) -> None:
        if self._executor_shutdown_called:
            raise RuntimeError("Executor shutdown has been called")
