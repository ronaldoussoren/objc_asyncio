import asyncio
import traceback

import objc
from objc_asyncio import EventLoop

objc.setVerbose(True)


async def printer():
    print("******* start")
    await asyncio.sleep(1)
    print("******* middle")
    await asyncio.sleep(1)
    print("******* end")


async def main():
    print("******* hello")
    await printer()
    print("******* world")
    el.stop()


async def run(cmd):
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )

    stdout, stderr = await proc.communicate()

    print(f"[{cmd!r} exited with {proc.returncode}]")
    if stdout:
        print(f"[stdout]\n{stdout.decode()}")
    if stderr:
        print(f"[stderr]\n{stderr.decode()}")

    el.stop()


def handler():
    print("Signal")
    el.stop()


async def resolver():
    print("Start resolving")
    info = await el.getaddrinfo("www.rivm.nl", 80)
    print(info)
    raise 1 / 0
    el.stop()


async def clock():
    while True:
        print("*")
        await asyncio.sleep(1)


def exec_func():
    print("*** Executing task")
    # return sys.version_info
    return 42


async def executor():
    print("*** start executing in executor")
    try:
        value = await el.run_in_executor(None, exec_func)
        print("*** done:", value)
    except:  # noqa: B001, E722
        print("*** error")
        traceback.print_exc()


el = EventLoop()
# el = asyncio.get_event_loop()
# el.set_debug(True)
asyncio.set_event_loop(el)
# el.add_signal_handler(signal.SIGTERM, handler)
# el.add_signal_handler(signal.SIGUSR1, handler)
# el.call_soon(lambda a: print(a), "hello world")
# el.call_later(1.0, lambda: print("timer 1"))
# el.call_later(2.0, lambda: print("timer 2"))
# task = el.create_task(main())
# el.call_later(5, lambda: el.stop())
# el.run_until_complete(task)
# task = el.create_task(run("ls -1"))
# task = el.create_task(clock())
task = el.create_task(resolver())
# task = el.create_task(executor())
# task = el.create_task(main())
el.run_forever()
