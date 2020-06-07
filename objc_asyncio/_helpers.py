__all__ = ("IBAction",)

import asyncio
import contextlib
import functools
import typing


def IBAction(
    method: typing.Union[
        typing.Callable[[typing.Any], None],
        typing.Callable[[typing.Any], typing.Awaitable[None]],
    ]
) -> typing.Callable[[typing.Any], None]:
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


def applicationShouldTerminateWrapper(
    method: typing.Callable[[typing.Any], typing.Awaitable[int]]
) -> typing.Callable[[typing.Any], int]:
    # XXX: Add API to pyobjc-core that will make it possible
    # to automate the application of this decorator...
    @functools.wraps(method)
    def applicationShouldTerminate_(self, application):
        task = asyncio.create_task(method(self, application))
        task.add_done_callback(
            lambda: application.replyToApplicationShouldTerminate_(task.result())
        )
        return 1  # XXX

    return applicationShouldTerminate_


@contextlib.contextmanager
def running_loop(self):
    # Note sure yet if this is good enough.
    asyncio.get_event_loop()
    yield
