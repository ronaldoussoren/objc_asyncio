import asyncio
import threading
import unittest

import objc_asyncio


class TestEventLoopPolicy(unittest.TestCase):
    def test_default_loop(self):
        p = objc_asyncio.PyObjCEventLoopPolicy()

        l1 = p.get_event_loop()
        self.assertIsInstance(l1, objc_asyncio.PyObjCEventLoop)

        l2 = p.get_event_loop()

        self.assertIs(l1, l2)

    def test_default_loop_in_thread(self):
        p = objc_asyncio.PyObjCEventLoopPolicy()

        exception = None
        result = no_object = object()

        def thread_main():
            nonlocal exception, result

            try:
                result = p.get_event_loop()

            except Exception as exc:
                exception = exc

        t = threading.Thread(target=thread_main)
        t.start()
        t.join()

        self.assertIsInstance(exception, RuntimeError)
        self.assertIs(result, no_object)

    def test_setting_loop(self):
        p = objc_asyncio.PyObjCEventLoopPolicy()

        p.get_event_loop()
        loop = objc_asyncio.PyObjCEventLoop()

        p.set_event_loop(loop)
        self.assertIs(p.get_event_loop(), loop)

    def test_setting_loop_in_thread(self):
        p = objc_asyncio.PyObjCEventLoopPolicy()

        exception = None
        thread_loop = None
        result = object()

        def thread_main():
            nonlocal exception, result, thread_loop

            thread_loop = objc_asyncio.PyObjCEventLoop()
            p.set_event_loop(thread_loop)

            try:
                result = p.get_event_loop()

            except Exception as exc:
                exception = exc

        before = p.get_event_loop()

        t = threading.Thread(target=thread_main)
        t.start()
        t.join()

        self.assertIs(exception, None)
        self.assertIs(result, thread_loop)
        self.assertIsInstance(result, objc_asyncio.PyObjCEventLoop)
        self.assertIs(p.get_event_loop(), before)

    def test_new_event_loop(self):
        p = objc_asyncio.PyObjCEventLoopPolicy()

        loops = [p.new_event_loop() for _ in range(2)]

        self.assertIsInstance(loops[0], objc_asyncio.PyObjCEventLoop)
        self.assertIsInstance(loops[1], objc_asyncio.PyObjCEventLoop)

        self.assertIsNot(loops[0], loops[1])

    def test_default_child_watcher(self):
        p = objc_asyncio.PyObjCEventLoopPolicy()

        watcher = p.get_child_watcher()
        self.assertIsInstance(watcher, objc_asyncio.KQueueChildWatcher)

        self.assertIs(p.get_child_watcher(), watcher)

        self.assertIs(watcher._loop, None)
        p.get_event_loop()
        self.assertIs(watcher._loop, p.get_event_loop())

    def test_default_child_watcher_on_thread(self):
        p = objc_asyncio.PyObjCEventLoopPolicy()
        p.get_event_loop()

        watcher = None

        def thread_main():
            nonlocal watcher

            p.set_event_loop(objc_asyncio.PyObjCEventLoop())

            watcher = p.get_child_watcher()

        t = threading.Thread(target=thread_main)
        t.start()
        t.join()

        self.assertIs(watcher, p.get_child_watcher())
        self.assertIsInstance(watcher, objc_asyncio.KQueueChildWatcher)
        self.assertIs(watcher._loop, None)

    def test_set_child_watcher(self):
        p = objc_asyncio.PyObjCEventLoopPolicy()

        watcher = asyncio.ThreadedChildWatcher()

        p.set_child_watcher(watcher)
        self.assertIs(p.get_child_watcher(), watcher)

    def test_set_child_watcher_on_thread(self):
        p = objc_asyncio.PyObjCEventLoopPolicy()

        watcher = asyncio.SafeChildWatcher()

        def thread_main():
            thread_loop = objc_asyncio.PyObjCEventLoop()
            p.set_event_loop(thread_loop)
            p.set_child_watcher(watcher)

        t = threading.Thread(target=thread_main)
        t.start()
        t.join()

        self.assertIs(p.get_child_watcher(), watcher)
        self.assertIs(watcher._loop, None)

    def test_resetting_child_watcher(self):
        p = objc_asyncio.PyObjCEventLoopPolicy()

        p.get_event_loop()

        watcher = p.get_child_watcher()
        self.assertIsInstance(watcher, objc_asyncio.KQueueChildWatcher)
        self.assertIs(watcher._loop, p.get_event_loop())

        new_watcher = asyncio.SafeChildWatcher()
        p.set_child_watcher(new_watcher)

        self.assertIs(watcher._loop, None)
        self.assertIs(new_watcher._loop, None)

        loop = objc_asyncio.PyObjCEventLoop()
        p.set_event_loop(loop)

        self.assertIs(watcher._loop, None)
        self.assertIs(new_watcher._loop, loop)
        self.assertIs(p.get_event_loop(), loop)
