import unittest

from objc_asyncio import _exceptionhandler as mod


class EHLoop(mod.ExceptionHandlerMixin):
    """Minimal loop to facilitate testing"""

    def __init__(self, debug=False):
        self._debug = debug
        self._current_handle = None

        mod.ExceptionHandlerMixin.__init__(self)


class TestExceptionHandler(unittest.TestCase):
    def test_setting_handler(self):
        loop = EHLoop()

        self.assertIs(loop.get_exception_handler(), None)

        def handler(loop, context):
            pass

        loop.set_exception_handler(handler)

        self.assertIs(loop.get_exception_handler(), handler)

        loop.set_exception_handler(None)

        self.assertIs(loop.get_exception_handler(), None)

    def test_calling_handler(self):
        loop = EHLoop()

        handled = []

        def handler(loop, context):
            handled.append((loop, context))

        loop.set_exception_handler(handler)

        context = {"a": "b"}

        loop.call_exception_handler(context)
        self.assertEqual(handled, [(loop, context)])

        # Make sure exceptions are swallowed
        handled = None
        loop.call_exception_handler(context)
        self.assertIs(handled, None)

        # XXX: This should test that the exception is logged!

    def test_default_handler(self):
        pass
