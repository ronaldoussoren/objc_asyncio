import asyncio

from objc_asyncio import EventLoop


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


el = EventLoop()
asyncio.set_event_loop(el)
# el.call_soon(lambda a: print(a), "hello world")
# el.call_later(1.0, lambda: print("timer 1"))
# el.call_later(2.0, lambda: print("timer 2"))
task = el.create_task(main())
# el.call_later(5, lambda: el.stop())
# el.run_until_complete(task)
el.run_forever()
