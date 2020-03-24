from objc_asyncio import _loop as loop

el = loop.EventLoop()
el.call_soon(lambda a: print(a), "hello world")
el.call_later(1.0, lambda: print("timer 1"))
el.call_later(2.0, lambda: print("timer 2"))
el.call_later(2.5, lambda: el.stop())
el.run_forever()
