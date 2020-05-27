import asyncio
import os
import socket
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

        with self.assertRaises(ValueError):
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

        with self.assertRaises(ValueError):
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

        with self.assertRaises(ValueError):
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

    def test_sock_sendfile(self):
        self.fail()
