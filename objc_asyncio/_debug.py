import asyncio
import functools
import traceback


def traceexceptions(function):
    if asyncio.iscoroutinefunction(function):

        @functools.wraps(function)
        async def wrapper(*args, **kwds):
            print(">", function.__name__, args, kwds)
            try:
                result = await function(*args, **kwds)
                print("<  ", function.__name__, args, kwds, "->", result)
                return result

            except:  # noqa: B001, E722
                traceback.print_exc()
                raise

    else:

        @functools.wraps(function)
        def wrapper(*args, **kwds):
            print(">", function.__name__, args, kwds)
            try:
                result = function(*args, **kwds)
                print("<  ", function.__name__, args, kwds, "->", result)
                return result

            except:  # noqa: B001, E722
                traceback.print_exc()
                raise

    return wrapper
    return function
