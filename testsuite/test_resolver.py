import socket
import unittest
import unittest.mock

from . import utils


class TestResolver(utils.TestCase):
    def test_getaddrinfo(self):
        for dom, port in (("blog.ronaldoussoren.net", 80), ("www.python.org", "https")):
            with self.subTest(dom=dom, family="*"):
                infos = self.loop.run_until_complete(self.loop.getaddrinfo(dom, port))
                self.assertEqual(set(infos), set(socket.getaddrinfo(dom, port)))

        for dom, port in (("blog.ronaldoussoren.net", 80), ("www.python.org", "https")):
            with self.subTest(dom=dom, family="IPv4"):
                infos = self.loop.run_until_complete(
                    self.loop.getaddrinfo(dom, port, family=socket.AF_INET)
                )
                self.assertEqual(
                    set(infos),
                    set(socket.getaddrinfo(dom, port, family=socket.AF_INET)),
                )

        for dom, port in (("blog.ronaldoussoren.net", 80), ("www.python.org", "https")):
            with self.subTest(dom=dom, proto="STREAM"):
                infos = self.loop.run_until_complete(
                    self.loop.getaddrinfo(dom, port, proto=socket.SOCK_STREAM)
                )
                self.assertEqual(
                    set(infos),
                    set(socket.getaddrinfo(dom, port, proto=socket.SOCK_STREAM)),
                )

    def test_getaddrinfo_debug(self):
        with utils.captured_log() as stream:

            self.loop.set_debug(True)
            for dom, port in (
                ("blog.ronaldoussoren.net", 80),
                ("www.python.org", "https"),
            ):
                with self.subTest(dom=dom, family="*"):
                    stream.seek(0)
                    stream.truncate()
                    infos = self.loop.run_until_complete(
                        self.loop.getaddrinfo(dom, port)
                    )
                    self.assertEqual(set(infos), set(socket.getaddrinfo(dom, port)))

                    contents = stream.getvalue()
                    self.assertIn("Get address info", contents)
                    self.assertIn("Getting address info", contents)

                    self.assertNotIn("family=", contents)
                    self.assertNotIn("type=", contents)
                    self.assertNotIn("proto=", contents)
                    self.assertNotIn("flags=", contents)
                    self.assertIn("DEBUG", contents)

            for dom, port in (
                ("blog.ronaldoussoren.net", 80),
                ("www.python.org", "https"),
            ):
                with self.subTest(dom=dom, family="IPv4"):
                    stream.seek(0)
                    stream.truncate()
                    infos = self.loop.run_until_complete(
                        self.loop.getaddrinfo(dom, port, family=socket.AF_INET)
                    )
                    self.assertEqual(
                        set(infos),
                        set(socket.getaddrinfo(dom, port, family=socket.AF_INET)),
                    )
                    contents = stream.getvalue()
                    self.assertIn("family=", contents)
                    self.assertNotIn("type=", contents)
                    self.assertNotIn("proto=", contents)
                    self.assertNotIn("flags=", contents)

            for dom, port in (
                ("blog.ronaldoussoren.net", 80),
                ("www.python.org", "https"),
            ):
                with self.subTest(dom=dom, type="STREAM"):
                    stream.seek(0)
                    stream.truncate()
                    infos = self.loop.run_until_complete(
                        self.loop.getaddrinfo(dom, port, type=socket.SOCK_STREAM)
                    )
                    self.assertEqual(
                        set(infos),
                        set(socket.getaddrinfo(dom, port, type=socket.SOCK_STREAM)),
                    )
                    contents = stream.getvalue()
                    self.assertNotIn("family=", contents)
                    self.assertIn("type=", contents)
                    self.assertNotIn("proto=", contents)
                    self.assertNotIn("flags=", contents)

            for dom, port in (
                ("blog.ronaldoussoren.net", 80),
                ("www.python.org", "https"),
            ):
                with self.subTest(dom=dom, proto="TCP"):
                    stream.seek(0)
                    stream.truncate()
                    infos = self.loop.run_until_complete(
                        self.loop.getaddrinfo(
                            dom, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
                        )
                    )
                    self.assertEqual(
                        set(infos),
                        set(
                            socket.getaddrinfo(
                                dom,
                                port,
                                type=socket.SOCK_STREAM,
                                proto=socket.IPPROTO_TCP,
                            )
                        ),
                    )
                    contents = stream.getvalue()
                    self.assertNotIn("family=", contents)
                    self.assertIn("type=", contents)
                    self.assertIn("proto=", contents)
                    self.assertNotIn("flags=", contents)

            for dom, port in (
                ("blog.ronaldoussoren.net", 80),
                ("www.python.org", "https"),
            ):
                with self.subTest(dom=dom, flags="AI_CANONNAME"):
                    stream.seek(0)
                    stream.truncate()
                    infos = self.loop.run_until_complete(
                        self.loop.getaddrinfo(dom, port, flags=socket.AI_CANONNAME)
                    )
                    self.assertEqual(
                        set(infos),
                        set(socket.getaddrinfo(dom, port, flags=socket.AI_CANONNAME)),
                    )
                    contents = stream.getvalue()
                    self.assertNotIn("family=", contents)
                    self.assertNotIn("type=", contents)
                    self.assertNotIn("proto=", contents)
                    self.assertIn("flags=", contents)

            with self.subTest("Resolving error"):
                stream.seek(0)
                stream.truncate()

                awaitable = self.loop.getaddrinfo("nosuchhost.python.org", 443)
                with self.assertRaises(socket.error):
                    self.loop.run_until_complete(awaitable)

                contents = stream.getvalue()
                self.assertIn("Getting address info", contents)
                self.assertIn("failed in", contents)
                self.assertIn("DEBUG", contents)

            # Check that slow queries get logged at INFO level by (crudely)
            # mocking a slow clock.
            with self.subTest("Slow resolver"):
                with unittest.mock.patch(
                    "objc_asyncio.PyObjCEventLoop.time", side_effect=list(range(1000))
                ):
                    stream.seek(0)
                    stream.truncate()

                    awaitable = self.loop.getaddrinfo("www.python.org", 443)
                    self.loop.run_until_complete(awaitable)

                    contents = stream.getvalue()
                    self.assertIn("INFO", contents)

            with self.subTest("Slow resolver"):
                with unittest.mock.patch(
                    "objc_asyncio.PyObjCEventLoop.time", side_effect=list(range(1000))
                ):
                    stream.seek(0)
                    stream.truncate()

                    awaitable = self.loop.getaddrinfo("nosuchhost.python.org", 443)
                    with self.assertRaises(socket.error):
                        self.loop.run_until_complete(awaitable)

                    contents = stream.getvalue()
                    self.assertIn("INFO", contents)

    def test_getaddrinfo_no_such_addr(self):
        awaitable = self.loop.getaddrinfo("nosuchhost.python.org", 443)
        with self.assertRaises(socket.error):
            self.loop.run_until_complete(awaitable)

        self.loop.set_debug(True)
        awaitable = self.loop.getaddrinfo("nosuchhost.python.org", 443)
        with self.assertRaises(socket.error):
            self.loop.run_until_complete(awaitable)

    def test_getnameinfo(self):
        infos = socket.getaddrinfo(
            "blog.ronaldoussoren.net", 80, proto=socket.SOCK_STREAM
        )
        self.assertNotEqual(infos, [])

        for flags in (0, socket.NI_NOFQDN):
            for info in infos:
                result = self.loop.run_until_complete(
                    self.loop.getnameinfo(info[-1], flags)
                )

                self.assertEqual(result, socket.getnameinfo(info[-1], flags))
