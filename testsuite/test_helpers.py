import asyncio
import unittest

import objc_asyncio

from . import utils


class TestHelpers(unittest.TestCase):
    def setUp(self):
        self._policy = asyncio.get_event_loop_policy()
        self._loop = asyncio.get_event_loop()

    def tearDown(self):
        asyncio.set_event_loop_policy(self._policy)
        asyncio.set_event_loop(self._loop)

    def test_install(self):
        self.assertNotIsInstance(
            asyncio.get_event_loop_policy(), objc_asyncio.PyObjCEventLoopPolicy
        )

        objc_asyncio.install()

        self.assertIsInstance(
            asyncio.get_event_loop_policy(), objc_asyncio.PyObjCEventLoopPolicy
        )

    def test_running_loop_normal(self):
        self.assertNotIsInstance(
            asyncio.get_event_loop_policy(), objc_asyncio.PyObjCEventLoopPolicy
        )

        with objc_asyncio.running_loop():
            self.assertIsInstance(
                asyncio.get_event_loop_policy(), objc_asyncio.PyObjCEventLoopPolicy
            )

            loop = asyncio.get_event_loop()
            self.assertIsInstance(loop, objc_asyncio.PyObjCEventLoop)

            self.assertTrue(loop.is_running())

        self.assertFalse(loop.is_running())

    def test_running_loop_exception(self):
        self.assertNotIsInstance(
            asyncio.get_event_loop_policy(), objc_asyncio.PyObjCEventLoopPolicy
        )

        try:
            with objc_asyncio.running_loop():
                self.assertIsInstance(
                    asyncio.get_event_loop_policy(), objc_asyncio.PyObjCEventLoopPolicy
                )

                loop = asyncio.get_event_loop()
                self.assertIsInstance(loop, objc_asyncio.PyObjCEventLoop)

                self.assertTrue(loop.is_running())

                raise ValueError()
        except ValueError:
            pass

        self.assertFalse(loop.is_running())


class TestContextManagers(utils.TestCase):
    def test_ibaction_sync(self):

        called = False
        the_sender = None

        @objc_asyncio.IBAction
        def actionWithSender_(self, sender):
            nonlocal called, the_sender
            called = True
            the_sender = sender

        async def main():
            actionWithSender_(None, 42)
            asyncio.sleep(0.1)

        self.loop.run_until_complete(main())

        self.assertTrue(called)
        self.assertEqual(the_sender, 42)

    def test_ibaction_async(self):

        called = False
        the_sender = None

        @objc_asyncio.IBAction
        async def actionWithSender_(self, sender):
            nonlocal called, the_sender
            called = True
            the_sender = sender

        async def main():
            actionWithSender_(None, 42)
            asyncio.sleep(0.1)

        self.loop.run_until_complete(main())

        self.assertTrue(called)
        self.assertEqual(the_sender, 42)
