Introduction
------------

**WARNING: This library is basically completely untested at this point**

Objc_asyncio is an experimental library that implements an
asyncio runloop using the Cocoa CFRunLoop, which makes
it possible to integrate macOS GUIs and asyncio.

The long-term goal for this library is to integrate with the
main PyObjC library (in particular, integrate into pyobjc-core).
