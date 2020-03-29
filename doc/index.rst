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

The library can be installed using `pip <https://pypi.org/project/pip/>`_.


Supported platforms
-------------------

Objectgraph supports Python 3.7 and later on macOS 10.9 or later, it is
not supported on other platforms like iOS, Windows and Linux.

Using objc_asyncio
------------------

.. toctree::
   :maxdepth: 2

   basic-use
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
