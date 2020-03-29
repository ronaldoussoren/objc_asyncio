Basic Library Usage
===================

In command-line scripts
-----------------------

Call objc_asyncio.install() before calling asyncio.run() or manually creating an asyncio event loop:

.. code-block:: python
   :linenos:

    import asyncio
    import objc_asyncio


    async def main():
        ...


    objc_asyncio.install()
    asyncio.run(main())


In GUI's
--------


Call objc_asyncio.install() before starting the main GUI:


.. code-block:: python
   :linenos:

    import sys
    import Cocoa

    import objc_asyncio


    objc_asyncio.install(create_loop=True)
    Cocoa.NSApplicationMain(sys.argv)
