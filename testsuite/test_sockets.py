import asyncio
import errno
import io
import os
import socket
import tempfile
import time
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

    def test_sock_accept(self):
        server_sd = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        server_sd.bind(("127.0.0.1", 0))
        server_sd.listen(5)
        server_sd.setblocking(False)

        client_sd = client_addr = None
        sd = None

        def cleanup():
            if server_sd is not None:
                server_sd.close()
            if client_sd is not None:
                client_sd.close()
            if sd is not None:
                sd.close()

        self.addCleanup(cleanup)

        def client():
            nonlocal sd
            sd = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
            sd.connect(server_sd.getsockname())

        async def main():
            nonlocal client_sd, client_addr

            client_sd, client_addr = await self.loop.sock_accept(server_sd)

        self.loop.call_later(0.1, client)
        self.loop.run_until_complete(main())

        self.assertIsInstance(client_sd, socket.socket)
        self.assertIsInstance(client_addr, tuple)

    def test_sock_accept_available(self):
        server_sd = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        server_sd.bind(("127.0.0.1", 0))
        server_sd.listen(5)
        server_sd.setblocking(False)

        client_sd = client_addr = None
        sd = None

        def cleanup():
            if server_sd is not None:
                server_sd.close()
            if client_sd is not None:
                client_sd.close()
            if sd is not None:
                sd.close()

        self.addCleanup(cleanup)

        def client():
            nonlocal sd
            sd = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
            sd.connect(server_sd.getsockname())

        async def main():
            nonlocal client_sd, client_addr

            client_sd, client_addr = await self.loop.sock_accept(server_sd)

        client()
        self.loop.run_until_complete(main())

        self.assertIsInstance(client_sd, socket.socket)
        self.assertIsInstance(client_addr, tuple)

    def test_sock_accept_blocking_socket(self):
        server_sd = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        server_sd.bind(("127.0.0.1", 0))
        server_sd.listen(5)

        self.addCleanup(server_sd.close)

        self.loop.set_debug(True)

        async def main():
            await self.loop.sock_accept(server_sd)

        with self.assertRaisesRegex(ValueError, "must be non-blocking"):
            self.loop.run_until_complete(main())

    def test_sock_accept_systemexit(self):
        for exception_class in (SystemExit, KeyboardInterrupt):
            with self.subTest(exception_class=exception_class):
                server_sd = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
                server_sd.bind(("127.0.0.1", 0))
                server_sd.listen(5)
                self.addCleanup(server_sd.close)
                sd_mock = unittest.mock.create_autospec(server_sd)
                sd_mock.accept.side_effect = [
                    BlockingIOError(),
                    exception_class(),
                    b"dummy",
                ]
                sd_mock.fileno.return_value = server_sd.fileno()

                exception = None

                sd = None

                def client():
                    nonlocal sd
                    sd = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
                    sd.connect(server_sd.getsockname())

                async def main():
                    nonlocal exception

                    try:
                        await self.loop.sock_accept(sd_mock)
                    except Exception as exc:
                        exception = exc

                client()
                self.addCleanup(sd.close)

                with self.assertRaises(exception_class):
                    self.loop.run_until_complete(main())

    def test_sock_accept_exception(self):
        class MyException(Exception):
            pass

        server_sd = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        server_sd.bind(("127.0.0.1", 0))
        server_sd.listen(5)
        self.addCleanup(server_sd.close)
        sd_mock = unittest.mock.create_autospec(server_sd)
        sd_mock.accept.side_effect = [BlockingIOError(), MyException(), b"dummy"]
        sd_mock.fileno.return_value = server_sd.fileno()

        exception = None

        sd = None

        def client():
            nonlocal sd
            sd = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
            sd.connect(server_sd.getsockname())

        async def main():
            nonlocal exception

            try:
                await self.loop.sock_accept(sd_mock)
            except Exception as exc:
                exception = exc

        client()
        self.addCleanup(sd.close)

        self.loop.run_until_complete(main())

        self.assertIsInstance(exception, MyException)

    def test_sock_connect(self):
        for famname, family, server_addr in (
            ("INET", socket.AF_INET, ("127.0.0.1", 0)),
            ("UNIX", socket.AF_UNIX, f"testsocket.{os.getpid()}"),
        ):

            with self.subTest(family=famname):
                server_sd = socket.socket(family, socket.SOCK_STREAM, 0)
                self.addCleanup(server_sd.close)
                server_sd.bind(server_addr)
                if family == socket.AF_UNIX:
                    self.addCleanup(os.unlink, server_addr)
                server_sd.listen(5)
                server_sd.setblocking(False)

                client_sd = socket.socket(family, socket.SOCK_STREAM, 0)
                self.addCleanup(client_sd.close)
                client_sd.setblocking(False)

                def server():
                    sd, addr = server_sd.accept()
                    try:
                        self.assertEqual(sd.getpeername(), client_sd.getsockname())
                        self.assertEqual(
                            client_sd.getpeername(), server_sd.getsockname()
                        )
                    finally:
                        sd.close()

                async def main():
                    await self.loop.sock_connect(client_sd, server_sd.getsockname())

                    await asyncio.sleep(0.2)

                self.loop.call_later(0.1, server)
                self.loop.run_until_complete(main())

                # self.assertEqual(client_sd.getpeername(), server_sd.getsockname())
                # self.assertEqual(sd.getpeername(), client_sd.getsockname())

    def test_sock_connect_blocking_socket(self):
        server_sd = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        self.addCleanup(server_sd.close)
        server_sd.bind(("127.0.0.1", 0))
        server_sd.listen(5)
        server_sd.setblocking(False)

        client_sd = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        self.addCleanup(client_sd.close)
        client_sd.setblocking(True)

        self.loop.set_debug(True)

        async def main():
            await self.loop.sock_connect(client_sd, server_sd.getsockname())

        with self.assertRaisesRegex(ValueError, "must be non-blocking"):
            self.loop.run_until_complete(main())

    def test_sock_connect_no_connection(self):
        server_sd = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        server_sd.bind(("127.0.0.1", 0))
        server_sd.listen(5)
        server_sd.setblocking(False)

        server_addr = server_sd.getsockname()
        server_sd.close()
        server_sd = None

        client_sd = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        client_sd.setblocking(False)
        self.addCleanup(client_sd.close)

        async def main():
            await self.loop.sock_connect(client_sd, server_addr)

        with self.assertRaises(socket.error):
            self.loop.run_until_complete(main())

    def test_sock_connect_systemexit(self):
        for exception_class in (SystemExit, KeyboardInterrupt):
            with self.subTest(exception_class=exception_class):
                server_sd = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
                server_sd.bind(("127.0.0.1", 0))
                server_sd.listen(5)
                self.addCleanup(server_sd.close)

                client_sd = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
                self.addCleanup(client_sd.close)
                client_sd.setblocking(False)

                sd_mock = unittest.mock.create_autospec(client_sd)

                sd_mock.connect.side_effect = [exception_class, b"dummy"]
                sd_mock.fileno.return_value = client_sd.fileno()
                sd_mock.family = client_sd.family
                sd_mock.proto = client_sd.proto
                sd_mock.getsockopt.side_effect = lambda *args: client_sd.getsockopt(
                    *args
                )

                exception = None

                async def main():
                    nonlocal exception

                    try:
                        await self.loop.sock_connect(sd_mock, server_sd.getsockname())
                    except Exception as exc:
                        exception = exc

                with self.assertRaises(exception_class):
                    self.loop.run_until_complete(main())

                    self.assertIs(exception, None)

    def test_sock_connect_exception(self):
        class MyException(Exception):
            pass

        server_sd = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        server_sd.bind(("127.0.0.1", 0))
        server_sd.listen(5)
        self.addCleanup(server_sd.close)

        client_sd = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        self.addCleanup(client_sd.close)
        client_sd.setblocking(False)

        sd_mock = unittest.mock.create_autospec(client_sd)

        sd_mock.connect.side_effect = [MyException, b"dummy"]
        sd_mock.fileno.return_value = client_sd.fileno()
        sd_mock.family = client_sd.family
        sd_mock.proto = client_sd.proto
        sd_mock.getsockopt.side_effect = lambda *args: client_sd.getsockopt(*args)

        exception = None

        async def main():
            nonlocal exception

            try:
                await self.loop.sock_connect(sd_mock, server_sd.getsockname())
            except Exception as exc:
                exception = exc

        self.loop.run_until_complete(main())
        self.assertIsInstance(exception, MyException)

    def test_connect_hostname(self):
        sd = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        self.addCleanup(sd.close)
        sd.setblocking(False)

        async def main():
            await self.loop.sock_connect(sd, ("www.python.org", 80))

        self.loop.run_until_complete(main())

        # Quick check that the socket is now connected:
        sd.getpeername()

    def test_sock_sendall_some_data(self):
        sd1, sd2 = self.make_socketpair()
        data = None

        async def main():
            await self.loop.sock_sendall(sd1, b"hello world")

        self.loop.run_until_complete(main())

        data = sd2.recv(100)
        self.assertEqual(data, b"hello world")

    def test_sock_sendall_bulk(self):
        sd1, sd2 = self.make_socketpair()
        data = None

        blob = b"data" * 1024 * 1024

        def client():
            sd2.setblocking(True)
            buf = []
            while True:
                data = sd2.recv(1024)
                if not data:
                    break

                buf.append(data)

            return b"".join(buf)

        async def main():
            await self.loop.sock_sendall(sd1, blob)

        fut = self.loop.run_in_executor(None, client)
        self.loop.run_until_complete(main())
        sd1.close()

        data = self.loop.run_until_complete(fut)

        self.assertEqual(data, blob)

    def test_sock_sendall_blocking_socket(self):
        sd1, sd2 = self.make_socketpair()
        sd1.setblocking(True)

        self.loop.set_debug(True)

        async def main():
            await self.loop.sock_sendall(sd1, b"hello world")

        with self.assertRaisesRegex(ValueError, "must be non-blocking"):
            self.loop.run_until_complete(main())

    def test_sock_sendall_blocked(self):
        sd1, sd2 = self.make_socketpair()

        exceptions = []

        def side_effect(*args):
            try:
                exc = exceptions.pop()
            except IndexError:
                pass
            else:
                raise exc from None

            return sd1.send(*args)

        sd_mock = unittest.mock.create_autospec(sd1)
        sd_mock.send.side_effect = side_effect
        sd_mock.fileno.return_value = sd1.fileno()

        async def main():
            await self.loop.sock_sendall(sd_mock, b"hello world")

        for level in (1, 2):
            for exception in (BlockingIOError, InterruptedError):
                with self.subTest(exception=exception, level=level):
                    exceptions = [exception for _ in range(level)]

                    self.loop.run_until_complete(main())
                    self.assertEqual(sd2.recv(1024), b"hello world")

    def test_sock_sendall_systemexit(self):
        sd1, sd2 = self.make_socketpair()

        exceptions = []

        def side_effect(*args):
            try:
                exc = exceptions.pop()
            except IndexError:
                pass

            else:
                raise exc from None

            return sd1.send(*args)

        sd_mock = unittest.mock.create_autospec(sd1)
        sd_mock.send.side_effect = side_effect
        sd_mock.fileno.return_value = sd1.fileno()

        async def main():
            await self.loop.sock_sendall(sd_mock, b"hello world")

        for level in (1, 2):
            for exc in (SystemExit, KeyboardInterrupt):
                exceptions = [exc]
                if level == 2:
                    exceptions.append(BlockingIOError)

                with self.subTest(exception=exc, level=level):
                    with self.assertRaises(exc):
                        self.loop.run_until_complete(main())

    def test_sock_sendall_exception(self):
        # Arrange for exeption using mock.
        class MyException(Exception):
            pass

        exceptions = []

        def side_effect(*args):
            try:
                exc = exceptions.pop()
            except IndexError:
                pass
            else:
                raise exc

            return sd1.send(*args)

        sd1, sd2 = self.make_socketpair()

        sd_mock = unittest.mock.create_autospec(sd1)
        sd_mock.send.side_effect = side_effect
        sd_mock.fileno.return_value = sd1.fileno()

        async def main():
            nonlocal exception
            try:
                await self.loop.sock_sendall(sd_mock, b"hello world")

            except Exception as exc:
                exception = exc

        for level in (1, 2):
            if level == 1:
                exceptions = [MyException]

            else:
                exceptions = [MyException, BlockingIOError]

            with self.subTest(level=level):
                exception = None
                self.loop.run_until_complete(main())
                self.assertIsInstance(exception, MyException)

    def basic_sendfile(self, stream, count=None, offset=0):
        sd1, sd2 = self.make_socketpair()

        expected = stream.read()
        stream.seek(0)

        def receiver(sd, buffer):
            sd.setblocking(True)
            while True:
                buf = sd.recv(1024 * 1024)
                if not buf:
                    break

                buffer.append(buf)

        async def main():
            try:
                await self.loop.sock_sendfile(sd1, stream, offset=offset, count=count)

            finally:
                sd1.close()

        data = []
        fut = self.loop.run_in_executor(None, receiver, sd2, data)
        self.loop.run_until_complete(main())
        self.loop.run_until_complete(fut)

        if count is not None:
            self.assertEqual(b"".join(data), expected[offset : offset + count])
            self.assertEqual(stream.tell(), offset + count)

        else:
            self.assertEqual(b"".join(data), expected[offset:])
            self.assertEqual(stream.tell(), len(expected))

    def test_sendfile_basic_file(self):
        with tempfile.NamedTemporaryFile() as stream:
            stream.write(b"X" * 1024 * 1024)
            stream.seek(0)

            self.basic_sendfile(stream)

    def test_sendfile_basic_stringio(self):
        stream = io.BytesIO()
        stream.write(b"X" * 1024 * 1024)
        stream.seek(0)

        self.basic_sendfile(stream)

    def test_sendfile_basic_file_empty(self):
        with tempfile.NamedTemporaryFile() as stream:
            self.basic_sendfile(stream)

    def test_sendfile_basic_stringio_empty(self):
        stream = io.BytesIO()
        self.basic_sendfile(stream)

    def test_sendfile_basic_file_with_count(self):
        with tempfile.NamedTemporaryFile() as stream:
            stream.write(b"X" * 1024 * 1024)
            stream.seek(0)

            self.basic_sendfile(stream, count=123456)

    def test_sendfile_basic_stringio_with_count(self):
        stream = io.BytesIO()
        stream.write(b"X" * 1024 * 1024)
        stream.seek(0)

        self.basic_sendfile(stream, count=123456)

    def test_sendfile_basic_file_with_offset(self):
        with tempfile.NamedTemporaryFile() as stream:
            stream.write(b"hello world")
            stream.write(b"X" * 1024 * 1024)
            stream.seek(0)

            self.basic_sendfile(stream, offset=5)

    def test_sendfile_basic_stringio_with_offset(self):
        stream = io.BytesIO()
        stream.write(b"hello world")
        stream.write(b"X" * 1024 * 1024)
        stream.seek(0)

        self.basic_sendfile(stream, offset=5)

    def test_sendfile_basic_file_with_offset_and_count(self):
        with tempfile.NamedTemporaryFile() as stream:
            stream.write(b"hello world")
            stream.write(b"X" * 1024 * 1024)
            stream.seek(0)

            self.basic_sendfile(stream, offset=5, count=12345)

    def test_sendfile_basic_stringio_with_offset_and_count(self):
        stream = io.BytesIO()
        stream.write(b"hello world")
        stream.write(b"X" * 1024 * 1024)
        stream.seek(0)

        self.basic_sendfile(stream, offset=5, count=12345)

    def test_sock_sendfile_blocking_socket(self):
        sd1, sd2 = self.make_socketpair()

        sd1.setblocking(True)

        async def main():
            await self.loop.sock_sendfile(sd1, stream)

        self.loop.set_debug(True)
        with open(__file__, "rb") as stream:
            with self.assertRaisesRegex(ValueError, "must be non-blocking"):
                self.loop.run_until_complete(main())

            self.assertEqual(stream.tell(), 0)
        self.loop.set_debug(False)

    def test_sock_sendfile_stringio_without_fallback(self):
        sd1, sd2 = self.make_socketpair()

        stream = io.BytesIO()
        stream.write(b"X" * 100)
        stream.seek(0)

        async def main():
            with self.assertRaises(asyncio.SendfileNotAvailableError):
                await self.loop.sock_sendfile(sd1, stream, fallback=False)

            self.assertEqual(stream.tell(), 0)

        self.loop.run_until_complete(main())

    def test_sock_sendfile_special_file_without_fallback(self):
        # XXX: I have no idea how to trigger this a failure
        # of os.fstat without using mock or a closed file.
        #
        # In particular, os.fstat should never fail unless either the file
        # is closed, or there is a serious problem with the filesystem itself.
        sd1, sd2 = self.make_socketpair()

        with unittest.mock.patch.object(os, "fstat", side_effect=OSError):
            with open("/dev/null", "rb") as stream:

                async def main():
                    with self.assertRaises(asyncio.SendfileNotAvailableError):
                        await self.loop.sock_sendfile(sd1, stream, fallback=False)
                    self.assertEqual(stream.tell(), 0)

                self.loop.run_until_complete(main())

    def test_sock_sendfile_no_seek(self):
        class MyFile:
            def __init__(self, stream):
                self._stream = stream

            def fileno(self):
                return self._stream.fileno()

            def readinto(self, buf):
                return self._stream.readinto(buf)

        sd1, sd2 = self.make_socketpair()

        def receiver(sd, buffer):
            sd.setblocking(True)
            while True:
                buf = sd.recv(1024 * 1024)
                if not buf:
                    break

                buffer.append(buf)

        async def main():
            try:
                await self.loop.sock_sendfile(sd1, stream)

            finally:
                sd1.close()

        with tempfile.NamedTemporaryFile() as raw_stream:
            raw_stream.write(b"X" * 1024 * 1024)
            raw_stream.seek(0)

            expected = raw_stream.read()
            raw_stream.seek(0)

            stream = MyFile(raw_stream)

            data = []
            fut = self.loop.run_in_executor(None, receiver, sd2, data)
            self.loop.run_until_complete(main())
            self.loop.run_until_complete(fut)

            self.assertEqual(b"".join(data), expected)

    def test_sock_sendfile_blocking_call(self):
        os_sendfile = os.sendfile
        with tempfile.NamedTemporaryFile() as stream:
            stream.write(b"X" * 1024 * 1024)

            for n in range(2):
                for exception in (BlockingIOError, InterruptedError):
                    with self.subTest(num_blocks=n, exception=exception):
                        stream.seek(0)

                        left = n

                        def side_effect(*args, **kwds):
                            nonlocal left
                            if left > 0:
                                left -= 1
                                raise exception

                            return os_sendfile(*args, **kwds)

                        with unittest.mock.patch.object(
                            os, "sendfile", side_effect=side_effect
                        ):
                            self.basic_sendfile(stream)

    def test_sock_sendfile_devzero(self):
        sd1, sd2 = self.make_socketpair()

        def receiver(sd, buffer):
            sd.setblocking(True)
            while True:
                buf = sd.recv(1024 * 1024)
                if not buf:
                    break

                buffer.append(buf)

        async def main():
            try:
                await self.loop.sock_sendfile(sd1, stream, count=1000)

            finally:
                sd1.close()

        with open("/dev/zero", "rb") as stream:
            data = []
            fut = self.loop.run_in_executor(None, receiver, sd2, data)
            self.loop.run_until_complete(main())
            self.loop.run_until_complete(fut)

            self.assertEqual(b"".join(data), b"\0" * 1000)

    def test_sock_sendfile_error(self):
        class MyException(Exception):
            pass

        sd1, sd2 = self.make_socketpair()
        exception = None

        def receiver(sd, buffer):
            sd.setblocking(True)
            while True:
                buf = sd.recv(1024 * 1024)
                if not buf:
                    break

                buffer.append(buf)

        async def main():
            nonlocal exception

            try:

                try:
                    await self.loop.sock_sendfile(sd1, stream, count=1000)

                finally:
                    sd1.close()

            except Exception as exc:
                exception = exc

        with unittest.mock.patch.object(os, "sendfile", side_effect=MyException):
            with tempfile.NamedTemporaryFile() as stream:
                stream.write(b"X" * 1024)
                stream.seek(0)

                data = []
                fut = self.loop.run_in_executor(None, receiver, sd2, data)

                self.loop.run_until_complete(main())
                self.loop.run_until_complete(fut)

                self.assertIsInstance(exception, MyException)
                self.assertEqual(b"".join(data), b"")

    def test_sock_sendfile_error_after_sent(self):
        sd1, sd2 = self.make_socketpair()
        exception = None

        def receiver(sd, buffer):
            sd.setblocking(True)
            while True:
                buf = sd.recv(1024 * 1024)
                if not buf:
                    break

                buffer.append(buf)

        async def main():
            nonlocal exception

            try:

                try:
                    await self.loop.sock_sendfile(sd1, stream, count=1000)

                finally:
                    sd1.close()

            except Exception as exc:
                exception = exc

        n = False
        os_sendfile = os.sendfile

        def side_effect(fd, fileno, offset, blocksize):
            nonlocal n
            if not n:
                n = True
                return os_sendfile(fd, fileno, offset, blocksize // 2)

            raise OSError("Invalid Argument", errno.EINVAL)

        with unittest.mock.patch.object(os, "sendfile", side_effect=side_effect):
            with tempfile.NamedTemporaryFile() as stream:
                stream.write(b"X" * 1024)
                stream.seek(0)

                data = []
                fut = self.loop.run_in_executor(None, receiver, sd2, data)

                self.loop.run_until_complete(main())
                self.loop.run_until_complete(fut)

                self.assertIsInstance(exception, OSError)
                self.assertEqual(b"".join(data), b"X" * 500)

    def test_sock_sendfile_socket_closed(self):
        sd1, sd2 = self.make_socketpair()
        exception = None

        def receiver(sd, buffer):
            sd.setblocking(True)
            buf = sd.recv(1024 * 1024)
            buffer.append(buf)
            sd.close()

        async def main():
            nonlocal exception

            try:

                try:
                    await self.loop.sock_sendfile(sd1, stream, count=1000)

                finally:
                    sd1.close()

            except Exception as exc:
                exception = exc

        os_sendfile = os.sendfile

        def side_effect(fd, fileno, offset, blocksize):
            result = os_sendfile(fd, fileno, offset, blocksize // 2)
            time.sleep(0.5)
            return result

        with unittest.mock.patch.object(os, "sendfile", side_effect=side_effect):
            with tempfile.NamedTemporaryFile() as stream:
                stream.write(b"X" * 1024)
                stream.seek(0)

                data = []
                fut = self.loop.run_in_executor(None, receiver, sd2, data)

                self.loop.run_until_complete(main())
                self.loop.run_until_complete(fut)

                self.assertIsInstance(exception, OSError)
                self.assertEqual(b"".join(data), b"X" * 500)

    def _test_sock_sendfile_systemexit(self):
        for exception in (SystemExit, KeyboardInterrupt):
            with self.subTest(exception=exception):
                sd1, sd2 = self.make_socketpair()
                exception = None

                def receiver(sd, buffer):
                    sd.setblocking(True)
                    while True:
                        buf = sd.recv(1024 * 1024)
                        if not buf:
                            break

                        buffer.append(buf)

                async def main():
                    nonlocal exception

                    try:

                        try:
                            await self.loop.sock_sendfile(sd1, stream, count=1000)

                        finally:
                            sd1.close()

                    except Exception as exc:
                        exception = exc

                with unittest.mock.patch.object(os, "sendfile", side_effect=exception):
                    with tempfile.NamedTemporaryFile() as stream:
                        stream.write(b"X" * 1024)
                        stream.seek(0)

                        data = []
                        fut = self.loop.run_in_executor(None, receiver, sd2, data)

                        with self.assertRaises(exception):
                            self.loop.run_until_complete(main())

                        self.loop.run_until_complete(fut)

                        self.assertEqual(b"".join(data), b"0" * 1000)
                        self.assertIs(exception, None)

    def test_sock_sendfile_params(self):
        sd1, sd2 = self.make_socketpair()

        with self.subTest("text mode file"):
            with open(__file__, "r") as stream:
                with self.assertRaisesRegex(ValueError, "binary mode"):
                    self.loop.run_until_complete(self.loop.sock_sendfile(sd1, stream))

        with open(__file__, "rb") as stream:
            with self.subTest("non-stream socket"):
                sd_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sd_udp.setblocking(False)
                self.addCleanup(sd_udp.close)

                with self.assertRaisesRegex(ValueError, "only SOCK_STREAM"):
                    self.loop.run_until_complete(
                        self.loop.sock_sendfile(sd_udp, stream)
                    )

            with self.subTest("count == 0"):
                with self.assertRaisesRegex(
                    ValueError, "count must be a positive integer"
                ):
                    self.loop.run_until_complete(
                        self.loop.sock_sendfile(sd1, stream, count=0)
                    )

            with self.subTest("count < 0"):
                with self.assertRaisesRegex(
                    ValueError, "count must be a positive integer"
                ):
                    self.loop.run_until_complete(
                        self.loop.sock_sendfile(sd1, stream, count=-5)
                    )

            with self.subTest("count not integer"):
                with self.assertRaisesRegex(
                    TypeError, "count must be a positive integer"
                ):
                    self.loop.run_until_complete(
                        self.loop.sock_sendfile(sd1, stream, count="count")
                    )

            with self.subTest("offset < 0"):
                with self.assertRaisesRegex(
                    ValueError, "offset must be a non-negative integer"
                ):
                    self.loop.run_until_complete(
                        self.loop.sock_sendfile(sd1, stream, offset=-5)
                    )

            with self.subTest("offset not integer"):
                with self.assertRaisesRegex(
                    TypeError, "offset must be a non-negative integer"
                ):
                    self.loop.run_until_complete(
                        self.loop.sock_sendfile(sd1, stream, offset="count")
                    )


class TestSocketHighlevel(utils.TestCase):
    pass


class TestSocketTLS(utils.TestCase):
    pass
