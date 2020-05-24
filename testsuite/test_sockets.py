import asyncio
import unittest.mock

from . import utils


class TestSocketEvents(utils.TestCase):
    def test_add_reader(self):
        sd1, sd2 = self.make_socketpair()
        data = []

        def callback(sd):
            data.append(sd.recv(100))

        self.loop.add_reader(sd1, callback, sd1)

        async def writer():
            sd2.sendall(b"hello")
            await asyncio.sleep(0.1)
            sd2.sendall(b"world")
            await asyncio.sleep(0.1)

        self.loop.run_until_complete(writer())

        self.assertEqual(data, [b"hello", b"world"])

        count = 0

        def callback(sd):
            nonlocal count

            count += 1

        self.loop.add_reader(sd1, callback, sd1)
        self.loop.run_until_complete(writer())

        # We pass through the loop at least twice without
        # consuming the read event, hence the callback should
        # be called multiple times.
        self.assertGreater(count, 1)

    def test_cancel_reader(self):
        sd1, sd2 = self.make_socketpair()
        data = []
        count = 0

        def callback(sd):
            data.append(sd.recv(100))

        def no_callback():
            nonlocal count
            count += 1

        self.loop.add_reader(sd1, callback, sd1)

        async def writer():
            sd2.sendall(b"hello")
            await asyncio.sleep(0.1)
            self.loop.add_reader(sd1, no_callback)
            sd2.sendall(b"world")
            await asyncio.sleep(0.1)

        self.loop.run_until_complete(writer())

        self.assertEqual(data, [b"hello"])
        self.assertGreater(count, 0)

    def test_remove_reader(self):
        sd1, sd2 = self.make_socketpair()
        data = []

        def callback(sd):
            data.append(sd.recv(100))

        self.loop.add_reader(sd1, callback, sd1)

        async def writer():
            sd2.sendall(b"hello")
            await asyncio.sleep(0.1)
            self.loop.remove_reader(sd1)
            sd2.sendall(b"world")
            await asyncio.sleep(0.1)

        self.loop.run_until_complete(writer())

        self.assertEqual(data, [b"hello"])

    def test_add_writer(self):
        sd1, sd2 = self.make_socketpair()
        data = []

        def callback(sd):
            sd.send(b"x" * 1024 * 1024)

        self.loop.add_writer(sd1, callback, sd1)

        async def writer():
            await asyncio.sleep(0.1)

        self.loop.run_until_complete(writer())

        data = sd2.recv(1024 * 1024)
        self.assertGreater(len(data), 0)
        self.assertRegex(data, b"^x+$")

        count = 0

        def callback(sd):
            nonlocal count

            count += 1

        self.loop.add_writer(sd1, callback, sd1)
        self.loop.run_until_complete(writer())

        # We pass through the loop at least twice without
        # consuming the read event, hence the callback should
        # be called multiple times.
        self.assertGreater(count, 1)

    def test_cancel_writer(self):
        sd1, sd2 = self.make_socketpair()
        count = 0

        def callback(sd):
            sd.send(b"hello world\n")
            self.loop.add_writer(sd1, no_callback)

        def no_callback():
            nonlocal count
            count += 1

        self.loop.add_writer(sd1, callback, sd1)

        async def writer():
            await asyncio.sleep(0.1)
            await asyncio.sleep(0.1)

        self.loop.run_until_complete(writer())

        data = sd2.recv(1024)
        self.assertTrue(data.startswith(b"hello world\n"))

        self.assertGreater(count, 0)

    def test_remove_writer(self):
        sd1, sd2 = self.make_socketpair()
        data = []

        def callback(sd):
            sd.send(b"hello")
            self.loop.remove_writer(sd)

        self.loop.add_writer(sd1, callback, sd1)

        async def writer():
            await asyncio.sleep(0.1)
            await asyncio.sleep(0.1)

        self.loop.run_until_complete(writer())

        data = sd2.recv(1024)
        self.assertEqual(data, b"hello")


class TestLowLevelIO(utils.TestCase):
    def test_sock_recv_data_available(self):
        sd1, sd2 = self.make_socketpair()
        data = None

        async def main():
            nonlocal data
            data = await self.loop.sock_recv(sd1, 100)

        sd2.send(b"hello")

        self.loop.run_until_complete(main())

        self.assertEqual(data, b"hello")

    def test_sock_recv_waiting(self):
        for debug in (False, True):
            with self.subTest(debug=debug):
                self.loop.set_debug(debug)

                sd1, sd2 = self.make_socketpair()
                data = None

                async def main():
                    nonlocal data
                    data = await self.loop.sock_recv(sd1, 100)

                self.loop.call_later(0.5, lambda: sd2.send(b"hello"))
                self.loop.run_until_complete(main())

                self.assertEqual(data, b"hello")

    def test_sock_recv_socket_is_blocking(self):
        # The check for blocking sockets is only done
        # in debug mode.
        self.loop.set_debug(True)

        sd1, sd2 = self.make_socketpair()

        sd1.setblocking(True)

        data = exception = None

        async def main():
            nonlocal data, exception

            try:
                data = await self.loop.sock_recv(sd1, 100)
            except Exception as exc:
                exception = exc

        sd2.send(b"hello")
        self.loop.run_until_complete(main())

        self.assertEqual(data, None)
        self.assertIsInstance(exception, ValueError)

    def test_sock_recv_blocking(self):
        self.loop.set_debug(True)
        for exception_class in (BlockingIOError, InterruptedError):
            with self.subTest(exception_class=exception_class):
                sd1, sd2 = self.make_socketpair()
                sd_mock = unittest.mock.create_autospec(sd1)
                sd_mock.recv.side_effect = [
                    BlockingIOError(),
                    exception_class(),
                    b"world",
                ]
                sd_mock.fileno.return_value = sd1.fileno()
                sd_mock.gettimeout.return_value = sd1.gettimeout()

                data = exception = None

                async def main():
                    nonlocal data, exception

                    try:
                        data = await self.loop.sock_recv(sd_mock, 100)
                    except Exception as exc:
                        exception = exc

                sd2.send(b"hello")

                self.loop.run_until_complete(main())

                self.assertIs(exception, None)
                self.assertEqual(data, b"world")

    def test_sock_recv_error(self):
        class MyException(Exception):
            pass

        sd1, sd2 = self.make_socketpair()
        sd_mock = unittest.mock.create_autospec(sd1)
        sd_mock.recv.side_effect = [BlockingIOError(), MyException()]
        sd_mock.fileno.return_value = sd1.fileno()

        data = exception = None

        async def main():
            nonlocal data, exception

            try:
                data = await self.loop.sock_recv(sd_mock, 100)
            except Exception as exc:
                exception = exc

        sd2.send(b"hello")
        self.loop.run_until_complete(main())

        self.assertIsInstance(exception, MyException)
        self.assertIs(data, None)

    def test_sock_recv_systemexit(self):
        # XXX: This test hangs, need to debug
        for exception_class in (SystemExit, KeyboardInterrupt):
            with self.subTest(exception_class=exception_class):
                sd1, sd2 = self.make_socketpair()
                sd_mock = unittest.mock.create_autospec(sd1)
                sd_mock.recv.side_effect = [
                    BlockingIOError(),
                    exception_class(),
                    b"dummy",
                ]
                sd_mock.fileno.return_value = sd1.fileno()

                data = exception = None

                async def main():
                    nonlocal data, exception

                    try:
                        data = await self.loop.sock_recv(sd_mock, 100)
                    except Exception as exc:
                        exception = exc

                sd2.send(b"hello")

                with self.assertRaises(exception_class):
                    self.loop.run_until_complete(main())

    def test_sock_recv_into_data_available(self):
        sd1, sd2 = self.make_socketpair()
        data = None
        n = None

        async def main():
            nonlocal data, n
            data = bytearray(500)
            n = await self.loop.sock_recv_into(sd1, data)

        sd2.send(b"hello")

        self.loop.run_until_complete(main())

        self.assertEqual(n, 5)
        self.assertEqual(data[:n], b"hello")

    def test_sock_recv_into_waiting(self):
        for debug in (False, True):
            with self.subTest(debug=debug):
                self.loop.set_debug(debug)

                sd1, sd2 = self.make_socketpair()
                data = None
                n = None

                async def main():
                    nonlocal data, n
                    data = bytearray(500)
                    n = await self.loop.sock_recv_into(sd1, data)

                self.loop.call_later(0.5, lambda: sd2.send(b"hello"))
                self.loop.run_until_complete(main())

                self.assertEqual(n, 5)
                self.assertEqual(data[:n], b"hello")

    def test_sock_recv_into_socket_is_blocking(self):
        # The check for blocking sockets is only done
        # in debug mode.
        self.loop.set_debug(True)

        sd1, sd2 = self.make_socketpair()

        sd1.setblocking(True)

        data = exception = n = None

        async def main():
            nonlocal data, n, exception

            try:
                data = bytearray(500)
                n = await self.loop.sock_recv_into(sd1, data)
            except Exception as exc:
                exception = exc

        sd2.send(b"hello")
        self.loop.run_until_complete(main())

        self.assertEqual(data[0], 0)
        self.assertIsInstance(exception, ValueError)

    def test_sock_recv_into_blocking(self):
        self.loop.set_debug(True)
        for exception_class in (BlockingIOError, InterruptedError):
            with self.subTest(exception_class=exception_class):
                sd1, sd2 = self.make_socketpair()
                sd_mock = unittest.mock.create_autospec(sd1)
                sd_mock.recv_into.side_effect = [
                    BlockingIOError(),
                    exception_class(),
                    8,
                ]
                sd_mock.fileno.return_value = sd1.fileno()
                sd_mock.gettimeout.return_value = sd1.gettimeout()

                data = n = exception = None

                async def main():
                    nonlocal data, n, exception

                    try:
                        data = bytearray(500)
                        n = await self.loop.sock_recv_into(sd_mock, data)
                    except Exception as exc:
                        exception = exc

                sd2.send(b"hello")

                self.loop.run_until_complete(main())

                self.assertIs(exception, None)
                self.assertEqual(n, 8)

    def test_sock_recv_into_error(self):
        class MyException(Exception):
            pass

        sd1, sd2 = self.make_socketpair()
        sd_mock = unittest.mock.create_autospec(sd1)
        sd_mock.recv_into.side_effect = [BlockingIOError(), MyException()]
        sd_mock.fileno.return_value = sd1.fileno()

        data = n = exception = None

        async def main():
            nonlocal data, n, exception

            try:
                data = bytearray(500)
                n = await self.loop.sock_recv_into(sd_mock, data)
            except Exception as exc:
                exception = exc

        sd2.send(b"hello")
        self.loop.run_until_complete(main())

        self.assertIsInstance(exception, MyException)
        self.assertIs(data[0], 0)

    def test_sock_recv_into_systemexit(self):
        for exception_class in (SystemExit, KeyboardInterrupt):
            with self.subTest(exception_class=exception_class):
                sd1, sd2 = self.make_socketpair()
                sd_mock = unittest.mock.create_autospec(sd1)
                sd_mock.recv_into.side_effect = [
                    BlockingIOError(),
                    exception_class(),
                    b"dummy",
                ]
                sd_mock.fileno.return_value = sd1.fileno()

                data = n = exception = None

                async def main():
                    nonlocal data, n, exception

                    try:
                        data = bytearray(500)
                        n = await self.loop.sock_recv_into(sd_mock, data)
                    except Exception as exc:
                        exception = exc

                sd2.send(b"hello")

                with self.assertRaises(exception_class):
                    self.loop.run_until_complete(main())

    def test_sock_sendall_unblocking(self):
        pass

    def test_sock_sendall_blocking(self):
        pass

    def test_sock_connect_unblocking(self):
        pass

    def test_sock_connect_blocking(self):
        pass

    def test_sock_accepting_available(self):
        pass

    def test_sock_accepting_waiting(self):
        pass

    def test_sock_sendfile_fallback(self):
        pass

    def test_sock_sendfile_native(self):
        pass

    def test_create_connection(self):
        pass
