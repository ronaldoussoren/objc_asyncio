__all__ = ("install", "IBAction")

import asyncio
import functools


def install(*, create_loop=False):
    """
    Install the objc_asyncio EventLoopPolicy.

    If *create_loop* is true also create the initial
    loop.
    """
    global _loop
    ...


def IBAction(method):
    """
    Mark a method as one that can be used as
    a Cocoa action.

    When the method is an async function
    triggering the action will start a new
    asyncio.Task.
    """
    if asyncio.iscoroutinefunction(method):

        @functools.wraps(method)
        def wrapper_(self, arg):
            asyncio.create_task(method(arg))

        return wrapper_

    else:
        return method
