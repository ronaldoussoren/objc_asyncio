import socket

import objc_asyncio
import objc_asyncio._loop

from . import utils


class TestPipes(utils.TestCase):
    def test_connect_read_pipe(self):
        sd1, sd2 = socket.socketpair()
        self.addCleanup(sd1.close)
        self.addCleanup(sd2.close)

        async def main():
            transport, protocol = await self.loop.connect_read_pipe(
                utils.EchoServerProtocol, sd1
            )
            return transport, protocol

        transport, protocol = self.loop.run_until_complete(main())
        self.assertIsInstance(transport, objc_asyncio.PyObjCReadPipeTransport)
        self.addCleanup(transport.close)
        self.assertIsInstance(protocol, utils.EchoServerProtocol)
        self.assertIs(protocol.transport, transport)
        self.assertIs(protocol.transport.get_extra_info("pipe"), sd1)

    def test_connect_read_pipe_debug(self):
        with utils.captured_log() as stream:
            sd1, sd2 = socket.socketpair()
            self.addCleanup(sd1.close)
            self.addCleanup(sd2.close)

            async def main():
                transport, protocol = await self.loop.connect_read_pipe(
                    utils.EchoServerProtocol, sd1
                )
                return transport, protocol

            self.loop.set_debug(True)
            transport, protocol = self.loop.run_until_complete(main())
            self.loop.set_debug(False)
            self.addCleanup(transport.close)

        self.assertIn(
            f"Read pipe {sd1.fileno()!r} connected: ({transport!r}, {protocol!r}",
            stream.getvalue(),
        )

    def test_connect_read_pipe_with_exception(self):
        class MyException(Exception):
            pass

        orig = objc_asyncio.PyObjCReadPipeTransport

        def side_effect(loop, pipe, protocol, waiter=None, extra=None):
            value = orig(loop, pipe, protocol, None, extra)
            waiter.set_exception(MyException())
            return value

        objc_asyncio._loop.PyObjCReadPipeTransport = side_effect
        self.addCleanup(setattr, objc_asyncio._loop, "PyObjCReadPipeTransport", orig)

        sd1, sd2 = socket.socketpair()
        self.addCleanup(sd1.close)
        self.addCleanup(sd2.close)

        async def main():
            transport, protocol = await self.loop.connect_read_pipe(
                utils.EchoServerProtocol, sd1
            )
            return transport, protocol

        self.loop.set_debug(True)

        with self.assertRaises(MyException):
            self.loop.run_until_complete(main())

    def test_connect_write_pipe(self):
        sd1, sd2 = socket.socketpair()
        self.addCleanup(sd1.close)
        self.addCleanup(sd2.close)

        async def main():
            transport, protocol = await self.loop.connect_write_pipe(
                utils.EchoServerProtocol, sd1
            )
            return transport, protocol

        transport, protocol = self.loop.run_until_complete(main())
        self.assertIsInstance(transport, objc_asyncio.PyObjCWritePipeTransport)
        self.addCleanup(transport.close)
        self.assertIsInstance(protocol, utils.EchoServerProtocol)
        self.assertIs(protocol.transport, transport)
        self.assertIs(protocol.transport.get_extra_info("pipe"), sd1)

    def test_connect_write_pipe_debug(self):
        with utils.captured_log() as stream:
            sd1, sd2 = socket.socketpair()
            self.addCleanup(sd1.close)
            self.addCleanup(sd2.close)

            async def main():
                transport, protocol = await self.loop.connect_write_pipe(
                    utils.EchoServerProtocol, sd1
                )
                return transport, protocol

            self.loop.set_debug(True)
            transport, protocol = self.loop.run_until_complete(main())
            self.loop.set_debug(False)
            self.addCleanup(transport.close)

        self.assertIn(
            f"Write pipe {sd1.fileno()!r} connected: ({transport!r}, {protocol!r}",
            stream.getvalue(),
        )

    def test_connect_write_pipe_with_exception(self):
        class MyException(Exception):
            pass

        orig = objc_asyncio.PyObjCWritePipeTransport

        def side_effect(loop, pipe, protocol, waiter=None, extra=None):
            value = orig(loop, pipe, protocol, None, extra)
            waiter.set_exception(MyException())
            return value

        objc_asyncio._loop.PyObjCWritePipeTransport = side_effect
        self.addCleanup(setattr, objc_asyncio._loop, "PyObjCWritePipeTransport", orig)

        sd1, sd2 = socket.socketpair()
        self.addCleanup(sd1.close)
        self.addCleanup(sd2.close)

        async def main():
            transport, protocol = await self.loop.connect_write_pipe(
                utils.EchoServerProtocol, sd1
            )
            return transport, protocol

        self.loop.set_debug(True)

        with self.assertRaises(MyException):
            self.loop.run_until_complete(main())


# XXX: Test transports as well, as soon as those
#      get copied into objc_asyncio
