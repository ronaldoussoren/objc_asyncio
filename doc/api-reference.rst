objc_asyncio - Reference documentation
======================================

.. module:: objc_asyncio
   :platform: macOS
   :synopsis: AsyncIO eventloop using CFRunLoop


Main entry point
................

.. function:: install(\*)

   Install the ``PyObjCEventLoopPolicy``
   with :mod:`asyncio`.

.. function:: runnning_loop()

   Returns a context manager that installs
   the event loop policy and runs the body
   of the with-statement with the ``PyObjCEventLoop``
   in running mode (without actually calling
   ``run_forever``.

   The primary use-case for this is starting
   a Cocoa event loop in the body of the with-statement,
   for example::

       with running_loop():
           NSApplicationMain()


Utility functions
.................

.. function:: IBAction(function)

   Decorator that marks a method for use as a
   an "action" callback in a Cocoa program. The
   method should have a single argument, and should
   conform to the PyObjC naming convention.

   When the decorated function is a coroutine
   the result of decorating is a plain function
   that we create a task with the decorated function.

Classes
.......

The module exports the event loop, event loop policy and child watcher classes. These
classes don't add APIs to the abstract base classes they derive from.

.. class:: PyObjCEventLoop

   An implementation of an :class:`AbstractEventLoop <asyncio.AbstractEventLoop>`
   that Cocoa ``CFRunLoop`` APIs in its implementation.

.. class:: PyObjCEventLoopPolicy

   An implementation of an :class:`AbstractEventLoopPolicy <asyncio.AbstractEventLoopPolicy>`
   that uses :class:`PyObjCEventLoop` and :class:`KQueueChildWatcher`.

.. class:: KQueueChildWatcher

   An implementation of :class:`AbstractChildWatcher <asyncio.AbstractChildWatcher>`
   which uses the kqueue APIs in its implementation.

   This watcher will only wait for processes that were explicitly registered with it,
   and is hence safe for using with code that starts and waits for subprocesses outside
   of the regular :mod:`asyncio` APIs.
