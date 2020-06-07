import asyncio
import os
import signal
import subprocess

import objc_asyncio
from objc_asyncio._subprocess import _compute_returncode

from . import utils


class TestChildWatcher(utils.TestCase):
    def test_basic_running(self):
        watcher = objc_asyncio.KQueueChildWatcher()
        watcher.attach_loop(self.loop)
        self.addCleanup(watcher.close)

        watch_results = []

        def watch(pid, result, stop_loop, *args):
            watch_results.append((pid, result, args))
            if stop_loop:
                self.loop.stop()

        for binary, status in [("/usr/bin/true", 0), ("/usr/bin/false", 1)]:
            with self.subTest(binary=binary):
                del watch_results[:]
                p = subprocess.Popen([binary])
                self.addCleanup(p.wait)

                watcher.add_child_handler(p.pid, watch, True, "a", "b")

                self.loop.run_forever()

                self.assertEqual(watch_results, [(p.pid, status, ("a", "b"))])
                self.assertNotIn(p.pid, watcher._callbacks)

    def test_with_signal(self):
        watcher = objc_asyncio.KQueueChildWatcher()
        watcher.attach_loop(self.loop)
        self.addCleanup(watcher.close)

        watch_results = []

        def watch(pid, result, stop_loop, *args):
            watch_results.append((pid, result, args))
            if stop_loop:
                self.loop.stop()

        p = subprocess.Popen(["/bin/sleep", "5"])
        self.addCleanup(p.wait)

        watcher.add_child_handler(p.pid, watch, True, "A", "b")

        os.kill(p.pid, signal.SIGUSR1)

        self.loop.run_forever()

        self.assertEqual(watch_results, [(p.pid, -signal.SIGUSR1, ("A", "b"))])
        self.assertNotIn(p.pid, watcher._callbacks)

    def test_multiple(self):
        watcher = objc_asyncio.KQueueChildWatcher()
        watcher.attach_loop(self.loop)
        self.addCleanup(watcher.close)

        watch_results = set()

        def watch(pid, result, stop_loop, *args):
            watch_results.add((pid, result, args))
            if stop_loop:
                self.loop.stop()

        p1 = subprocess.Popen(["/usr/bin/true"])
        self.addCleanup(p1.wait)
        watcher.add_child_handler(p1.pid, watch, False)

        p2 = subprocess.Popen(["/usr/bin/false"])
        self.addCleanup(p2.wait)
        watcher.add_child_handler(p2.pid, watch, False)

        async def main():
            await asyncio.sleep(0.5)

        self.loop.run_until_complete(main())

        self.assertEqual(watch_results, {(p1.pid, 0, ()), (p2.pid, 1, ())})
        self.assertNotIn(p1.pid, watcher._callbacks)
        self.assertNotIn(p2.pid, watcher._callbacks)

    def test_add_remove(self):
        watcher = objc_asyncio.KQueueChildWatcher()
        watcher.attach_loop(self.loop)
        self.addCleanup(watcher.close)

        watch_results = set()

        def watch(pid, result, stop_loop, *args):
            watch_results.add((pid, result, args))
            if stop_loop:
                self.loop.stop()

        p1 = subprocess.Popen(["/usr/bin/true"])
        self.addCleanup(p1.wait)
        watcher.add_child_handler(p1.pid, watch, False)

        s = watcher.remove_child_handler(p1.pid)
        self.assertEqual(s, True)
        self.assertNotIn(p1.pid, watcher._callbacks)

        s = watcher.remove_child_handler(p1.pid)
        self.assertEqual(s, False)
        self.assertNotIn(p1.pid, watcher._callbacks)

        async def main():
            await asyncio.sleep(0.5)

        self.loop.run_until_complete(main())

        self.assertEqual(watch_results, set())

    def test_wait_for_reaped(self):
        watcher = objc_asyncio.KQueueChildWatcher()
        watcher.attach_loop(self.loop)
        self.addCleanup(watcher.close)

        watch_results = set()

        def watch(pid, result, stop_loop, *args):
            watch_results.add((pid, result, args))
            if stop_loop:
                self.loop.stop()

        p1 = subprocess.Popen(["/usr/bin/true"])
        self.addCleanup(p1.wait)
        watcher.add_child_handler(p1.pid, watch, False)

        p1.wait()

        async def main():
            await asyncio.sleep(0.5)

        with utils.captured_log() as stream:
            self.loop.run_until_complete(main())

        self.assertEqual(watch_results, {(p1.pid, 255, ())})
        self.assertNotIn(p1.pid, watcher._callbacks)

        self.assertIn("exit status already read", stream.getvalue())

    def test_decoding_status(self):
        with self.subTest("exit"):
            p = subprocess.Popen(["/usr/bin/false"])
            self.addCleanup(p.wait)
            _, status = os.waitpid(p.pid, 0)
            self.assertEqual(_compute_returncode(status), 1)
            p.wait()

        with self.subTest("signal"):
            p = subprocess.Popen(["/bin/sleep", "5"])
            self.addCleanup(p.wait)
            os.kill(p.pid, signal.SIGTERM)
            _, status = os.waitpid(p.pid, 0)
            self.assertEqual(_compute_returncode(status), -signal.SIGTERM)

        with self.subTest("stopped"):
            p = subprocess.Popen(["/bin/sleep", "50"])
            self.addCleanup(p.wait)
            p.send_signal(signal.SIGTSTP)
            _, status = os.waitpid(p.pid, os.WUNTRACED | os.WNOHANG)
            self.assertEqual(_compute_returncode(status), status)

            os.kill(p.pid, signal.SIGTERM)
            _, status = os.waitpid(p.pid, 0)
            self.assertEqual(_compute_returncode(status), -signal.SIGTERM)

    def test_attach_with_work(self):
        watcher = objc_asyncio.KQueueChildWatcher()
        watcher.attach_loop(self.loop)
        self.addCleanup(watcher.close)

        watch_results = set()

        def watch(pid, result):
            watch_results.add((pid, result))

        p1 = subprocess.Popen(["/usr/bin/true"], stdout=subprocess.DEVNULL)
        self.addCleanup(p1.wait)
        watcher.add_child_handler(p1.pid, watch)

        p2 = subprocess.Popen(["/usr/bin/true"], stdout=subprocess.DEVNULL)
        self.addCleanup(p2.wait)
        watcher.add_child_handler(p2.pid, watch)

        self.assertIn(p1.pid, watcher._callbacks)
        self.assertIn(p2.pid, watcher._callbacks)

        self.assertIs(watcher._loop, self.loop)

        loop2 = objc_asyncio.PyObjCEventLoop()
        self.assertIs(watcher._loop, self.loop)

        watcher.attach_loop(loop2)
        self.assertIs(watcher._loop, loop2)

        self.assertIn(p1.pid, watcher._callbacks)
        self.assertIn(p2.pid, watcher._callbacks)

        async def main():
            await asyncio.sleep(0.5)

        loop2.run_until_complete(main())

        self.assertNotIn(p1.pid, watcher._callbacks)
        self.assertNotIn(p2.pid, watcher._callbacks)

        self.assertEqual(watch_results, {(p1.pid, 0), (p2.pid, 0)})

    def test_detach_with_work(self):
        watcher = objc_asyncio.KQueueChildWatcher()
        watcher.attach_loop(self.loop)
        self.addCleanup(watcher.close)

        watch_results = set()

        def watch(pid, result):
            watch_results.add((pid, result))

        p1 = subprocess.Popen(["/bin/ls"], stdout=subprocess.DEVNULL)
        self.addCleanup(p1.wait)
        watcher.add_child_handler(p1.pid, watch)

        p2 = subprocess.Popen(["/bin/ls"], stdout=subprocess.DEVNULL)
        self.addCleanup(p2.wait)
        watcher.add_child_handler(p2.pid, watch)

        self.assertIn(p1.pid, watcher._callbacks)
        self.assertIn(p2.pid, watcher._callbacks)

        self.assertIs(watcher._loop, self.loop)

        with self.assertWarnsRegex(
            RuntimeWarning, "child watcher with pending handlers"
        ):
            watcher.attach_loop(None)

        self.assertIs(watcher._loop, None)

        self.assertNotIn(p1.pid, watcher._callbacks)
        self.assertNotIn(p2.pid, watcher._callbacks)
