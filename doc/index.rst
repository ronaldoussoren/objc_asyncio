objc_asyncio - asyncio support for PyObjC
=========================================

The library "objc_asyncio" contains the implementation of an
:mod:`asyncio` eventloop on top of the Cocoa eventloop
library (in particular CFRunLoop), which makes it easy to
use :mod:`asyncio` in Cocoa GUIs on macOS.

The library also contains a number of utilities to make
using :mod:`asyncio` in Cocoa GUIs easier.


Release information
-------------------

Objc_asyncio 0.1 is not yet released. See the :doc:`changelog <changelog>`
for information on this release.


Installation
------------

The library can be installed using `pip <https://pypi.org/project/pip/>`_. Installing
does not require a compiler.


Supported platforms
-------------------

This package supports Python 3.7 and later on macOS 10.9 or later, it is
not supported on other platforms like iOS, Windows and Linux.

Basic Usage
-----------

Interative use
..............

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
.......................

Call objc_asyncio.install() before calling asyncio.run() or manually creating an asyncio event loop:

.. code-block:: python
   :linenos:

    import asyncio
    import objc_asyncio

    objc_asyncio.install()

    async def main():
        ...


    asyncio.run(main())


In GUI programs
...............


Call objc_asyncio.install() before starting the main GUI:


.. code-block:: python
   :linenos:

    import sys
    import Cocoa

    import objc_asyncio

    with objc_asyncio.running_loop():
        Cocoa.NSApplicationMain(sys.argv)


Using objc_asyncio
------------------

.. toctree::
   :maxdepth: 2

   api-reference

Development
-----------

.. toctree::
   :maxdepth: 2

   license
   changelog
   development

Online Resources
................

* `Sourcecode repository on GitHub <https://github.com/ronaldoussoren/objc_asyncio/>`_

* `The issue tracker <https://github.com/ronaldoussoren/objc_asyncio/issues>`_

Indices and tables
------------------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
