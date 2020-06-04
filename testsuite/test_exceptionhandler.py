import io
import logging
import traceback

from objc_asyncio._log import logger

from . import utils


class Attr:
    pass


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

    def test_default_handler_with_traceback(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)

        for key, needle in [
            ("source_traceback", "Object"),
            ("handle_traceback", "Handle"),
        ]:

            with self.subTest(key=key):

                stream.seek(0)
                stream.truncate()

                tb = traceback.extract_stack()

                context = {"attribute": "value", key: tb}
                self.loop.call_exception_handler(context)

                contents = stream.getvalue()

                self.assertIn("Unhandled exception in event loop", contents)
                self.assertIn("attribute", contents)
                self.assertIn("value", contents)

                self.assertIn(f"{needle} created at (most", contents)

    def test_default_handler_with_handle_traceback(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)

        tb = traceback.extract_stack()

        context = {"attribute": "value"}
        self.loop._current_handle = Attr()
        self.loop._current_handle._source_traceback = tb

        self.loop.call_exception_handler(context)

        contents = stream.getvalue()

        self.assertIn("Unhandled exception in event loop", contents)
        self.assertIn("attribute", contents)
        self.assertIn("value", contents)

        self.assertIn(f"Handle created at (most", contents)

    def test_exit_in_exception_handler(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)

        def handler(loop, context):
            raise exception

        self.loop.set_exception_handler(handler)

        for exception in (SystemExit, KeyboardInterrupt):
            with self.subTest(exception=exception):
                stream.seek(0)
                stream.truncate()

                async def main():
                    context = {"a": "b"}
                    self.loop.call_exception_handler(context)

                with self.assertRaises(exception):
                    self.loop.run_until_complete(main())

                self.assertEqual(stream.getvalue(), "")

    def test_exit_in_default_handler(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)

        def handler(loop, context):
            raise ValueError("dummy")

        def default_handler(context):
            raise exception

        self.loop.default_exception_handler = default_handler

        for handler in (None, handler):
            self.loop.set_exception_handler(handler)

            for exception in (SystemExit, KeyboardInterrupt):
                with self.subTest(handler=handler, exception=exception):
                    stream.seek(0)
                    stream.truncate()

                    async def main():
                        context = {"a": "b"}
                        self.loop.call_exception_handler(context)

                    with self.assertRaises(exception):
                        self.loop.run_until_complete(main())

                    self.assertEqual(stream.getvalue(), "")

    def test_error_in_default_handler(self):
        class MyException(Exception):
            pass

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)

        def handler(loop, context):
            raise ValueError("dummy")

        def default_handler(context):
            raise exception

        self.loop.default_exception_handler = default_handler

        for handler in (None, handler):
            self.loop.set_exception_handler(handler)

            for exception in (MyException,):
                with self.subTest(handler=handler, exception=exception):
                    stream.seek(0)
                    stream.truncate()

                    context = {"a": "b"}
                    self.loop.call_exception_handler(context)

                    self.assertIn(
                        "Exception in default exception handler", stream.getvalue()
                    )
                    if handler is not None:
                        self.assertIn(
                            "while handling an unexpected error in custom exception handler",
                            stream.getvalue(),
                        )
