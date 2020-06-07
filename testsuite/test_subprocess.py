import asyncio
import subprocess
import sys
import unittest.mock

from objc_asyncio._subprocess import _format_pipe

from . import utils


class TestUtils(utils.TestCase):
    def test_pipe_formatter(self):
        self.assertEqual(_format_pipe(subprocess.PIPE), "<pipe>")
        self.assertEqual(_format_pipe(subprocess.STDOUT), "<stdout>")
        self.assertEqual(_format_pipe(subprocess.DEVNULL), "<devnull>")
        self.assertEqual(_format_pipe(sys.stdout), repr(sys.stdout))

    def test_logging_support(self):
        with utils.captured_log() as stream:
            with self.subTest("message only"):
                self.loop._log_subprocess("hello world", None, None, None)
                self.assertEqual(stream.getvalue(), "DEBUG hello world\n")

            stream.seek(0)
            stream.truncate()

            with self.subTest("message and stdin"):
                self.loop._log_subprocess("hello world", subprocess.PIPE, None, None)
                self.assertEqual(stream.getvalue(), "DEBUG hello world stdin=<pipe>\n")

            stream.seek(0)
            stream.truncate()

            with self.subTest("message and stdout"):
                self.loop._log_subprocess("hello world", None, subprocess.PIPE, None)
                self.assertEqual(stream.getvalue(), "DEBUG hello world stdout=<pipe>\n")

            stream.seek(0)
            stream.truncate()

            with self.subTest("message and stderr to explicit stdout"):
                self.loop._log_subprocess(
                    "hello world", None, subprocess.PIPE, subprocess.STDOUT
                )
                self.assertEqual(
                    stream.getvalue(), "DEBUG hello world stdout=stderr=<pipe>\n"
                )

            stream.seek(0)
            stream.truncate()

            with self.subTest("message and stderr"):
                self.loop._log_subprocess("hello world", None, None, subprocess.PIPE)
                self.assertEqual(stream.getvalue(), "DEBUG hello world stderr=<pipe>\n")

            stream.seek(0)
            stream.truncate()

            with self.subTest("message and streams"):
                self.loop._log_subprocess(
                    "hello world", subprocess.STDOUT, sys.stdout, subprocess.PIPE
                )
                self.assertEqual(
                    stream.getvalue(),
                    f"DEBUG hello world stdin=<stdout> stdout={sys.stdout!r} stderr=<pipe>\n",
                )


class TestSubprocessShell(utils.TestCase):
    def test_basic(self):
        async def main():
            proc = await asyncio.create_subprocess_shell(
                "echo hello; echo done>&2",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            self.assertEqual(proc.returncode, 0)

            self.assertEqual(stdout.decode(), "hello\n")
            self.assertEqual(stderr.decode(), "done\n")

        self.loop.run_until_complete(main())

    def test_basic_debuglog(self):
        async def main():
            proc = await asyncio.create_subprocess_shell(
                "echo hello; echo done>&2",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            self.assertEqual(proc.returncode, 0)

            self.assertEqual(stdout.decode(), "hello\n")
            self.assertEqual(stderr.decode(), "done\n")

        self.loop.set_debug(True)
        with utils.captured_log() as stream:
            self.loop.run_until_complete(main())
        self.loop.set_debug(False)

        self.assertIn(
            "DEBUG run shell command 'echo hello; echo done>&2' stdout=<pipe> stderr=<pipe>",
            stream.getvalue(),
        )

    def test_piping(self):
        async def main():
            proc = await asyncio.create_subprocess_shell(
                f'{sys.executable} -c "import sys; print(sys.stdin.readline().upper())"',
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, stderr = await proc.communicate(b"hello world")
            self.assertEqual(proc.returncode, 0)

            self.assertEqual(stdout.decode(), "HELLO WORLD\n")
            self.assertIs(stderr, None)

        self.loop.run_until_complete(main())

    def test_piping_failed(self):
        async def main():
            with self.assertRaisesRegex(
                TypeError, "unexpected keyword argument 'dummy'"
            ):
                await asyncio.create_subprocess_shell(
                    f'{sys.executable} -c "import sys; print(sys.stdin.readline().upper())"',
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    dummy=False,
                )

        self.loop.run_until_complete(main())

    def test_argument_validation(self):
        async def main():
            with self.subTest("cmd type"):
                with self.assertRaises(ValueError):
                    await asyncio.create_subprocess_shell(42)

            for key in (
                "bufsize",
                "universal_newlines",
                "shell",
                "text",
                "encoding",
                "errors",
            ):
                with self.subTest(f"{key} should not be specified"):
                    with self.assertRaises(ValueError):
                        await asyncio.create_subprocess_shell("true", **{key: 1})

        self.loop.run_until_complete(main())

    def test_inactive_loop(self):
        v = self.loop.subprocess_shell(lambda: None, "true")

        with self.assertRaisesRegex(
            RuntimeError, r"get_child_watcher\(\) is not activated"
        ):
            v.send(None)


class TestSubprocessExec(utils.TestCase):
    def test_basic(self):
        async def main():
            proc = await asyncio.create_subprocess_exec(
                "echo",
                "hello",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            self.assertEqual(proc.returncode, 0)

            self.assertEqual(stdout.decode(), "hello\n")
            self.assertEqual(stderr.decode(), "")

        self.loop.run_until_complete(main())

    def test_basic_debuglog(self):
        async def main():
            proc = await asyncio.create_subprocess_exec(
                "echo",
                "hello",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            self.assertEqual(proc.returncode, 0)

            self.assertEqual(stdout.decode(), "hello\n")
            self.assertEqual(stderr.decode(), "")

        self.loop.set_debug(True)
        with utils.captured_log() as stream:
            self.loop.run_until_complete(main())
        self.loop.set_debug(False)

        self.assertIn(
            "DEBUG run shell command 'echo' stdout=<pipe> stderr=<pipe>",
            stream.getvalue(),
        )

    def test_piping(self):
        async def main():
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                "import sys; print(sys.stdin.readline().upper())",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, stderr = await proc.communicate(b"hello world")
            self.assertEqual(proc.returncode, 0)

            self.assertEqual(stdout.decode(), "HELLO WORLD\n")
            self.assertIs(stderr, None)

        self.loop.run_until_complete(main())
        self.loop.set_debug(False)

    def test_piping_failed(self):
        async def main():
            with self.assertRaisesRegex(
                TypeError, "unexpected keyword argument 'dummy'"
            ):
                await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-c",
                    "import sys; print(sys.stdin.readline().upper())",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    dummy=True,
                )

        self.loop.run_until_complete(main())

    def test_argument_validation(self):
        async def main():
            with self.subTest("program type"):
                with self.assertRaises(ValueError):
                    await asyncio.create_subprocess_exec(42)

            with self.subTest("program argument type"):
                with self.assertRaises(ValueError):
                    await asyncio.create_subprocess_exec("echo", 42)

            with self.subTest("program argument type inconsistent"):
                with self.assertRaises(ValueError):
                    await asyncio.create_subprocess_exec("echo", b"42")

            for key in (
                "bufsize",
                "universal_newlines",
                "shell",
                "text",
                "encoding",
                "errors",
            ):
                with self.subTest(f"{key} should not be specified"):
                    with self.assertRaises(ValueError):
                        await asyncio.create_subprocess_exec("true", **{key: 1})

        self.loop.run_until_complete(main())

    def test_inactive_loop(self):
        v = self.loop.subprocess_exec(lambda: None, "true")

        with self.assertRaisesRegex(
            RuntimeError, r"asyncio\.get_child_watcher\(\) is not activated"
        ):
            v.send(None)

    def test_exception_during_transport_construction(self):
        # XXX: This depends on implementation details of asyncio itself...
        from asyncio import base_subprocess

        caught = result = None

        async def main():
            nonlocal caught, result
            try:
                proc = await asyncio.create_subprocess_exec("true")

            except Exception as exc:
                caught = exc

            else:
                stdout, stderr = await proc.communicate()
                self.assertIs(stdout, None)
                self.assertIs(stderr, None)
                self.assertEqual(proc.returncode, 0)
                result = proc.returncode

        with self.subTest("selftest"):
            caught = result = None

            self.loop.run_until_complete(main())

            self.assertIs(caught, None)
            self.assertEqual(result, 0)

        def side_effect(waiter, *args, **kwargs):
            waiter.set_exception(exception())

        for exception in (SystemExit, KeyboardInterrupt):
            with self.subTest(exception=exception):
                with unittest.mock.patch.object(
                    base_subprocess.BaseSubprocessTransport,
                    "_connect_pipes",
                    spec=True,
                    side_effect=side_effect,
                ):
                    caught = result = None

                    with self.assertRaises(exception):
                        self.loop.run_until_complete(main())

                    self.assertIs(caught, None)
                    self.assertIs(result, None)

        class MyException(Exception):
            pass

        with self.subTest(exception=MyException):
            exception = MyException

            with unittest.mock.patch.object(
                base_subprocess.BaseSubprocessTransport,
                "_connect_pipes",
                spec=True,
                side_effect=side_effect,
            ):
                caught = result = None

                self.loop.run_until_complete(main())

                self.assertIsInstance(caught, MyException)
                self.assertIs(result, None)
