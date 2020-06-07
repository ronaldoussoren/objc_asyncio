"""
Interactive interpreter exposing asyncio functionality

This code just calls into the stdlib functionality for that
after setting the objc_asyncio eventloop policy.
"""
import asyncio
import asyncio.__main__ as asyncio_main  # type: ignore

import objc_asyncio

if __name__ == "__main__":
    asyncio.set_event_loop_policy(objc_asyncio.PyObjCEventLoopPolicy())

    # The code below is copied from the stdlib

    loop = asyncio_main.loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    repl_locals = {"asyncio": asyncio}
    for key in {
        "__name__",
        "__package__",
        "__loader__",
        "__spec__",
        "__builtins__",
        "__file__",
    }:
        repl_locals[key] = locals()[key]

    console = asyncio_main.console = asyncio_main.AsyncIOInteractiveConsole(
        repl_locals, loop
    )

    repl_future = None
    repl_future_interrupted = False

    try:
        import readline  # NoQA
    except ImportError:
        pass

    repl_thread = asyncio_main.REPLThread()
    repl_thread.daemon = True
    repl_thread.start()

    while True:
        try:
            loop.run_forever()
        except KeyboardInterrupt:
            if repl_future and not repl_future.done():
                repl_future.cancel()
                repl_future_interrupted = True
            continue
        else:
            break
