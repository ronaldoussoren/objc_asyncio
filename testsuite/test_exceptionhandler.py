import io
import logging

from objc_asyncio._log import logger

from . import utils


class TestExceptionHandler(utils.TestCase):
    def test_setting_handler(self):
        self.assertIs(self.loop.get_exception_handler(), None)

        def handler(loop, context):
            pass

        self.loop.set_exception_handler(handler)

        self.assertIs(self.loop.get_exception_handler(), handler)

        self.loop.set_exception_handler(None)

        self.assertIs(self.loop.get_exception_handler(), None)

    def test_calling_handler(self):
        handled = []

        def handler(loop, context):
            handled.append((loop, context))

        self.loop.set_exception_handler(handler)

        context = {"a": "b"}

        self.loop.call_exception_handler(context)
        self.assertEqual(handled, [(self.loop, context)])

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)

        # Make sure exceptions are swallowed
        handled = None
        self.loop.call_exception_handler(context)
        self.assertIs(handled, None)

        contents = stream.getvalue()

        self.assertIn("Unhandled error in exception handler", contents)
        self.assertIn("AttributeError", contents)

    def test_default_handler(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)

        context = {"attribute": "value", "dogs": "cats"}
        self.loop.call_exception_handler(context)

        contents = stream.getvalue()

        self.assertIn("Unhandled exception in event loop", contents)
        self.assertIn("attribute", contents)
        self.assertIn("value", contents)
        self.assertIn("dogs", contents)
        self.assertIn("cats", contents)
