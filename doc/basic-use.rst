Basic Library Usage
===================

Interative use
--------------

To experiment with objc_asyncio you can use an interactive interpreter
with asyncio support:

.. code-block::

   asyncio REPL 3.8.3 (v3.8.3:6f8c8320e9, May 13 2020, 16:29:34)
   [Clang 6.0 (clang-600.0.57)] on darwin
   Use "await" directly instead of "asyncio.run()".
   Type "help", "copyright", "credits" or "license" for more information.
   >>> import asyncio
   >>>
   >>> await asyncio.sleep(0.5)
   >>>

 This behaves the same as ``python -m asyncio``, but uses the objc_asyncio
 event loop instead of the regular one.


In command-line scripts
-----------------------

Call objc_asyncio.install() before calling asyncio.run() or manually creating an asyncio event loop:

.. code-block:: python
   :linenos:

    import asyncio
    import objc_asyncio


    async def main():
        ...


    asyncio.set_event_loop_policy(objc_asyncio.PyObjCEventLoopPolicy())
    asyncio.run(main())


In GUI's
--------


Call objc_asyncio.install() before starting the main GUI:


.. code-block:: python
   :linenos:

    import sys
    import Cocoa

    import objc_asyncio


    asyncio.set_event_loop_policy(objc_asyncio.PyObjCEventLoopPolicy())

    with objc_asyncio.running_loop():
        Cocoa.NSApplicationMain(sys.argv)
