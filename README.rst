**WARNING: This library is basically completely untested at this point**

Objc_asyncio is a library that implements an
asyncio runloop using the Cocoa CFRunLoop, which makes
it possible to integrate macOS GUIs and asyncio.

The basic usage in command-line scripts is to
call ``objc_asyncio.install`` and then use asyncio
as usual.

The more interesting use-case are GUI programs using
PyObjC, in which case you can use the ``running_loop``
context manager:

::
    import sys
    import Cocoa

    import objc_asyncio

    with objc_asyncio.running_loop():
        Cocoa.NSApplicationMain(sys.argv)
