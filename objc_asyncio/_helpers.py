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


def applicationShouldTerminateWrapper(method):
    # XXX: Add API to pyobjc-core that will make it possible
    # to automate the application of this decorator...
    if not asyncio.iscoroutine(method):
        return method

    @functools.wraps(method)
    def applicationShouldTerminate_(self, application):
        task = asyncio.create_task(method(self, application))
        task.add_done_callback(
            lambda: application.replyToApplicationShouldTerminate_(task.result())
        )

    return applicationShouldTerminate_
