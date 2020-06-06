import asyncio
import os
import signal
import threading
import time
import unittest.mock

import objc_asyncio

from . import utils


class TestSignal(utils.TestCase):
    def test_signal_handler(self):
        signal_list = []

        def signal_callback(signo):
            signal_list.append(signo)

        def killer(signo):
            time.sleep(0.1)
            os.kill(os.getpid(), signo)

        async def main():
            self.loop.run_in_executor(None, killer, signal.SIGWINCH)
            self.loop.run_in_executor(None, killer, signal.SIGUSR2)
            await asyncio.sleep(0.3)
            self.loop.remove_signal_handler(signal.SIGWINCH)  # default: ignore
            self.loop.run_in_executor(None, killer, signal.SIGWINCH)
            self.loop.run_in_executor(None, killer, signal.SIGUSR2)
            await asyncio.sleep(0.3)

        self.loop.add_signal_handler(signal.SIGWINCH, signal_callback, "WINCH")
        self.loop.add_signal_handler(signal.SIGUSR2, signal_callback, "USR2")

        self.loop.run_until_complete(main())

        self.assertEqual(len(signal_list), 3)
        self.assertEqual(signal_list.count("WINCH"), 1)
        self.assertEqual(signal_list.count("USR2"), 2)

    def test_invalid_signo(self):
        with self.assertRaises(ValueError):
            self.loop.add_signal_handler(999, lambda: None)

        with self.assertRaises(TypeError):
            self.loop.add_signal_handler("SIGINT", lambda: None)

    def test_invalid_handler(self):
        async def handler(a, b):
            pass

        with self.subTest("not callable"):
            with self.assertRaises(TypeError):
                self.loop.add_signal_handler(signal.SIGUSR1, 42)

        with self.subTest("coroutine function"):
            with self.assertRaises(TypeError):
                self.loop.add_signal_handler(signal.SIGUSR1, handler)

        with self.subTest("coroutine"):
            with self.assertRaises(TypeError):
                self.loop.add_signal_handler(signal.SIGUSR1, handler())

    def test_uncatchable_signals(self):
        def handler():
            pass

        with self.assertRaises(RuntimeError):
            self.loop.add_signal_handler(signal.SIGKILL, handler)

        self.loop.add_signal_handler(signal.SIGUSR1, handler)
        with self.assertRaises(RuntimeError):
            self.loop.add_signal_handler(signal.SIGKILL, handler)
        self.loop.remove_signal_handler(signal.SIGUSR1)

        with self.assertRaises(RuntimeError):
            self.loop._signal_handlers[signal.SIGKILL] = 42
            self.loop.remove_signal_handler(signal.SIGKILL)

    def test_closing_regular(self):
        def handler():
            pass

        loop = objc_asyncio.PyObjCEventLoop()
        asyncio.set_event_loop(loop)

        loop.add_signal_handler(signal.SIGUSR1, handler)
        self.assertIn(signal.SIGUSR1, loop._signal_handlers)

        loop.close()

        self.assertNotIn(signal.SIGUSR1, loop._signal_handlers)

        # Closing again should be safe
        loop.close()

    def test_closing_system_exit(self):
        # Testing at interpreter shutdown cannot be done for real, use
        # mocks.

        def handler():
            pass

        loop = objc_asyncio.PyObjCEventLoop()
        asyncio.set_event_loop(loop)

        loop.add_signal_handler(signal.SIGUSR1, handler)
        self.assertIn(signal.SIGUSR1, loop._signal_handlers)

        with self.assertWarns(ResourceWarning):
            with unittest.mock.patch("sys.is_finalizing", return_value=True):
                with unittest.mock.patch.object(
                    objc_asyncio.PyObjCEventLoop, "remove_signal_handler"
                ) as remove_mock:
                    loop.close()

        self.assertNotIn(signal.SIGUSR1, loop._signal_handlers)
        remove_mock.assert_not_called()

    def test_no_signal_handlers_no_threads(self):

        ok = False
        exception = None

        def thread_main():
            nonlocal ok, exception
            loop = objc_asyncio.PyObjCEventLoop()
            asyncio.set_event_loop(loop)

            try:
                loop.add_signal_handler(signal.SIGUSR1, lambda: None)
                ok = True

            except Exception as exc:
                exception = exc

        thr = threading.Thread(target=thread_main)
        thr.start()
        thr.join()

        self.assertFalse(ok)
        self.assertIsInstance(exception, RuntimeError)

    def test_remove_from_thread(self):
        ok = False
        exception = None

        self.loop.add_signal_handler(signal.SIGUSR1, lambda: None)

        def thread_main():
            nonlocal ok, exception

            try:
                self.loop.remove_signal_handler(signal.SIGUSR1)
                ok = True

            except Exception as exc:
                exception = exc

        thr = threading.Thread(target=thread_main)
        thr.start()
        thr.join()

        self.assertFalse(ok)
        self.assertIsInstance(exception, (ValueError, OSError))

        self.loop.add_signal_handler(signal.SIGUSR1, lambda: None)

    def test_add_remove(self):
        # Add and remove handlers for a couple of signals, and
        # check this actually changes the signal handler
        curhandlers = {}
        for signo in (signal.SIGUSR1, signal.SIGINT):
            curhandlers[signo] = signal.signal(signo, lambda *args: None)
            signal.signal(signo, curhandlers[signo])

        for signo in (signal.SIGUSR1, signal.SIGINT):
            self.loop.add_signal_handler(signo, lambda: None)

        for signo in (signal.SIGUSR1, signal.SIGINT):
            h = signal.signal(signo, lambda *args: None)
            self.assertIsNot(h, curhandlers[signo])
            signal.signal(signo, h)

        for signo in (signal.SIGUSR1, signal.SIGINT):
            self.assertEqual(self.loop.remove_signal_handler(signo), True)

        for signo in (signal.SIGUSR1, signal.SIGINT):
            h = signal.signal(signo, lambda *args: None)
            self.assertIs(h, curhandlers[signo])
            signal.signal(signo, h)

    def test_remove_non_existing(self):
        self.assertEqual(self.loop.remove_signal_handler(signal.SIGINT), False)

    def test_signal_fd_problems(self):
        self.loop.add_signal_handler(signal.SIGUSR1, lambda: None)
        self.assertIn(signal.SIGUSR1, self.loop._signal_handlers)

        with self.subTest("remove last signal handler"):
            with unittest.mock.patch(
                "signal.set_wakeup_fd", side_effect=ValueError
            ) as mock_func:
                self.loop.remove_signal_handler(signal.SIGUSR1)

            mock_func.assert_called_once_with(-1)
            self.assertNotIn(signal.SIGUSR1, self.loop._signal_handlers)

        with self.subTest("add first signal handler"):
            with self.assertRaises(RuntimeError):
                with unittest.mock.patch(
                    "signal.set_wakeup_fd", side_effect=ValueError
                ) as mock_func:
                    self.loop.add_signal_handler(signal.SIGUSR1, lambda: None)

            mock_func.assert_called_once_with(self.loop._csock.fileno())
            self.assertNotIn(signal.SIGUSR1, self.loop._signal_handlers)

        with self.subTest("adding handler for SIGKILL"):

            def side_effect(value):
                if value == -1:
                    raise ValueError

            with self.assertRaises(RuntimeError):
                with unittest.mock.patch(
                    "signal.set_wakeup_fd", side_effect=side_effect
                ) as mock_func:
                    self.loop.add_signal_handler(signal.SIGKILL, lambda: None)

            mock_func.assert_called_with(-1)
            self.assertNotIn(signal.SIGKILL, self.loop._signal_handlers)

    def test_signal_gone(self):
        signal_list = []

        def signal_callback(signo):
            signal_list.append(signo)

        def killer(signo):
            time.sleep(0.1)
            os.kill(os.getpid(), signo)

        async def main():
            self.loop.run_in_executor(None, killer, signal.SIGWINCH)
            await asyncio.sleep(0.3)

        self.loop.add_signal_handler(signal.SIGWINCH, signal_callback, "WINCH")
        del self.loop._signal_handlers[signal.SIGWINCH]

        self.loop.run_until_complete(main())

        self.assertEqual(len(signal_list), 0)

    def test_signal_cancelled(self):
        signal_list = []

        def signal_callback(signo):
            signal_list.append(signo)

        def killer(signo):
            time.sleep(0.1)
            os.kill(os.getpid(), signo)

        async def main():
            self.loop.run_in_executor(None, killer, signal.SIGWINCH)
            await asyncio.sleep(0.3)

        self.loop.add_signal_handler(signal.SIGWINCH, signal_callback, "WINCH")
        self.loop._signal_handlers[signal.SIGWINCH].cancel()

        self.loop.run_until_complete(main())

        self.assertEqual(len(signal_list), 0)

    def test_self_pipe_full(self):
        count = 0

        def handler():
            nonlocal count
            count += 1

        sent = self.loop._csock.send(bytes((signal.SIGUSR1,)) * 5000)
        self.assertEqual(sent, 5000)

        self.loop.add_signal_handler(signal.SIGUSR1, handler)

        async def main():
            await asyncio.sleep(0.5)

        self.loop.run_until_complete(main())

        self.assertEqual(count, 5000)

    def test_self_pipe_eof(self):
        count = 0

        def handler():
            nonlocal count
            count += 1

        sent = self.loop._csock.send(bytes((signal.SIGUSR1,)) * 800)
        self.assertEqual(sent, 800)
        self.loop._csock.close()

        self.loop.add_signal_handler(signal.SIGUSR1, handler)

        async def main():
            await asyncio.sleep(0.5)

        self.loop.run_until_complete(main())

        self.assertEqual(count, 800)

    def test_self_pipe_read_interrupted(self):
        count = 0

        def handler():
            nonlocal count
            count += 1

        sent = self.loop._csock.send(bytes((signal.SIGUSR1,)))
        self.assertEqual(sent, 1)
        self.loop._csock.close()

        self.loop.add_signal_handler(signal.SIGUSR1, handler)

        async def main():
            await asyncio.sleep(0.5)

        raised = False

        def mocked_recv(count, sock=self.loop._ssock):
            nonlocal raised
            if not raised:
                raised = True
                raise InterruptedError

            else:
                return sock.recv(count)

        with unittest.mock.patch.object(self.loop, "_ssock", spec=True) as mock:
            mock.recv = unittest.mock.Mock(side_effect=mocked_recv)
            self.loop.run_until_complete(main())

        self.assertEqual(count, 1)
