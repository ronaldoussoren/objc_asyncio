import socket
import sys
import unittest
from unittest import mock

import Cocoa
from Cocoa import (
    kCFSocketAcceptCallBack,
    kCFSocketConnectCallBack,
    kCFSocketReadCallBack,
    kCFSocketWriteCallBack,
)
from objc_asyncio import _selector as mod

all_events = (
    kCFSocketReadCallBack
    | kCFSocketAcceptCallBack
    | kCFSocketConnectCallBack
    | kCFSocketWriteCallBack
)


class TestSupportCode(unittest.TestCase):
    def test_selector_key(self):
        v = mod.SelectorKey(1, 2, 3, 4, 5, 6)
        self.assertEqual(v.fileobj, 1)
        self.assertEqual(v.fd, 2)
        self.assertEqual(v.events, 3)
        self.assertEqual(v.data, 4)
        self.assertEqual(v.cfsocket, 5)
        self.assertEqual(v.cfsource, 6)

    def test_valid_events(self):
        # mod._valid_events
        self.assertTrue(mod._valid_events(kCFSocketReadCallBack))
        self.assertTrue(mod._valid_events(kCFSocketReadCallBack))
        self.assertTrue(mod._valid_events(kCFSocketAcceptCallBack))
        self.assertTrue(mod._valid_events(kCFSocketConnectCallBack))
        self.assertTrue(mod._valid_events(kCFSocketWriteCallBack))
        self.assertTrue(
            mod._valid_events(kCFSocketWriteCallBack | kCFSocketAcceptCallBack)
        )
        self.assertTrue(mod._valid_events(all_events))

        self.assertFalse(mod._valid_events(all_events + 16))

    def test__fileobj_to_fd__integer(self):
        with self.subTest("valid"):
            self.assertEqual(mod._fileobj_to_fd(42), 42)
            self.assertEqual(mod._fileobj_to_fd(0), 0)

        with self.subTest("invalid"):
            with self.assertRaises(ValueError):
                mod._fileobj_to_fd(-1)

            with self.assertRaises(ValueError):
                mod._fileobj_to_fd(-30)

    def test__fileobj_to_fd__file(self):
        with self.subTest("standard stream"):
            self.assertEqual(mod._fileobj_to_fd(sys.stderr), 2)

        class File:
            def __init__(self, fd):
                self._fd = fd

            def fileno(self):
                return self._fd

        with self.subTest("file like"):
            self.assertEqual(mod._fileobj_to_fd(File(42)), 42)
            self.assertEqual(mod._fileobj_to_fd(File(0)), 0)

        with self.subTest("file like - invalid"):
            with self.assertRaises(ValueError):
                mod._fileobj_to_fd(File(-1))

            with self.assertRaises(ValueError):
                mod._fileobj_to_fd(File(-40))

        with self.subTest("invalid type"):
            with self.assertRaises(ValueError):
                mod._fileobj_to_fd("42")

            with self.assertRaises(ValueError):
                mod._fileobj_to_fd(1.0)


class FakeEventloop:
    def __init__(self):
        self._loop = Cocoa.CFRunLoopGetCurrent()
        self._io_called = []

    def _io_event(self, event, key):
        self._io_called.append((event, key))


class TestSelector(unittest.TestCase):
    def assert_key_consistent(self, key):
        self.assertTrue(isinstance(key, mod.SelectorKey), f"{key} is not a SelectorKey")
        self.assertTrue(isinstance(key.fd, int), f"FD {key.fd} is not an integer")
        self.assertTrue(
            isinstance(key.events, int), f"Events {key.events} is not an integer"
        )
        self.assertTrue(
            isinstance(key.cfsocket, Cocoa.CFSocketRef),
            f"cfsocket {key.cfsocket} is not an CFSocketRef",
        )
        self.assertTrue(
            isinstance(key.cfsource, Cocoa.CFRunLoopSourceRef),
            f"cfsource {key.cfsource} is not an CFRunLoopSourceRef",
        )

        self.assertEqual(key.fd, mod._fileobj_to_fd(key.fileobj))
        self.assertEqual(key.fd, Cocoa.CFSocketGetNative(key.cfsocket))
        # It would be nice to check if cfsocket and cfsource are related...
        # It would be nice to check if events and cfsocket are consistent...

    def setUp(self):
        self.eventloop = FakeEventloop()
        self.selector = mod.RunLoopSelector(self.eventloop)

    def tearDown(self):
        self.selector.close()

    def test_basic_registration(self):
        sd = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(sd.close)

        with self.subTest("registration"):
            key = self.selector.register(sd, Cocoa.kCFSocketReadCallBack, "data")
            self.assert_key_consistent(key)
            self.assertIs(key.fileobj, sd)
            self.assertEqual(key.data, "data")
            self.assertEqual(key.events, Cocoa.kCFSocketReadCallBack)

            self.assertIs(self.selector.get_key(sd), key)

        with self.subTest("modification"):
            key2 = self.selector.modify(sd, Cocoa.kCFSocketWriteCallBack, key.data)
            self.assertIsNot(key, key2)
            self.assert_key_consistent(key2)
            self.assertIs(key2.fileobj, sd)
            self.assertIs(key2.data, key.data)
            self.assertEqual(key2.events, Cocoa.kCFSocketWriteCallBack)

            self.assertIs(self.selector.get_key(sd), key2)

        with self.subTest("unregistration"):
            self.selector.unregister(sd)

            with self.assertRaises(KeyError):
                self.selector.get_key(sd)

        self.assertEqual(self.eventloop._io_called, [])

    @mock.patch("objc_asyncio._selector.CFRunLoopAddSource", autospec=True)
    @mock.patch("objc_asyncio._selector.CFRunLoopRemoveSource", autospec=True)
    @mock.patch("objc_asyncio._selector.CFSocketDisableCallBacks", autospec=True)
    @mock.patch("objc_asyncio._selector.CFSocketEnableCallBacks", autospec=True)
    def test_cf_registration(
        self,
        CFSocketEnableCallBacks,
        CFSocketDisableCallBacks,
        CFRunLoopRemoveSource,
        CFRunLoopAddSource,
    ):
        # Simular to test_basic_registration, but using mocks to test
        # low-level API use that cannot be verified otherwise.
        sd = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(sd.close)

        with self.subTest("registration"):
            key = self.selector.register(sd, Cocoa.kCFSocketReadCallBack, "data")

            CFRunLoopAddSource.assert_called_once_with(
                self.eventloop._loop, key.cfsource, Cocoa.kCFRunLoopCommonModes
            )
            CFRunLoopRemoveSource.assert_not_called()
            CFSocketDisableCallBacks.assert_called_once_with(
                key.cfsocket, Cocoa.kCFSocketNoCallBack
            )
            CFSocketEnableCallBacks.assert_called_once_with(
                key.cfsocket, Cocoa.kCFSocketReadCallBack
            )

            CFRunLoopAddSource.reset_mock()
            CFRunLoopRemoveSource.reset_mock()
            CFSocketDisableCallBacks.reset_mock()
            CFSocketEnableCallBacks.reset_mock()

        with self.subTest("modification"):
            key2 = self.selector.modify(sd, Cocoa.kCFSocketWriteCallBack, key.data)

            CFRunLoopAddSource.assert_not_called()
            CFRunLoopRemoveSource.assert_not_called()
            CFSocketDisableCallBacks.assert_called_once_with(
                key.cfsocket, Cocoa.kCFSocketReadCallBack
            )
            CFSocketEnableCallBacks.assert_called_once_with(
                key.cfsocket, Cocoa.kCFSocketWriteCallBack
            )

            CFRunLoopAddSource.reset_mock()
            CFRunLoopRemoveSource.reset_mock()
            CFSocketDisableCallBacks.reset_mock()
            CFSocketEnableCallBacks.reset_mock()

        with self.subTest("unregistration"):
            self.selector.unregister(sd)

            CFRunLoopAddSource.assert_not_called()
            CFRunLoopRemoveSource.assert_called_once_with(
                self.eventloop._loop, key2.cfsource, Cocoa.kCFRunLoopCommonModes
            )
            CFSocketDisableCallBacks.assert_not_called()
            CFSocketEnableCallBacks.assert_not_called()

    def test_register_existing_fails(self):
        sd = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(sd.close)

        self.selector.register(sd, Cocoa.kCFSocketReadCallBack, "data")

        with self.assertRaises(KeyError):
            self.selector.register(sd, Cocoa.kCFSocketWriteCallBack, "data2")

    def test_close_unregisters(self):
        sd1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(sd1.close)

        sd2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(sd2.close)

        key1 = self.selector.register(sd1, Cocoa.kCFSocketReadCallBack, "data")
        key2 = self.selector.register(sd2, Cocoa.kCFSocketReadCallBack, "data")

        self.assertIs(key1, self.selector.get_key(sd1))
        self.assertIs(key2, self.selector.get_key(sd2))

        orig_map = self.selector._map
        orig_fd_to_key = self.selector._fd_to_key.copy()

        with mock.patch.object(mod.RunLoopSelector, "unregister") as mock_method:
            self.selector.close()

        # Reset object state to ensure the actual clean-up happens
        self.selector._map = orig_map
        self.selector._fd_to_keyu = orig_fd_to_key

        mock_method.assert_any_call(sd1)
        mock_method.assert_any_call(sd2)
        self.assertEqual(mock_method.call_count, 2)

        self.selector.close()

        self.assertEqual(self.selector.get_map(), None)
        self.assertRaises(RuntimeError, self.selector.get_key, sd1)

    # Test I/O using sockets
    # Test I/O using pipes
    # Test I/O using files
