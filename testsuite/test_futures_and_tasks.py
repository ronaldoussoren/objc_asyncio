import asyncio
import sys

from . import utils


class TestFuturesAndTasks(utils.TestCase):
    def test_create_future(self):
        future = self.loop.create_future()
        self.assertIsInstance(future, asyncio.Future)

        self.assertIs(future.get_loop(), self.loop)

    def test_create_task_default(self):
        async def coro():
            pass

        task = self.loop.create_task(coro())
        self.assertIsInstance(task, asyncio.Task)
        self.loop.run_until_complete(task)

        if sys.version_info[:2] > (3, 7):
            task = self.loop.create_task(coro(), name="My Name")
            self.assertIsInstance(task, asyncio.Task)
            self.assertEqual(task.get_name(), "My Name")
            self.loop.run_until_complete(task)

    def test_create_task_with_factory(self):
        async def coro():
            pass

        class MyTask(asyncio.Task):
            pass

        def factory(loop, coro):
            self.assertIs(loop, loop)
            return MyTask(coro, loop=loop)

        self.loop.set_task_factory(factory)
        task = self.loop.create_task(coro())
        self.assertIsInstance(task, MyTask)
        self.loop.run_until_complete(task)

        if sys.version_info[:2] > (3, 7):
            task = self.loop.create_task(coro(), name="My Name")
            self.assertIsInstance(task, MyTask)
            self.assertEqual(task.get_name(), "My Name")
            self.loop.run_until_complete(task)

    def test_task_factory(self):
        self.assertIs(self.loop.get_task_factory(), None)

        with self.assertRaises(TypeError):
            self.loop.set_task_factory(1)

        def factory(loop, coro):
            pass

        self.loop.set_task_factory(factory)
        self.assertIs(self.loop.get_task_factory(), factory)

        self.loop.set_task_factory(None)
        self.assertIs(self.loop.get_task_factory(), None)
