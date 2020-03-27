import asyncio
from asyncio import futures

from objc_asyncio import _loop as loop


async def sleep(delay, result=None):
    future = el.create_future()
    h = el.call_later(delay, futures._set_result_unless_cancelled, future, result)
    try:
        value = await future
        return value
    finally:
        h.cancel()


async def printer():
    print("******* start")
    await sleep(1)
    print("******* middle")
    await sleep(1)
    print("******* end")


async def main():
    print("******* hello")
    await printer()
    print("******* world")
    el.stop()


el = loop.EventLoop()
asyncio.set_event_loop(el)
# el.call_soon(lambda a: print(a), "hello world")
# el.call_later(1.0, lambda: print("timer 1"))
# el.call_later(2.0, lambda: print("timer 2"))
task = el.create_task(main())
# el.call_later(5, lambda: el.stop())
# el.run_until_complete(task)
el.run_forever()
