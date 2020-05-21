import asyncio
import signal
import unittest

import objc_asyncio


class TestFuturesAndTasks(unittest.TestCase):
    def setUp(self):
        signal.alarm(2)

    def tearDown(self):
        signal.alarm(0)

    def test_create_future(self):
        loop = objc_asyncio.PyObjCEventLoop()
        asyncio.set_event_loop(loop)
        self.addCleanup(loop.close)

        future = loop.create_future()
        self.assertIsInstance(future, asyncio.Future)

        self.assertIs(future.get_loop(), loop)

    def test_create_task_default(self):
        loop = objc_asyncio.PyObjCEventLoop()
        asyncio.set_event_loop(loop)
        self.addCleanup(loop.close)

        async def coro():
            pass

        task = loop.create_task(coro())
        self.assertIsInstance(task, asyncio.Task)
        loop.run_until_complete(task)

        task = loop.create_task(coro(), name="My Name")
        self.assertIsInstance(task, asyncio.Task)
        self.assertEqual(task.get_name(), "My Name")
        loop.run_until_complete(task)

    def test_create_task_with_factory(self):
        loop = objc_asyncio.PyObjCEventLoop()
        asyncio.set_event_loop(loop)
        self.addCleanup(loop.close)

        async def coro():
            pass

        class MyTask(asyncio.Task):
            pass

        def factory(loop, coro):
            self.assertIs(loop, loop)
            return MyTask(coro, loop=loop)

        loop.set_task_factory(factory)
        task = loop.create_task(coro())
        self.assertIsInstance(task, MyTask)
        loop.run_until_complete(task)

        task = loop.create_task(coro(), name="My Name")
        self.assertIsInstance(task, MyTask)
        self.assertEqual(task.get_name(), "My Name")
        loop.run_until_complete(task)

    def test_task_factory(self):
        loop = objc_asyncio.PyObjCEventLoop()
        asyncio.set_event_loop(loop)
        self.addCleanup(loop.close)

        self.assertIs(loop.get_task_factory(), None)

        with self.assertRaises(TypeError):
            loop.set_task_factory(1)

        def factory(loop, coro):
            pass

        loop.set_task_factory(factory)
        self.assertIs(loop.get_task_factory(), factory)

        loop.set_task_factory(None)
        self.assertIs(loop.get_task_factory(), None)
