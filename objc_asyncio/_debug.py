import asyncio
import functools
import traceback


def traceexceptions(function):
    if asyncio.iscoroutine(function):

        @functools.wraps(function)
        async def wrapper(*args, **kwds):
            # print(function, args, kwds)
            try:
                return await function(*args, **kwds)

            except:  # noqa: B001, E722
                traceback.print_exc()
                raise

    else:

        @functools.wraps(function)
        def wrapper(*args, **kwds):
            # print(function, args, kwds)
            try:
                return function(*args, **kwds)

            except:  # noqa: B001, E722
                traceback.print_exc()
                raise

    return wrapper
    return function
